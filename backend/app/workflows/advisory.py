"""Fishing Advisory Workflow — the ORCA master pipeline (deterministic core).

Topology (identical whether driven directly or through the Microsoft Agent
Framework graph — see :mod:`app.agents.orchestrator`)::

    query text
        │
        ▼
    [Query Understanding]  ── deterministic parser (LLM optional, JSON only)
        │  ParsedQuery
        ▼
    [Master / Orchestrator]  ── thin: validates, picks zone-evaluation plan
        │  ParsedQuery
        ▼
    [Ocean + Safety + Navigation specialists]
        │  ZoneEvaluationService  (deterministic engines; LLM never used)
        ▼
    [Verification]  ── response integrity + hard-constraint re-check
        │  RecommendationResponse
        ▼
    [Explanation]  ── template (LLM optional, evidence-constrained)

The LLM is used ONLY for parsing refinement and explanation. It can never
compute coordinates, scores, distances, or override geofence verdicts.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.agents.explainer import TemplateExplainer
from app.config.settings import get_settings
from app.providers.hub import OceanDataHub
from app.schemas.common import LatLon
from app.schemas.recommendation import ParsedQuery, RecommendationResponse, WorkflowTrace
from app.services.place_resolver import PlaceResolver
from app.services.zone_evaluator import ZoneEvaluationService

logger = logging.getLogger(__name__)


@dataclass
class AdvisoryContext:
    """State carried through the pipeline (one advisory request)."""

    raw_text: str
    parsed: ParsedQuery | None = None
    response: RecommendationResponse | None = None


class FishingAdvisoryWorkflow:
    """End-to-end advisory: text query → evidence-backed recommendation."""

    def __init__(
        self,
        hub: OceanDataHub | None = None,
        evaluator: ZoneEvaluationService | None = None,
        resolver: PlaceResolver | None = None,
        explainer: TemplateExplainer | None = None,
    ) -> None:
        from app.engines.geospatial.safety import GeospatialSafetyEngine
        from app.services.place_resolver import PlaceResolver as _PR

        self.settings = get_settings()
        self.resolver = resolver or _PR()
        self.hub = hub or OceanDataHub()
        self.evaluator = evaluator or ZoneEvaluationService(
            self.hub, GeospatialSafetyEngine.from_directory(self.settings.boundaries_dir)
        )
        self.explainer = explainer or TemplateExplainer()

    # ------------------------------------------------------------------ run
    async def run(self, raw_text: str, request_id: str | None = None) -> RecommendationResponse:
        request_id = request_id or uuid.uuid4().hex[:12]
        ctx = AdvisoryContext(raw_text=raw_text)
        started = datetime.now(timezone.utc)
        trace = WorkflowTrace(steps=[], started_at=started)

        # 1 — Query Understanding
        parser = self._build_parser()
        ctx.parsed = await self._parse(parser, ctx.raw_text, trace)

        origin = self._require_origin(ctx.parsed, trace)

        # 2 — Ocean/Safety/Navigation specialists (deterministic engines)
        response = await self.evaluator.evaluate(origin, ctx.parsed, request_id=request_id)
        for step in response.trace.steps if response.trace else []:
            trace.steps.append(step)

        # 3 — Verification (integrity + hard-constraint re-check)
        problems = self._verify(response)
        if problems:
            trace.steps.append("verification: " + "; ".join(problems))
        else:
            trace.steps.append("verification: ok")

        # 4 — Explanation
        response.explanation = self.explainer.explain(response)
        trace.steps.append("explanation generated")

        trace.finished_at = datetime.now(timezone.utc)
        trace.duration_seconds = round((trace.finished_at - trace.started_at).total_seconds(), 2)
        response.trace = trace
        return response

    # -------------------------------------------------------------- steps
    async def _parse(self, parser, text: str, trace: WorkflowTrace) -> ParsedQuery:
        from app.agents.query_parser import QueryParsingError

        try:
            parsed = await parser.parse(text)
        except QueryParsingError as exc:
            raise ValueError(f"could not parse query: {exc}") from exc
        parser_kind = type(parser).__name__
        trace.steps.append(
            f"query parsed ({parser_kind}): "
            + ", ".join(
                f"{k}={v}"
                for k, v in {
                    "distance_km": parsed.distance_km,
                    "place": parsed.origin.place if parsed.origin else None,
                    "objectives": parsed.objectives,
                }.items()
                if v is not None
            )
        )
        return parsed

    def _require_origin(self, parsed: ParsedQuery, trace: WorkflowTrace) -> LatLon:
        from app.schemas.common import LatLon

        if parsed.origin is None:
            trace.steps.append("no resolvable place in query")
            raise ValueError(
                "Could not identify a departure place in the query. Name a port or landing centre, e.g. 'off Rameswaram'."
            )
        return LatLon(lat=parsed.origin.lat, lon=parsed.origin.lon)

    def _verify(self, response: RecommendationResponse) -> list[str]:
        """Verification Agent — deterministic re-checks (hardened in Phase 8)."""
        problems: list[str] = []
        rec = response.recommended
        if rec is not None:
            if rec.excluded:
                problems.append(f"recommended zone {rec.candidate.id} is marked excluded")
            if rec.geofence and not rec.geofence.ok:
                problems.append(f"recommended zone {rec.candidate.id} fails geofence")
            if response.route and response.route.blocked_by_constraints:
                problems.append("route to recommended zone violates hard constraints")
        if response.demo_banner_required and not any(
            w.code == "DEMO_MODE" for w in response.warnings
        ):
            problems.append("demo mode active but DEMO_MODE warning missing")
        if response.insufficient and response.recommended is not None:
            problems.append("INSUFFICIENT_DATA set but a zone is still recommended")
        return problems

    # ------------------------------------------------------------- helpers
    def _build_parser(self):
        from app.agents.explainer import build_query_parser

        return build_query_parser(self.resolver)
