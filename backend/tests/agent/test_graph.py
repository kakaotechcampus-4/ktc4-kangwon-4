from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.agent.graph import AgentGraph
from app.agent.schemas import (
    ActionDecisionDraft,
    Blocker,
    CaseCreatedTrigger,
    CaseFact,
    CaseSnapshot,
    ConflictCandidate,
    EvidenceRecord,
    InfoAnalysisResult,
    MutationSet,
    NextAction,
    ProcedureLookupResult,
    ProcedureStepEvaluation,
    ProcedureStepRef,
    RedactedInput,
    ReviewIssue,
    ReviewResult,
    SupervisorDraft,
    SupervisorRunInput,
    SupportAnalysisResult,
    SupportSearchSummary,
)
from app.agent.support_agent import SupportAnalysisGuardrailError

NOW = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000301")


def evidence(evidence_id: str, source_type: str = "SYSTEM_RECORD") -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_type=source_type,
        source_ref="fixture:standalone",
        source_version="fixture-v1",
        locator="record:1",
        excerpt="테스트용 최소 근거",
        parent_evidence_refs=[],
        published_at=NOW,
        retrieved_at=NOW,
        freshness_status="CURRENT",
        content_hash="sha256:" + "a" * 64,
    )


def request() -> SupervisorRunInput:
    redacted = RedactedInput(
        input_event_id="input-graph",
        source_type="USER_INPUT",
        redacted_text="카페를 정리하려고 하며 원상복구 범위는 아직 모릅니다.",
        redactions=[],
        submitted_at=NOW,
    )
    return SupervisorRunInput(
        trigger=CaseCreatedTrigger(
            trigger_type="CASE_CREATED",
            input_event_id="input-graph",
            client_event_id="client-graph",
            input=redacted,
            submitted_at=NOW,
        ),
        case_snapshot=CaseSnapshot(
            snapshot_id=SNAPSHOT_ID,
            case_id=1,
            case_version=1,
            case_status="IN_PROGRESS",
            facts=[
                CaseFact(
                    field_path="restoration_scope",
                    value_type="ENUM",
                    value=None,
                    status="UNKNOWN",
                    evidence_refs=[],
                    updated_at=None,
                )
            ],
            procedure_progress=[],
            evidence_records=[evidence("ev-system")],
            captured_at=NOW,
        ),
    )


class FakeInfo:
    def __init__(self, *, conflict: bool = False) -> None:
        self.conflict = conflict
        self.calls = 0

    async def analyze(
        self,
        component_input: Any,
        *,
        source_call_id: UUID | None = None,
    ) -> InfoAnalysisResult:
        self.calls += 1
        conflicts = []
        records = []
        if self.conflict:
            records = [evidence("ev-conflict", "USER_INPUT")]
            conflicts = [
                ConflictCandidate.create_standalone(
                    candidate_id=UUID("00000000-0000-4000-8000-000000000302"),
                    snapshot_id=SNAPSHOT_ID,
                    case_version=1,
                    field_path="restoration_scope",
                    committed_status="CONFIRMED",
                    committed_value="TENANT_ALL",
                    proposed_operation="SET",
                    proposed_status="CONFIRMED",
                    proposed_value="LANDLORD_ALL",
                    source_evidence_refs=["ev-conflict"],
                    source_call_id=source_call_id,
                )
            ]
        missing_fields = []
        questions = []
        if conflicts:
            question_id = UUID("00000000-0000-4000-8000-000000000303")
            missing_fields = [
                {
                    "field_path": "restoration_scope",
                    "reason_summary": "기존 정보와 새 입력이 충돌합니다.",
                    "blocks": ["SUPERVISOR_DECISION"],
                    "question_candidate_id": question_id,
                }
            ]
            questions = [
                {
                    "question_id": question_id,
                    "text": "원상복구 범위 중 어느 정보가 맞는지 확인해 주세요.",
                    "resolves_field_paths": ["restoration_scope"],
                    "reason_summary": "충돌 확인이 필요합니다.",
                }
            ]
        return InfoAnalysisResult(
            completion_status="NEEDS_USER_INPUT" if conflicts else "COMPLETE",
            fact_candidates=[],
            procedure_progress_observations=[],
            conflicts=conflicts,
            missing_fields=missing_fields,
            uncertainties=[],
            question_candidates=questions,
            evidence_records=records,
            parser_version="fake/1",
            based_on_snapshot_id=component_input.case_snapshot.snapshot_id,
        )


