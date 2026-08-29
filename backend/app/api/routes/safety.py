"""Safety + routing API — deterministic geospatial engine, no LLM anywhere."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config.settings import get_settings
from app.engines.geospatial.safety import GeospatialSafetyEngine
from app.engines.routing.engine import RouteOptimizationEngine
from app.schemas.common import LatLon

router = APIRouter(prefix="/api", tags=["safety"])

_safety = GeospatialSafetyEngine.from_directory(get_settings().boundaries_dir)
_routing: RouteOptimizationEngine | None = None


def get_routing() -> RouteOptimizationEngine:
    global _routing
    if _routing is None:
        _routing = RouteOptimizationEngine(_safety)
    return _routing


class SafetyCheckRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


@router.post("/safety/check")
async def safety_check(req: SafetyCheckRequest) -> dict:
    """Geofence verdict for a point (MPA / restricted / IMBL / land)."""
    geofence = _safety.check_geofence(LatLon(lat=req.lat, lon=req.lon))
    return {
        "lat": req.lat,
        "lon": req.lon,
        "ok": geofence.ok,
        "inside_mpa": geofence.inside_mpa,
        "inside_restricted": geofence.inside_restricted,
        "imbl_violation": geofence.inside_imbl_violation,
        "on_land": geofence.on_land,
        "distance_to_imbl_km": round(geofence.distance_to_imbl_m / 1000.0, 3) if geofence.distance_to_imbl_m is not None else None,
        "warnings": [w.model_dump(mode="json") for w in geofence.warnings],
    }


class OptimizeRouteRequest(BaseModel):
    from_lat: float = Field(..., ge=-90, le=90)
    from_lon: float = Field(..., ge=-180, le=180)
    to_lat: float = Field(..., ge=-90, le=90)
    to_lon: float = Field(..., ge=-180, le=180)
    mode: str = Field("safe", pattern="^(shortest|safe|fuel|risk_optimal)$")


@router.post("/route/optimize")
async def optimize_route(req: OptimizeRouteRequest) -> dict:
    """Risk-aware A* route between two points (hard constraints absolute)."""
    origin = LatLon(lat=req.from_lat, lon=req.from_lon)
    dest = LatLon(lat=req.to_lat, lon=req.to_lon)
    if abs(origin.lat - dest.lat) < 1e-6 and abs(origin.lon - dest.lon) < 1e-6:
        raise HTTPException(status_code=422, detail="origin and destination are identical")
    try:
        if req.mode == "shortest":
            route = get_routing().calculate_shortest_route(origin, dest)
        elif req.mode == "fuel":
            route = get_routing().calculate_fuel_optimal_route(origin, dest)
        elif req.mode == "risk_optimal":
            route = get_routing().calculate_risk_optimal_route(origin, dest)
        else:
            route = get_routing().calculate_safe_route(origin, dest)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"routing failed: {exc}") from exc

    safety = _safety.check_route_safety([(c.lon, c.lat) for c in route.coords])
    return {
        "mode": route.mode,
        "coords": [[round(c.lon, 5), round(c.lat, 5)] for c in route.coords],
        "distance_km": round(route.distance_km, 2),
        "estimated_time_h": round(route.estimated_time_h, 2),
        "hazard_stats": route.hazard_stats,
        "blocked_by_constraints": route.blocked_by_constraints or (not safety.ok),
        "route_safety": {
            "ok": safety.ok,
            "crosses_imbl": safety.crosses_imbl,
            "crosses_restricted": safety.crosses_restricted,
            "crosses_land": safety.crosses_land,
            "min_imbl_distance_km": round(safety.min_imbl_distance_m / 1000.0, 3) if safety.min_imbl_distance_m is not None else None,
        },
    }
