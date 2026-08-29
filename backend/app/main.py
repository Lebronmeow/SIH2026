"""ORCA FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import advisory, health, ocean, safety, voice
from app.config.registry import registry
from app.config.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("orca")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ORCA API",
        version="0.1.0",
        summary="Marine Ecosystem Reasoning with Collaborative Agents (SIH26176)",
        description=(
            "Agentic marine decision-support for Indian fishermen. "
            "LLM agents reason and explain; deterministic engines retrieve, "
            "compute and verify. Scientific values always carry provenance."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api", tags=["system"])
    app.include_router(advisory.router)
    app.include_router(ocean.router)
    app.include_router(safety.router)
    app.include_router(voice.router)

    logger.info(
        "ORCA starting: mode=%s llm=%s sources=%d",
        settings.data_mode.value,
        settings.llm_provider.value if settings.llm_enabled else "none (deterministic pipeline)",
        len(registry.all()),
    )
    return app


app = create_app()
