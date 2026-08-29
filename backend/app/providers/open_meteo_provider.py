"""Open-Meteo marine/weather provider — free, no-API-key forecast data.

Used for wind and wave **forecasts** at a point (the ERDDAP historical/nowcast
catalog complements it). Open-Meteo's free tier requires no key for
non-commercial use; the attribution requirement is recorded in the registry.

Requests are plain HTTP JSON (httpx), so this provider is fully async.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.config.registry import registry
from app.config.settings import get_settings
from app.providers.base import OceanDataProvider, ProviderError
from app.schemas.common import BoundingBox, Measurement, Provenance, QualityFlag

logger = logging.getLogger(__name__)

_HOURLY_MARINE = ["wave_height", "wave_period", "wave_direction", "sea_surface_temperature"]
_HOURLY_WEATHER = ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "precipitation"]


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
        return [
            Measurement(
                variable="current_u", value=None, unit="m s-1",
                provenance=self._prov("marine", valid_time),
                quality=QualityFlag.MISSING, notes="not offered by this provider",
            ),
            Measurement(
                variable="current_v", value=None, unit="m s-1",
                provenance=self._prov("marine", valid_time),
                quality=QualityFlag.MISSING, notes="not offered by this provider",
            ),
        ]

    async def get_ocean_forecast(self, lat: float, lon: float, start: datetime, end: datetime) -> list[Measurement]:
        raise ProviderError("use get_wave_data/get_wind per timestamp")

    async def get_field(self, variable: str, bbox: BoundingBox, valid_time: datetime) -> object:
        raise ProviderError("Open-Meteo is point-based; use ERDDAP/Demo providers for fields")
