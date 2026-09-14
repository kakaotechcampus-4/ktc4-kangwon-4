"""Bounded LangGraph orchestration for one RE:BORN planning run.

This graph is deliberately persistence-free.  A BE coordinator supplies the
immutable ``SupervisorRunInput`` and, after a reviewed outcome is returned,
owns authorization, transaction and storage guardrails.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import date, datetime, timezone
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

from app.agent.enrichment import build_fact_overlays
from app.agent.schemas import (
    CASE_FIELD_SPECS,
    AgentRunOutcome,
    AllProcedureLookupInput,
    Component,
    ConflictOutcome,
    DiscoverSupportInput,
    InfoAnalysisInput,
    InvocationMeta,
    KnownProcedureStep,
    PlanningContext,
    RefreshSupportInput,
    ReviewedPlanOutcome,
    ReviewIssue,
    ReviewProof,
    ReviewResult,
    ReviewSourceResult,
    ReviewSubject,
    ReviewVerdict,
    SafeFailureOutcome,
    SupervisorDraft,
    SupervisorRunInput,
    SupportRefreshTrigger,
    canonical_digest,
)
from app.agent.state import AgentGraphState
from app.agent.tracing import NullTraceSink, TraceEvent, TraceSink
from langgraph.graph import END, START, StateGraph


class InfoRunner(Protocol):
    async def analyze(
        self,
        request: InfoAnalysisInput,
        *,
        source_call_id: UUID | None = None,
    ) -> Any: ...


class ProcedureRunner(Protocol):
    def lookup(self, request: Any) -> Any: ...


class SupportRunner(Protocol):
    async def analyze(self, request: Any) -> Any: ...


class SupervisorRunner(Protocol):
    async def draft(
        self,
        request: SupervisorRunInput,
        source_results: Sequence[ReviewSourceResult],
        *,
        draft_version: int = 1,
        review_feedback: Sequence[ReviewIssue] = (),
        fact_overlays: Sequence[Any] | None = None,
        previous_draft: SupervisorDraft | None = None,
    ) -> SupervisorDraft: ...


class ReviewRunner(Protocol):
    async def review(self, subject: ReviewSubject) -> ReviewResult: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentGraph:
    """Run the Agent components and expose only reviewed or safe outcomes."""

    def __init__(
        self,
        *,
        info_agent: InfoRunner,
        procedure_tool: ProcedureRunner,
        support_agent: SupportRunner,
        supervisor: SupervisorRunner,
        review_tool: ReviewRunner,
        known_procedure_steps: Sequence[KnownProcedureStep],
        clock: Callable[[], datetime] = _utc_now,
        uuid_factory: Callable[[], UUID] = uuid4,
        trace_sink: TraceSink | None = None,
        max_review_revisions: int = 2,
    ) -> None:
        if max_review_revisions < 0 or max_review_revisions > 2:
            raise ValueError("max_review_revisions must be between 0 and 2")
        self._info_agent = info_agent
        self._procedure_tool = procedure_tool
        self._support_agent = support_agent
        self._supervisor = supervisor
        self._review_tool = review_tool
        self._known_procedure_steps = list(known_procedure_steps)
        self._clock = clock
        self._uuid = uuid_factory
        self._trace_sink = trace_sink or NullTraceSink()
        self._max_review_revisions = max_review_revisions
        self.compiled = self._compile()

    async def run(
        self,
        request: SupervisorRunInput,
        *,
        trace_id: str | None = None,
    ) -> AgentRunOutcome:
        # An owned deep copy prevents caller-side mutation while the graph is in flight.
        owned_request = request.model_copy(deep=True)
        failure_request = request.model_copy(deep=True)
        snapshot_digest = canonical_digest(owned_request.case_snapshot)
        run_id = self._uuid()
        initial: AgentGraphState = {
            "request": owned_request,
            "run_id": run_id,
            "trace_id": trace_id,
            "phase": "PLANNING",
            "source_results": [],
            "fact_overlays": [],
            "review_feedback": [],
            "revision_count": 0,
        }
        try:
            result = await self.compiled.ainvoke(
                initial,
                config={"recursion_limit": 32},
            )
            if canonical_digest(owned_request.case_snapshot) != snapshot_digest:
                raise RuntimeError("Agent graph mutated its Case snapshot")
            outcome = result.get("outcome")
            if outcome is None:
                raise RuntimeError("Agent graph terminated without a safe outcome")
            return cast(AgentRunOutcome, outcome)
        except Exception as exc:  # noqa: BLE001 - public graph boundary fails closed
            failure = self._failure(exc, None)
            return self._build_safe_failure(
                failure_request,
                run_id=run_id,
                trace_id=trace_id,
                failure=failure,
            )

    def _compile(self) -> Any:
        builder = StateGraph(AgentGraphState)
        builder.add_node("info_analysis", self._info_node)
        builder.add_node("conflict", self._conflict_node)
        builder.add_node("procedure_lookup", self._procedure_node)
        builder.add_node("support_analysis", self._support_node)
        builder.add_node("supervisor", self._supervisor_node)
        builder.add_node("review", self._review_node)
        builder.add_node("finalize", self._finalize_node)
        builder.add_node("safe_failure", self._safe_failure_node)

        builder.add_edge(START, "info_analysis")
        builder.add_conditional_edges(
            "info_analysis",
            self._route_after_info,
            {
                "continue": "procedure_lookup",
                "conflict": "conflict",
                "failure": "safe_failure",
            },
        )
        builder.add_edge("conflict", END)
        builder.add_conditional_edges(
            "procedure_lookup",
            self._route_after_component,
            {"continue": "support_analysis", "failure": "safe_failure"},
        )
        builder.add_conditional_edges(
            "support_analysis",
            self._route_after_component,
            {"continue": "supervisor", "failure": "safe_failure"},
        )
        builder.add_conditional_edges(
            "supervisor",
            self._route_after_component,
            {"continue": "review", "failure": "safe_failure"},
        )
        builder.add_conditional_edges(
            "review",
            self._route_after_review,
            {
                "pass": "finalize",
                "info": "info_analysis",
                "procedure": "procedure_lookup",
                "support": "support_analysis",
                "supervisor": "supervisor",
                "failure": "safe_failure",
            },
        )
        builder.add_edge("finalize", END)
        builder.add_edge("safe_failure", END)
        return builder.compile()

    async def _info_node(self, state: AgentGraphState) -> dict[str, Any]:
        request = state["request"]
        trigger_input = getattr(request.trigger, "input", None)
        if trigger_input is None:
            return {"phase": "INFO_ANALYSIS", "fact_overlays": []}

        meta = self._meta(
            state,
            Component.INFO_AGENT,
            attempt=state.get("revision_count", 0) + 1,
        )
        component_input = InfoAnalysisInput(
            input=trigger_input,
            case_snapshot=request.case_snapshot,
            allowed_field_paths=list(CASE_FIELD_SPECS),
            known_procedure_steps=self._known_procedure_steps,
            review_feedback=state.get("review_feedback", []),
        )
        started = time.monotonic()
        try:
            output = await self._info_agent.analyze(
                component_input,
                source_call_id=meta.call_id,
            )
            source = ReviewSourceResult(
                meta=meta,
                output_digest=canonical_digest(output),
                output=output,
            )
            overlays = build_fact_overlays(
                request.case_snapshot,
                output,
                meta.call_id,
                uuid_factory=self._uuid,
            )
        except Exception as exc:  # noqa: BLE001 - graph must fail closed
            self._emit(meta, started, "ERROR", exc)
            return self._failure(exc, Component.INFO_AGENT)
        self._emit(meta, started, "SUCCESS")
        return {
            "phase": "INFO_ANALYSIS",
            "source_results": [source],
            "fact_overlays": overlays,
        }

    def _conflict_node(self, state: AgentGraphState) -> dict[str, Any]:
        info = state["source_results"][0].output
        outcome = ConflictOutcome(
            outcome_type="CONFLICT",
            run_id=state["run_id"],
            case_id=state["request"].case_snapshot.case_id,
            trigger=state["request"].trigger,
            snapshot_id=state["request"].case_snapshot.snapshot_id,
            case_version=state["request"].case_snapshot.case_version,
            conflicts=info.conflicts,
            message_code="CONFIRM_CONFLICT",
        )
        return {"phase": "COMPLETED", "outcome": outcome}

    async def _procedure_node(self, state: AgentGraphState) -> dict[str, Any]:
        request = state["request"]
        meta = self._meta(
            state,
            Component.PROCEDURE_TOOL,
            attempt=state.get("revision_count", 0) + 1,
        )
        component_input = AllProcedureLookupInput(
            lookup_scope="ALL_STEPS",
            planning_context=PlanningContext(
                case_snapshot=request.case_snapshot,
                fact_overlays=state.get("fact_overlays", []),
            ),
            as_of=self._as_of(request),
        )
        started = time.monotonic()
        try:
            output = self._procedure_tool.lookup(component_input)
            source = ReviewSourceResult(
                meta=meta,
                output_digest=canonical_digest(output),
                output=output,
            )
        except Exception as exc:  # noqa: BLE001 - graph must fail closed
            self._emit(meta, started, "ERROR", exc)
            return self._failure(exc, Component.PROCEDURE_TOOL)
        self._emit(meta, started, "SUCCESS")
        return {
            "phase": "PROCEDURE_LOOKUP",
            "source_results": [*state.get("source_results", []), source],
        }

    async def _support_node(self, state: AgentGraphState) -> dict[str, Any]:
        request = state["request"]
        meta = self._meta(
            state,
            Component.SUPPORT_AGENT,
            attempt=state.get("revision_count", 0) + 1,
        )
        context = PlanningContext(
            case_snapshot=request.case_snapshot,
            fact_overlays=state.get("fact_overlays", []),
        )
        procedure_steps = [
            item.procedure_step
            for source in state.get("source_results", [])
            if source.meta.component == Component.PROCEDURE_TOOL
            for item in source.output.step_evaluations
        ]
        if isinstance(request.trigger, SupportRefreshTrigger):
            component_input: Any = RefreshSupportInput(
                lookup_goal="REFRESH_STALE",
                planning_context=context,
                related_steps=procedure_steps,
                as_of=request.trigger.as_of,
                review_feedback=state.get("review_feedback", []),
                support_programs=request.trigger.support_programs,
            )
        else:
            component_input = DiscoverSupportInput(
                lookup_goal="DISCOVER_RELEVANT",
                planning_context=context,
                related_steps=procedure_steps,
                as_of=self._as_of(request),
                review_feedback=state.get("review_feedback", []),
            )
        started = time.monotonic()
        try:
            output = await self._support_agent.analyze(component_input)
            source = ReviewSourceResult(
                meta=meta,
                output_digest=canonical_digest(output),
                output=output,
            )
        except Exception as exc:  # noqa: BLE001 - graph must fail closed
            self._emit(meta, started, "ERROR", exc)
            return self._failure(exc, Component.SUPPORT_AGENT)
        self._emit(meta, started, "SUCCESS")
        return {
            "phase": "SUPPORT_ANALYSIS",
            "source_results": [*state.get("source_results", []), source],
        }

    async def _supervisor_node(self, state: AgentGraphState) -> dict[str, Any]:
        meta = self._meta(
            state,
            Component.SUPERVISOR,
            attempt=state.get("revision_count", 0) + 1,
        )
        started = time.monotonic()
        try:
            previous_draft = (
                state.get("current_draft")
                if state.get("revision_count", 0) > 0
                else None
            )
            draft = await self._supervisor.draft(
                state["request"],
                state["source_results"],
                draft_version=state.get("revision_count", 0) + 1,
                review_feedback=state.get("review_feedback", []),
                fact_overlays=state.get("fact_overlays", []),
                previous_draft=previous_draft,
            )
        except Exception as exc:  # noqa: BLE001 - graph must fail closed
            self._emit(meta, started, "ERROR", exc)
            return self._failure(exc, Component.SUPERVISOR)
        self._emit(meta, started, "SUCCESS")
        return {"phase": "DRAFTING", "current_draft": draft}

    async def _review_node(self, state: AgentGraphState) -> dict[str, Any]:
        attempt = state.get("revision_count", 0) + 1
        started = time.monotonic()
        try:
            meta = self._meta(state, Component.REVIEW_TOOL, attempt=attempt)
            subject = ReviewSubject.create(
                schema_version="agent-io/1.0",
                review_subject_id=self._uuid(),
                review_attempt=attempt,
                run_id=state["run_id"],
                case_id=state["request"].case_snapshot.case_id,
                trigger=state["request"].trigger,
                snapshot=state["request"].case_snapshot,
                source_results=state["source_results"],
                supervisor_draft=state["current_draft"],
            )
            result = await self._review_tool.review(subject)
        except Exception as exc:  # noqa: BLE001 - graph must fail closed
            if "meta" in locals():
                self._emit(meta, started, "ERROR", exc)
            return self._failure(exc, Component.REVIEW_TOOL)
        self._emit(meta, started, "SUCCESS")
        update: dict[str, Any] = {
            "phase": "REVIEWING",
            "review_subject": subject,
            "review_result": result,
            "review_meta": meta,
        }
        if result.verdict == ReviewVerdict.REVISE:
            revision_count = state.get("revision_count", 0)
            if revision_count >= self._max_review_revisions:
                update.update(
                    {
                        "phase": "SAFE_FAILED",
                        "failure_code": "REVIEW_RETRY_EXHAUSTED",
                        "failure_message_code": "REVIEW_RETRY_EXHAUSTED",
                        "failed_component": Component.REVIEW_TOOL,
                        "retryable": False,
                    }
                )
            else:
                targets = list(result.recommended_rework_targets)
                if not targets:
                    targets = [Component.SUPERVISOR]
                feedback = self._review_feedback(result)
                earliest = self._earliest_rework_target(targets)
                retained_sources = self._retain_sources_for_rework(
                    state.get("source_results", []),
                    earliest,
                )
                update.update(
                    {
                        "phase": "REVISING",
                        "revision_count": revision_count + 1,
                        "review_feedback": feedback,
                        "rework_targets": targets,
                        "source_results": retained_sources,
                    }
                )
        return update

    def _finalize_node(self, state: AgentGraphState) -> dict[str, Any]:
        proof = ReviewProof.from_passed_review(
            subject=state["review_subject"],
            result=state["review_result"],
            review_meta=state["review_meta"],
            reviewed_at=self._aware_now(),
        )
        outcome = ReviewedPlanOutcome(
            outcome_type="REVIEWED_PLAN",
            review_subject=state["review_subject"],
            review_proof=proof,
        )
        return {"phase": "COMPLETED", "outcome": outcome}

    def _safe_failure_node(self, state: AgentGraphState) -> dict[str, Any]:
        outcome = self._build_safe_failure(
            state["request"],
            run_id=state["run_id"],
            trace_id=state.get("trace_id"),
            failure=state,
        )
        return {"phase": "SAFE_FAILED", "outcome": outcome}

    @staticmethod
    def _build_safe_failure(
        request: SupervisorRunInput,
        *,
        run_id: UUID,
        trace_id: str | None,
        failure: dict[str, Any],
    ) -> SafeFailureOutcome:
        return SafeFailureOutcome(
            outcome_type="SAFE_FAILURE",
            run_id=run_id,
            case_id=request.case_snapshot.case_id,
            trigger=request.trigger,
            snapshot_id=request.case_snapshot.snapshot_id,
            case_version=request.case_snapshot.case_version,
            failure_code=failure.get("failure_code", "COMPONENT_UNAVAILABLE"),
            message_code=failure.get(
                "failure_message_code", "AGENT_COMPONENT_UNAVAILABLE"
            ),
            recovery_action_code="RETRY" if failure.get("retryable", False) else "NONE",
            requested_field_paths=[],
            retryable=failure.get("retryable", False),
            failed_component=failure.get("failed_component"),
            trace_id=trace_id,
        )

    @staticmethod
    def _route_after_info(
        state: AgentGraphState,
    ) -> Literal["continue", "conflict", "failure"]:
        if state.get("failure_code"):
            return "failure"
        sources = state.get("source_results", [])
        if sources and getattr(sources[-1].output, "conflicts", []):
            return "conflict"
        return "continue"

    @staticmethod
    def _route_after_component(
        state: AgentGraphState,
    ) -> Literal["continue", "failure"]:
        return "failure" if state.get("failure_code") else "continue"

    @staticmethod
    def _route_after_review(
        state: AgentGraphState,
    ) -> Literal["pass", "info", "procedure", "support", "supervisor", "failure"]:
        if state.get("failure_code"):
            return "failure"
        result = state.get("review_result")
        if result is not None and result.verdict == ReviewVerdict.PASS:
            return "pass"
        targets = state.get("rework_targets", [Component.SUPERVISOR])
        if Component.INFO_AGENT in targets:
            return "info"
        if Component.PROCEDURE_TOOL in targets:
            return "procedure"
        if Component.SUPPORT_AGENT in targets:
            return "support"
        return "supervisor"

    @staticmethod
    def _earliest_rework_target(targets: Sequence[Component]) -> Component:
        for component in (
            Component.INFO_AGENT,
            Component.PROCEDURE_TOOL,
            Component.SUPPORT_AGENT,
            Component.SUPERVISOR,
        ):
            if component in targets:
                return component
        return Component.SUPERVISOR

    @staticmethod
    def _retain_sources_for_rework(
        sources: Sequence[ReviewSourceResult],
        earliest: Component,
    ) -> list[ReviewSourceResult]:
        if earliest == Component.INFO_AGENT:
            return []
        if earliest == Component.PROCEDURE_TOOL:
            return [
                item for item in sources if item.meta.component == Component.INFO_AGENT
            ]
        if earliest == Component.SUPPORT_AGENT:
            return [
                item
                for item in sources
                if item.meta.component
                in {Component.INFO_AGENT, Component.PROCEDURE_TOOL}
            ]
        return list(sources)

    @staticmethod
    def _review_feedback(result: ReviewResult) -> list[ReviewIssue]:
        feedback = list(result.issues)
        for missing in result.missing_evidence:
            feedback.append(
                ReviewIssue(
                    issue_code="MISSING_EVIDENCE",
                    category="EVIDENCE",
                    severity="BLOCKING",
                    target_component="SUPERVISOR",
                    target_call_id=None,
                    target_path=missing.claim_path,
                    reason_summary=missing.reason_summary,
                    evidence_refs=[],
                )
            )
        return feedback

    def _meta(
        self,
        state: AgentGraphState,
        component: Component,
        *,
        attempt: int = 1,
    ) -> InvocationMeta:
        return InvocationMeta(
            schema_version="agent-io/1.0",
            run_id=state["run_id"],
            call_id=self._uuid(),
            parent_call_id=None,
            case_id=state["request"].case_snapshot.case_id,
            component=component,
            attempt=attempt,
            requested_at=self._aware_now(),
            trace_id=state.get("trace_id"),
        )

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Agent clock must return an aware datetime")
        return value

    @staticmethod
    def _as_of(request: SupervisorRunInput) -> date:
        trigger = request.trigger
        if isinstance(trigger, SupportRefreshTrigger):
            return trigger.as_of
        return trigger.submitted_at.date()

    @staticmethod
    def _failure(
        exc: Exception,
        component: Component | None,
    ) -> dict[str, Any]:
        name = exc.__class__.__name__
        response_like = name in {
            "InfoAnalysisGuardrailError",
            "LLMResponseError",
            "ProcedureLookupInputError",
            "ReviewIntegrityError",
            "ReviewOutputViolation",
            "SupportAnalysisGuardrailError",
            "SupportAnalysisInputError",
            "SupervisorGuardrailError",
            "ValidationError",
        } or isinstance(exc, ValueError)
        unavailable_like = name in {
            "LLMConfigurationError",
            "LLMRequestError",
            "ProcedureMasterUnavailableError",
            "SupportCatalogUnavailableError",
        }
        if response_like and not unavailable_like:
            failure_code = "STRUCTURED_OUTPUT_FAILED"
            message_code = "AGENT_STRUCTURED_OUTPUT_FAILED"
        else:
            failure_code = "COMPONENT_UNAVAILABLE"
            message_code = "AGENT_COMPONENT_UNAVAILABLE"
        return {
            "phase": "SAFE_FAILED",
            "failure_code": failure_code,
            "failure_message_code": message_code,
            "failed_component": component,
            "retryable": bool(getattr(exc, "retryable", unavailable_like)),
        }

    def _emit(
        self,
        meta: InvocationMeta,
        started: float,
        status: str,
        exc: Exception | None = None,
    ) -> None:
        event = TraceEvent(
            run_id=str(meta.run_id),
            call_id=str(meta.call_id),
            component=meta.component.value,
            status=status,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            attempt=meta.attempt,
            error_code=(
                str(getattr(exc, "code", exc.__class__.__name__)) if exc else None
            ),
        )
        try:
            self._trace_sink.emit(event)
        except Exception:  # noqa: BLE001 - telemetry is deliberately best-effort
            # Observability must not change planning behavior.
            return


__all__ = ["AgentGraph"]
