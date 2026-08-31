"""Master Orchestration via Microsoft Agent Framework (agent-framework).

ORCA's pipeline topology is expressed ONCE as an Agent Framework workflow
(:class:`agent_framework.WorkflowBuilder` + ``Executor`` classes). Every
executor is a THIN wrapper around a deterministic ORCA service — the
framework provides message passing, tracing and (later) Agent-based
executors, never the science:

- ``QueryUnderstandingExecutor``  → app.agents.query_parser  (LLM optional)
- ``MasterOrchestratorExecutor``  → thin router (LLM optional, decisions only)
- ``ZoneEvaluationExecutor``      → app.services.zone_evaluator (deterministic)
- ``VerificationExecutor``        → response integrity re-checks
- ``ExplanationExecutor``         → app.agents.explainer (LLM optional)

Hard-safety rule: no executor ever asks an LLM to compute coordinates,
scores, distances or geofence verdicts. The topology is identical in
deterministic mode and LLM mode; only parser/explainer/master swap.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.workflows.advisory import FishingAdvisoryWorkflow

logger = logging.getLogger(__name__)

try:  # agent-framework is a direct dependency; tolerate its absence at runtime
    from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler

    MAF_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the package
    MAF_AVAILABLE = False
    Executor = object  # type: ignore[assignment, misc]


def build_advisory_workflow(hub=None, language: str = "en") -> Any:
    """Return the MAF-graph advisory workflow, or None when MAF is absent.

    The graph is: parse → master → zone-evaluation → verification → explain.
    ``language`` is threaded to the explanation executor so the final WHY text
    is rendered in the user's language.
    """
    if not MAF_AVAILABLE:
        return None

    advisory = FishingAdvisoryWorkflow(hub=hub)
    trace_sink: dict[str, list[str]] = {"steps": []}

    class QueryUnderstandingExecutor(Executor):
        @handler
        async def handle(self, raw: str, ctx: WorkflowContext[Any]) -> None:
            parser = advisory._build_parser()
            parsed = await parser.parse(raw)
            trace_sink["steps"].append(f"query parsed ({type(parser).__name__})")
            await ctx.send_message(parsed, "master")

    class MasterOrchestratorExecutor(Executor):
        """Thin router — validates the plan and forwards to the specialist.

        With ORCA_LLM_* configured this executor is where an Agent would
        choose among specialists; the specialist itself stays deterministic.
        """

        @handler
        async def handle(self, parsed: Any, ctx: WorkflowContext[Any]) -> None:
            from app.schemas.common import LatLon

            if parsed.origin is None:
                await ctx.yield_output({"error": "no_resolvable_place"})
                return
            # same hard region gate as the direct pipeline (ValueError → 422)
            advisory.require_origin_in_supported_region(parsed)
            trace_sink["steps"].append("master: plan = ring candidates + deterministic engines")
            await ctx.send_message(parsed, "specialist_zones")

    class ZoneEvaluationExecutor(Executor):
        @handler
        async def handle(self, parsed: Any, ctx: WorkflowContext[Any]) -> None:
            from app.schemas.common import LatLon

            origin = LatLon(lat=parsed.origin.lat, lon=parsed.origin.lon)
            response = await advisory.evaluator.evaluate(
                origin, parsed, request_id=uuid.uuid4().hex[:12]
            )
            trace_sink["steps"].extend(response.trace.steps if response.trace else [])
            await ctx.send_message(response, "verifier")

    class VerificationExecutor(Executor):
        @handler
        async def handle(self, response: Any, ctx: WorkflowContext[Any]) -> None:
            # same verification suite as the direct pipeline: integrity checks,
            # on-land origin disclosure, outside-region disclosure
            problems = advisory._verify(response)
            problems += advisory._check_origin_coastal(response)
            problems += advisory._check_supported_region(response)
            trace_sink["steps"].append(
                "verification: " + ("; ".join(problems) if problems else "ok")
            )
            await ctx.send_message(response, "explainer")

    class ExplanationExecutor(Executor):
        @handler
        async def handle(self, response: Any, ctx: WorkflowContext[Any, Any]) -> None:
            response.explanation = advisory.explainer.explain(response, language)
            trace_sink["steps"].append(f"explanation generated (language={language})")
            if response.trace is None:
                from datetime import datetime, timezone

                from app.schemas.recommendation import WorkflowTrace

                response.trace = WorkflowTrace(steps=trace_sink["steps"], started_at=datetime.now(timezone.utc))
            else:
                response.trace.steps = trace_sink["steps"]
            await ctx.yield_output(response)

    parse_exec = QueryUnderstandingExecutor(id="query_understanding")
    master_exec = MasterOrchestratorExecutor(id="master")
    zones_exec = ZoneEvaluationExecutor(id="specialist_zones")
    verify_exec = VerificationExecutor(id="verifier")
    explain_exec = ExplanationExecutor(id="explainer")

    return (
        WorkflowBuilder(start_executor=parse_exec)
        .add_edge(parse_exec, master_exec)
        .add_edge(master_exec, zones_exec)
        .add_edge(zones_exec, verify_exec)
        .add_edge(verify_exec, explain_exec)
        .build()
    )


async def run_advisory(raw_text: str, hub=None, request_id: str | None = None, language: str = "en"):
    """Run the advisory through the MAF graph when available, else directly."""
    request_id = request_id or uuid.uuid4().hex[:12]
    if hub is None:
        # the process-wide hub: a fresh hub per call would empty the last-good
        # cache (and reset the failure breaker) between requests
        from app.providers.hub import get_hub

        hub = get_hub()
    wf = build_advisory_workflow(hub, language=language)
    if wf is not None:
        result = await wf.run(raw_text)
        outputs = result.get_outputs()
        if outputs:
            out = outputs[0]
            if isinstance(out, dict) and out.get("error") == "no_resolvable_place":
                raise ValueError(
                    "Could not identify a departure place in the query. Name a port, e.g. 'off Rameswaram'."
                )
            return out
        logger.warning("MAF workflow produced no output; using direct pipeline")
    advisory = FishingAdvisoryWorkflow(hub=hub)
    return await advisory.run(raw_text, request_id=request_id, language=language)
