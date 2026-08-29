"""Shared, provenance-first schemas used across providers, engines and agents.

Rule: every scientific value leaving a provider or engine is wrapped in a
:class:`Measurement` (or a compact collection of them) carrying explicit units,
quality flags and provenance. Nothing numeric reaches the LLM or the UI bare.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config.registry import Authority
from app.config.settings import DataMode


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Provenance(BaseModel):
    """Where a value came from and how much to trust it."""

    model_config = ConfigDict(json_schema_extra={"example": {
        "source_id": "erddap-noaa",
        "source_name": "NOAA CoastWatch/PFEL ERDDAP",
        "dataset": "nesdisVHNSQchlaDaily",
        "retrieved_at": "2026-08-29T04:12:00Z",
        "valid_time": "2026-08-29T00:00:00Z",
        "spatial_resolution": "0.01°",
        "unit": "mg m-3",
        "confidence": 0.9,
        "mode": "live",
        "notes": None,
    }})

    source_id: str
    source_name: str
    dataset: str | None = None
    retrieved_at: datetime = Field(default_factory=utcnow)
    valid_time: datetime | None = None
    spatial_resolution: str | None = None
    unit: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    mode: DataMode = DataMode.LIVE
    authority: Authority = Authority.DESCRIPTIVE
    notes: str | None = None


class QualityFlag(str, Enum):
    OK = "ok"
    STALE = "stale"  # older than the configured freshness window
    MISSING = "missing"
    INTERPOLATED = "interpolated"
    ESTIMATED = "estimated"


class Measurement(BaseModel):
    """A single scientific value + its provenance. `value is None` means the
    provider had no data — this is a valid, expected outcome and must never be
    replaced by a guess."""

    model_config = ConfigDict(frozen=False)

    variable: str  # e.g. "sst_c", "chlorophyll_mg_m3", "wave_height_m"
    value: float | None
    unit: str
    provenance: Provenance
    quality: QualityFlag = QualityFlag.OK
    notes: str | None = None

    @property
    def is_available(self) -> bool:
        return self.value is not None and self.quality != QualityFlag.MISSING


class BoundingBox(BaseModel):
    """WGS84 geographic bounding box (degrees)."""

    south: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lon <= self.east


class LatLon(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class GeoJSONFeature(BaseModel):
    """Minimal GeoJSON feature wrapper for API responses."""

    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any]
    properties: dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    """One verifiable claim backing a recommendation."""

    claim: str
    basis: str  # which measurement/computation supports it
    measurement_variable: str | None = None
    value: float | None = None
    unit: str | None = None
    provenance: Provenance | None = None
    computation: str | None = None  # e.g. "front_detection.canny_gradient@0.02°C/km"


class Warning(BaseModel):
    severity: Literal["info", "caution", "warning", "critical"]
    message: str
    code: str | None = None
    source: str | None = None
    # Value slots (wave_m, wind_kmh, count, total, place…) so the frontend can
    # render the message from a localized template instead of the English text.
    params: dict[str, float | str] | None = None


class InsufficiencyReason(BaseModel):
    """Structured explanation for an INSUFFICIENT_DATA verdict."""

    code: str
    detail: str
    missing_variables: list[str] = Field(default_factory=list)
