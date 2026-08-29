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

from app import i18n as i18n_texts
from app.config.settings import get_settings
from app.schemas.common import Measurement, Provenance, QualityFlag, Warning
from app.schemas.recommendation import ParsedQuery, RecommendationResponse

logger = logging.getLogger(__name__)

TIMEZONE_OFFSET = 5.5  # IST — used by parser + explanations

_DEMO_NOTICE = " (DEMO / CACHED DATA — not live observations)"


def _i18n_texts(language: str) -> dict[str, str]:
    return i18n_texts.texts(language)


class TemplateExplainer:
    """Deterministic WHY-THIS-ZONE text built only from response contents.

    Sentences come from per-language templates (app.i18n); the numbers inside
    them are the backend's own values, never recomputed or re-interpreted.
    """

    def explain(self, resp: RecommendationResponse, language: str = "en") -> str:
        T = _i18n_texts(language)
        parts: list[str] = []
        origin = resp.parsed_query.origin
        if origin:
            km = resp.parsed_query.distance_km
            parts.append(
                T["searching"].format(km=f"{km:g}", place=origin.place)
                if km is not None else T["searching_nodist"].format(place=origin.place)
            )

        if resp.insufficient:
            parts.append(T["unable"] + " " + resp.insufficient.detail)
            parts.extend(self._warnings(resp, T))
            return " ".join(parts)

        rec = resp.recommended
        if rec is None:
            parts.append(T["no_candidates"])
            parts.extend(self._warnings(resp, T))
            return " ".join(parts)

        cand = rec.candidate
        parts.append(
            T["rec_zone"].format(
                id=cand.id, lat=f"{cand.lat:.3f}", lon=f"{abs(cand.lon):.3f}",
                bearing=f"{cand.bearing_deg:.0f}", place=origin.place if origin else "—",
                dist=f"{cand.distance_from_origin_km:.1f}",
            )
        )
        parts.append(self._why(rec, T))
        route = resp.route
        if route:
            parts.append(
                T["route_ok"].format(km=f"{route.distance_km:.1f}", h=f"{route.estimated_time_h:.1f}")
                if not route.blocked_by_constraints
                else T["route_blocked"]
            )
        parts.extend(self._warnings(resp, T))
        parts.append(self._validity(resp, T))
        parts.append(T["demo"] if resp.demo_banner_required else "")
        return " ".join(p for p in parts if p)

    # ------------------------------------------------------------------ bits
    @staticmethod
    def _why(rec, T: dict[str, str]) -> str:
        """WHY sentence from the zone's own measurements.

        Variable names must match what zone_evaluator emits (sst_c,
        chlorophyll_mg_m3, wave_height_m, wind_speed_kmh).
        """
        bits: list[str] = []
        sb = rec.score
        if sb.productivity_score is not None:
            bits.append(T["b_productivity"].format(v=f"{sb.productivity_score:.2f}"))
        if sb.risk_score is not None:
            bits.append(T["b_risk"].format(v=f"{sb.risk_score:.2f}"))
        values: dict[str, Measurement] = {m.variable: m for m in rec.measurements}
        sst = values.get("sst_c")
        chl = values.get("chlorophyll_mg_m3")
        wave = values.get("wave_height_m")
        wind = values.get("wind_speed_kmh")
        front = rec.front_strength.get("sst_front_c_per_km")
        if sst is not None and sst.value is not None:
            bits.append(T["b_sst"].format(v=f"{sst.value:.2f}"))
        if chl is not None and chl.value is not None:
            bits.append(T["b_chl"].format(v=f"{chl.value:.2f}"))
        if front is not None:
            bits.append(T["b_front"].format(v=f"{front:.2f}"))
        if wave is not None and wave.value is not None:
            bits.append(T["b_wave"].format(v=f"{wave.value:.2f}"))
        if wind is not None and wind.value is not None:
            bits.append(T["b_wind"].format(v=f"{wind.value:.1f}"))
        if rec.distance_to_boundary_km is not None:
            bits.append(T["b_boundary"].format(v=f"{rec.distance_to_boundary_km:.1f}"))
        text = T["why_prefix"] + ", ".join(bits) + "."
        text += " " + T["weights"]
        return text

    @staticmethod
    def _warnings(resp: RecommendationResponse, T: dict[str, str]) -> list[str]:
        out = []
        for w in resp.warnings:
            prefix = {
                "info": T["p_info"],
                "caution": T["p_caution"],
                "warning": T["p_warning"],
                "critical": T["p_critical"],
            }.get(w.severity, T["p_info"])
            out.append(f"{prefix} {w.message}")
        return out

    @staticmethod
    def _validity(resp: RecommendationResponse, T: dict[str, str]) -> str:
        vt = resp.valid_time
        if vt is None:
            return ""
        local = vt.astimezone(timezone(timedelta(hours=TIMEZONE_OFFSET)))
        return T["valid"].format(t=f"{local:%d %b %Y, %H:%M}")

    @staticmethod
    def _demo(resp: RecommendationResponse, T: dict[str, str]) -> str:
        return T["demo"] if resp.demo_banner_required else ""


class LLMExplainer:
    """LLM narrative constrained to the evidence already computed."""

    def __init__(self, api_key: str, model: str, base_url: str | None, fallback: TemplateExplainer) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.fallback = fallback

    def explain(self, resp: RecommendationResponse, language: str = "en") -> str:
        import json

        import httpx

        from app.i18n import language_name

        template_text = self.fallback.explain(resp, language)
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
            f"facts for the fisher in 4-6 short sentences, written in {language_name(language)}. "
            "STRICT RULES: only use facts present in the JSON; "
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
