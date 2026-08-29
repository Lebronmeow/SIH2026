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
        "sources": registry.to_public_json(),
    }
