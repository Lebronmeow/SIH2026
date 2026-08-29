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
from datetime import datetime, timedelta, timezone

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


def _canonicalize(ds: xr.Dataset) -> xr.Dataset:
    """Rename dims/coords to canonical latitude/longitude/time."""
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
    return ds.rename(ren) if ren else ds


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
            e = ERDDAP(server=self.server_url, protocol="griddap", dataset_id=dataset_id)
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
        """Blocking ERDDAP subset -> xarray Dataset (canonical coords)."""
        protocol = entry.protocol or "griddap"
        e = ERDDAP(server=self.server_url, protocol=protocol, dataset_id=entry.dataset_id)
        if self._source.id == "incois-erddap":
            # INCOIS serves an incomplete TLS chain — documented in research
            e.requests_kwargs = {"verify": False}
        if protocol == "griddap":
            e.griddap_initialize()
            day = valid_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            e.constraints.update(
                {
                    "time<=": day,
                    "time>=": day,
                    "latitude>=": bbox.south,
                    "latitude<=": bbox.north,
                    "longitude>=": bbox.west,
                    "longitude<=": bbox.east,
                }
            )
            # pin any remaining single-value dims (depth, altitude, zlev...)
            # so griddap returns a plain time/lat/lon cube, not the full column
            pinned = dict(entry.extras.get("extra_dim", "").split("=", 1)) if entry.extras.get("extra_dim") else {}
            for dim_name in list(e.constraints):
                base = dim_name.split("<")[0].split(">")[0]
                if base in ("time", "latitude", "longitude"):
                    continue
                if base in pinned:
                    try:
                        e.constraints[dim_name] = float(pinned[base])
                    except ValueError:
                        e.constraints[dim_name] = pinned[base]
                elif str(dim_name).endswith("="):
                    # "<dim>=" (equals form) keeps the first slice of that axis
                    continue
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
        try:
            ds = await asyncio.to_thread(self._subset_sync, entry, bbox, valid_time)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ERDDAP subset failed (%s/%s): %s", entry.dataset_id, variable, exc)
            return OceanField.empty(variable, entry.unit or "unknown", prov, bbox)
        if entry.variable not in ds:
            return OceanField.empty(variable, entry.unit or "unknown", prov, bbox)
        da = ds[entry.variable]
        return OceanField(variable, _unit_of(da) if _unit_of(da) != "unknown" else (entry.unit or "unknown"), da, prov, bbox)

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
            if "time" in da.dims:
                da = da.sel(time=valid_time, method="nearest")
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
