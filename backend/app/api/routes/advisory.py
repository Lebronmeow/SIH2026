"""Advisory API: natural-language query → evidence-backed recommendation.

POST /api/query is the primary demo endpoint. It runs the full ORCA pipeline
(see app.workflows.advisory / app.agents.orchestrator) and returns the
machine-readable RecommendationResponse including map layers, warnings,
evidence, provenance and the WHY explanation.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.orchestrator import run_advisory
from app.config.settings import get_settings
from app.services.response_store import get_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["advisory"])


class QueryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500, description="Natural-language fishing query")
    language: str = Field(default="en", pattern="^[a-z]{2}(-[A-Za-z]{2})?$")


@router.post("/query")
async def query(req: QueryRequest) -> dict:
    """Full pipeline: parse → retrieve → evaluate → verify → explain."""
    settings = get_settings()
    try:
        response = await run_advisory(req.query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("advisory pipeline failed")
        raise HTTPException(status_code=500, detail=f"advisory pipeline failed: {exc}") from exc
    out = response.model_dump(mode="json")
    out["demo_banner_required"] = out["demo_banner_required"] or settings.data_mode == "demo"
    get_store().put(response)
    return out


@router.get("/recommendations/{request_id}")
async def get_recommendation(request_id: str) -> dict:
    """Re-fetch a previously computed advisory response by request_id."""
    resp = get_store().get(request_id)
    if resp is None:
        raise HTTPException(status_code=404, detail=f"no recommendation {request_id} in this session")
    return resp.model_dump(mode="json")
