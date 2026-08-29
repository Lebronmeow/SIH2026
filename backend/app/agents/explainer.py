"""Explanation generation — template (deterministic) + optional LLM narrative.

The template explainer is the default and the fallback: it renders the WHY
THIS ZONE explanation **directly from the RecommendationResponse fields**, so
it cannot hallucinate a fact that is not backed by a Measurement/Evidence
object. The LLM explainer (only when configured) receives the SAME evidence
list and is instructed to narrate it without adding facts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.config.settings import get_settings
from app.schemas.common import Measurement, Provenance, QualityFlag, Warning
from app.schemas.recommendation import ParsedQuery, RecommendationResponse

logger = logging.getLogger(__name__)

TIMEZONE_OFFSET = 5.5  # IST — used by parser + explanations

_DEMO_NOTICE = " (DEMO / CACHED DATA — not live observations)"


class TemplateExplainer:
    """Deterministic WHY-THIS-ZONE text built only from response contents."""

    def explain(self, resp: RecommendationResponse) -> str:
        parts: list[str] = []
        origin = resp.parsed_query.origin
        if origin:
            parts.append(f"Searching {resp.parsed_query.distance_km or 'a nominal'} km from {origin.place}.")

        if resp.insufficient:
            parts.append(
                "Unable to make a reliable recommendation with the currently available data: "
                + resp.insufficient.detail
            )
            parts.extend(self._warnings(resp))
            return " ".join(parts)

        rec = resp.recommended
        if rec is None:
            parts.append("No candidate zones were acceptable — all candidates failed hard safety checks.")
            parts.extend(self._warnings(resp))
            return " ".join(parts)

        cand = rec.candidate
        parts.append(
            f"Recommended zone {cand.id} at {cand.lat:.3f}°N, {abs(cand.lon):.3f}°E "
            f"({cand.bearing_deg:.0f}° from {origin.place if origin else 'origin'}, "
            f"{cand.distance_from_origin_km:.1f} km offshore)."
        )
        parts.append(self._why(rec, resp))
        route = resp.route
        if route:
            hours = route.estimated_time_h
            parts.append(
                f"The suggested route is {route.distance_km:.1f} km, about {hours:.1f} h at your vessel speed, "
                f"and it does not cross any restricted area or the India–Sri Lanka maritime boundary."
                if not route.blocked_by_constraints
                else "WARNING: no fully compliant route could be generated to this zone."
            )
        parts.extend(self._warnings(resp))
        parts.append(self._validity(resp))
        parts.append(self._demo(resp))
        return " ".join(p for p in parts if p)

    # ------------------------------------------------------------------ bits
    @staticmethod
    def _why(rec, resp: RecommendationResponse) -> str:
        bits: list[str] = []
        sb = rec.score
        if sb.productivity_score is not None:
            bits.append(f"productivity {sb.productivity_score:.2f}/1")
        if sb.risk_score is not None:
            bits.append(f"risk {sb.risk_score:.2f}/1 (lower is better)")
        values: dict[str, Measurement] = {m.variable: m for m in rec.measurements}
        sst = values.get("sst")
        chl = values.get("chlorophyll")
        wave = values.get("wave_height")
        wind = values.get("wind_speed")
        front = rec.front_strength.get("sst") or rec.front_strength.get("chlorophyll")
        if sst is not None and sst.value is not None:
            bits.append(f"SST {sst.value:.2f} °C")
        if chl is not None and chl.value is not None:
            bits.append(f"chlorophyll {chl.value:.2f} mg m⁻³")
        if front is not None:
            bits.append(f"thermal/front activity {front:.2f} (normalized)")
        if wave is not None and wave.value is not None:
            bits.append(f"waves {wave.value:.2f} m")
        if wind is not None and wind.value is not None:
            bits.append(f"wind {wind.value:.1f} km/h")
        if rec.distance_to_boundary_km is not None:
            bits.append(f"{rec.distance_to_boundary_km:.1f} km from the maritime boundary")
        text = "Why: " + ", ".join(bits) + "."
        text += " Scores use ORCA's prototype decision weights — they are not scientifically validated."
        return text

    @staticmethod
    def _warnings(resp: RecommendationResponse) -> list[str]:
        out = []
        for w in resp.warnings:
            prefix = {
                "info": "Note:",
                "caution": "Caution:",
                "warning": "WARNING:",
                "critical": "CRITICAL:",
            }.get(w.severity, "Note:")
            out.append(f"{prefix} {w.message}")
        return out

    @staticmethod
    def _validity(resp: RecommendationResponse) -> str:
        vt = resp.valid_time
        if vt is None:
            return ""
        local = vt.astimezone(timezone(timedelta(hours=TIMEZONE_OFFSET)))
        return f"Valid for {local:%d %b %Y, %H:%M} IST."

    @staticmethod
    def _demo(resp: RecommendationResponse) -> str:
        return "Data is DEMO / CACHED — not live observations." if resp.demo_banner_required else ""


class LLMExplainer:
    """LLM narrative constrained to the evidence already computed."""

    def __init__(self, api_key: str, model: str, base_url: str | None, fallback: TemplateExplainer) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.fallback = fallback

    def explain(self, resp: RecommendationResponse) -> str:
        import json

        import httpx

        template_text = self.fallback.explain(resp)
        facts = {
            "parsed_query": resp.parsed_query.model_dump(mode="json"),
            "recommended_zone": resp.recommended.model_dump(mode="json") if resp.recommended else None,
            "route": resp.route.model_dump(mode="json") if resp.route else None,
            "warnings": [w.message for w in resp.warnings],
            "evidence_count": len(resp.evidence),
            "demo_mode": resp.demo_banner_required,
            "insufficient": resp.insufficient.model_dump(mode="json") if resp.insufficient else None,
        }
        system = (
            "You are ORCA's explanation agent for Indian small-scale fishers. Narrate the provided JSON "
            "facts for the fisher in 4-6 short sentences. STRICT RULES: only use facts present in the JSON; "
            "never invent measurements, zones, boundaries or warnings; always keep any DEMO-data notice and "
            "any warning; do not override safety statements. If insufficient is set, say a reliable "
            "recommendation is not possible."
        )
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
            ],
        }
        try:
            with httpx.Client(timeout=30) as client:
                url = (self.base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
                r = client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001 — explanation is never allowed to break the response
            logger.warning("LLM explainer failed, using template: %s", exc)
            return template_text


def build_explainer() -> TemplateExplainer | LLMExplainer:
    settings = get_settings()
    template = TemplateExplainer()
    if settings.llm_enabled:
        return LLMExplainer(settings.llm_api_key or "", settings.llm_model, settings.llm_base_url, template)
    return template


def build_query_parser(resolver=None):
    """Deterministic parser, upgraded to LLM-backed when configured."""
    from app.agents.query_parser import DeterministicQueryParser, LLMQueryParser
    from app.services.place_resolver import PlaceResolver

    deterministic = DeterministicQueryParser(resolver or PlaceResolver())
    settings = get_settings()
    if settings.llm_enabled:
        return LLMQueryParser(settings.llm_api_key or "", settings.llm_model, settings.llm_base_url, deterministic)
    return deterministic


__all__ = [
    "TIMEZONE_OFFSET",
    "TemplateExplainer",
    "LLMExplainer",
    "build_explainer",
    "build_query_parser",
]
