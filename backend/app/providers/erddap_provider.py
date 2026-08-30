"""ERDDAP-based ocean data provider (erddapy + xarray).

Implements :class:`OceanDataProvider` over one ERDDAP server using a
catalog-driven mapping (logical variable -> dataset id/protocol/variable).

Design rules enforced here:

* **No dataset IDs in code** — everything comes from ``datasets.json``.
* Fetches are *subsets* (time/lat/lon bounding boxes); the LLM never sees raw
  arrays, only compact summaries / point samples.
* Any transport or subsetting failure degrades to a *missing* measurement —
  never an exception leaking into the agent loop, never a guessed value.
* erddapy/xarray are synchronous; blocking calls run in a worker thread via
  ``asyncio.to_thread`` so FastAPI handlers stay responsive.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
import xarray as xr
from erddapy import ERDDAP

from app.config.dataset_catalog import DatasetEntry, DatasetCatalog
from app.config.registry import DataSource
from app.config.registry import registry as source_registry
from app.config.settings import get_settings
from app.providers.base import OceanField, OceanDataProvider, ProviderError
from app.schemas.common import (
    BoundingBox,
    Measurement,
    Provenance,
    QualityFlag,
    utcnow,
)

logger = logging.getLogger(__name__)

# coordinate aliasing: ERDDAP datasets name their dims inconsistently
_LAT_NAMES = ("latitude", "lat", "y")
_LON_NAMES = ("longitude", "lon", "x")
_TIME_NAMES = ("time", "t")

_USER_AGENT = {"User-Agent": "ORCA-demo-fetch/0.1 (hackathon prototype; contact via repo)"}

# Host-level circuit breaker. Datacenter/cloud IPs (Render, AWS…) are commonly
# blocked by public ERDDAP hosts — SYNs are dropped (connect hangs) or the
# connection is accepted and the response stalls (read hangs). One dead HOST
# usually serves several of our variables (coastwatch: SST + chlorophyll…), so
# a per-variable breaker would re-burn the same host once per variable. This
# layer is keyed by host and shared by every ErddapProvider instance.
_HOST_DOWN_S = 600.0      # retry a dead host after this long
_HOST_PROBE_OK_S = 300.0  # cache a successful reachability probe this long
_PROBE_TIMEOUT_S = 2.0
_host_down_at: dict[str, float] = {}
_host_probe_ok_at: dict[str, float] = {}


def _is_transport_failure(exc: BaseException) -> bool:
    """True when an exception chain says 'the network failed', False when the
    server answered (HTTP 4xx/5xx → HTTPError — the host is clearly up)."""
    import requests as _requests

    e: BaseException | None = exc
    for _ in range(6):
        if e is None:
            break
        if isinstance(e, _requests.exceptions.HTTPError):
            return False
        if isinstance(e, (_requests.exceptions.ConnectionError, _requests.exceptions.Timeout)):
            return True
        e = e.__cause__ or e.__context__
    return isinstance(exc, (socket.timeout, TimeoutError, ConnectionError, OSError))


def _install_erddapy_default_headers() -> None:
    """Set a truthful User-Agent on every erddapy HTTP fetch.

    The NOAA CoastWatch ERDDAPs answer the default requests UA with 403 on
    griddap ``.ncml`` metadata (observed 2026-08-29), and erddapy 3.3 neither
    threads ``requests_kwargs`` through ``griddap_initialize``'s metadata call
    nor accepts a ``headers`` dict there at all — its ``_urlopen`` is
    ``lru_cache``-wrapped, so a dict kwarg is an unhashable cache key. We
    replace ``_urlopen`` with an equivalent that always sends our UA (and,
    incidentally, drop a cache of file-like objects that was of little use).
    """
    import io

    import requests as _requests
    import erddapy.core.url as _url_mod

    def _urlopen_with_headers(url: str, auth: tuple | None = None, **kwargs):
        # requests-style (connect, read) pair: hosts that silently drop
        # packets (common blocking behaviour for datacenter IPs) must fail
        # fast on connect instead of burning the full read budget. 3 s is
        # generous for a reachable host; 25 s still covers a real griddap
        # subset of our small bboxes (typically 2-5 s).
        timeout = kwargs.pop("timeout", (3, 25))
        response = _requests.get(
            url,
            allow_redirects=True,
            auth=auth,
            timeout=timeout,
            headers=_USER_AGENT,
            **kwargs,
        )
        try:
            response.raise_for_status()
        except _requests.exceptions.HTTPError as err:
            msg = str(response.content.decode())
            raise _requests.exceptions.HTTPError(msg) from err
        return io.BytesIO(response.content)

    _url_mod._urlopen = _urlopen_with_headers


_install_erddapy_default_headers()


def _axis_end_from_seeded(constraints: dict) -> datetime:
    """Latest time step reported by ``griddap_initialize`` (epoch or ISO)."""
    raw = constraints.get("time>=")
    if raw is None:
        return datetime.now(timezone.utc)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            raw = float(raw)
    return datetime.fromtimestamp(float(raw), tz=timezone.utc)


def _select_nearest_time(da: xr.DataArray, valid_time: datetime) -> xr.DataArray:
    """``.sel(time=..., method='nearest')`` with dtype-safe timestamp handling.

    pandas 3 refuses naive-vs-aware comparisons ("Cannot compare dtypes
    datetime64[ns] and datetime64[us, UTC]"), and ERDDAP axes decode with
    different unit/tz combos per dataset — normalize to the index's own dtype.
    """
    idx = da.indexes["time"]
    ts = pd.Timestamp(valid_time)
    if idx.tz is None:
        ts = ts.tz_convert(timezone.utc).tz_localize(None) if ts.tzinfo else ts
    else:
        ts = ts.tz_convert(idx.tz) if ts.tzinfo else ts.tz_localize(idx.tz)
    return da.sel(time=ts, method="nearest")


def _latest_step_with_data(da: xr.DataArray, valid_time: datetime) -> tuple[xr.DataArray, pd.Timestamp] | None:
    """Most recent time step at or before ``valid_time`` holding ≥1 finite
    pixel in this window, or None when every step is empty.

    Optical ocean-colour products (chlorophyll) are cloud-gated: during the
    monsoon the *nearest* day is routinely 100% masked over the Bay of Bengal
    even though a few days earlier the region was observed. Falling back to
    the latest OBSERVED step — with that step's own timestamp carried in
    provenance — is the honest alternative to reporting "missing" for weeks.
    """
    if "time" not in da.dims or da.sizes["time"] < 2:
        return None
    ts = pd.Timestamp(valid_time)
    idx = da.indexes["time"]
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_convert(idx.tz).tz_localize(None) if idx.tz is None else ts.tz_convert(idx.tz)
    elif idx.tz is not None:
        ts = ts.tz_localize(idx.tz)
    steps = [t for t in idx if t <= ts] or list(idx)  # analyses only look back
    for t in sorted(steps, reverse=True):
        step = da.sel(time=t)
        if float(np.isfinite(step.values.astype(float)).sum()) > 0:
            return step, t
    return None


def _canonicalize(ds: xr.Dataset) -> xr.Dataset:
    """Rename dims/coords to canonical latitude/longitude/time and drop
    leftover single-value axes (altitude/depth/height) from pinning."""
    ren: dict[str, str] = {}
    for names, canonical in (
        (_LAT_NAMES, "latitude"),
        (_LON_NAMES, "longitude"),
        (_TIME_NAMES, "time"),
    ):
        for n in names:
            if n in ds.dims and n != canonical:
                ren[n] = canonical
            elif n in ds.coords and n != canonical:
                ren[n] = canonical
    ds = ds.rename(ren) if ren else ds
    canonical_dims = {"latitude", "longitude", "time"}
    for dim in [d for d in ds.dims if d not in canonical_dims]:
        ds = ds.squeeze(dim, drop=True) if ds.sizes[dim] == 1 else ds.isel({dim: 0}, drop=True)
    return ds


def _unit_of(da: xr.DataArray) -> str:
    attrs = da.attrs
    for key in ("units", "unit"):
        if attrs.get(key):
            return str(attrs[key])
    return "unknown"


class ErddapProvider(OceanDataProvider):
    """One instance per ERDDAP server (configured in erddap_servers.json)."""

    def __init__(self, source_id: str, server_url: str, catalog: DatasetCatalog) -> None:
        self.source_id = source_id
        self.server_url = server_url.rstrip("/")
        self.catalog = catalog
        src: DataSource = source_registry.get(source_id)
        self._source = src
        u = urlsplit(self.server_url)
        self._host_key = u.netloc
        self._host_name = u.hostname or u.netloc
        self._host_port = u.port or (443 if u.scheme == "https" else 80)

    # ------------------------------------------------- host reachability
    def _host_is_down(self) -> bool:
        t = _host_down_at.get(self._host_key)
        return t is not None and (time.monotonic() - t) < _HOST_DOWN_S

    def _mark_host_down(self) -> None:
        _host_down_at[self._host_key] = time.monotonic()

    def _probe_host(self) -> bool:
        """One cheap TCP connect as a reachability preflight, cached.

        A griddap attempt is TWO requests (metadata + data); against a host
        that blackholes a datacenter IP each would burn the full connect or
        read budget. A single 2 s socket check answers "is this host even
        reachable from here" once, and the verdict is shared by every
        variable (and every provider instance) for the host.
        """
        ok_t = _host_probe_ok_at.get(self._host_key)
        if ok_t is not None and (time.monotonic() - ok_t) < _HOST_PROBE_OK_S:
            return True
        try:
            with socket.create_connection((self._host_name, self._host_port), timeout=_PROBE_TIMEOUT_S):
                _host_probe_ok_at[self._host_key] = time.monotonic()
                return True
        except OSError:
            self._mark_host_down()
            logger.warning("ERDDAP host %s unreachable (TCP probe failed) — marked down %ss", self._host_key, int(_HOST_DOWN_S))
            return False

    # ------------------------------------------------------------------ meta
    async def get_available_datasets(self) -> list[dict[str, object]]:
        entries = [e for e in self.catalog.all() if e.source_id == self.source_id]
        return [
            {
                "key": e.key,
                "dataset_id": e.dataset_id,
                "protocol": e.protocol,
                "unit": e.unit,
                "spatial_resolution": e.spatial_resolution,
            }
            for e in entries
        ]

    async def get_dataset_metadata(self, dataset_id: str) -> dict[str, object]:
        def _fetch() -> dict[str, object]:
            e = ERDDAP(server=self.server_url, protocol="griddap")
            e.dataset_id = dataset_id  # erddapy 3.x: attribute, not ctor kwarg
            e.griddap_initialize()
            vars_meta = {v: {"units": e.get_var_attr(v, "units")} for v in e.variables}
            return {
                "source_id": self.source_id,
                "dataset_id": dataset_id,
                "variables": vars_meta,
                "constraints": dict(e.constraints),
            }

        try:
            return await asyncio.to_thread(_fetch)
        except Exception as exc:  # noqa: BLE001 — degrade, never crash the agent
            logger.warning("metadata fetch failed for %s: %s", dataset_id, exc)
            return {"source_id": self.source_id, "dataset_id": dataset_id, "error": str(exc)}

    # ----------------------------------------------------------------- entry
    def _entry(self, variable: str) -> DatasetEntry | None:
        entry = self.catalog.get(variable)
        if entry is None or entry.provider != "erddap" or not entry.dataset_id:
            return None
        if entry.source_id != self.source_id:
            # this server doesn't host the variable — let the hub fall through
            # to the provider that does (never 404-spam other servers)
            return None
        return entry

    def _provenance(self, entry: DatasetEntry, valid_time: datetime) -> Provenance:
        return Provenance(
            source_id=self._source.id,
            source_name=self._source.name,
            dataset=entry.dataset_id,
            valid_time=valid_time,
            unit=entry.unit,
            spatial_resolution=entry.spatial_resolution,
            mode=get_settings().data_mode,
            authority=self._source.authority,
        )

    @staticmethod
    def _freshness_flag(valid_time: datetime, max_age_days: float) -> QualityFlag:
        age = datetime.now(timezone.utc) - valid_time
        return QualityFlag.STALE if age > timedelta(days=max_age_days) else QualityFlag.OK

    # --------------------------------------------------------------- gridded
    def _subset_sync(self, entry: DatasetEntry, bbox: BoundingBox, valid_time: datetime) -> xr.Dataset:
        """Blocking ERDDAP subset -> xarray Dataset (canonical coords).

        The time axis is requested as a WINDOW ending at ``valid_time`` (not a
        single instant): analysis products lag real time (SST ~1 d, archived
        geostrophy ~months), so pinning ``time`` to "tomorrow 05:00" 404s on
        any dataset whose axis ends earlier. ``get_field`` then picks the
        nearest available step, which is what downstream provenance reports.
        """
        protocol = entry.protocol or "griddap"
        e = ERDDAP(server=self.server_url, protocol=protocol)
        if self._source.id == "incois-erddap":
            # INCOIS serves an incomplete TLS chain — documented in research
            e.requests_kwargs = {"verify": False}
        # NOTE: assigning dataset_id triggers griddap_initialize (erddapy 3.x
        # property setter) — the .ncml metadata fetch happens right here
        e.dataset_id = entry.dataset_id
        if protocol == "griddap":
            # clamp the requested instant to the axis end (analysis products
            # lag real time by hours-to-months; ERDDAP 404s when either window
            # edge exceeds the axis maximum), then look back `window_days`
            axis_end = _axis_end_from_seeded(e.constraints)
            end = min(valid_time, axis_end)
            window_days = float((entry.extras or {}).get("window_days", 14))
            start = end - timedelta(days=window_days)
            e.constraints.update(
                {
                    "time>=": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "time<=": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "latitude>=": bbox.south,
                    "latitude<=": bbox.north,
                    "longitude>=": bbox.west,
                    "longitude<=": bbox.east,
                }
            )
            # pin any remaining single-value dims (depth, altitude, zlev...)
            # so griddap returns a plain time/lat/lon cube, not the full column
            extra_dim = (entry.extras or {}).get("extra_dim")
            pinned: dict[str, str] = {}
            if extra_dim:
                name, _, val = str(extra_dim).partition("=")
                pinned = {name.strip(): val.strip()}
            for dim_name in list(e.constraints):
                base = dim_name.split("<")[0].split(">")[0]
                if base in ("time", "latitude", "longitude"):
                    continue
                if base in pinned:
                    try:
                        e.constraints[dim_name] = float(pinned[base])
                    except ValueError:
                        e.constraints[dim_name] = pinned[base]
        if entry.variable:
            e.variables = [entry.variable]
        ds = e.to_xarray()
        return _canonicalize(ds)

    async def get_field(self, variable: str, bbox: BoundingBox, valid_time: datetime) -> OceanField:
        entry = self._entry(variable)
        if entry is None:
            logger.info("no catalog entry for %r on %s", variable, self.source_id)
            return OceanField.empty(variable, "unknown", self._prov_none(variable), bbox)
        prov = self._provenance(entry, valid_time)
        if self._host_is_down():
            logger.info("ERDDAP host %s skipped (recent failure)", self._host_key)
            return OceanField.empty(variable, entry.unit or "unknown", prov, bbox)
        try:
            if not await asyncio.to_thread(self._probe_host):
                return OceanField.empty(variable, entry.unit or "unknown", prov, bbox)
            ds = await asyncio.to_thread(self._subset_sync, entry, bbox, valid_time)
        except Exception as exc:  # noqa: BLE001
            if _is_transport_failure(exc):
                self._mark_host_down()
                logger.warning("ERDDAP transport failure on %s — host marked down %ss", self._host_key, int(_HOST_DOWN_S))
            logger.warning("ERDDAP subset failed (%s/%s): %s", entry.dataset_id, variable, exc)
            return OceanField.empty(variable, entry.unit or "unknown", prov, bbox)
        if entry.variable not in ds:
            return OceanField.empty(variable, entry.unit or "unknown", prov, bbox)
        da = ds[entry.variable]
        if "time" in da.dims and da.sizes["time"] > 1:
            # nearest available step to the requested valid time (analysis
            # products resolve to their latest ≤ valid_time; forecasts to the
            # requested hour) — provenance.valid_time reports what we actually
            # got, not what was asked for
            da = _select_nearest_time(da, valid_time)
            if not bool(np.isfinite(da.values.astype(float)).any()):
                # the nearest day is fully masked (cloud-gated optical data) —
                # fall back to the latest day with real pixels and date it
                fallback = _latest_step_with_data(ds[entry.variable], valid_time)
                if fallback is not None:
                    da, used_t = fallback
                    prov.valid_time = (
                        used_t.to_pydatetime().replace(tzinfo=timezone.utc)
                        if used_t.tzinfo is None
                        else used_t.tz_convert(timezone.utc).to_pydatetime()
                    )
                    logger.info(
                        "%s: nearest step fully masked — using latest observed step %s",
                        variable, used_t,
                    )
        unit = _unit_of(da)
        return OceanField(variable, unit if unit != "unknown" else (entry.unit or "unknown"), da, prov, bbox)

    def _prov_none(self, variable: str) -> Provenance:
        return Provenance(
            source_id=self._source.id,
            source_name=self._source.name,
            dataset=None,
            valid_time=None,
            mode=get_settings().data_mode,
            authority=self._source.authority,
            notes=f"no catalog entry for {variable!r} on {self.source_id}",
        )

    # ----------------------------------------------------------------- point
    async def _point(self, variable: str, lat: float, lon: float, valid_time: datetime) -> Measurement:
        """Sample a small window around (lat, lon) and take the nearest cell."""
        pad = 0.75  # degrees — small window keeps the download tiny
        bbox = BoundingBox(south=lat - pad, north=lat + pad, west=lon - pad, east=lon + pad)
        field = await self.get_field(variable, bbox, valid_time)
        prov = field.provenance
        if field.is_empty:
            return Measurement(
                variable=variable,
                value=None,
                unit=field.unit,
                provenance=prov,
                quality=QualityFlag.MISSING,
                notes="no data in ERDDAP window",
            )
        try:
            da = field.data
            if "time" in da.dims and da.sizes["time"] > 1:
                da = _select_nearest_time(da, valid_time)
            pt = da.sel(latitude=lat, longitude=lon, method="nearest")
            value = float(np.asarray(pt.values).squeeze())
            used_time = pd.Timestamp(da["time"].values).to_pydatetime() if "time" in da.dims else valid_time
            flag = self._freshness_flag(used_time, max_age_days=3.0)
            prov.valid_time = used_time if used_time.tzinfo else used_time.replace(tzinfo=timezone.utc)
            return Measurement(
                variable=variable,
                value=None if not np.isfinite(value) else value,
                unit=field.unit,
                provenance=prov,
                quality=flag if np.isfinite(value) else QualityFlag.MISSING,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("point sampling failed for %s: %s", variable, exc)
            return Measurement(
                variable=variable,
                value=None,
                unit=field.unit,
                provenance=prov,
                quality=QualityFlag.MISSING,
                notes=f"sampling failed: {exc}",
            )

    async def get_sst(self, lat: float, lon: float, valid_time: datetime) -> Measurement:
        return await self._point("sst", lat, lon, valid_time)

    async def get_chlorophyll(self, lat: float, lon: float, valid_time: datetime) -> Measurement:
        return await self._point("chlorophyll", lat, lon, valid_time)

    async def get_currents(self, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        return [
            await self._point("current_u", lat, lon, valid_time),
            await self._point("current_v", lat, lon, valid_time),
        ]

    async def get_wave_data(self, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        return [await self._point("wave_height", lat, lon, valid_time)]

    async def get_ocean_forecast(
        self, lat: float, lon: float, start: datetime, end: datetime
    ) -> list[Measurement]:
        """Forecast series: reuse field window across the requested hours."""
        raise NotImplementedError("forecast series lands with the demo/live forecast providers")
