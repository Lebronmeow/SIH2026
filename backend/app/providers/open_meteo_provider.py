"""Open-Meteo marine/weather provider — free, no-API-key forecast data.

Used for wind and wave **forecasts** at a point (the ERDDAP historical/nowcast
catalog complements it). Open-Meteo's free tier requires no key for
non-commercial use; the attribution requirement is recorded in the registry.

Requests are plain HTTP JSON (httpx), so this provider is fully async.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

import httpx
import numpy as np
import xarray as xr

from app.config.registry import registry
from app.config.settings import get_settings
from app.providers.base import OceanDataProvider, OceanField, ProviderError
from app.schemas.common import BoundingBox, Measurement, Provenance, QualityFlag

logger = logging.getLogger(__name__)

_HOURLY_MARINE = [
    "wave_height", "wave_period", "wave_direction", "sea_surface_temperature",
    "ocean_current_velocity", "ocean_current_direction",
]
_HOURLY_WEATHER = ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "precipitation"]

# LIVE-mode gridded fallback: variables this provider can stand in for when
# the primary ERDDAP source is unreachable (e.g. PacIOOS outage, or ERDDAP
# hosts that block datacenter IPs — the Render free tier hits both).
_FIELD_FALLBACK_VARS = ("wind_u", "wind_v", "wave_height", "sst", "current_u", "current_v")
_WIND_DERIVATION_NOTE = (
    "wind components derived from the provider's wind_speed + wind_direction "
    "via the standard meteorological decomposition u = -V·sin(θ), v = -V·cos(θ) "
    "(θ = direction the wind blows FROM) — same observation, vector form"
)
_CURRENT_DERIVATION_NOTE = (
    "current components derived from the provider's ocean_current_velocity + "
    "ocean_current_direction via u = V·sin(θ), v = V·cos(θ) (θ = direction the "
    "current flows TOWARD, 0°=N, 90°=E — oceanographic convention, km/h "
    "converted to m s-1); provider resolution ~8 km, indicative near coasts"
)
_FIELD_LATTICE_STEP_DEG = 0.25
_FIELD_LATTICE_MAX_N = 12  # per axis; 12x12 = 144 points, within API limits


def _pick(series: dict[str, list], name: str, idx: int) -> float | None:
    vals = series.get(name)
    if not vals or idx >= len(vals):
        return None
    v = vals[idx]
    return float(v) if v is not None else None


class OpenMeteoProvider(OceanDataProvider):
    source_id = "open-meteo"

    def __init__(self) -> None:
        settings = get_settings()
        self._base = settings.open_meteo_base_url
        self._marine_base = settings.open_meteo_marine_base_url
        self._source = registry.get(self.source_id)

    def _prov(self, dataset: str, valid_time: datetime) -> Provenance:
        return Provenance(
            source_id=self._source.id,
            source_name=self._source.name,
            dataset=dataset,
            valid_time=valid_time,
            mode=get_settings().data_mode,
            authority=self._source.authority,
        )

    @staticmethod
    def _hour_index(times: list[str], target: datetime) -> int:
        """Index of the hourly step closest to target (times are ISO strings)."""
        parsed = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in times]
        target = target if target.tzinfo else target.replace(tzinfo=timezone.utc)
        return min(range(len(parsed)), key=lambda i: abs(parsed[i] - target))

    async def _fetch_marine(self, lat: float, lon: float) -> dict:
        params = {"latitude": lat, "longitude": lon, "hourly": ",".join(_HOURLY_MARINE), "timezone": "UTC"}
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(self._marine_base, params=params)
            r.raise_for_status()
            return r.json()

    async def _fetch_weather(self, lat: float, lon: float) -> dict:
        params = {"latitude": lat, "longitude": lon, "hourly": ",".join(_HOURLY_WEATHER), "timezone": "UTC"}
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(self._base, params=params)
            r.raise_for_status()
            return r.json()

    async def get_wave_data(self, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        try:
            data = await self._fetch_marine(lat, lon)
        except Exception as exc:  # noqa: BLE001
            logger.warning("open-meteo marine fetch failed: %s", exc)
            unit_by_var = {"wave_height": "m", "wave_period": "s", "wave_direction": "°"}
            return [
                Measurement(variable=v, value=None, unit=u, provenance=self._prov("marine", valid_time), quality=QualityFlag.MISSING)
                for v, u in unit_by_var.items()
            ]
        idx = self._hour_index(data["hourly"]["time"], valid_time)
        out = []
        for var, unit in (("wave_height", "m"), ("wave_period", "s"), ("wave_direction", "°")):
            out.append(
                Measurement(
                    variable=var,
                    value=_pick(data["hourly"], var, idx),
                    unit=unit,
                    provenance=self._prov("marine", valid_time),
                    quality=QualityFlag.OK,
                )
            )
        return out

    async def get_wind(self, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        try:
            data = await self._fetch_weather(lat, lon)
        except Exception as exc:  # noqa: BLE001
            logger.warning("open-meteo weather fetch failed: %s", exc)
            unit_by_var = {"wind_speed": "km/h", "wind_direction": "°", "wind_gust": "km/h"}
            return [
                Measurement(variable=v, value=None, unit=u, provenance=self._prov("forecast", valid_time), quality=QualityFlag.MISSING)
                for v, u in unit_by_var.items()
            ]
        idx = self._hour_index(data["hourly"]["time"], valid_time)
        out = []
        for src_var, var, unit, factor in (
            ("wind_speed_10m", "wind_speed", "km/h", 1.0),
            ("wind_direction_10m", "wind_direction", "°", 1.0),
            ("wind_gusts_10m", "wind_gust", "km/h", 1.0),
        ):
            raw = _pick(data["hourly"], src_var, idx)
            out.append(
                Measurement(
                    variable=var,
                    value=None if raw is None else raw * factor,
                    unit=unit,
                    provenance=self._prov("forecast", valid_time),
                    quality=QualityFlag.OK,
                )
            )
        return out

    # ----------------------------------------------------------------- fields
    @staticmethod
    def _lattice(bbox: BoundingBox) -> tuple[list[float], list[float]]:
        """Deterministic sample grid over ``bbox`` (≥2 points per axis)."""
        def axis(lo: float, hi: float) -> list[float]:
            n = int(round((hi - lo) / _FIELD_LATTICE_STEP_DEG)) + 1
            n = max(2, min(n, _FIELD_LATTICE_MAX_N))
            return [round(lo + (hi - lo) * i / (n - 1), 4) for i in range(n)]
        return axis(bbox.south, bbox.north), axis(bbox.west, bbox.east)

    async def _lattice_field(self, variable: str, bbox: BoundingBox, valid_time: datetime) -> OceanField:
        """Gridded fallback built from point forecasts over a fixed lattice.

        Serves as the LIVE fallback when the ERDDAP source for a gridded
        variable is down. One multi-coordinate HTTP request per call; values
        are the provider's own — vector components are decomposed from the
        provider's speed+direction by documented formulas (no invented
        numbers), with the derivation recorded in provenance.
        """
        use_weather = variable in ("wind_u", "wind_v")
        lats, lons = self._lattice(bbox)
        prov = self._prov("forecast" if use_weather else "marine", valid_time)
        unit = {"wave_height": "m", "sst": "°C"}.get(variable, "m s-1")
        # Open-Meteo pairs multi-coordinate lists element-wise, so the lat/lon
        # cartesian product is expanded into explicit point pairs up front.
        pairs = [(la, lo) for la in lats for lo in lons]
        params: dict[str, str] = {
            "latitude": ",".join(str(la) for la, _ in pairs),
            "longitude": ",".join(str(lo) for _, lo in pairs),
            "hourly": (
                "wind_speed_10m,wind_direction_10m" if use_weather
                else "wave_height" if variable == "wave_height"
                else "sea_surface_temperature" if variable == "sst"
                else "ocean_current_velocity,ocean_current_direction"
            ),
            "timezone": "UTC",
        }
        if use_weather:
            params["wind_speed_unit"] = "ms"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(self._base if use_weather else self._marine_base, params=params)
                r.raise_for_status()
        except Exception as exc:  # noqa: BLE001 — degrade like any other source
            logger.warning("open-meteo lattice field %s failed: %s", variable, exc)
            return OceanField.empty(variable, unit, prov, bbox)

        items = r.json() if isinstance(r.json(), list) else [r.json()]
        grid = np.full((len(lats), len(lons)), np.nan)
        lat_ix = {v: i for i, v in enumerate(lats)}
        lon_ix = {v: i for i, v in enumerate(lons)}
        # Vector families: wind blows FROM θ (u = -V·sinθ), currents flow
        # TOWARD θ (u = +V·sinθ). Open-Meteo currents are km/h → m s-1.
        is_vector = variable in ("wind_u", "wind_v", "current_u", "current_v")
        speed_var = "wind_speed_10m" if use_weather else "ocean_current_velocity"
        dir_var = "wind_direction_10m" if use_weather else "ocean_current_direction"
        sign, scale = (-1.0, 1.0) if use_weather else (1.0, 1.0 / 3.6)

        def extract(hourly: dict[str, list], idx: int) -> float | None:
            if not is_vector:
                src = "wave_height" if variable == "wave_height" else "sea_surface_temperature"
                return _pick(hourly, src, idx)
            speed = _pick(hourly, speed_var, idx)
            direction = _pick(hourly, dir_var, idx)
            if speed is None or direction is None:
                return None
            rad = math.radians(direction)
            u = sign * speed * scale * math.sin(rad)
            v = sign * speed * scale * math.cos(rad)
            return u if variable.endswith("_u") else v

        n_filled = 0
        for item in items:
            try:
                if item.get("hourly") is None:
                    continue
                idx = self._hour_index(item["hourly"]["time"], valid_time)
                value = extract(item["hourly"], idx)
                i = lat_ix.get(min(lats, key=lambda v: abs(v - float(item["latitude"]))))
                j = lon_ix.get(min(lons, key=lambda v: abs(v - float(item["longitude"]))))
                if value is not None and i is not None and j is not None:
                    grid[i, j] = value
                    n_filled += 1
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("open-meteo lattice point skipped: %s", exc)
        if n_filled == 0:
            return OceanField.empty(variable, unit, prov, bbox)
        da = xr.DataArray(grid, coords={"latitude": lats, "longitude": lons}, dims=("latitude", "longitude"))
        if variable in ("wind_u", "wind_v"):
            prov.notes = _WIND_DERIVATION_NOTE
        elif variable in ("current_u", "current_v"):
            prov.notes = _CURRENT_DERIVATION_NOTE
        else:
            prov.notes = "fallback grid from point forecasts"
        return OceanField(variable, unit, da, prov, bbox)

    async def get_field(self, variable: str, bbox: BoundingBox, valid_time: datetime) -> OceanField:
        if variable not in _FIELD_FALLBACK_VARS:
            raise ProviderError("Open-Meteo is point-based; use ERDDAP/Demo providers for fields")
        return await self._lattice_field(variable, bbox, valid_time)

    # ---- interface completeness: Open-Meteo is forecast-only -------------
    async def get_available_datasets(self) -> list[dict[str, object]]:
        return [
            {"key": "wind", "dataset_id": "forecast", "unit": "km/h"},
            {"key": "wave_height", "dataset_id": "marine", "unit": "m"},
        ]

    async def get_dataset_metadata(self, dataset_id: str) -> dict[str, object]:
        return {"source_id": self.source_id, "dataset_id": dataset_id, "variables": _HOURLY_MARINE + _HOURLY_WEATHER}

    async def get_sst(self, lat: float, lon: float, valid_time: datetime) -> Measurement:
        try:
            data = await self._fetch_marine(lat, lon)
            idx = self._hour_index(data["hourly"]["time"], valid_time)
            return Measurement(
                variable="sst",
                value=_pick(data["hourly"], "sea_surface_temperature", idx),
                unit="°C",
                provenance=self._prov("marine", valid_time),
                quality=QualityFlag.OK,
            )
        except Exception as exc:  # noqa: BLE001
            return Measurement(
                variable="sst", value=None, unit="°C",
                provenance=self._prov("marine", valid_time),
                quality=QualityFlag.MISSING, notes=str(exc),
            )

    async def get_chlorophyll(self, lat: float, lon: float, valid_time: datetime) -> Measurement:
        return Measurement(
            variable="chlorophyll", value=None, unit="mg m-3",
            provenance=self._prov("marine", valid_time),
            quality=QualityFlag.MISSING, notes="not offered by this provider",
        )

    async def get_currents(self, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        try:
            data = await self._fetch_marine(lat, lon)
            idx = self._hour_index(data["hourly"]["time"], valid_time)
            speed = _pick(data["hourly"], "ocean_current_velocity", idx)
            direction = _pick(data["hourly"], "ocean_current_direction", idx)
            if speed is None or direction is None:
                raise ValueError("currents absent at this point/time")
            rad = math.radians(direction)
            # direction the current flows TOWARD (0°=N, 90°=E); km/h → m s-1
            u = (speed / 3.6) * math.sin(rad)
            v = (speed / 3.6) * math.cos(rad)
            out = []
            for var, val in (("current_u", u), ("current_v", v)):
                m = Measurement(
                    variable=var, value=val, unit="m s-1",
                    provenance=self._prov("marine", valid_time),
                    quality=QualityFlag.OK,
                )
                m.provenance.notes = _CURRENT_DERIVATION_NOTE
                out.append(m)
            return out
        except Exception as exc:  # noqa: BLE001
            return [
                Measurement(
                    variable=var, value=None, unit="m s-1",
                    provenance=self._prov("marine", valid_time),
                    quality=QualityFlag.MISSING, notes=str(exc),
                )
                for var in ("current_u", "current_v")
            ]

    async def get_ocean_forecast(self, lat: float, lon: float, start: datetime, end: datetime) -> list[Measurement]:
        raise ProviderError("use get_wave_data/get_wind per timestamp")