class FakeProcedure:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def lookup(self, component_input: Any) -> ProcedureLookupResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("private upstream detail")
        master_evidence = evidence("ev-procedure", "PROCEDURE_MASTER")
        return ProcedureLookupResult(
            completion_status="COMPLETE",
            procedure_data_version="fixture-v1",
            step_evaluations=[
                ProcedureStepEvaluation(
                    procedure_step=ProcedureStepRef(
                        procedure_step_id=1,
                        step_code="CONFIRM_RESTORATION_SCOPE",
                    ),
                    step_name="원상복구 범위 확인",
                    is_active=True,
                    applicability="APPLICABLE",
                    readiness="READY",
                    current_status=None,
                    conditions=[],
                    prerequisites=[],
                    unavailable_reasons=[],
                    requires_professional=False,
                    professional_type=None,
                    decision_authority="LANDLORD",
                    evidence_refs=[master_evidence.evidence_id],
                )
            ],
            evidence_records=[master_evidence],
            based_on_snapshot_id=component_input.planning_context.case_snapshot.snapshot_id,
            based_on_candidate_ids=[],
        )


class FakeSupport:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, component_input: Any) -> SupportAnalysisResult:
        self.calls += 1
        return SupportAnalysisResult(
            completion_status="NO_CANDIDATE",
            support_checks=[],
            no_candidate_reason_code="NO_REVIEWED_PROGRAM",
            uncertainties=[],
            search_summary=SupportSearchSummary(
                wiki_lookup="NOT_REQUESTED",
                rag_used=False,
                official_source_checked=False,
                checked_at=NOW,
            ),
            evidence_records=[],
            based_on_snapshot_id=component_input.planning_context.case_snapshot.snapshot_id,
            based_on_candidate_ids=[],
        )


class GuardrailFailingSupport(FakeSupport):
    async def analyze(self, component_input: Any) -> SupportAnalysisResult:
        del component_input
        self.calls += 1
        raise SupportAnalysisGuardrailError(
            "synthetic model output failed deterministic validation"
        )


class FakeSupervisor:
    def __init__(self, *, revised_title: str | None = None) -> None:
        self.calls = 0
        self.feedback_sizes: list[int] = []
        self.previous_drafts: list[SupervisorDraft | None] = []
        self.revised_title = revised_title

    async def draft(
        self,
        component_input: SupervisorRunInput,
        source_results: Any,
        *,
        draft_version: int = 1,
        review_feedback: Any = (),
        fact_overlays: Any = None,
        previous_draft: SupervisorDraft | None = None,
    ) -> SupervisorDraft:
        del component_input, fact_overlays
        self.calls += 1
        self.feedback_sizes.append(len(review_feedback))
        self.previous_drafts.append(previous_draft)
        call_ids = [item.meta.call_id for item in source_results]
        title = "임대인에게 원상복구 범위를 확인하세요"
        if previous_draft is not None and self.revised_title is not None:
            title = self.revised_title
        decision = ActionDecisionDraft(
            decision_type="ACTION",
            draft_id=UUID(int=100 + draft_version),
            draft_version=draft_version,
            selection_summary="원상복구 범위를 먼저 확인해야 합니다.",
            requires_human=True,
            evidence_refs=["ev-system"],
            based_on_call_ids=call_ids,
            created_at=NOW,
            blocker=Blocker(
                blocker_code="RESTORATION_SCOPE_UNCONFIRMED",
                title="원상복구 범위 미확인",
                description="원상복구 범위가 아직 확인되지 않았습니다.",
                evidence_refs=["ev-system"],
            ),
            next_action=NextAction(
                action_code="ASK_LANDLORD_RESTORATION_SCOPE",
                sequence=1,
                title=title,
                reason="철거 범위를 정하기 전에 확인이 필요합니다.",
                questions_to_ask=["어느 시설까지 원상복구해야 하나요?"],
                target_procedure=None,
                evidence_refs=["ev-system"],
            ),
            questions_for_user=[],
        )
        return SupervisorDraft(
            decision=decision,
            mutations=MutationSet(
                fact_changes=[],
                procedure_progress_changes=[],
                support_match_updates=[],
                case_status_change=None,
            ),
            grounded_claims=[],
            source_call_ids=call_ids,
        )


class FakeReview:
    def __init__(self, verdicts: list[str], *, target: str = "SUPERVISOR") -> None:
        self.verdicts = verdicts
        self.target = target
        self.calls = 0

    async def review(self, subject: Any) -> ReviewResult:
        verdict = self.verdicts[min(self.calls, len(self.verdicts) - 1)]
        self.calls += 1
        issues: list[ReviewIssue] = []
        if verdict == "REVISE":
            target_call_id = next(
                (
                    item.meta.call_id
                    for item in subject.source_results
                    if item.meta.component == self.target
                ),
                None,
            )
            issues = [
                ReviewIssue(
                    issue_code="AMBIGUOUS_LANGUAGE",
                    category="LANGUAGE",
                    severity="BLOCKING",
                    target_component=self.target,
                    target_call_id=target_call_id,
                    target_path="/supervisor_draft/decision/next_action/title",
                    reason_summary="행동 문구를 더 구체적으로 써야 합니다.",
                    evidence_refs=[],
                )
            ]
        return ReviewResult(
            reviewed_subject_id=subject.review_subject_id,
            reviewed_subject_digest=subject.subject_digest,
            verdict=verdict,
            issues=issues,
            missing_evidence=[],
            recommended_rework_targets=([self.target] if verdict == "REVISE" else []),
            resolution_reason=(
                "수정이 필요합니다."
                if verdict == "REVISE"
                else "검토 기준을 충족했습니다."
            ),
        )


