"""RecommendationScoringEngine — deterministic, configurable, honestly labeled.

All weights are PROTOTYPE DECISION WEIGHTS: plausible orderings chosen by the
team, NOT a scientifically validated fish-stock or safety model. The label is
propagated into every API response that carries a score.

Score model (all components normalized to 0-1)::

    productivity = w1·sst_front + w2·chl_gradient + w3·chl_magnitude + w4·current_smooth
    risk         = r1·wave + r2·wind + r3·current + r4·boundary_proximity
    overall      = productivity − risk_weight·risk − fuel_weight·fuel_norm

Missing components are EXCLUDED with their weight redistributed to the
remaining components; if too few are available (<50% of weight mass), the
engine returns ``insufficient=True`` and the pipeline reports
INSUFFICIENT_DATA instead of a score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dc_field

from pydantic import BaseModel, Field


class ScoringWeights(BaseModel):
    """Prototype decision weights (documented as unvalidated)."""

    # productivity components
    w_sst_front: float = 0.30
    w_chl_gradient: float = 0.25
    w_chl_magnitude: float = 0.25
    w_current_smooth: float = 0.20
    # risk components
    r_wave: float = 0.35
    r_wind: float = 0.30
    r_current: float = 0.15
    r_boundary: float = 0.20
    # combination
    risk_weight: float = 0.60
    fuel_weight: float = 0.10


class ScoreBreakdown(BaseModel):
    model_config = {"protected_namespaces": ("model_config",)}

    productivity_score: float | None = None
    risk_score: float | None = None
    overall_score: float | None = None
    fuel_cost_norm: float | None = None
    components: dict[str, float] = Field(default_factory=dict)
    weights_used: dict[str, float] = Field(default_factory=dict)
    missing_components: list[str] = Field(default_factory=list)
    weight_coverage: float = 0.0
    insufficient: bool = False
    label: str = "prototype decision weights — not scientifically validated"


def _norm(v: float, lo: float, hi: float) -> float:
    """Clamp to [0,1] over a documented operating range."""
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))


# documented normalization ranges (prototype calibration)
_SST_FRONT_RANGE = (0.0, 0.25)  # °C/km
_CHL_MG_M3_RANGE = (0.1, 3.0)  # log-scaled below
_CHL_GRADIENT_RANGE = (0.0, 0.5)  # (log10 mg m-3)/km
_CURRENT_MS_RANGE = (0.0, 1.2)  # drift-risk proxy
_WAVE_RANGE = (0.0, 3.0)  # m — 3 m is effectively unfishable for small craft
_WIND_KMH_RANGE = (0.0, 45.0)
_BOUNDARY_KM_RANGE = (0.0, 20.0)


class RecommendationScoringEngine:
    def __init__(self, weights: ScoringWeights | None = None) -> None:
        self.weights = weights or ScoringWeights()

    # ------------------------------------------------------------- components
    def score_zone(
        self,
        *,
        sst_front_strength: float | None,  # °C/km (max within cell window)
        chl_value: float | None,  # mg m-3
        chl_gradient: float | None,  # (log10 mg m-3)/km
        current_speed_ms: float | None,
        wave_height_m: float | None,
        wind_speed_kmh: float | None,
        distance_to_boundary_km: float | None,
        fuel_cost_norm: float | None = None,
    ) -> ScoreBreakdown:
        w = self.weights
        comp: dict[str, float] = {}
        missing: list[str] = []

        prod_terms: list[tuple[float, float]] = []  # (weight, value)
        if sst_front_strength is not None:
            comp["sst_front"] = _norm(sst_front_strength, *_SST_FRONT_RANGE)
            prod_terms.append((w.w_sst_front, comp["sst_front"]))
        else:
            missing.append("sst_front_strength")
        if chl_gradient is not None:
            comp["chl_gradient"] = _norm(chl_gradient, *_CHL_GRADIENT_RANGE)
            prod_terms.append((w.w_chl_gradient, comp["chl_gradient"]))
        else:
            missing.append("chlorophyll_gradient")
        if chl_value is not None and chl_value > 0:
            comp["chl_magnitude"] = _norm(math.log10(chl_value), math.log10(_CHL_MG_M3_RANGE[0]), math.log10(_CHL_MG_M3_RANGE[1]))
            prod_terms.append((w.w_chl_magnitude, comp["chl_magnitude"]))
        else:
            missing.append("chlorophyll_value")
        if current_speed_ms is not None:
            comp["current_smooth"] = 1.0 - _norm(current_speed_ms, *_CURRENT_MS_RANGE)
            prod_terms.append((w.w_current_smooth, comp["current_smooth"]))
        else:
            missing.append("current_speed")

        risk_terms: list[tuple[float, float]] = []
        if wave_height_m is not None:
            # risk curve: linear to 1.25 m, then accelerating
            x = _norm(wave_height_m, *_WAVE_RANGE)
            comp["wave_risk"] = min(1.0, x * (0.6 + 0.9 * x))
            risk_terms.append((w.r_wave, comp["wave_risk"]))
        else:
            missing.append("wave_height")
        if wind_speed_kmh is not None:
            comp["wind_risk"] = _norm(wind_speed_kmh, *_WIND_KMH_RANGE)
            risk_terms.append((w.r_wind, comp["wind_risk"]))
        else:
            missing.append("wind_speed")
        if current_speed_ms is not None:
            comp["current_risk"] = _norm(current_speed_ms, *_CURRENT_MS_RANGE)
            risk_terms.append((w.r_current, comp["current_risk"]))
        else:
            missing.append("current_speed")
        if distance_to_boundary_km is not None:
            comp["boundary_proximity"] = 1.0 - _norm(distance_to_boundary_km, *_BOUNDARY_KM_RANGE)
            risk_terms.append((w.r_boundary, comp["boundary_proximity"]))
        else:
            missing.append("boundary_distance")

        out = ScoreBreakdown(components={k: round(v, 4) for k, v in comp.items()}, missing_components=missing, fuel_cost_norm=fuel_cost_norm)

        # weight coverage: are enough inputs present to score honestly?
        prod_total = sum(wd for wd, _ in prod_terms)
        risk_total = sum(wd for wd, _ in risk_terms)
        prod_max = w.w_sst_front + w.w_chl_gradient + w.w_chl_magnitude + w.w_current_smooth
        risk_max = w.r_wave + w.r_wind + w.r_current + w.r_boundary
        coverage = (prod_total / prod_max + risk_total / risk_max) / 2.0
        out.weight_coverage = round(coverage, 3)
        if coverage < 0.5:
            out.insufficient = True
            return out

        productivity = sum(wd * v for wd, v in prod_terms) / prod_total if prod_total else None
        risk = sum(wd * v for wd, v in risk_terms) / risk_total if risk_total else None
        out.productivity_score = round(productivity, 4) if productivity is not None else None
        out.risk_score = round(risk, 4) if risk is not None else None
        out.weights_used = {
            "risk_weight": w.risk_weight,
            "fuel_weight": w.fuel_weight,
        }
        if productivity is not None and risk is not None:
            out.overall_score = round(
                productivity - w.risk_weight * risk - w.fuel_weight * (fuel_cost_norm or 0.0), 4
            )
        return out
