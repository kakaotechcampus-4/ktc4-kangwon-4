from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from app.agent.review_tool import (
    ReviewIntegrityError,
    ReviewModelOutput,
    ReviewOutputViolation,
    ReviewProviderOutput,
    ReviewTool,
)
from app.agent.schemas import (
    ActionDecisionDraft,
    Blocker,
    CaseCompleteDecisionDraft,
    CaseCreatedTrigger,
    CaseFact,
    CaseSnapshot,
    CaseStatusChangeCandidate,
    EvidenceRecord,
    FactCandidate,
    FactChangeCandidate,
    GroundedClaim,
    InfoAnalysisResult,
    InvocationMeta,
    MissingEvidence,
    MutationSet,
    NextAction,
    ProcedureConditionResult,
    ProcedureLookupResult,
    ProcedureProgressChangeCandidate,
    ProcedureProgressObservation,
    ProcedureStepEvaluation,
    ProcedureStepRef,
    RedactedInput,
    ReviewIssue,
    ReviewSourceResult,
    ReviewSubject,
    SupervisorDraft,
    SupportAnalysisResult,
    SupportCheck,
    SupportMatchUpdateCandidate,
    SupportProgramRef,
    SupportSearchSummary,
    VerifiedTextSpan,
    canonical_digest,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
RUN_ID = UUID("10000000-0000-4000-8000-000000000001")
CALL_ID = UUID("10000000-0000-4000-8000-000000000002")
PARENT_CALL_ID = UUID("10000000-0000-4000-8000-000000000003")
SNAPSHOT_ID = UUID("10000000-0000-4000-8000-000000000004")
SUBJECT_ID = UUID("10000000-0000-4000-8000-000000000005")
DRAFT_ID = UUID("10000000-0000-4000-8000-000000000006")
CLAIM_ID = UUID("10000000-0000-4000-8000-000000000007")
INVENTED_CALL_ID = UUID("10000000-0000-4000-8000-000000000099")
INFO_CALL_ID = UUID("10000000-0000-4000-8000-000000000008")
SUPPORT_CALL_ID = UUID("10000000-0000-4000-8000-000000000009")
SOURCE_FACT_ID = UUID("10000000-0000-4000-8000-000000000010")
MUTATION_ID = UUID("10000000-0000-4000-8000-000000000011")
OBSERVATION_ID = UUID("10000000-0000-4000-8000-000000000012")

TARGET_STEP = ProcedureStepRef(
    procedure_step_id=10,
    step_code="FILE_CLOSURE_REPORT",
)


class FakeStructuredClient:
    def __init__(self, outputs: list[Any]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        response_model: type[Any],
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            {
                "response_model": response_model,
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        return self.outputs.pop(0)


def evidence(
    evidence_id: str,
    *,
    source_type: str,
    freshness_status: str = "CURRENT",
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_type=source_type,
        source_ref=f"fixture:{evidence_id}",
        source_version="fixture-v1",
        locator="fixture.section",
        excerpt="검증된 가짜 테스트 근거",
        parent_evidence_refs=[],
        published_at=NOW,
        retrieved_at=NOW,
        freshness_status=freshness_status,
        content_hash="sha256:" + "b" * 64,
    )


def pass_output() -> ReviewModelOutput:
    return ReviewModelOutput(
        verdict="PASS",
        issues=[],
        missing_evidence=[],
        recommended_rework_targets=[],
        resolution_reason="제공된 근거와 절차 평가가 초안을 뒷받침합니다.",
    )


def review_subject(
    *,
    procedure_freshness: str = "CURRENT",
    procedure_evidence_source_type: str = "PROCEDURE_MASTER",
    target_step: ProcedureStepRef = TARGET_STEP,
    action_evidence_refs: list[str] | None = None,
    action_reason: str = "업종 확인 결과를 바탕으로 신고 방법을 확인할 차례입니다.",
    include_claim: bool = True,
    claim_type: str = "PROCEDURE",
    claim_assertion_level: str = "INFORMATION",
    claim_evidence_refs: list[str] | None = None,
) -> ReviewSubject:
    case_evidence = evidence("case:business-type", source_type="USER_INPUT")
    unrelated_evidence = evidence("case:unrelated", source_type="SYSTEM_RECORD")
    procedure_evidence = evidence(
        "procedure:file-report",
        source_type=procedure_evidence_source_type,
        freshness_status=procedure_freshness,
    )
    snapshot = CaseSnapshot(
        snapshot_id=SNAPSHOT_ID,
        case_id=1,
        case_version=1,
        case_status="IN_PROGRESS",
        facts=[
            CaseFact(
                field_path="business_type",
                value_type="STRING",
                value="CAFE",
                status="CONFIRMED",
                evidence_refs=[case_evidence.evidence_id],
                updated_at=NOW,
            )
        ],
        procedure_progress=[],
        evidence_records=[case_evidence, unrelated_evidence],
        captured_at=NOW,
    )
    procedure_output = ProcedureLookupResult(
        completion_status="COMPLETE",
        procedure_data_version="procedure-fixture-v1",
        step_evaluations=[
            ProcedureStepEvaluation(
                procedure_step=TARGET_STEP,
                step_name="폐업 신고",
                is_active=True,
                applicability="APPLICABLE",
                readiness="READY",
                current_status=None,
                conditions=[
                    ProcedureConditionResult(
                        condition_id=1,
                        field_path="business_type",
                        operator="EQ",
                        expected_values=["CAFE"],
                        actual_value="CAFE",
                        status="MET",
                        evidence_refs=[
                            procedure_evidence.evidence_id,
                            case_evidence.evidence_id,
                        ],
                    )
                ],
                prerequisites=[],
                unavailable_reasons=[],
                requires_professional=False,
                professional_type=None,
                decision_authority="OFFICIAL_AGENCY",
                evidence_refs=[procedure_evidence.evidence_id],
            )
        ],
        evidence_records=[procedure_evidence],
        based_on_snapshot_id=SNAPSHOT_ID,
        based_on_candidate_ids=[],
    )
    meta = InvocationMeta(
        schema_version="agent-io/1.0",
        run_id=RUN_ID,
        call_id=CALL_ID,
        parent_call_id=PARENT_CALL_ID,
        case_id=1,
        component="PROCEDURE_TOOL",
        attempt=1,
        requested_at=NOW,
        trace_id=None,
    )
    source = ReviewSourceResult(
        meta=meta,
        output_digest=canonical_digest(procedure_output),
        output=procedure_output,
    )
    trigger = CaseCreatedTrigger(
        trigger_type="CASE_CREATED",
        input_event_id="input-event-1",
        client_event_id="client-event-1",
        input=RedactedInput(
            input_event_id="input-event-1",
            source_type="USER_INPUT",
            redacted_text="카페를 폐업하려고 합니다.",
            redactions=[],
            submitted_at=NOW,
        ),
        submitted_at=NOW,
    )
    action_refs = (
        [procedure_evidence.evidence_id]
        if action_evidence_refs is None
        else action_evidence_refs
    )
    decision = ActionDecisionDraft(
        decision_type="ACTION",
        draft_id=DRAFT_ID,
        draft_version=1,
        selection_summary="확인된 업종과 절차 자료를 사용했습니다.",
        requires_human=True,
        evidence_refs=[case_evidence.evidence_id, procedure_evidence.evidence_id],
        based_on_call_ids=[CALL_ID],
        created_at=NOW,
        blocker=Blocker(
            blocker_code="CLOSURE_REPORT_NOT_STARTED",
            title="폐업 신고 방법 미확인",
            description="관할 기관의 신고 방법을 아직 확인하지 않았습니다.",
            evidence_refs=[case_evidence.evidence_id],
        ),
        next_action=NextAction(
            action_code="ASK_OFFICIAL_CLOSURE_REPORT_METHOD",
            sequence=1,
            title="관할 기관에 폐업 신고 방법을 확인하세요",
            reason=action_reason,
            questions_to_ask=["필요한 서류와 접수 방법은 무엇인가요?"],
            target_procedure=target_step,
            evidence_refs=action_refs,
        ),
        questions_for_user=[],
    )
    claims = []
    if include_claim:
        grounded_evidence_refs = (
            [procedure_evidence.evidence_id, case_evidence.evidence_id]
            if claim_evidence_refs is None
            else claim_evidence_refs
        )
        claims.append(
            GroundedClaim(
                claim_id=CLAIM_ID,
                claim_type=claim_type,
                target_path="/supervisor_draft/decision/next_action/reason",
                text=action_reason,
                assertion_level=claim_assertion_level,
                evidence_refs=grounded_evidence_refs,
            )
        )
    draft = SupervisorDraft(
        decision=decision,
        mutations=MutationSet(
            fact_changes=[],
            procedure_progress_changes=[],
            support_match_updates=[],
            case_status_change=None,
        ),
        grounded_claims=claims,
        source_call_ids=[CALL_ID],
    )
    return ReviewSubject.create(
        schema_version="agent-io/1.0",
        review_subject_id=SUBJECT_ID,
        review_attempt=1,
        run_id=RUN_ID,
        case_id=1,
        trigger=trigger,
        snapshot=snapshot,
        source_results=[source],
        supervisor_draft=draft,
    )


def case_complete_subject(*, current_status: str | None) -> ReviewSubject:
    original = review_subject()
    original_source = original.source_results[0]
    procedure_output = original_source.output.model_copy(deep=True)
    procedure_output.step_evaluations[0].current_status = current_status
    procedure_source = ReviewSourceResult(
        meta=original_source.meta,
        output_digest=canonical_digest(procedure_output),
        output=procedure_output,
    )
    decision = CaseCompleteDecisionDraft(
        decision_type="CASE_COMPLETE",
        draft_id=DRAFT_ID,
        draft_version=1,
        selection_summary="검수된 절차가 모두 완료되었습니다.",
        requires_human=False,
        evidence_refs=["procedure:file-report"],
        based_on_call_ids=[CALL_ID],
        created_at=NOW,
        blocker=None,
        next_action=None,
        questions_for_user=[],
    )
    draft = SupervisorDraft(
        decision=decision,
        mutations=MutationSet(
            fact_changes=[],
            procedure_progress_changes=[],
            support_match_updates=[],
            case_status_change=CaseStatusChangeCandidate(
                candidate_id=MUTATION_ID,
                before_status="IN_PROGRESS",
                proposed_status="COMPLETED",
                reason_summary=decision.selection_summary,
                evidence_refs=decision.evidence_refs,
            ),
        ),
        grounded_claims=[],
        source_call_ids=[CALL_ID],
    )
    return ReviewSubject.create(
        schema_version=original.schema_version,
        review_subject_id=original.review_subject_id,
        review_attempt=original.review_attempt,
        run_id=original.run_id,
        case_id=original.case_id,
        trigger=original.trigger,
        snapshot=original.snapshot,
        source_results=[procedure_source],
        supervisor_draft=draft,
    )


def blocked_action_subject() -> ReviewSubject:
    original = review_subject()
    original_source = original.source_results[0]
    procedure_output = original_source.output.model_copy(deep=True)
    evaluation_payload = procedure_output.step_evaluations[0].model_dump(mode="python")
    evaluation_payload.update(
        {
            "is_active": False,
            "applicability": "NOT_APPLICABLE",
            "readiness": "BLOCKED",
        }
    )
    procedure_output.step_evaluations = [
        ProcedureStepEvaluation.model_validate(evaluation_payload)
    ]
    procedure_source = ReviewSourceResult(
        meta=original_source.meta,
        output_digest=canonical_digest(procedure_output),
        output=procedure_output,
    )
    return ReviewSubject.create(
        schema_version=original.schema_version,
        review_subject_id=original.review_subject_id,
        review_attempt=original.review_attempt,
        run_id=original.run_id,
        case_id=original.case_id,
        trigger=original.trigger,
        snapshot=original.snapshot,
        source_results=[procedure_source],
        supervisor_draft=original.supervisor_draft,
    )


def source_meta(component: str, call_id: UUID) -> InvocationMeta:
    return InvocationMeta(
        schema_version="agent-io/1.0",
        run_id=RUN_ID,
        call_id=call_id,
        parent_call_id=PARENT_CALL_ID,
        case_id=1,
        component=component,
        attempt=1,
        requested_at=NOW,
        trace_id=None,
    )


def rebuild_subject(
    original: ReviewSubject,
    *,
    extra_sources: list[ReviewSourceResult],
    mutations: MutationSet,
) -> ReviewSubject:
    sources = [*original.source_results, *extra_sources]
    call_ids = [source.meta.call_id for source in sources]
    decision_values = original.supervisor_draft.decision.model_dump(mode="python")
    decision_values["based_on_call_ids"] = call_ids
    decision = ActionDecisionDraft.model_validate(decision_values)
    draft = SupervisorDraft(
        decision=decision,
        mutations=mutations,
        grounded_claims=original.supervisor_draft.grounded_claims,
        source_call_ids=call_ids,
    )
    return ReviewSubject.create(
        schema_version=original.schema_version,
        review_subject_id=original.review_subject_id,
        review_attempt=original.review_attempt,
        run_id=original.run_id,
        case_id=original.case_id,
        trigger=original.trigger,
        snapshot=original.snapshot,
        source_results=sources,
        supervisor_draft=draft,
    )


def subject_with_fact_mutation(
    *,
    proposed_value: int = 3,
    requires_confirmation: bool = False,
) -> ReviewSubject:
    original = review_subject()
    case_evidence = original.snapshot.evidence_records[0]
    fact_candidate = FactCandidate(
        candidate_id=SOURCE_FACT_ID,
        operation="SET",
        field_path="employee_count",
        value_type="INTEGER",
        value=3,
        source_span=VerifiedTextSpan(
            input_event_id="input-event-1",
            text="카페",
            start_offset=0,
            end_offset=2,
        ),
        source_evidence_refs=[case_evidence.evidence_id],
        confidence_bps=9000,
        requires_confirmation=requires_confirmation,
        reason_summary="입력에서 종업원 수를 확인했습니다.",
    )
    output = InfoAnalysisResult(
        completion_status="COMPLETE",
        fact_candidates=[fact_candidate],
        procedure_progress_observations=[],
        conflicts=[],
        missing_fields=[],
        uncertainties=[],
        question_candidates=[],
        evidence_records=[case_evidence],
        parser_version="fixture-info-v1",
        based_on_snapshot_id=SNAPSHOT_ID,
    )
    source = ReviewSourceResult(
        meta=source_meta("INFO_AGENT", INFO_CALL_ID),
        output_digest=canonical_digest(output),
        output=output,
    )
    mutation = FactChangeCandidate(
        candidate_id=MUTATION_ID,
        operation="SET",
        source_fact_candidate_id=SOURCE_FACT_ID,
        source_type="INFO_ANALYSIS",
        field_path="employee_count",
        value_type="INTEGER",
        before_status="UNKNOWN",
        before_value=None,
        proposed_status="CONFIRMED",
        proposed_value=proposed_value,
        candidate_status="READY_FOR_REVIEW",
        reason_summary=fact_candidate.reason_summary,
        source_evidence_refs=fact_candidate.source_evidence_refs,
        source_call_id=INFO_CALL_ID,
        confirmed_conflict_ref=None,
    )
    return rebuild_subject(
        original,
        extra_sources=[source],
        mutations=MutationSet(
            fact_changes=[mutation],
            procedure_progress_changes=[],
            support_match_updates=[],
            case_status_change=None,
        ),
    )


def subject_with_procedure_mutation(*, execution_ref: str) -> ReviewSubject:
    original = review_subject()
    case_evidence = original.snapshot.evidence_records[0]
    observation = ProcedureProgressObservation(
        observation_id=OBSERVATION_ID,
        procedure_step=TARGET_STEP,
        observed_status="IN_PROGRESS",
        source_span=VerifiedTextSpan(
            input_event_id="input-event-1",
            text="카페",
            start_offset=0,
            end_offset=2,
        ),
        source_evidence_refs=[case_evidence.evidence_id],
        requires_confirmation=False,
        reason_summary="사용자가 절차 진행을 시작했다고 알렸습니다.",
    )
    info_output = InfoAnalysisResult(
        completion_status="COMPLETE",
        fact_candidates=[],
        procedure_progress_observations=[observation],
        conflicts=[],
        missing_fields=[],
        uncertainties=[],
        question_candidates=[],
        evidence_records=[case_evidence],
        parser_version="fixture-info-v1",
        based_on_snapshot_id=SNAPSHOT_ID,
    )
    info_source = ReviewSourceResult(
        meta=source_meta("INFO_AGENT", INFO_CALL_ID),
        output_digest=canonical_digest(info_output),
        output=info_output,
    )
    mutation = ProcedureProgressChangeCandidate(
        candidate_id=MUTATION_ID,
        procedure_step=TARGET_STEP,
        before_status=None,
        proposed_status="IN_PROGRESS",
        reason_summary=observation.reason_summary,
        execution_evidence_refs=[execution_ref],
        procedure_evaluation_call_id=CALL_ID,
    )
    return rebuild_subject(
        original,
        extra_sources=[info_source],
        mutations=MutationSet(
            fact_changes=[],
            procedure_progress_changes=[mutation],
            support_match_updates=[],
            case_status_change=None,
        ),
    )


def subject_with_support_mutation(*, tampered: bool) -> ReviewSubject:
    original = review_subject()
    official = evidence("support:official", source_type="OFFICIAL_DOCUMENT")
    program = SupportProgramRef(
        support_program_id=501,
        wiki_uuid=UUID("10000000-0000-4000-8000-000000000501"),
    )
    support_check = SupportCheck(
        support_program=program,
        program_name="가짜 점포정리 검토 항목",
        related_steps=[TARGET_STEP],
        match_status="NEEDS_CONFIRMATION",
        criteria=[],
        unknown_field_paths=["employee_count"],
        required_documents=[],
        application_channel=None,
        application_url=None,
        application_period=None,
        source_version="fixture-support-v1",
        freshness_status="CURRENT",
        checked_at=NOW,
        reason_summary="추가 사실 확인이 필요합니다.",
        evidence_refs=[official.evidence_id],
    )
    output = SupportAnalysisResult(
        completion_status="COMPLETE",
        support_checks=[support_check],
        no_candidate_reason_code=None,
        uncertainties=[],
        search_summary=SupportSearchSummary(
            wiki_lookup="HIT",
            rag_used=False,
            official_source_checked=True,
            checked_at=NOW,
        ),
        evidence_records=[official],
        based_on_snapshot_id=SNAPSHOT_ID,
        based_on_candidate_ids=[],
    )
    source = ReviewSourceResult(
        meta=source_meta("SUPPORT_AGENT", SUPPORT_CALL_ID),
        output_digest=canonical_digest(output),
        output=output,
    )
    mutation_check = (
        support_check.model_copy(update={"reason_summary": "변조된 비교 이유입니다."})
        if tampered
        else support_check
    )
    mutation = SupportMatchUpdateCandidate(
        candidate_id=MUTATION_ID,
        support_check=mutation_check,
        source_call_id=SUPPORT_CALL_ID,
    )
    return rebuild_subject(
        original,
        extra_sources=[source],
        mutations=MutationSet(
            fact_changes=[],
            procedure_progress_changes=[],
            support_match_updates=[mutation],
            case_status_change=None,
        ),
    )


def test_review_calls_model_and_injects_subject_identity() -> None:
    subject = review_subject()
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "PASS"
    assert result.reviewed_subject_id == subject.review_subject_id
    assert result.reviewed_subject_digest == subject.subject_digest
    assert len(client.calls) == 1
    response_fields = client.calls[0]["response_model"].model_fields
    assert "reviewed_subject_id" not in response_fields
    assert "reviewed_subject_digest" not in response_fields
    prompt = client.calls[0]["messages"][1]["content"]
    assert str(subject.review_subject_id) not in prompt
    assert subject.subject_digest not in prompt
    assert "source_ref" not in prompt
    assert "fixture:procedure:file-report" not in prompt
    assert "case:unrelated" not in prompt
    assert "카페를 폐업하려고 합니다." in prompt
    assert "input-event-1" not in prompt


def test_warning_only_output_passes_without_rework_target() -> None:
    subject = review_subject()
    output = ReviewModelOutput(
        verdict="PASS",
        issues=[
            ReviewIssue(
                issue_code="AMBIGUOUS_LANGUAGE",
                category="LANGUAGE",
                severity="WARNING",
                target_component="PROCEDURE_TOOL",
                target_call_id=CALL_ID,
                target_path=("/source_results/0/output/step_evaluations/0/readiness"),
                reason_summary="절차 준비 상태 표현을 다시 확인해야 합니다.",
                evidence_refs=["procedure:file-report"],
            )
        ],
        missing_evidence=[],
        recommended_rework_targets=[],
        resolution_reason="표현상 경고는 있지만 결정 차단 사유는 없습니다.",
    )
    client = FakeStructuredClient([output])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "PASS"
    assert result.recommended_rework_targets == []
    prompt = client.calls[0]["messages"][1]["content"]
    payload = json.loads(prompt.removeprefix("INPUT_JSON="))
    assert payload["source_results"][0]["meta"]["call_id"] == str(CALL_ID)
    assert "call_id" not in payload["source_results"][0]
    assert "evidence_records" not in payload
    assert (
        payload["source_results"][0]["output"]["evidence_records"][0]["evidence_id"]
        == "procedure:file-report"
    )


def test_blocking_model_issue_target_is_always_added_to_rework_targets() -> None:
    subject = review_subject()
    output = ReviewModelOutput(
        verdict="REVISE",
        issues=[
            ReviewIssue(
                issue_code="INFEASIBLE_ACTION",
                category="ACTIONABILITY",
                severity="BLOCKING",
                target_component="PROCEDURE_TOOL",
                target_call_id=CALL_ID,
                target_path="/source_results/0/output/step_evaluations/0/readiness",
                reason_summary="절차 준비 상태를 다시 조회해야 합니다.",
                evidence_refs=["procedure:file-report"],
            )
        ],
        missing_evidence=[],
        recommended_rework_targets=["SUPERVISOR"],
        resolution_reason="절차 조회를 다시 실행해야 합니다.",
    )
    client = FakeStructuredClient([output])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "REVISE"
    assert result.recommended_rework_targets == ["PROCEDURE_TOOL"]


def test_warning_only_revise_is_rejected_by_local_semantic_schema() -> None:
    with pytest.raises(ValidationError, match="warning-only findings must PASS"):
        ReviewModelOutput(
            verdict="REVISE",
            issues=[
                ReviewIssue(
                    issue_code="AMBIGUOUS_LANGUAGE",
                    category="LANGUAGE",
                    severity="WARNING",
                    target_component="SUPERVISOR",
                    target_call_id=None,
                    target_path="/supervisor_draft/decision/next_action/reason",
                    reason_summary="문장을 조금 더 명확히 표현할 수 있습니다.",
                    evidence_refs=[],
                )
            ],
            missing_evidence=[],
            recommended_rework_targets=[],
            resolution_reason="차단 사유는 없습니다.",
        )


def test_missing_evidence_derives_supervisor_target_and_ignores_model_target() -> None:
    subject = review_subject()
    output = ReviewModelOutput(
        verdict="REVISE",
        issues=[],
        missing_evidence=[
            MissingEvidence(
                claim_path="/supervisor_draft/decision/next_action/reason",
                required_source_types=["PROCEDURE_MASTER"],
                reason_summary="행동 이유를 뒷받침할 절차 근거가 더 필요합니다.",
            )
        ],
        recommended_rework_targets=["PROCEDURE_TOOL"],
        resolution_reason="Supervisor가 근거를 갖춘 행동을 다시 선택해야 합니다.",
    )
    client = FakeStructuredClient([output])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "REVISE"
    assert result.recommended_rework_targets == ["SUPERVISOR"]


def test_source_owned_missing_evidence_retries_then_rejects() -> None:
    subject = review_subject()
    invalid = ReviewModelOutput(
        verdict="REVISE",
        issues=[],
        missing_evidence=[
            MissingEvidence(
                claim_path=(
                    "/source_results/0/output/step_evaluations/0/evidence_refs"
                ),
                required_source_types=["PROCEDURE_MASTER"],
                reason_summary="절차 조회 근거를 보강해야 합니다.",
            )
        ],
        recommended_rework_targets=["PROCEDURE_TOOL"],
        resolution_reason="절차 조회 결과에 근거가 더 필요합니다.",
    )
    client = FakeStructuredClient([invalid, invalid])

    with pytest.raises(ReviewOutputViolation, match="Supervisor draft path"):
        asyncio.run(ReviewTool(client, max_output_attempts=2).review(subject))

    assert len(client.calls) == 2
    corrective_message = client.calls[1]["messages"][-1]["content"]
    assert "below /supervisor_draft/" in corrective_message
    assert "never use a /source_results/ path" in corrective_message


def test_source_path_cannot_be_owned_by_supervisor() -> None:
    subject = review_subject()
    invalid = ReviewModelOutput(
        verdict="REVISE",
        issues=[
            ReviewIssue(
                issue_code="INFEASIBLE_ACTION",
                category="ACTIONABILITY",
                severity="BLOCKING",
                target_component="SUPERVISOR",
                target_call_id=None,
                target_path="/source_results/0/output/step_evaluations/0/readiness",
                reason_summary="절차 조회 결과를 다시 확인해야 합니다.",
                evidence_refs=["procedure:file-report"],
            )
        ],
        missing_evidence=[],
        recommended_rework_targets=["SUPERVISOR"],
        resolution_reason="대상 소유권이 일치해야 합니다.",
    )
    client = FakeStructuredClient([invalid])

    with pytest.raises(ReviewOutputViolation, match="does not own"):
        asyncio.run(ReviewTool(client, max_output_attempts=1).review(subject))


def test_supervisor_path_cannot_be_owned_by_source_call() -> None:
    subject = review_subject()
    invalid = ReviewModelOutput(
        verdict="REVISE",
        issues=[
            ReviewIssue(
                issue_code="INFEASIBLE_ACTION",
                category="ACTIONABILITY",
                severity="BLOCKING",
                target_component="PROCEDURE_TOOL",
                target_call_id=CALL_ID,
                target_path="/supervisor_draft/decision/next_action",
                reason_summary="Supervisor의 행동 선택을 다시 확인해야 합니다.",
                evidence_refs=["procedure:file-report"],
            )
        ],
        missing_evidence=[],
        recommended_rework_targets=["PROCEDURE_TOOL"],
        resolution_reason="대상 소유권이 일치해야 합니다.",
    )
    client = FakeStructuredClient([invalid])

    with pytest.raises(ReviewOutputViolation, match="does not own"):
        asyncio.run(ReviewTool(client, max_output_attempts=1).review(subject))


def test_source_path_requires_the_call_id_at_that_exact_index() -> None:
    original = review_subject()
    original_source = original.source_results[0]
    second_source = ReviewSourceResult(
        meta=source_meta("PROCEDURE_TOOL", INVENTED_CALL_ID),
        output_digest=original_source.output_digest,
        output=original_source.output,
    )
    subject = rebuild_subject(
        original,
        extra_sources=[second_source],
        mutations=MutationSet(
            fact_changes=[],
            procedure_progress_changes=[],
            support_match_updates=[],
            case_status_change=None,
        ),
    )
    invalid = ReviewModelOutput(
        verdict="REVISE",
        issues=[
            ReviewIssue(
                issue_code="INFEASIBLE_ACTION",
                category="ACTIONABILITY",
                severity="BLOCKING",
                target_component="PROCEDURE_TOOL",
                target_call_id=INVENTED_CALL_ID,
                target_path="/source_results/0/output/step_evaluations/0/readiness",
                reason_summary="첫 번째 조회 결과를 다시 확인해야 합니다.",
                evidence_refs=["procedure:file-report"],
            )
        ],
        missing_evidence=[],
        recommended_rework_targets=["PROCEDURE_TOOL"],
        resolution_reason="경로와 호출 ID가 같은 source를 가리켜야 합니다.",
    )
    client = FakeStructuredClient([invalid])

    with pytest.raises(ReviewOutputViolation, match="does not own"):
        asyncio.run(ReviewTool(client, max_output_attempts=1).review(subject))


def test_invented_model_call_reference_is_retried_then_rejected() -> None:
    subject = review_subject()
    invalid = ReviewModelOutput(
        verdict="REVISE",
        issues=[
            ReviewIssue(
                issue_code="INFEASIBLE_ACTION",
                category="ACTIONABILITY",
                severity="BLOCKING",
                target_component="PROCEDURE_TOOL",
                target_call_id=INVENTED_CALL_ID,
                target_path="/supervisor_draft/decision/next_action",
                reason_summary="대상 호출을 확인해야 합니다.",
                evidence_refs=["procedure:file-report"],
            )
        ],
        missing_evidence=[],
        recommended_rework_targets=["PROCEDURE_TOOL"],
        resolution_reason="절차 근거를 다시 확인해야 합니다.",
    )
    client = FakeStructuredClient([invalid, invalid])

    with pytest.raises(ReviewOutputViolation, match="component call"):
        asyncio.run(ReviewTool(client, max_output_attempts=2).review(subject))

    assert len(client.calls) == 2


def test_contract_extra_runtime_identity_is_retried() -> None:
    subject = review_subject()
    invalid = {
        **pass_output().model_dump(mode="python"),
        "reviewed_subject_id": str(subject.review_subject_id),
    }
    client = FakeStructuredClient([invalid, pass_output()])

    result = asyncio.run(ReviewTool(client, max_output_attempts=2).review(subject))

    assert result.verdict == "PASS"
    assert len(client.calls) == 2


def test_provider_semantic_gate_failure_is_retried_then_succeeds() -> None:
    subject = review_subject()
    invalid = ReviewProviderOutput(
        verdict="PASS",
        issues=[],
        missing_evidence=[
            {
                "claim_path": "/supervisor_draft/decision/next_action/reason",
                "required_source_types": ["PROCEDURE_MASTER"],
                "reason_summary": "절차 근거를 다시 확인해야 합니다.",
            }
        ],
        recommended_rework_targets=["SUPERVISOR"],
        resolution_reason="근거를 다시 확인해야 합니다.",
    )
    client = FakeStructuredClient([invalid, pass_output()])

    result = asyncio.run(ReviewTool(client, max_output_attempts=2).review(subject))

    assert result.verdict == "PASS"
    assert len(client.calls) == 2
    assert client.calls[0]["response_model"] is ReviewProviderOutput
    correction = client.calls[1]["messages"][-1]["content"]
    assert "PASS must have no blocking issue" in correction


def test_provider_semantic_gate_failure_exhausts_bounded_retry() -> None:
    subject = review_subject()
    invalid = ReviewProviderOutput(
        verdict="REVISE",
        issues=[
            {
                "issue_code": "AMBIGUOUS_LANGUAGE",
                "category": "LANGUAGE",
                "severity": "WARNING",
                "target_component": "SUPERVISOR",
                "target_call_id": None,
                "target_path": "/supervisor_draft/decision/next_action/reason",
                "reason_summary": "문장을 조금 더 명확히 표현할 수 있습니다.",
                "evidence_refs": [],
            }
        ],
        missing_evidence=[],
        recommended_rework_targets=["SUPERVISOR"],
        resolution_reason="근거를 보강해야 합니다.",
    )
    client = FakeStructuredClient([invalid, invalid])

    with pytest.raises(ReviewOutputViolation, match="violates its schema"):
        asyncio.run(ReviewTool(client, max_output_attempts=2).review(subject))

    assert len(client.calls) == 2
    assert all(call["response_model"] is ReviewProviderOutput for call in client.calls)


def test_blocked_selected_action_reworks_supervisor_not_procedure_tool() -> None:
    subject = blocked_action_subject()
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    issue = next(
        item for item in result.issues if item.issue_code == "INFEASIBLE_ACTION"
    )
    assert result.verdict == "REVISE"
    assert issue.target_component == "SUPERVISOR"
    assert issue.target_call_id is None
    assert result.recommended_rework_targets == ["SUPERVISOR"]


def test_invented_model_evidence_reference_is_rejected() -> None:
    subject = review_subject()
    invalid = ReviewModelOutput(
        verdict="REVISE",
        issues=[
            ReviewIssue(
                issue_code="INFEASIBLE_ACTION",
                category="ACTIONABILITY",
                severity="BLOCKING",
                target_component="SUPERVISOR",
                target_call_id=None,
                target_path="/supervisor_draft/decision/next_action",
                reason_summary="행동 근거를 다시 확인해야 합니다.",
                evidence_refs=["invented:evidence"],
            )
        ],
        missing_evidence=[],
        recommended_rework_targets=["SUPERVISOR"],
        resolution_reason="근거를 다시 확인해야 합니다.",
    )
    client = FakeStructuredClient([invalid])

    with pytest.raises(ReviewOutputViolation, match="evidence reference"):
        asyncio.run(ReviewTool(client, max_output_attempts=1).review(subject))


@pytest.mark.parametrize("freshness", ["STALE", "UNKNOWN"])
def test_unverified_claim_forces_revise_even_when_model_passes(
    freshness: str,
) -> None:
    subject = review_subject(procedure_freshness=freshness)
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert len(client.calls) == 1
    assert result.verdict == "REVISE"
    assert any(issue.issue_code == "STALE_EVIDENCE" for issue in result.issues)
    assert "SUPERVISOR" in result.recommended_rework_targets


@pytest.mark.parametrize(
    ("claim_type", "assertion_level"),
    [
        ("LEGAL", "INFORMATION"),
        ("TAX", "INFORMATION"),
        ("AMOUNT", "INFORMATION"),
        ("DATE_OR_DEADLINE", "INFORMATION"),
        ("ELIGIBILITY", "NEEDS_CONFIRMATION"),
    ],
)
def test_high_risk_claim_cannot_pass_with_user_input_only(
    claim_type: str,
    assertion_level: str,
) -> None:
    subject = review_subject(
        claim_type=claim_type,
        claim_assertion_level=assertion_level,
        claim_evidence_refs=["case:business-type"],
    )
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert len(client.calls) == 1
    assert result.verdict == "REVISE"
    assert any(issue.issue_code == "MISSING_EVIDENCE" for issue in result.issues)
    assert result.missing_evidence


@pytest.mark.parametrize(
    "reason",
    [
        "소상공인 재도약 지원사업 지원 대상입니다.",
        "소상공인 재도약 지원사업 지원 대상일 수 있어 공식 확인이 필요합니다.",
    ],
)
def test_review_rejects_support_program_claim_masking_eligibility(
    reason: str,
) -> None:
    subject = review_subject(
        procedure_evidence_source_type="OFFICIAL_DOCUMENT",
        action_reason=reason,
        claim_type="SUPPORT_PROGRAM",
        claim_assertion_level="INFORMATION",
        claim_evidence_refs=["procedure:file-report"],
    )
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "REVISE"
    assert any(issue.issue_code == "UNSUPPORTED_CLAIM" for issue in result.issues)
    assert result.missing_evidence


def test_review_accepts_confirmation_only_eligibility_with_nonfinal_wording() -> None:
    subject = review_subject(
        procedure_evidence_source_type="OFFICIAL_DOCUMENT",
        action_reason=(
            "소상공인 재도약 지원사업 지원 대상 여부는 공식 확인이 필요합니다."
        ),
        claim_type="ELIGIBILITY",
        claim_assertion_level="NEEDS_CONFIRMATION",
        claim_evidence_refs=["procedure:file-report"],
    )
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "PASS"
    assert result.issues == []
    assert result.missing_evidence == []


def test_review_blocks_overconfident_eligibility_despite_confirmation_claim() -> None:
    subject = review_subject(
        procedure_evidence_source_type="OFFICIAL_DOCUMENT",
        action_reason="소상공인 재도약 지원사업 지원 대상입니다.",
        claim_type="ELIGIBILITY",
        claim_assertion_level="NEEDS_CONFIRMATION",
        claim_evidence_refs=["procedure:file-report"],
    )
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "REVISE"
    assert any(issue.issue_code == "OVERCONFIDENT_LANGUAGE" for issue in result.issues)


def test_fact_mutation_accepts_exact_info_candidate_provenance() -> None:
    subject = subject_with_fact_mutation()
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "PASS"
    assert len(client.calls) == 1


def test_fact_mutation_value_mismatch_is_rejected_before_model() -> None:
    subject = subject_with_fact_mutation(proposed_value=4)
    client = FakeStructuredClient([pass_output()])

    with pytest.raises(ReviewIntegrityError, match="differs from its Info"):
        asyncio.run(ReviewTool(client).review(subject))

    assert client.calls == []


def test_fact_mutation_requiring_confirmation_is_rejected_before_model() -> None:
    subject = subject_with_fact_mutation(requires_confirmation=True)
    client = FakeStructuredClient([pass_output()])

    with pytest.raises(ReviewIntegrityError, match="requires confirmation"):
        asyncio.run(ReviewTool(client).review(subject))

    assert client.calls == []


def test_procedure_mutation_accepts_exact_evaluation_and_observation() -> None:
    subject = subject_with_procedure_mutation(execution_ref="case:business-type")
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "PASS"
    assert len(client.calls) == 1


def test_procedure_mutation_observation_mismatch_is_rejected_before_model() -> None:
    subject = subject_with_procedure_mutation(execution_ref="procedure:file-report")
    client = FakeStructuredClient([pass_output()])

    with pytest.raises(ReviewIntegrityError, match="one Info observation"):
        asyncio.run(ReviewTool(client).review(subject))

    assert client.calls == []


def test_support_mutation_accepts_exact_support_check_provenance() -> None:
    subject = subject_with_support_mutation(tampered=False)
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "PASS"
    assert len(client.calls) == 1


def test_support_mutation_mismatch_is_rejected_before_model() -> None:
    subject = subject_with_support_mutation(tampered=True)
    client = FakeStructuredClient([pass_output()])

    with pytest.raises(ReviewIntegrityError, match="differs from its source"):
        asyncio.run(ReviewTool(client).review(subject))

    assert client.calls == []


def test_missing_target_procedure_forces_revise() -> None:
    unknown_step = ProcedureStepRef(
        procedure_step_id=99,
        step_code="UNKNOWN_PROCEDURE",
    )
    subject = review_subject(target_step=unknown_step)
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "REVISE"
    assert any(issue.issue_code == "PROCEDURE_CONFLICT" for issue in result.issues)


def test_action_evidence_must_intersect_target_procedure_evidence() -> None:
    subject = review_subject(action_evidence_refs=["case:unrelated"])
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "REVISE"
    assert any(issue.issue_code == "MISSING_EVIDENCE" for issue in result.issues)


def test_overconfident_visible_language_forces_revise_without_a_claim() -> None:
    subject = review_subject(
        action_reason="무조건 이 절차를 진행하세요.",
        include_claim=False,
    )
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "REVISE"
    assert any(issue.issue_code == "OVERCONFIDENT_LANGUAGE" for issue in result.issues)


def test_grounded_claim_cannot_point_to_its_own_text() -> None:
    original = review_subject()
    original_claim = original.supervisor_draft.grounded_claims[0]
    circular_claim = original_claim.model_copy(
        update={
            "target_path": "/supervisor_draft/grounded_claims/0/text",
        }
    )
    draft = original.supervisor_draft.model_copy(
        update={"grounded_claims": [circular_claim]}
    )
    subject = ReviewSubject.create(
        schema_version=original.schema_version,
        review_subject_id=original.review_subject_id,
        review_attempt=original.review_attempt,
        run_id=original.run_id,
        case_id=original.case_id,
        trigger=original.trigger,
        snapshot=original.snapshot,
        source_results=original.source_results,
        supervisor_draft=draft,
    )
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "REVISE"
    assert any(issue.issue_code == "CONTRACT_VIOLATION" for issue in result.issues)


def test_unclaimed_deadline_forces_revise_and_missing_evidence() -> None:
    subject = review_subject(
        action_reason="2026-10-01까지 신고해야 합니다.",
        include_claim=False,
    )
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "REVISE"
    assert any(issue.issue_code == "UNSUPPORTED_CLAIM" for issue in result.issues)
    assert result.missing_evidence
    assert result.missing_evidence[0].claim_path.endswith("/next_action/reason")


def test_unresolved_subject_evidence_is_rejected_before_model_call() -> None:
    subject = review_subject(action_evidence_refs=["invented:evidence"])
    client = FakeStructuredClient([pass_output()])

    with pytest.raises(ReviewIntegrityError, match="unresolved evidence"):
        asyncio.run(ReviewTool(client).review(subject))

    assert client.calls == []


def test_case_complete_with_incomplete_applicable_step_is_rejected_pre_model() -> None:
    subject = case_complete_subject(current_status=None)
    client = FakeStructuredClient([pass_output()])

    with pytest.raises(ReviewIntegrityError, match="incomplete applicable procedure"):
        asyncio.run(ReviewTool(client).review(subject))

    assert client.calls == []


def test_case_complete_with_full_procedure_coverage_can_be_reviewed() -> None:
    subject = case_complete_subject(current_status="COMPLETED")
    client = FakeStructuredClient([pass_output()])

    result = asyncio.run(ReviewTool(client).review(subject))

    assert result.verdict == "PASS"
    assert len(client.calls) == 1


def test_tampered_subject_digest_is_rejected_before_model_call() -> None:
    subject = review_subject()
    object.__setattr__(subject, "subject_digest", "sha256:" + "0" * 64)
    client = FakeStructuredClient([pass_output()])

    with pytest.raises(ReviewIntegrityError, match="digest"):
        asyncio.run(ReviewTool(client).review(subject))

    assert client.calls == []


def test_sensitive_review_projection_is_rejected_before_model_call() -> None:
    original = review_subject()
    trigger = original.trigger.model_copy(deep=True)
    trigger.input.redacted_text = "Bearer abcdefghijklmnop 토큰이 포함된 입력입니다."
    subject = ReviewSubject.create(
        schema_version=original.schema_version,
        review_subject_id=original.review_subject_id,
        review_attempt=original.review_attempt,
        run_id=original.run_id,
        case_id=original.case_id,
        trigger=trigger,
        snapshot=original.snapshot,
        source_results=original.source_results,
        supervisor_draft=original.supervisor_draft,
    )
    client = FakeStructuredClient([pass_output()])

    with pytest.raises(ReviewIntegrityError, match="sensitive-data preflight"):
        asyncio.run(ReviewTool(client).review(subject))

    assert client.calls == []