class MismatchedPassReview(FakeReview):
    async def review(self, subject: Any) -> ReviewResult:
        self.calls += 1
        return ReviewResult(
            reviewed_subject_id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
            reviewed_subject_digest="sha256:" + "f" * 64,
            verdict="PASS",
            issues=[],
            missing_evidence=[],
            recommended_rework_targets=[],
            resolution_reason="검토 식별자가 일치하지 않는 합성 응답입니다.",
        )


class ContentAwareReview(FakeReview):
    def __init__(self, *, required_title: str) -> None:
        super().__init__(["REVISE"])
        self.required_title = required_title
        self.observed_titles: list[str] = []

    async def review(self, subject: Any) -> ReviewResult:
        self.calls += 1
        title = subject.supervisor_draft.decision.next_action.title
        self.observed_titles.append(title)
        passed = title == self.required_title
        issues = []
        if not passed:
            issues = [
                ReviewIssue(
                    issue_code="AMBIGUOUS_LANGUAGE",
                    category="LANGUAGE",
                    severity="BLOCKING",
                    target_component="SUPERVISOR",
                    target_call_id=None,
                    target_path="/supervisor_draft/decision/next_action/title",
                    reason_summary="계약서에서 확인할 항목을 구체적으로 써야 합니다.",
                    evidence_refs=[],
                )
            ]
        return ReviewResult(
            reviewed_subject_id=subject.review_subject_id,
            reviewed_subject_digest=subject.subject_digest,
            verdict="PASS" if passed else "REVISE",
            issues=issues,
            missing_evidence=[],
            recommended_rework_targets=[] if passed else ["SUPERVISOR"],
            resolution_reason=(
                "구체적인 수정이 확인되었습니다."
                if passed
                else "행동 문구 수정이 필요합니다."
            ),
        )


def graph(
    *,
    info: FakeInfo | None = None,
    procedure: FakeProcedure | None = None,
    support: FakeSupport | None = None,
    supervisor: FakeSupervisor | None = None,
    review: FakeReview | None = None,
) -> tuple[
    AgentGraph, FakeInfo, FakeProcedure, FakeSupport, FakeSupervisor, FakeReview
]:
    info = info or FakeInfo()
    procedure = procedure or FakeProcedure()
    support = support or FakeSupport()
    supervisor = supervisor or FakeSupervisor()
    review = review or FakeReview(["PASS"])
    runtime = AgentGraph(
        info_agent=info,
        procedure_tool=procedure,
        support_agent=support,
        supervisor=supervisor,
        review_tool=review,
        known_procedure_steps=[],
        clock=lambda: NOW,
    )
    return runtime, info, procedure, support, supervisor, review


def test_full_graph_returns_only_reviewed_plan_with_pass_proof() -> None:
    runtime, info, procedure, support, supervisor, review = graph()
    outcome = asyncio.run(runtime.run(request(), trace_id="trace-graph"))

    assert outcome.outcome_type == "REVIEWED_PLAN"
    assert outcome.review_proof.verdict == "PASS"
    assert (
        outcome.review_proof.review_subject_id
        == outcome.review_subject.review_subject_id
    )
    assert (
        info.calls
        == procedure.calls
        == support.calls
        == supervisor.calls
        == review.calls
        == 1
    )


def test_review_revise_routes_back_to_supervisor_then_passes() -> None:
    supervisor = FakeSupervisor()
    review = FakeReview(["REVISE", "PASS"])
    runtime, *_ = graph(supervisor=supervisor, review=review)

    outcome = asyncio.run(runtime.run(request()))

    assert outcome.outcome_type == "REVIEWED_PLAN"
    assert supervisor.calls == 2
    assert supervisor.feedback_sizes == [0, 1]
    assert supervisor.previous_drafts[0] is None
    assert supervisor.previous_drafts[1] is not None
    assert review.calls == 2
    assert outcome.review_subject.review_attempt == 2


