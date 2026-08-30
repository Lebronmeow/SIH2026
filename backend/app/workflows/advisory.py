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
from app.schemas.common import Warning as OrcaWarning
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
            self.hub, GeospatialSafetyEngine.from_settings()
        )
        self.explainer = explainer or TemplateExplainer()

    # ------------------------------------------------------------------ run
    async def run(
        self, raw_text: str, request_id: str | None = None, language: str = "en"
    ) -> RecommendationResponse:
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
        problems += self._check_origin_coastal(response)
        problems += self._check_supported_region(response)
        if problems:
            trace.steps.append("verification: " + "; ".join(problems))
        else:
            trace.steps.append("verification: ok")

        # 4 — Explanation (rendered in the user's language from templates)
        response.explanation = self.explainer.explain(response, language)
        trace.steps.append(f"explanation generated (language={language})")

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
        """Verification Agent — deterministic re-checks (hardened in Phase 8).

        Checks the *integrity of the response artifact itself*: every
        evidence claim must trace to a real measurement with provenance,
        every available measurement must carry a unit, the recommended zone
        must not violate hard constraints, and demo mode must be disclosed.
        """
        problems: list[str] = []
        rec = response.recommended
        if rec is not None:
            if rec.excluded:
                problems.append(f"recommended zone {rec.candidate.id} is marked excluded")
            if rec.geofence and not rec.geofence.ok:
                problems.append(f"recommended zone {rec.candidate.id} fails geofence")
            if response.route and response.route.blocked_by_constraints:
                problems.append("route to recommended zone violates hard constraints")

        # evidence → measurement cross-check: a claim that names a variable
        # must match (variable, value, unit) on the recommended zone, and any
        # claim about a *measured* value must carry provenance
        measured = {m.variable: m for m in (rec.measurements if rec else [])}
        for ev in response.evidence:
            if ev.measurement_variable is None:
                continue
            m = measured.get(ev.measurement_variable)
            if m is None:
                problems.append(f"evidence claims {ev.measurement_variable} but the recommended zone has no such measurement")
                continue
            if ev.value is not None and m.value is not None and abs(ev.value - m.value) > 1e-6:
                problems.append(f"evidence value for {ev.measurement_variable} ({ev.value}) != measurement ({m.value})")
            if ev.unit and m.unit and ev.unit != m.unit:
                problems.append(f"evidence unit for {ev.measurement_variable} ({ev.unit!r}) != measurement ({m.unit!r})")
            if ev.value is not None and ev.provenance is None and m.provenance is None:
                problems.append(f"evidence for {ev.measurement_variable} has no provenance")

        # unit audit: an *available* measurement without a unit is not presentable
        for m in (rec.measurements if rec else []):
            if m.value is not None and not m.unit:
                problems.append(f"measurement {m.variable} has a value but no unit")

        # integrity of the validity/provenance envelope
        if response.recommended is not None and response.valid_time is None:
            problems.append("recommendation without a valid_time")

        if response.demo_banner_required and not any(
            w.code == "DEMO_MODE" for w in response.warnings
        ):
            problems.append("demo mode active but DEMO_MODE warning missing")
        if response.insufficient and response.recommended is not None:
            problems.append("INSUFFICIENT_DATA set but a zone is still recommended")
        return problems

    def _check_origin_coastal(self, response: RecommendationResponse) -> list[str]:
        """Disclose an on-land departure place (Phase 8).

        Place names resolve to town centres, which sit inside the land layer
        under the accurate Natural Earth coastline — that is expected, not an
        error: the routing engine launches from the nearest water point and
        says so in the route notes. A *badly wrong* origin (deep inland) makes
        every ring candidate violate the hard constraints, which the pipeline
        already reports as INSUFFICIENT_DATA. Kept as a caution so the fisher
        knows the departure coordinates are the town centre.
        """
        origin = response.parsed_query.origin
        if origin is None:
            return []
        geofence = self.evaluator.safety.check_geofence(LatLon(lat=origin.lat, lon=origin.lon))
        if not geofence.on_land:
            return []
        response.warnings.append(
            OrcaWarning(
                severity="caution",
                code="ORIGIN_INLAND",
                message=(
                    f"Departure place '{origin.place}' is a town centre on land — "
                    "the boat route starts at the nearest water point."
                ),
                source="verification",
                params={"place": origin.place},
            )
        )
        return ["resolved origin is on land (ORIGIN_INLAND caution attached)"]

    def _check_supported_region(self, response: RecommendationResponse) -> list[str]:
        """Disclose queries outside the validated pilot region.

        Boundary layers, shorelines and provider coverage are verified only
        inside the configured supported-region bbox. An origin outside it
        still gets a full deterministic answer, but the response carries an
        explicit caution — nobody should mistake an unvalidated area for a
        covered one.
        """
        origin = response.parsed_query.origin
        if origin is None:
            return []
        s = get_settings()
        inside = (
            s.supported_region_south <= origin.lat <= s.supported_region_north
            and s.supported_region_west <= origin.lon <= s.supported_region_east
        )
        if inside:
            return []
        response.warnings.append(
            OrcaWarning(
                severity="caution",
                code="OUTSIDE_SUPPORTED_REGION",
                message=(
                    f"'{origin.place}' is outside the validated pilot region "
                    f"({s.supported_region_south:g}–{s.supported_region_north:g}°N, "
                    f"{s.supported_region_west:g}–{s.supported_region_east:g}°E). "
                    "Boundary and shoreline checks are not verified here — treat this advice as indicative only."
                ),
                source="verification",
                params={"place": origin.place},
            )
        )
        return ["origin outside supported region (OUTSIDE_SUPPORTED_REGION caution attached)"]

    # ------------------------------------------------------------- helpers
    def _build_parser(self):
        from app.agents.explainer import build_query_parser

        return build_query_parser(self.resolver)
