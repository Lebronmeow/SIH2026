"""OceanDataHub — routes logical-variable requests to the right provider.

The hub is the *only* object agents and engines touch for ocean data:

* Honors ``ORCA_DATA_MODE`` (demo pack vs live providers).
* Wraps provider failures into ``Measurement(quality=MISSING)`` — a data gap is
  a first-class, visible outcome, never a crash and never a fabricated value.
* Records which provider answered via provenance already attached by them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import xarray as xr

from app.config.settings import DataMode, get_settings
from app.providers.base import OceanField, OceanDataProvider
from app.providers.demo_provider import DemoOceanProvider
from app.providers.erddap_provider import ErddapProvider
from app.providers.open_meteo_provider import OpenMeteoProvider
from app.schemas.common import (
    BoundingBox,
    Measurement,
    Provenance,
    QualityFlag,
)

logger = logging.getLogger(__name__)

# Circuit breaker: after a provider failure, skip that (provider, variable)
# pair for this long before retrying. Keeps a dead host (that blackholes
# connections until timeout) from re-taxing every request; the primary
# source is retried after the TTL, so an outage is never permanent.
_FAILURE_TTL_S = 600.0

# Last-good cache: when EVERY live source for a variable fails (host down,
# throttled, fully masked window), the most recent successful field is still
# real data — served with its ORIGINAL provenance (true valid_time and
# retrieved_at) plus an explicit note. Beyond this horizon it is no longer
# representative of today's ocean and the advisory reports MISSING instead.
_LAST_GOOD_TTL_S = 72 * 3600.0


class OceanDataHub:
    def __init__(self) -> None:
        settings = get_settings()
        self.mode = settings.data_mode
        self._erddap: list[ErddapProvider] = []
        self._openmeteo: OpenMeteoProvider | None = None
        self._demo: DemoOceanProvider | None = None

        if self.mode is DataMode.LIVE:
            servers = self._load_servers(settings.erddap_servers_config)
            from app.config.dataset_catalog import load_catalog

            catalog = load_catalog(settings.datasets_config)
            self._erddap = [
                ErddapProvider(server_id, server["url"], catalog)
                for server_id, server in servers
                if server.get("enabled", True)
            ]
            self._openmeteo = OpenMeteoProvider()
            logger.info("hub: LIVE mode with %d erddap server(s)", len(self._erddap))
        else:
            self._demo = DemoOceanProvider(settings.demo_dir)
            logger.info("hub: DEMO mode (cached data pack)")
        self._failures: dict[tuple[str, str], float] = {}
        self._last_good: dict[str, OceanField] = {}

    @staticmethod
    def _load_servers(path) -> list[tuple[str, dict]]:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            servers = raw.get("servers", [])
            servers.sort(key=lambda s: s.get("priority", 99))
            return [(s["id"], s) for s in servers]
        except Exception as exc:  # noqa: BLE001
            logger.warning("cannot read erddap servers config %s: %s", path, exc)
            return []

    # ------------------------------------------------------------- internals
    def _skip(self, source_id: str, variable: str) -> bool:
        """True while a recent failure marks this (provider, variable) down."""
        t = self._failures.get((source_id, variable))
        return t is not None and (time.monotonic() - t) < _FAILURE_TTL_S

    def _mark_failed(self, source_id: str, variable: str) -> None:
        self._failures[(source_id, variable)] = time.monotonic()

    async def _first_ok(self, coros: list, description: str):
        """Run provider calls in priority order; return first non-exception."""
        last_exc: Exception | None = None
        for coro in coros:
            try:
                return await coro
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("%s failed: %s", description, exc)
        if last_exc:
            raise ProviderError(f"{description}: {last_exc}")
        raise ProviderError(f"{description}: no provider configured")

    # -------------------------------------------------------------- point API
    async def get_sst(self, lat: float, lon: float, valid_time: datetime) -> Measurement:
        if self.mode is DataMode.DEMO and self._demo:
            return await self._demo.get_sst(lat, lon, valid_time)
        return await self._first_ok([p.get_sst(lat, lon, valid_time) for p in self._erddap], "get_sst")

    async def get_chlorophyll(self, lat: float, lon: float, valid_time: datetime) -> Measurement:
        if self.mode is DataMode.DEMO and self._demo:
            return await self._demo.get_chlorophyll(lat, lon, valid_time)
        return await self._first_ok(
            [p.get_chlorophyll(lat, lon, valid_time) for p in self._erddap], "get_chlorophyll"
        )

    async def get_wave_data(self, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        if self.mode is DataMode.DEMO and self._demo:
            return await self._demo.get_wave_data(lat, lon, valid_time)
        coros: list = []
        if self._openmeteo:
            coros.append(self._openmeteo.get_wave_data(lat, lon, valid_time))
        coros.extend(p.get_wave_data(lat, lon, valid_time) for p in self._erddap)
        return await self._first_ok(coros, "get_wave_data")  # type: ignore[return-value]

    async def get_wind(self, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        if self.mode is DataMode.DEMO and self._demo:
            return await self._demo.get_wind(lat, lon, valid_time)
        if not self._openmeteo:
            prov = Provenance(source_id="none", source_name="unconfigured", mode=self.mode)
            return [
                Measurement(variable="wind_speed", value=None, unit="km/h", provenance=prov, quality=QualityFlag.MISSING)
            ]
        return await self._openmeteo.get_wind(lat, lon, valid_time)

    async def get_currents(self, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        if self.mode is DataMode.DEMO and self._demo:
            return await self._demo.get_currents(lat, lon, valid_time)
        return await self._first_ok(
            [p.get_currents(lat, lon, valid_time) for p in self._erddap], "get_currents"
        )

    # ------------------------------------------------------------- field API
    async def get_field(self, variable: str, bbox: BoundingBox, valid_time: datetime) -> OceanField:
        if self.mode is DataMode.DEMO and self._demo:
            return await self._demo.get_field(variable, bbox, valid_time)
        for provider in self._erddap:
            if self._skip(provider.source_id, variable):
                logger.info("field %s from %s skipped (recent failure)", variable, provider.source_id)
                continue
            try:
                field = await provider.get_field(variable, bbox, valid_time)
                if not field.is_empty:
                    self._remember(variable, field)
                    return field
                # empty is the provider's degraded return for a failed
                # subset — treat like a transport failure for the breaker
                self._mark_failed(provider.source_id, variable)
                logger.warning("field %s from %s empty (marked down %ss)", variable, provider.source_id, int(_FAILURE_TTL_S))
            except Exception as exc:  # noqa: BLE001
                self._mark_failed(provider.source_id, variable)
                logger.warning("field %s from %s failed: %s (marked down %ss)", variable, provider.source_id, exc, int(_FAILURE_TTL_S))
        # LIVE fallback: an outage on one server (e.g. PacIOOS hosting wind and
        # wave fields) must not blind the whole advisory. Open-Meteo serves
        # wind speed+direction and wave height as point forecasts; the provider
        # builds a deterministic lattice grid from them (derivation documented
        # in provenance). Primary sources are always tried first.
        if self._openmeteo is not None:
            try:
                field = await self._openmeteo.get_field(variable, bbox, valid_time)
                if not field.is_empty:
                    logger.info("field %s served by open-meteo fallback grid", variable)
                    self._remember(variable, field)
                    return field
            except Exception as exc:  # noqa: BLE001
                logger.warning("open-meteo field fallback for %s failed: %s", variable, exc)
        cached = self._serve_cached(variable)
        if cached is not None:
            return cached
        prov = Provenance(source_id="none", source_name="unconfigured", mode=self.mode)
        return OceanField.empty(variable=variable, unit="unknown", provenance=prov, bbox=bbox)

    # ------------------------------------------------------------ last-good
    def _remember(self, variable: str, field: OceanField) -> None:
        """Record a successful field so an outage can still be served the
        last REAL observations (honestly labeled) instead of a bare MISSING."""
        self._last_good[variable] = field

    def _serve_cached(self, variable: str) -> OceanField | None:
        cached = self._last_good.get(variable)
        if cached is None or cached.is_empty or cached.provenance.valid_time is None:
            return None
        vt = cached.provenance.valid_time
        if vt.tzinfo is None:
            vt = vt.replace(tzinfo=timezone.utc)
        age_s = (datetime.now(timezone.utc) - vt).total_seconds()
        if age_s < 0 or age_s > _LAST_GOOD_TTL_S:
            return None
        prov = cached.provenance.model_copy(deep=True)
        note = "live source unreachable — values from the last successful retrieval"
        prov.notes = f"{prov.notes}; {note}" if prov.notes else note
        logger.info("field %s served from last-good cache (%.1f h old)", variable, age_s / 3600.0)
        return replace(cached, provenance=prov)