def test_content_aware_review_keeps_revising_an_unchanged_draft() -> None:
    required_title = "계약서 특약에서 원상복구 대상 시설을 확인하세요"
    supervisor = FakeSupervisor()
    review = ContentAwareReview(required_title=required_title)
    runtime, *_ = graph(supervisor=supervisor, review=review)

    outcome = asyncio.run(runtime.run(request()))

    assert outcome.outcome_type == "SAFE_FAILURE"
    assert outcome.failure_code == "REVIEW_RETRY_EXHAUSTED"
    assert review.observed_titles == [
        "임대인에게 원상복구 범위를 확인하세요",
        "임대인에게 원상복구 범위를 확인하세요",
        "임대인에게 원상복구 범위를 확인하세요",
    ]
    assert supervisor.previous_drafts[0] is None
    assert all(item is not None for item in supervisor.previous_drafts[1:])


def test_content_aware_review_passes_a_corrected_revision() -> None:
    required_title = "계약서 특약에서 원상복구 대상 시설을 확인하세요"
    supervisor = FakeSupervisor(revised_title=required_title)
    review = ContentAwareReview(required_title=required_title)
    runtime, *_ = graph(supervisor=supervisor, review=review)

    outcome = asyncio.run(runtime.run(request()))

    assert outcome.outcome_type == "REVIEWED_PLAN"
    assert review.observed_titles == [
        "임대인에게 원상복구 범위를 확인하세요",
        required_title,
    ]
    assert supervisor.previous_drafts[0] is None
    assert supervisor.previous_drafts[1] is not None
    assert supervisor.previous_drafts[1].decision.next_action.title == (
        "임대인에게 원상복구 범위를 확인하세요"
    )
    assert outcome.review_subject.supervisor_draft.decision.next_action.title == (
        required_title
    )


def test_review_retry_exhaustion_discards_unreviewed_draft() -> None:
    review = FakeReview(["REVISE"])
    runtime, *_ = graph(review=review)

    outcome = asyncio.run(runtime.run(request()))

    assert outcome.outcome_type == "SAFE_FAILURE"
    assert outcome.failure_code == "REVIEW_RETRY_EXHAUSTED"
    assert outcome.failed_component == "REVIEW_TOOL"
    assert review.calls == 3
    assert "review_subject" not in outcome.model_dump(mode="json")


def test_support_review_target_reruns_support_and_downstream_only() -> None:
    review = FakeReview(["REVISE", "PASS"], target="SUPPORT_AGENT")
    runtime, info, procedure, support, supervisor, _ = graph(review=review)

    outcome = asyncio.run(runtime.run(request()))

    assert outcome.outcome_type == "REVIEWED_PLAN"
    assert info.calls == procedure.calls == 1
    assert support.calls == supervisor.calls == review.calls == 2


def test_info_review_target_rebuilds_every_dependent_result() -> None:
    review = FakeReview(["REVISE", "PASS"], target="INFO_AGENT")
    runtime, info, procedure, support, supervisor, _ = graph(review=review)

    outcome = asyncio.run(runtime.run(request()))

    assert outcome.outcome_type == "REVIEWED_PLAN"
    assert info.calls == procedure.calls == support.calls == supervisor.calls == 2
    assert review.calls == 2


def test_component_exception_fails_closed_without_supervisor_or_review() -> None:
    procedure = FakeProcedure(fail=True)
    supervisor = FakeSupervisor()
    review = FakeReview(["PASS"])
    runtime, _, _, support, _, _ = graph(
        procedure=procedure,
        supervisor=supervisor,
        review=review,
    )

    outcome = asyncio.run(runtime.run(request()))

    assert outcome.outcome_type == "SAFE_FAILURE"
    assert outcome.failed_component == "PROCEDURE_TOOL"
    assert support.calls == supervisor.calls == review.calls == 0


def test_support_guardrail_exhaustion_is_classified_as_structured_failure() -> None:
    support = GuardrailFailingSupport()
    runtime, *_ = graph(support=support)

    outcome = asyncio.run(runtime.run(request()))

    assert outcome.outcome_type == "SAFE_FAILURE"
    assert outcome.failure_code == "STRUCTURED_OUTPUT_FAILED"
    assert outcome.failed_component == "SUPPORT_AGENT"


def test_unexpected_finalize_integrity_error_is_converted_to_safe_outcome() -> None:
    review = MismatchedPassReview(["PASS"])
    runtime, *_ = graph(review=review)

    outcome = asyncio.run(runtime.run(request()))

    assert outcome.outcome_type == "SAFE_FAILURE"
    assert outcome.failure_code == "STRUCTURED_OUTPUT_FAILED"
    assert outcome.failed_component is None


def test_fact_conflict_stops_before_lookup_and_returns_structured_conflict() -> None:
    info = FakeInfo(conflict=True)
    runtime, _, procedure, support, supervisor, review = graph(info=info)

    outcome = asyncio.run(runtime.run(request()))

    assert outcome.outcome_type == "CONFLICT"
    assert outcome.message_code == "CONFIRM_CONFLICT"
    assert len(outcome.conflicts) == 1
    assert procedure.calls == support.calls == supervisor.calls == review.calls == 0
