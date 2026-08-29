"""Schemas for the recommendation workflow output (machine-readable)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.engines.geospatial.safety import GeofenceResult
from app.engines.scoring.engine import ScoreBreakdown
from app.schemas.common import Evidence, GeoJSONFeature, InsufficiencyReason, Measurement, Provenance, Warning


class Origin(BaseModel):
    place: str
    lat: float
    lon: float
    resolver: str  # which service resolved the place name
    resolver_note: str | None = None


class TimeWindow(BaseModel):
    start: datetime
    end: datetime


class ParsedQuery(BaseModel):
    """Strict structured output of the Query Understanding Agent."""

    intent: str = "find_safe_productive_zone"
    origin: Origin | None = None
    distance_km: float | None = None
    distance_range_km: tuple[float, float] | None = None
    time_window: TimeWindow | None = None
    objectives: list[str] = Field(default_factory=lambda: ["high_productivity", "low_risk"])
    vessel: dict[str, Any] | None = None
    safety_constraints: list[str] = Field(default_factory=list)
    raw_text: str = ""
    language: str = "en"
    notes: str | None = None


class ZoneCandidate(BaseModel):
    id: str
    lat: float
    lon: float
    bearing_deg: float
    distance_from_origin_km: float


class ZoneEvaluation(BaseModel):
    candidate: ZoneCandidate
    score: ScoreBreakdown
    measurements: list[Measurement] = Field(default_factory=list)
    front_strength: dict[str, float | None] = Field(default_factory=dict)
    geofence: GeofenceResult | None = None
    distance_to_boundary_km: float | None = None
    excluded: bool = False
    exclusion_reason: str | None = None
    rank: int | None = None


class RouteOut(BaseModel):
    mode: str
    coords: list[tuple[float, float]]  # (lon, lat)
    distance_km: float
    estimated_time_h: float
    hazard_stats: dict[str, float | None] = Field(default_factory=dict)
    blocked_by_constraints: bool = False
    notes: list[str] = Field(default_factory=list)


class WorkflowTrace(BaseModel):
    """Deterministic record of what the workflow executed (for the UI/verifier)."""

    steps: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None


class RecommendationResponse(BaseModel):
    request_id: str
    parsed_query: ParsedQuery
    mode: str  # live | demo
    demo_banner_required: bool
    generated_at: datetime
    valid_time: datetime | None = None
    data_available: dict[str, bool] = Field(default_factory=dict)
    zones: list[ZoneEvaluation] = Field(default_factory=list)
    recommended: ZoneEvaluation | None = None
    route: RouteOut | None = None
    map_layers: list[GeoJSONFeature] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    sources: list[Provenance] = Field(default_factory=list)
    insufficient: InsufficiencyReason | None = None
    explanation: str | None = None  # LLM narrative when enabled; template otherwise
    trace: WorkflowTrace | None = None
