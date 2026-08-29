"""Ocean data API — thin, provenance-first views over the OceanDataHub."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.config.registry import registry
from app.config.settings import get_settings
from app.providers.hub import OceanDataHub
from app.schemas.common import BoundingBox, Provenance, QualityFlag

router = APIRouter(prefix="/api/ocean", tags=["ocean"])

_HUB: OceanDataHub | None = None


def get_hub() -> OceanDataHub:
    global _HUB
    if _HUB is None:
        _HUB = OceanDataHub(get_settings())
    return _HUB


@router.get("/point")
async def ocean_point(
    variable: str = Query(..., description="sst | chlorophyll | current_u | current_v | wave_height | wind_u | wind_v"),
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    when: str | None = Query(None, description="ISO-8601 valid time (UTC); default now"),
) -> dict:
    """Sample one variable at one point — full provenance, honest MISSING."""
    try:
        valid_time = datetime.fromisoformat(when.replace("Z", "+00:00")) if when else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"bad `when`: {exc}") from exc
    pad = 0.1
    bbox = BoundingBox(south=lat - pad, north=lat + pad, west=lon - pad, east=lon + pad)
    try:
        field = await get_hub().get_field(variable, bbox, valid_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"provider failure: {exc}") from exc
    value = None
    if not field.is_empty:
        da = field.data
        try:
            sel = da.sel(latitude=lat, longitude=lon, method="nearest")
            raw = float(sel.values.reshape(-1)[0]) if sel.ndim else float(sel.values)
            value = raw if math.isfinite(raw) else None
        except Exception:  # noqa: BLE001
            value = None
    prov = field.provenance.model_dump(mode="json") if field.provenance else None
    return {
        "variable": variable,
        "lat": lat,
        "lon": lon,
        "valid_time": (valid_time or datetime.now(timezone.utc)).isoformat(),
        "value": value,
        "unit": field.unit,
        "available": value is not None,
        "quality": ("ok" if value is not None else "missing"),
        "provenance": prov,
        "summary": field.summary(),
    }


@router.get("/fields")
async def ocean_fields(
    south: float = Query(..., ge=-90, le=90),
    north: float = Query(..., ge=-90, le=90),
    west: float = Query(..., ge=-180, le=180),
    east: float = Query(..., ge=-180, le=180),
    variables: str = Query("sst", description="comma-separated variables"),
    when: str | None = None,
) -> dict:
    """Field summaries (never raw grids) for a bbox — used by the map UI."""
    if north <= south or east <= west:
        raise HTTPException(status_code=422, detail="bbox must have north>south and east>west")
    bbox = BoundingBox(south=south, north=north, west=west, east=east)
    valid_time = None
    if when:
        try:
            valid_time = datetime.fromisoformat(when.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"bad `when`: {exc}") from exc
    out = []
    for var in [v.strip() for v in variables.split(",") if v.strip()]:
        try:
            field = await get_hub().get_field(var, bbox, valid_time)
        except Exception as exc:  # noqa: BLE001
            out.append({"variable": var, "available": False, "error": str(exc)})
            continue
        out.append({"variable": var, "available": not field.is_empty, **field.summary()})
    return {"bbox": bbox.model_dump(mode="json"), "fields": out}


@router.get("/sources")
async def ocean_sources() -> dict:
    """DataSourceRegistry + demo-mode banner state (frontend source of truth)."""
    settings = get_settings()
    return {
        "mode": settings.data_mode,
        "demo_banner_required": settings.data_mode == "demo",
        "banner_text": "DEMO / CACHED DATA — not live observations",
        "sources": registry.to_public_json(),
    }
