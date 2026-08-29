"""DemoOceanProvider — serves a cached data pack from ``data/demo/``.

DEMO MODE IS VISIBLE BY DESIGN: every measurement this provider returns is
flagged ``mode="demo"`` and quality ``stale`` (with a truthful note). The API
layer surfaces the demo banner; nothing here may be presented as live data.

Pack layout (see scripts/fetch_demo_data.py, which builds it from REAL data)::

    data/demo/<pack>/
      manifest.json                     # provenance + retrieval dates + sources
      ocean/{sst,chlorophyll,...}.nc    # cached real gridded fields (canonical dims)
      weather/{wind,waves}.json         # cached Open-Meteo responses (API shape)
      boundaries/*.geojson              # reference boundary layers
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from app.providers.base import OceanField, OceanDataProvider
from app.providers.erddap_provider import _canonicalize, _unit_of
from app.schemas.common import (
    BoundingBox,
    Measurement,
    Provenance,
    QualityFlag,
)
from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_VARIABLE_FILES = {
    "sst": "ocean/sst.nc",
    "chlorophyll": "ocean/chlorophyll.nc",
    "current_u": "ocean/current_u.nc",
    "current_v": "ocean/current_v.nc",
    "wave_height": "ocean/wave_height.nc",
}


class DemoOceanProvider(OceanDataProvider):
    source_id = "demo-pack"

    def __init__(self, demo_dir: Path | str) -> None:
        self.demo_dir = Path(demo_dir)
        self._packs: dict[str, Path] = {
            p.name: p for p in self.demo_dir.iterdir() if p.is_dir()
        } if self.demo_dir.exists() else {}
        if not self._packs:
            logger.warning("DEMO mode but no packs under %s — all lookups will be MISSING", self.demo_dir)
        self.default_pack: str | None = next(iter(self._packs), None)

    # ------------------------------------------------------------------ pack
    def _pack_path(self, pack: str | None) -> Path:
        name = pack or self.default_pack
        if name is None or name not in self._packs:
            raise FileNotFoundError(f"demo pack {name!r} not found in {self.demo_dir}")
        return self._packs[name]

    @staticmethod
    @lru_cache(maxsize=8)
    def _manifest(pack_path: str) -> dict:
        p = Path(pack_path) / "manifest.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {}

    @staticmethod
    @lru_cache(maxsize=16)
    def _load_nc(file_path: str) -> xr.Dataset:
        ds = xr.open_dataset(file_path)
        return _canonicalize(ds)

    def _pack_prov(self, variable: str, pack: Path) -> Provenance:
        manifest = self._manifest(str(pack))
        var_meta = (manifest.get("variables") or {}).get(variable, {})
        settings = get_settings()
        retrieved = manifest.get("retrieved_at")
        return Provenance(
            source_id=str(var_meta.get("source_id", manifest.get("source_id", "demo-pack"))),
            source_name=str(var_meta.get("source_name", manifest.get("source_name", "cached demo pack"))),
            dataset=var_meta.get("dataset_id"),
            retrieved_at=datetime.fromisoformat(retrieved) if retrieved else datetime.now(timezone.utc),
            valid_time=None,
            unit=var_meta.get("unit"),
            spatial_resolution=var_meta.get("spatial_resolution"),
            mode=settings.data_mode,
            notes="DEMO/CACHED data — originally retrieved " + str(retrieved or "unknown date"),
        )

    # ----------------------------------------------------------------- field
    async def get_field(self, variable: str, bbox: BoundingBox, valid_time: datetime) -> OceanField:
        pack = self._pack_path(None)
        rel = _VARIABLE_FILES.get(variable)
        file = pack / rel if rel else None
        prov = self._pack_prov(variable, pack)
        if file is None or not file.exists():
            return OceanField.empty(variable, "unknown", prov, bbox)
        ds = self._load_nc(str(file))
        var_name = variable if variable in ds else (list(ds.data_vars)[0] if ds.data_vars else None)
        if var_name is None:
            return OceanField.empty(variable, "unknown", prov, bbox)
        da = ds[var_name]
        if "latitude" in da.dims and "longitude" in da.dims:
            lat_slice = slice(bbox.south, bbox.north)
            lon_slice = slice(bbox.west, bbox.east)
            da = da.sel(latitude=lat_slice, longitude=lon_slice)
        unit = _unit_of(da)
        if unit == "unknown":
            unit = (self._manifest(str(pack)).get("variables") or {}).get(variable, {}).get("unit", "unknown")
        prov.unit = unit
        return OceanField(variable, unit, da, prov, bbox)

    # ----------------------------------------------------------------- point
    async def _point(self, variable: str, lat: float, lon: float, valid_time: datetime) -> Measurement:
        field = await self.get_field(variable, bbox_for_point(lat, lon), valid_time)
        if field.is_empty:
            return Measurement(
                variable=variable, value=None, unit=field.unit,
                provenance=field.provenance, quality=QualityFlag.MISSING,
                notes="no cached data for this variable",
            )
        da = field.data
        if "time" in da.dims and da.sizes.get("time", 0) > 0:
            da = da.sel(time=valid_time, method="nearest") if da.sizes["time"] > 1 else da.isel(time=0)
        value = float(np.asarray(da.sel(latitude=lat, longitude=lon, method="nearest").values).squeeze())
        prov = field.provenance
        prov.valid_time = (
            pd.Timestamp(da["time"].values).to_pydatetime().replace(tzinfo=timezone.utc)
            if "time" in da.dims
            else valid_time
        )
        return Measurement(
            variable=variable,
            value=value if np.isfinite(value) else None,
            unit=field.unit,
            provenance=prov,
            quality=QualityFlag.STALE,  # cached data is never presented as live
            notes="DEMO/CACHED value",
        )

    async def get_sst(self, lat: float, lon: float, valid_time: datetime) -> Measurement:
        return await self._point("sst", lat, lon, valid_time)

    async def get_chlorophyll(self, lat: float, lon: float, valid_time: datetime) -> Measurement:
        return await self._point("chlorophyll", lat, lon, valid_time)

    async def get_currents(self, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        return [await self._point("current_u", lat, lon, valid_time), await self._point("current_v", lat, lon, valid_time)]

    async def get_wind(self, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        return await self._from_weather_cache("wind", lat, lon, valid_time)

    async def get_wave_data(self, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        cached = await self._from_weather_cache("waves", lat, lon, valid_time)
        if cached and all(m.is_available for m in cached):
            return cached
        fallback = await self._point("wave_height", lat, lon, valid_time)
        return [*cached, fallback] if cached else [fallback]

    async def _from_weather_cache(self, kind: str, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        pack = self._pack_path(None)
        file = pack / "weather" / f"{kind}.json"
        if not file.exists():
            return []
        data = json.loads(file.read_text(encoding="utf-8"))
        prov = self._pack_prov(kind, pack)
        prov.notes = "DEMO/CACHED forecast — retrieved " + str(data.get("retrieved_at", "unknown"))
        hourly = data.get("hourly", {})
        spec = {
            "wind": (("wind_speed", "km/h"), ("wind_direction", "°"), ("wind_gust", "km/h")),
            "waves": (("wave_height", "m"), ("wave_period", "s"), ("wave_direction", "°")),
        }[kind]
        out: list[Measurement] = []
        times = hourly.get("time") or []
        if times:
            parsed = [pd.Timestamp(t).to_pydatetime().replace(tzinfo=timezone.utc) for t in times]
            idx = min(range(len(parsed)), key=lambda i: abs(parsed[i] - valid_time))
            for var, unit in spec:
                vals = hourly.get(_api_name(var)) or []
                value = float(vals[idx]) if idx < len(vals) and vals[idx] is not None else None
                out.append(Measurement(variable=var, value=value, unit=unit, provenance=prov, quality=QualityFlag.STALE))
        return out

    # ------------------------------------------------------------- not served
    async def get_available_datasets(self) -> list[dict[str, object]]:
        if self.default_pack is None:
            return []
        manifest = self._manifest(str(self._pack_path(self.default_pack)))
        return [
            {"key": k, "dataset_id": v.get("dataset_id"), "unit": v.get("unit"), "cached": True}
            for k, v in (manifest.get("variables") or {}).items()
        ]

    async def get_dataset_metadata(self, dataset_id: str) -> dict[str, object]:
        return {"source_id": self.source_id, "dataset_id": dataset_id, "cached": True}

    async def get_ocean_forecast(self, lat: float, lon: float, start: datetime, end: datetime) -> list[Measurement]:
        return []


_API_NAMES = {
    "wind_speed": "wind_speed_10m",
    "wind_direction": "wind_direction_10m",
    "wind_gust": "wind_gusts_10m",
    "wave_height": "wave_height",
    "wave_period": "wave_period",
    "wave_direction": "wave_direction",
}


def _api_name(var: str) -> str:
    return _API_NAMES.get(var, var)


def bbox_for_point(lat: float, lon: float, pad: float = 0.25) -> BoundingBox:
    return BoundingBox(south=lat - pad, north=lat + pad, west=lon - pad, east=lon + pad)
