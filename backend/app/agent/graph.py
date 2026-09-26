"""Bounded LangGraph orchestration for one RE:BORN planning run.

This graph is deliberately persistence-free.  A BE coordinator supplies the
immutable ``AgentGraphInput`` and, after a reviewed outcome is returned,
owns authorization, transaction and storage guardrails.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from app.agent.enrichment import build_confirmed_conflict_overlay, build_fact_overlays
from app.agent.llm import current_call_budget
from app.agent.run_scope import current_deadline
from app.agent.schemas import (
    CASE_FIELD_SPECS,
    AgentGraphInput,
    AgentGraphOutput,
    CaseFieldKey,
    Component,
    ConflictConfirmedTrigger,
    ConflictOutcome,
    DiscoverSupportInput,
    FactChangeSourceType,
    FactStatus,
    InfoAnalysisInput,
    InfoAnalysisResult,
    InvocationMeta,
    KnownProcedureStep,
    MissingFieldBlock,
    PlanningContext,
    ProcedureLookupInput,
    ProcedureLookupResult,
    ReviewedPlanOutcome,
    ReviewIssue,
    ReviewProof,
    ReviewResult,
    ReviewSourceResult,
    ReviewSubject,
    ReviewVerdict,
    SafeFailureOutcome,
    SupervisorAgentInput,
    SupervisorDraft,
    SupportAgentInput,
    SupportAnalysisResult,
    canonical_digest,
    validate_procedure_registry,
)
from app.agent.state import AgentGraphState
from app.agent.tracing import (
    NullTraceSink,
    TraceEvent,
    TraceSink,
    UsageAccumulator,
)


class InfoRunner(Protocol):
    async def analyze(self, request: InfoAnalysisInput) -> InfoAnalysisResult: ...


class ProcedureRunner(Protocol):
    async def lookup(self, request: ProcedureLookupInput) -> ProcedureLookupResult: ...


class SupportRunner(Protocol):
    async def analyze(self, request: SupportAgentInput) -> SupportAnalysisResult: ...


class SupervisorRunner(Protocol):
    async def draft(self, request: SupervisorAgentInput) -> SupervisorDraft: ...


class ReviewRunner(Protocol):
    async def review(self, subject: ReviewSubject) -> ReviewResult: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class _ReviewTraceCounters:
    review_count: int = 0
    review_revise_count: int = 0
    started_rework_rounds: set[int] = field(default_factory=set)


_REVIEW_TRACE_COUNTERS: ContextVar[_ReviewTraceCounters | None] = ContextVar(
    "agent_review_trace_counters", default=None
)


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
        usage: UsageAccumulator | None = None,
    ) -> None:
        if max_review_revisions < 0 or max_review_revisions > 2:
            raise ValueError("max_review_revisions must be between 0 and 2")
        self._info_agent = info_agent
        self._procedure_tool = procedure_tool
        self._support_agent = support_agent
        self._supervisor = supervisor
        self._review_tool = review_tool
        self._known_procedure_steps = [
            step.model_copy(deep=True) for step in known_procedure_steps
        ]
        validate_procedure_registry(self._known_procedure_steps)
        self._clock = clock
        self._uuid = uuid_factory
        self._trace_sink = trace_sink or NullTraceSink()
        self._max_review_revisions = max_review_revisions
        self._usage = usage
        self.compiled = self._compile()

    async def run(self, request: AgentGraphInput) -> AgentGraphOutput:
        if self._usage is not None:
            # Usage a previous run recorded but never drained would otherwise be
            # attributed to this run's first component.
            self._usage.reset()
        # An owned deep copy prevents caller-side mutation while the graph is in flight.
        owned_request = request.model_copy(deep=True)
        failure_request = request.model_copy(deep=True)
        snapshot_digest = canonical_digest(owned_request.case_snapshot)
        run_id = self._uuid()
        initial: AgentGraphState = {
            "request": owned_request,
            "run_id": run_id,
            "trace_id": owned_request.trace_id,
            "phase": "PLANNING",
            "source_results": [],
            "fact_overlays": [],
            "review_feedback": [],
            "revision_count": 0,
        }
        run_started = time.monotonic()
        review_counters = _ReviewTraceCounters()
        counter_scope = _REVIEW_TRACE_COUNTERS.set(review_counters)
        outcome: AgentGraphOutput
        try:
            result = await self.compiled.ainvoke(
                initial,
                config={"recursion_limit": 32},
            )
            if canonical_digest(owned_request.case_snapshot) != snapshot_digest:
                raise RuntimeError("Agent graph mutated its Case snapshot")
            raw_outcome = result.get("outcome")
            if raw_outcome is None:
                raise RuntimeError("Agent graph terminated without a safe outcome")
            outcome = cast(AgentGraphOutput, raw_outcome)
        except Exception as exc:  # noqa: BLE001 - public graph boundary fails closed
            failure = self._failure(exc, None)
            outcome = self._build_safe_failure(
                failure_request,
                run_id=run_id,
                trace_id=failure_request.trace_id,
                failure=failure,
            )
        finally:
            _REVIEW_TRACE_COUNTERS.reset(counter_scope)
        self._emit_run_summary(
            run_id=run_id,
            started=run_started,
            outcome=outcome,
            review_counters=review_counters,
        )
        return outcome

    def _emit_run_summary(
        self,
        *,
        run_id: UUID,
        started: float,
        outcome: AgentGraphOutput,
        review_counters: _ReviewTraceCounters,
    ) -> None:
        """Record what one whole run actually cost.

        Per-component events cannot answer this: one of them may cover several
        provider calls, so their count is not the run's call count.  Without
        this the per-run call budget can only be guessed at, which is the whole
        reason it is hard to say whether the current cap is the right one.
        """

        budget = current_call_budget()
        event = TraceEvent(
            run_id=str(run_id),
            call_id=str(run_id),
            component="RUN",
            status=("ERROR" if outcome.outcome_type == "SAFE_FAILURE" else "SUCCESS"),
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            attempt=1,
            provider_calls=None if budget is None else budget.spent,
            outcome_type=outcome.outcome_type,
            review_count=review_counters.review_count,
            review_revise_count=review_counters.review_revise_count,
            rework_count=len(review_counters.started_rework_rounds),
            error_code=(
                outcome.failure_code if outcome.outcome_type == "SAFE_FAILURE" else None
            ),
        )
        try:
            self._trace_sink.emit(event)
        except Exception:  # noqa: BLE001 - telemetry is deliberately best-effort
            return

    def _compile(self) -> Any:
        builder = StateGraph(AgentGraphState)
        builder.add_node("info_analysis", self._info_node)
        builder.add_node("conflict", self._conflict_node)
        builder.add_node("confirmed_conflict", self._confirmed_conflict_node)
        builder.add_node("procedure_lookup", self._procedure_node)
        builder.add_node("support_analysis", self._support_node)
        builder.add_node("supervisor", self._supervisor_node)
        builder.add_node("review", self._review_node)
        builder.add_node("finalize", self._finalize_node)
        builder.add_node("safe_failure", self._safe_failure_node)

        builder.add_conditional_edges(
            START,
            self._route_start,
            {
                "procedure": "procedure_lookup",
                "support": "support_analysis",
                "confirmed_conflict": "confirmed_conflict",
            },
        )
        builder.add_conditional_edges(
            "confirmed_conflict",
            self._route_after_component,
            {"continue": "procedure_lookup", "failure": "safe_failure"},
        )
        builder.add_conditional_edges(
            "procedure_lookup",
            self._route_after_component,
            {"continue": "info_analysis", "failure": "safe_failure"},
        )
        builder.add_conditional_edges(
            "info_analysis",
            self._route_after_info,
            {
                "continue": "support_analysis",
                "conflict": "conflict",
                "failure": "safe_failure",
            },
        )
        builder.add_edge("conflict", END)
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

    @staticmethod
    def _check_deadline() -> None:
        """Stop before starting work the run no longer has time to finish.

        Checked per node rather than as one timeout around the whole graph: an
        outer timeout would abort mid-node and lose the typed outcome, while
        this returns a normal SAFE_FAILURE the caller can act on.
        """

        deadline = current_deadline()
        if deadline is not None:
            deadline.check()

    @staticmethod
    def _record_rework_start(meta: InvocationMeta) -> None:
        # One round can re-run several components; count it once, only after
        # the deadline check and immediately before actual component work.
        counters = _REVIEW_TRACE_COUNTERS.get()
        if counters is not None and meta.attempt > 1:
            counters.started_rework_rounds.add(meta.attempt - 1)

    async def _info_node(self, state: AgentGraphState) -> dict[str, Any]:
        request = state["request"]
        trigger_input = getattr(request.trigger, "input", None)
        confirmed_overlays = [
            item
            for item in state.get("fact_overlays", [])
            if item.source_type == FactChangeSourceType.CONFIRMED_CONFLICT
        ]

        procedure_sources = [
            item
            for item in state.get("source_results", [])
            if item.meta.component == Component.PROCEDURE_TOOL
        ]
        if len(procedure_sources) != 1:
            raise RuntimeError("Info analysis requires one procedure lookup result")
        procedure_source = procedure_sources[0]

        meta = self._meta(
            state,
            Component.INFO_AGENT,
            attempt=state.get("revision_count", 0) + 1,
        )
        component_input = InfoAnalysisInput(
            input=trigger_input,
            case_snapshot=request.case_snapshot,
            fact_overlays=confirmed_overlays,
            allowed_field_paths=list(CASE_FIELD_SPECS),
            known_procedure_steps=[
                step.model_copy(deep=True) for step in self._known_procedure_steps
            ],
            source_call_id=meta.call_id,
            procedure_lookup_call_id=procedure_source.meta.call_id,
            procedure_lookup_result=procedure_source.output,
            review_feedback=state.get("review_feedback", []),
        )
        started = time.monotonic()
        try:
            self._check_deadline()
            self._record_rework_start(meta)
            output = await self._info_agent.analyze(component_input)
            source = ReviewSourceResult(
                meta=meta,
                output_digest=canonical_digest(output),
                output=output,
            )
            overlays = [
                *confirmed_overlays,
                *build_fact_overlays(
                    request.case_snapshot,
                    output,
                    meta.call_id,
                    uuid_factory=self._uuid,
                ),
            ]
        except Exception as exc:  # noqa: BLE001 - graph must fail closed
            self._emit(meta, started, "ERROR", exc)
            return self._failure(exc, Component.INFO_AGENT)
        self._emit(meta, started, "SUCCESS")
        return {
            "phase": "INFO_ANALYSIS",
            "source_results": [*state.get("source_results", []), source],
            "fact_overlays": overlays,
        }

    def _conflict_node(self, state: AgentGraphState) -> dict[str, Any]:
        info_sources = [
            item
            for item in state["source_results"]
            if item.meta.component == Component.INFO_AGENT
        ]
        if len(info_sources) != 1:
            raise RuntimeError("conflict outcome requires one Info result")
        info = info_sources[0].output
        evidence_by_id = {}
        for evidence in [
            *state["request"].case_snapshot.evidence_records,
            *info.evidence_records,
        ]:
            existing = evidence_by_id.get(evidence.evidence_id)
            if existing is not None and existing != evidence:
                raise ValueError("conflict evidence ID has conflicting content")
            evidence_by_id[evidence.evidence_id] = evidence
        evidence_records = []
        pending = [
            ref for conflict in info.conflicts for ref in conflict.source_evidence_refs
        ]
        included = set()
        while pending:
            ref = pending.pop()
            if ref in included:
                continue
            evidence = evidence_by_id.get(ref)
            if evidence is None:
                raise ValueError("conflict evidence reference cannot be resolved")
            included.add(ref)
            evidence_records.append(evidence)
            pending.extend(evidence.parent_evidence_refs)
        outcome = ConflictOutcome(
            outcome_type="CONFLICT",
            run_id=state["run_id"],
            case_id=state["request"].case_snapshot.case_id,
            trigger=state["request"].trigger,
            snapshot_id=state["request"].case_snapshot.snapshot_id,
            conflicts=info.conflicts,
            evidence_records=evidence_records,
            message_code="CONFIRM_CONFLICT",
        )
        return {"phase": "COMPLETED", "outcome": outcome}

    def _confirmed_conflict_node(self, state: AgentGraphState) -> dict[str, Any]:
        """Turn the user's confirmation into one reviewable change candidate.

        Deliberately not a write.  Letting the caller apply a confirmed value
        straight to the Case would put a Case change outside Review, and every
        change reaching a user has to have passed it.
        """

        request = state["request"]
        trigger = request.trigger
        if not isinstance(trigger, ConflictConfirmedTrigger):
            raise TypeError("confirmed-conflict node requires its own trigger")
        meta = self._meta(state, Component.INFO_AGENT, attempt=1)
        started = time.monotonic()
        try:
            self._check_deadline()
            overlay = build_confirmed_conflict_overlay(
                request.case_snapshot,
                trigger.confirmed_conflict,
                uuid_factory=self._uuid,
            )
        except Exception as exc:  # noqa: BLE001 - graph must fail closed
            self._emit(meta, started, "ERROR", exc)
            return self._failure(exc, Component.INFO_AGENT)
        self._emit(meta, started, "SUCCESS")
        return {"phase": "INFO_ANALYSIS", "fact_overlays": [overlay]}

    async def _procedure_node(self, state: AgentGraphState) -> dict[str, Any]:
        request = state["request"]
        meta = self._meta(
            state,
            Component.PROCEDURE_TOOL,
            attempt=state.get("revision_count", 0) + 1,
        )
        component_input = ProcedureLookupInput(
            lookup_goal="BUSINESS_CLOSURE",
            search_queries=self._procedure_queries(request),
            as_of=self._as_of(request),
            locale="ko-KR",
            source_policy="OFFICIAL_ONLY",
            max_results_per_query=5,
            based_on_snapshot_id=request.case_snapshot.snapshot_id,
            review_feedback=state.get("review_feedback", []),
        )
        started = time.monotonic()
        try:
            self._check_deadline()
            self._record_rework_start(meta)
            output = await self._procedure_tool.lookup(component_input)
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
        component_input: SupportAgentInput = DiscoverSupportInput(
            planning_context=context,
            as_of=self._as_of(request),
            review_feedback=state.get("review_feedback", []),
        )
        started = time.monotonic()
        try:
            self._check_deadline()
            self._record_rework_start(meta)
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
            self._check_deadline()
            previous_draft = (
                state.get("current_draft")
                if state.get("revision_count", 0) > 0
                else None
            )
            component_input = SupervisorAgentInput(
                trigger=state["request"].trigger,
                case_snapshot=state["request"].case_snapshot,
                known_procedure_steps=[
                    step.model_copy(deep=True) for step in self._known_procedure_steps
                ],
                source_results=state["source_results"],
                draft_version=state.get("revision_count", 0) + 1,
                review_feedback=state.get("review_feedback", []),
                fact_overlays=state.get("fact_overlays", []),
                previous_draft=previous_draft,
            )
            self._record_rework_start(meta)
            draft = await self._supervisor.draft(component_input)
        except Exception as exc:  # noqa: BLE001 - graph must fail closed
            self._emit(meta, started, "ERROR", exc)
            return self._failure(exc, Component.SUPERVISOR)
        self._emit(meta, started, "SUCCESS")
        return {"phase": "DRAFTING", "current_draft": draft}

    async def _review_node(self, state: AgentGraphState) -> dict[str, Any]:
        attempt = state.get("revision_count", 0) + 1
        started = time.monotonic()
        try:
            self._check_deadline()
            meta = self._meta(state, Component.REVIEW_TOOL, attempt=attempt)
            subject = ReviewSubject.create(
                schema_version="agent-io/2.0",
                review_subject_id=self._uuid(),
                review_attempt=attempt,
                run_id=state["run_id"],
                case_id=state["request"].case_snapshot.case_id,
                trigger=state["request"].trigger,
                snapshot=state["request"].case_snapshot,
                known_procedure_steps=[
                    step.model_copy(deep=True) for step in self._known_procedure_steps
                ],
                source_results=state["source_results"],
                supervisor_draft=state["current_draft"],
            )
            result = await self._review_tool.review(subject)
        except Exception as exc:  # noqa: BLE001 - graph must fail closed
            if "meta" in locals():
                self._emit(meta, started, "ERROR", exc)
            return self._failure(exc, Component.REVIEW_TOOL)
        self._emit(
            meta,
            started,
            "SUCCESS",
            review_verdict="PASS" if result.verdict == ReviewVerdict.PASS else "REVISE",
        )
        update: dict[str, Any] = {
            "phase": "REVIEWING",
            "review_subject": subject,
            "review_result": result,
            "review_meta": meta,
        }
        if result.verdict == ReviewVerdict.REVISE:
            revision_count = state.get("revision_count", 0)
            if revision_count >= self._max_review_revisions:
                # Keep the last Review's findings instead of dropping them.
                # Without this the caller learns only that the run failed, not
                # what would unblock it, and the reason for the verdict is gone.
                update.update(
                    {
                        "phase": "SAFE_FAILED",
                        "failure_code": "REVIEW_RETRY_EXHAUSTED",
                        "failure_message_code": "REVIEW_RETRY_EXHAUSTED",
                        "failed_component": Component.REVIEW_TOOL,
                        "retryable": False,
                        "review_feedback": self._review_feedback(result),
                        "rework_targets": list(result.recommended_rework_targets),
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
    def _requested_field_paths(failure: dict[str, Any]) -> list[CaseFieldKey]:
        """Name the Case fields whose absence is what stopped this run.

        The Review result cannot answer this.  Its paths point inside the draft
        (``/decision/next_action/...``) while this field takes Case field keys,
        and no mapping between the two exists; inventing one would be a guess.
        The source results do carry real field keys, so ask them instead, most
        specific first: what blocks the decision, then what the support
        comparison could not resolve, then what asking the user would settle.
        """

        blocks_decision: set[CaseFieldKey] = set()
        unresolved_support: set[CaseFieldKey] = set()
        answerable: set[CaseFieldKey] = set()
        for source in failure.get("source_results", []):
            output = source.output
            if isinstance(output, InfoAnalysisResult):
                blocks_decision.update(
                    item.field_path
                    for item in output.missing_fields
                    if MissingFieldBlock.SUPERVISOR_DECISION in item.blocks
                )
                for question in output.question_candidates:
                    answerable.update(question.resolves_field_paths)
            elif isinstance(output, SupportAnalysisResult):
                for check in output.support_checks:
                    unresolved_support.update(check.unknown_field_paths)
        found = blocks_decision or unresolved_support or answerable
        # Canonical order, so two runs that found the same fields in a
        # different sequence still produce the same outcome digest.
        return [key for key in CASE_FIELD_SPECS if key in found]

    @staticmethod
    def _build_safe_failure(
        request: AgentGraphInput,
        *,
        run_id: UUID,
        trace_id: str | None,
        failure: dict[str, Any],
    ) -> SafeFailureOutcome:
        requested = AgentGraph._requested_field_paths(failure)
        retryable = failure.get("retryable", False)
        # Naming fields the caller can actually collect beats telling them
        # there is nothing to do.  Only when a retry is not the answer: a
        # timeout is a latency problem, not a missing-input one.
        fallback_recovery = "RETRY" if retryable else "NONE"
        if requested and not retryable:
            fallback_recovery = "RESUBMIT_INPUT"
        return SafeFailureOutcome(
            outcome_type="SAFE_FAILURE",
            run_id=run_id,
            case_id=request.case_snapshot.case_id,
            trigger=request.trigger,
            snapshot_id=request.case_snapshot.snapshot_id,
            failure_code=failure.get("failure_code", "COMPONENT_UNAVAILABLE"),
            message_code=failure.get(
                "failure_message_code", "AGENT_COMPONENT_UNAVAILABLE"
            ),
            recovery_action_code=failure.get("recovery_action_code", fallback_recovery),
            requested_field_paths=requested,
            retryable=retryable,
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
    def _route_start(
        state: AgentGraphState,
    ) -> Literal["procedure", "support", "confirmed_conflict"]:
        trigger = state["request"].trigger
        if isinstance(trigger, ConflictConfirmedTrigger):
            return "confirmed_conflict"
        return "procedure"

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
        if Component.PROCEDURE_TOOL in targets:
            return "procedure"
        if Component.INFO_AGENT in targets:
            return "info"
        if Component.SUPPORT_AGENT in targets:
            return "support"
        return "supervisor"

    @staticmethod
    def _earliest_rework_target(targets: Sequence[Component]) -> Component:
        for component in (
            Component.PROCEDURE_TOOL,
            Component.INFO_AGENT,
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
        if earliest == Component.PROCEDURE_TOOL:
            return []
        if earliest == Component.INFO_AGENT:
            return [
                item
                for item in sources
                if item.meta.component == Component.PROCEDURE_TOOL
            ]
        if earliest == Component.SUPPORT_AGENT:
            return [
                item
                for item in sources
                if item.meta.component
                in {Component.PROCEDURE_TOOL, Component.INFO_AGENT}
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
            schema_version="agent-io/2.0",
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
    def _as_of(request: AgentGraphInput) -> date:
        trigger = request.trigger
        if isinstance(trigger, ConflictConfirmedTrigger):
            return trigger.confirmed_at.date()
        return trigger.submitted_at.date()

    @staticmethod
    def _failure(
        exc: Exception,
        component: Component | None,
    ) -> dict[str, Any]:
        name = exc.__class__.__name__
        if name == "StaleConfirmationError":
            return {
                "phase": "SAFE_FAILED",
                "failure_code": "STALE_CONFLICT_CONFIRMATION",
                "failure_message_code": "AGENT_STALE_CONFLICT_CONFIRMATION",
                "failed_component": component,
                # Resending the same answer cannot help; the user has to see the
                # value as it is now and decide again.
                "retryable": False,
                "recovery_action_code": "RESUBMIT_INPUT",
            }
        if name == "RunDeadlineExceededError":
            return {
                "phase": "SAFE_FAILED",
                "failure_code": "RUN_DEADLINE_EXCEEDED",
                "failure_message_code": "AGENT_RUN_DEADLINE_EXCEEDED",
                "failed_component": component,
                # A slow run may well succeed on a second try, unlike an
                # exhausted call budget, which would be spent again.
                "retryable": True,
            }
        if name == "LLMBudgetExceededError":
            return {
                "phase": "SAFE_FAILED",
                "failure_code": "LOOP_LIMIT_REACHED",
                "failure_message_code": "AGENT_LOOP_LIMIT_REACHED",
                "failed_component": component,
                "retryable": False,
            }
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
            "ProcedureSearchConfigurationError",
            "ProcedureLookupRequestError",
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

    @staticmethod
    def _procedure_queries(request: AgentGraphInput) -> list[str]:
        """Select at most four static topics without copying user text or facts."""

        confirmed = {
            fact.field_path.value: fact.value
            for fact in request.case_snapshot.facts
            if fact.status.value == "CONFIRMED"
        }
        if isinstance(request.trigger, ConflictConfirmedTrigger):
            conflict = request.trigger.confirmed_conflict
            if conflict.proposed_status == FactStatus.CONFIRMED:
                confirmed[conflict.field_path.value] = conflict.proposed_value
            else:
                confirmed.pop(conflict.field_path.value, None)
        trigger_input = getattr(request.trigger, "input", None)
        redacted_text = trigger_input.redacted_text if trigger_input is not None else ""

        queries: list[str] = []
        if (
            confirmed.get("lease_status") in {"LEASED_PAID", "LEASED_FREE"}
            or any(
                keyword in redacted_text
                for keyword in ("임차", "임대", "원상복구", "원상회복", "철거", "반환")
            )
            or (
                isinstance(request.trigger, ConflictConfirmedTrigger)
                and request.trigger.confirmed_conflict.field_path.value
                in {
                    "lease_status",
                    "restoration_status",
                    "restoration_scope",
                    "demolition_required",
                }
            )
        ):
            queries.append("임차 상가 원상복구 범위 확인 철거 절차")

        # Entity type is not a CASE field in schema_table.md. Explicit wording
        # may select a lookup topic, but never creates or confirms a Case fact.
        if "개인사업자" in redacted_text:
            queries.append("개인사업자 폐업 신고 절차 국세청")
        elif "법인사업자" in redacted_text or "법인 사업자" in redacted_text:
            queries.append("법인 사업자 폐업 신고 절차 국세청")
        else:
            queries.append("사업자 폐업 신고 절차 국세청")

        business_type = confirmed.get("business_type")
        if business_type is None:
            if any(keyword in redacted_text for keyword in ("카페", "휴게음식점")):
                business_type = "CAFE"
            elif any(
                keyword in redacted_text for keyword in ("식당", "음식점", "일반음식점")
            ):
                business_type = "RESTAURANT"
        business_queries = {
            "CAFE": "휴게음식점 폐업 신고 절차 정부24",
            "카페": "휴게음식점 폐업 신고 절차 정부24",
            "휴게음식점": "휴게음식점 폐업 신고 절차 정부24",
            "RESTAURANT": "일반음식점 폐업 신고 절차 정부24",
            "식당": "일반음식점 폐업 신고 절차 정부24",
            "일반음식점": "일반음식점 폐업 신고 절차 정부24",
        }
        business_query = business_queries.get(business_type)
        if business_query is not None:
            queries.append(business_query)
        employee_count = confirmed.get("employee_count")
        employee_hint = any(
            keyword in redacted_text
            for keyword in ("직원", "근로자", "4대보험", "사업장 소멸")
        )
        if (type(employee_count) is int and employee_count > 0) or employee_hint:
            queries.append("4대보험 탈퇴 사업장 폐업 신고 절차")
        return queries

    def _emit(
        self,
        meta: InvocationMeta,
        started: float,
        status: str,
        exc: Exception | None = None,
        *,
        review_verdict: Literal["PASS", "REVISE"] | None = None,
    ) -> None:
        counters = _REVIEW_TRACE_COUNTERS.get()
        if counters is not None and review_verdict is not None:
            counters.review_count += 1
            if review_verdict == "REVISE":
                counters.review_revise_count += 1
        model, prompt_tokens, completion_tokens = (
            self._usage.drain() if self._usage is not None else (None, None, None)
        )
        event = TraceEvent(
            run_id=str(meta.run_id),
            call_id=str(meta.call_id),
            component=meta.component.value,
            status=status,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            attempt=meta.attempt,
            review_verdict=review_verdict,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
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
