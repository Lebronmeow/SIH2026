"""System endpoints: health, mode banner flag, registered data sources."""

from __future__ import annotations

from fastapi import APIRouter

from app.config.registry import registry
from app.config.settings import DataMode, get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "orca", "version": "0.1.0"}


@router.get("/system/status")
def system_status() -> dict[str, object]:
    """Runtime status used by the frontend, including the mandatory
    DEMO/CACHED-DATA banner flag and the LLM reasoning-layer state."""
    settings = get_settings()
    return {
        "mode": settings.data_mode.value,
        # The frontend must render a visible banner when this is true.
        "demo_banner_required": settings.data_mode == DataMode.DEMO,
        "banner_text": (
            "DEMO / CACHED DATA — not live observations"
            if settings.data_mode == DataMode.DEMO
            else None
        ),
        "llm_reasoning_enabled": settings.llm_enabled,
        "llm_provider": settings.llm_provider.value,
        # Validated pilot region: the UI surfaces this as a coverage chip and
        # the backend attaches an outside-region caution to responses whose
        # origin falls outside it.
        "supported_region": {
            "name": settings.supported_region_name,
            "south": settings.supported_region_south,
            "west": settings.supported_region_west,
            "north": settings.supported_region_north,
            "east": settings.supported_region_east,
        },
        "sources": registry.to_public_json(),
    }


@router.get("/system/warm")
async def system_warm() -> dict[str, object]:
    """Keep-alive target for the 5-minute pinger.

    A free-tier host forgets everything on restart, so a ping that only
    wakes the process leaves the data caches cold — the next fisherman then
    waits on every provider at once, and a throttled source shows up as
    MISSING. Pointing the ping HERE instead refreshes the last-good fields
    for every pilot variable while it warms the instance, so outages are
    bridged from recently retrieved REAL data instead of silence. Never
    raises: a failed refresh is reported, not thrown.
    """
    import asyncio
    from datetime import datetime, timezone

    from app.providers.hub import get_hub
    from app.schemas.common import BoundingBox

    settings = get_settings()
    hub = get_hub()
    bbox = BoundingBox(
        south=settings.supported_region_south,
        north=settings.supported_region_north,
        west=settings.supported_region_west,
        east=settings.supported_region_east,
    )
    now = datetime.now(timezone.utc)
    variables = ["sst", "chlorophyll", "wave_height", "wind_u", "wind_v", "current_u", "current_v"]

    async def _one(variable: str) -> str:
        try:
            field = await hub.get_field(variable, bbox, now)
            return "missing" if field.is_empty else "ok"
        except Exception:  # noqa: BLE001 — warming must never fail the ping
            return "missing"

    results = dict(zip(variables, await asyncio.gather(*(_one(v) for v in variables))))
    return {
        "status": "ok",
        "fields": results,
        "ok": sum(1 for v in results.values() if v != "missing"),
        "total": len(variables),
    }
