from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from app.agent.schemas import (
    ActionDecisionDraft,
    AgentRunOutcome,
    Blocker,
    CaseCreatedTrigger,
    CaseFact,
    CaseSnapshot,
    CaseStatus,
    Component,
    ConflictCandidate,
    ConflictOutcome,
    EvidenceRecord,
    EvidenceSourceType,
    FactStatus,
    FactValueType,
    FreshnessStatus,
    InfoAnalysisResult,
    InfoCompletionStatus,
    InvocationMeta,
    MutationSet,
    NextAction,
    ProcedureCompletionStatus,
    ProcedureLookupResult,
    ProcedureSearchSummary,
    ProcedureSourceDocument,
    RedactedInput,
    ReviewedPlanOutcome,
    ReviewIssue,
    ReviewIssueCode,
    ReviewProof,
    ReviewResult,
    ReviewSourceResult,
    ReviewSubject,
    ReviewVerdict,
    SupervisorDraft,
    SupportAnalysisResult,
    SupportCheck,
    SupportCompletionStatus,
    SupportMatchStatus,
    SupportProgramRef,
    SupportSearchSummary,
    canonical_digest,
)
from pydantic import TypeAdapter, ValidationError
from pydantic_core import PydanticSerializationError

NOW = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000001")
RUN_ID = UUID("00000000-0000-4000-8000-000000000002")
INFO_CALL_ID = UUID("00000000-0000-4000-8000-000000000003")
PROCEDURE_CALL_ID = UUID("00000000-0000-4000-8000-000000000007")
REVIEW_CALL_ID = UUID("00000000-0000-4000-8000-000000000004")
SUBJECT_ID = UUID("00000000-0000-4000-8000-000000000005")
DRAFT_ID = UUID("00000000-0000-4000-8000-000000000006")


def evidence(
    evidence_id: str = "ev-user-1",
    *,
    freshness: FreshnessStatus = FreshnessStatus.CURRENT,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_type=EvidenceSourceType.USER_INPUT,
        source_ref="input-event-1",
        source_version=None,
        locator="/redacted_text/0:16",
        excerpt="임대차 계약이 진행 중입니다",
        parent_evidence_refs=[],
        published_at=None,
        retrieved_at=NOW,
        freshness_status=freshness,
        content_hash=None,
    )


def snapshot() -> CaseSnapshot:
    return CaseSnapshot(
        snapshot_id=SNAPSHOT_ID,
        case_id=1,
        case_version=1,
        case_status=CaseStatus.IN_PROGRESS,
        facts=[
            CaseFact(
                field_path="lease_status",
                value_type=FactValueType.ENUM,
                value="ACTIVE",
                status=FactStatus.CONFIRMED,
                evidence_refs=["ev-user-1"],
                updated_at=NOW,
            ),
            CaseFact(
                field_path="restoration_scope",
                value_type=FactValueType.ENUM,
                value=None,
                status=FactStatus.UNKNOWN,
                evidence_refs=[],
                updated_at=None,
            ),
        ],
        procedure_progress=[],
        evidence_records=[evidence()],
        captured_at=NOW,
    )


def info_result() -> InfoAnalysisResult:
    return InfoAnalysisResult(
        completion_status=InfoCompletionStatus.COMPLETE,
        fact_candidates=[],
        procedure_progress_observations=[],
        procedure_findings=[],
        conflicts=[],
        missing_fields=[],
        uncertainties=[],
        question_candidates=[],
        evidence_records=[],
        parser_version="info/1.0",
        based_on_snapshot_id=SNAPSHOT_ID,
        based_on_procedure_lookup_call_id=PROCEDURE_CALL_ID,
        based_on_procedure_lookup_digest="sha256:" + "a" * 64,
    )


def invocation(component: Component, call_id: UUID) -> InvocationMeta:
    return InvocationMeta(
        schema_version="agent-io/2.0",
        run_id=RUN_ID,
        call_id=call_id,
        parent_call_id=None,
        case_id=1,
        component=component,
        attempt=1,
        requested_at=NOW,
        trace_id="trace-test",
    )


def trigger() -> CaseCreatedTrigger:
    return CaseCreatedTrigger(
        trigger_type="CASE_CREATED",
        input_event_id="input-event-1",
        client_event_id="client-event-1",
        input=RedactedInput(
            input_event_id="input-event-1",
            source_type="USER_INPUT",
            redacted_text="임대차 계약이 진행 중입니다",
            redactions=[],
            submitted_at=NOW,
        ),
        submitted_at=NOW,
    )


def supervisor_draft() -> SupervisorDraft:
    decision = ActionDecisionDraft(
        decision_type="ACTION",
        draft_id=DRAFT_ID,
        draft_version=1,
        selection_summary="원상복구 범위를 먼저 확인해야 합니다.",
        requires_human=True,
        evidence_refs=["ev-user-1"],
        based_on_call_ids=[INFO_CALL_ID],
        created_at=NOW,
        blocker=Blocker(
            blocker_code="RESTORATION_SCOPE_UNCONFIRMED",
            title="원상복구 범위 미확인",
            description="임대인과 원상복구 범위를 아직 합의하지 않았습니다.",
            evidence_refs=["ev-user-1"],
        ),
        next_action=NextAction(
            action_code="ASK_LANDLORD_RESTORATION_SCOPE",
            sequence=1,
            title="임대인에게 원상복구 범위를 확인하세요",
            reason="철거와 이후 절차 범위를 정하려면 먼저 확인해야 합니다.",
            questions_to_ask=["어느 시설까지 철거해야 하나요?"],
            target={
                "target_kind": "PROCEDURE",
                "procedure_step": {
                    "procedure_step_id": 1,
                    "step_code": "RESTORATION_SCOPE_CHECK",
                },
            },
            evidence_refs=["ev-user-1"],
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
        source_call_ids=[INFO_CALL_ID],
    )


def review_subject() -> ReviewSubject:
    output = info_result()
    source = ReviewSourceResult(
        meta=invocation(Component.INFO_AGENT, INFO_CALL_ID),
        output_digest=canonical_digest(output),
        output=output,
    )
    return ReviewSubject.create(
        schema_version="agent-io/2.0",
        review_subject_id=SUBJECT_ID,
        review_attempt=1,
        run_id=RUN_ID,
        case_id=1,
        trigger=trigger(),
        snapshot=snapshot(),
        source_results=[source],
        supervisor_draft=supervisor_draft(),
    )


def test_all_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CaseFact(
            field_path="lease_status",
            value_type="ENUM",
            value="ACTIVE",
            status="CONFIRMED",
            evidence_refs=["ev-user-1"],
            updated_at=NOW,
            made_up=True,
        )


def test_case_fact_rejects_free_form_enum_and_preserves_unknown() -> None:
    with pytest.raises(ValidationError, match="lease_status must be one of"):
        CaseFact(
            field_path="lease_status",
            value_type="ENUM",
            value="임대차 계약 진행 중",
            status="CONFIRMED",
            evidence_refs=["ev-user-1"],
            updated_at=NOW,
        )

    unknown = CaseFact(
        field_path="demolition_required",
        value_type="ENUM",
        value=None,
        status="UNKNOWN",
        evidence_refs=[],
        updated_at=None,
    )
    assert unknown.value is None

    with pytest.raises(ValidationError, match="UNKNOWN fact must have value=null"):
        CaseFact(
            field_path="demolition_required",
            value_type="ENUM",
            value="UNKNOWN",
            status="UNKNOWN",
            evidence_refs=[],
            updated_at=None,
        )


def test_case_snapshot_rejects_duplicate_fields_and_dangling_evidence() -> None:
    data = snapshot().model_dump()
    data["facts"].append(data["facts"][0])
    with pytest.raises(ValidationError, match="duplicate fact field_path"):
        CaseSnapshot.model_validate(data)

    data = snapshot().model_dump()
    data["facts"][0]["evidence_refs"] = ["missing-evidence"]
    with pytest.raises(ValidationError, match="unresolved evidence refs"):
        CaseSnapshot.model_validate(data)


def support_check(
    *,
    match_status: SupportMatchStatus,
    freshness: FreshnessStatus,
) -> SupportCheck:
    return SupportCheck(
        support_program=SupportProgramRef(
            support_program_id=1,
            wiki_uuid=UUID("00000000-0000-4000-8000-000000000010"),
        ),
        program_name="희망리턴패키지",
        related_steps=[],
        match_status=match_status,
        criteria=[],
        unknown_field_paths=["previous_support_history"],
        required_documents=[],
        application_channel=None,
        application_url=None,
        application_period=None,
        source_version=None,
        freshness_status=freshness,
        checked_at=NOW,
        reason_summary="공식 자료 최신성을 확인할 수 없습니다.",
        evidence_refs=[],
    )


def test_support_unknown_freshness_is_only_unverifiable() -> None:
    check = support_check(
        match_status=SupportMatchStatus.UNVERIFIABLE,
        freshness=FreshnessStatus.UNKNOWN,
    )
    assert check.match_status == SupportMatchStatus.UNVERIFIABLE

    with pytest.raises(ValidationError, match="UNKNOWN freshness"):
        support_check(
            match_status=SupportMatchStatus.POSSIBLY_RELEVANT,
            freshness=FreshnessStatus.UNKNOWN,
        )


def test_support_completion_discriminator_is_consistent() -> None:
    result = SupportAnalysisResult(
        completion_status=SupportCompletionStatus.NO_CANDIDATE,
        support_checks=[],
        no_candidate_reason_code="NO_VERIFIED_PROGRAM",
        uncertainties=[],
        search_summary=SupportSearchSummary(
            wiki_lookup="MISS",
            rag_used=False,
            official_source_checked=True,
            checked_at=NOW,
        ),
        evidence_records=[],
        based_on_snapshot_id=SNAPSHOT_ID,
        based_on_candidate_ids=[],
    )
    assert result.support_checks == []

    with pytest.raises(ValidationError, match="NO_CANDIDATE"):
        SupportAnalysisResult.model_validate(
            {
                **result.model_dump(),
                "no_candidate_reason_code": None,
            }
        )


def test_procedure_result_produces_json_schema() -> None:
    official = EvidenceRecord(
        evidence_id="procedure:web:1",
        source_type="OFFICIAL_DOCUMENT",
        source_ref="https://www.gov.kr/closure",
        source_version=None,
        locator="body:text",
        excerpt="사업자 폐업 신고 절차 안내",
        parent_evidence_refs=[],
        published_at=None,
        retrieved_at=NOW,
        freshness_status="UNKNOWN",
        content_hash="sha256:" + "b" * 64,
    )
    document = ProcedureSourceDocument(
        document_id=UUID("00000000-0000-4000-8000-000000000030"),
        title="사업자 폐업 신고",
        authority_name="정부24",
        canonical_url=official.source_ref,
        source_domain="www.gov.kr",
        excerpt=official.excerpt,
        published_at=None,
        retrieved_at=NOW,
        freshness_status="UNKNOWN",
        content_hash=official.content_hash,
        evidence_ref=official.evidence_id,
        search_query="사업자 폐업 신고 절차",
        discovery_provider="KAKAO_DAUM_WEB",
    )
    result = ProcedureLookupResult(
        completion_status=ProcedureCompletionStatus.COMPLETE,
        lookup_id=UUID("00000000-0000-4000-8000-000000000031"),
        documents=[document],
        search_summary=ProcedureSearchSummary(
            provider_order=["KAKAO_DAUM_WEB"],
            provider_summaries=[
                {
                    "provider": "KAKAO_DAUM_WEB",
                    "attempted_query_count": 1,
                    "successful_query_count": 1,
                    "failed_query_count": 0,
                    "provider_result_count": 1,
                }
            ],
            fallback_query_count=0,
            requested_query_count=1,
            successful_query_count=1,
            failed_query_count=0,
            provider_result_count=1,
            official_candidate_count=1,
            fetched_document_count=1,
            rejected_result_count=0,
            fetch_failure_count=0,
            searched_at=NOW,
        ),
        warnings=[],
        evidence_records=[official],
        based_on_snapshot_id=SNAPSHOT_ID,
        as_of=NOW.date(),
    )
    assert result.documents[0].canonical_url == official.source_ref
    assert ProcedureLookupResult.model_json_schema()["type"] == "object"

    unsafe_document = document.model_dump(mode="python")
    unsafe_document["canonical_url"] = "https://user:pass@GOV.KR:444/closure#x"
    unsafe_document["source_domain"] = "GOV.KR"
    with pytest.raises(ValidationError, match="credentials|canonical"):
        ProcedureSourceDocument.model_validate(unsafe_document)

    no_match = ProcedureLookupResult(
        completion_status=ProcedureCompletionStatus.NO_RESULTS,
        lookup_id=UUID("00000000-0000-4000-8000-000000000032"),
        documents=[],
        search_summary=ProcedureSearchSummary(
            provider_order=["KAKAO_DAUM_WEB"],
            provider_summaries=[
                {
                    "provider": "KAKAO_DAUM_WEB",
                    "attempted_query_count": 1,
                    "successful_query_count": 1,
                    "failed_query_count": 0,
                    "provider_result_count": 0,
                }
            ],
            fallback_query_count=0,
            requested_query_count=1,
            successful_query_count=1,
            failed_query_count=0,
            provider_result_count=0,
            official_candidate_count=0,
            fetched_document_count=0,
            rejected_result_count=0,
            fetch_failure_count=0,
            searched_at=NOW,
        ),
        warnings=[],
        evidence_records=[],
        based_on_snapshot_id=SNAPSHOT_ID,
        as_of=NOW.date(),
    )
    assert no_match.documents == []

    impossible_no_match = no_match.model_dump(mode="python")
    impossible_no_match["search_summary"]["provider_result_count"] = 1
    impossible_no_match["search_summary"]["official_candidate_count"] = 1
    impossible_no_match["search_summary"]["provider_summaries"][0][
        "provider_result_count"
    ] = 1
    with pytest.raises(ValidationError, match="NO_RESULTS"):
        ProcedureLookupResult.model_validate(impossible_no_match)

    all_queries_failed = no_match.search_summary.model_dump(mode="python")
    all_queries_failed["successful_query_count"] = 0
    all_queries_failed["failed_query_count"] = 1
    all_queries_failed["provider_summaries"][0]["successful_query_count"] = 0
    all_queries_failed["provider_summaries"][0]["failed_query_count"] = 1
    with pytest.raises(ValidationError, match="successful provider response"):
        ProcedureSearchSummary.model_validate(all_queries_failed)

    mismatched_provider = result.model_dump(mode="python")
    mismatched_provider["documents"][0]["discovery_provider"] = "GOOGLE_AGENT_SEARCH"
    with pytest.raises(ValidationError, match="successful search result"):
        ProcedureLookupResult.model_validate(mismatched_provider)

    failed_provider_with_results = no_match.search_summary.model_dump(mode="python")
    failed_provider_with_results.update(
        {
            "provider_order": ["GOOGLE_AGENT_SEARCH", "KAKAO_DAUM_WEB"],
            "provider_summaries": [
                {
                    "provider": "GOOGLE_AGENT_SEARCH",
                    "attempted_query_count": 1,
                    "successful_query_count": 0,
                    "failed_query_count": 1,
                    "provider_result_count": 1,
                },
                {
                    "provider": "KAKAO_DAUM_WEB",
                    "attempted_query_count": 1,
                    "successful_query_count": 1,
                    "failed_query_count": 0,
                    "provider_result_count": 0,
                },
            ],
            "fallback_query_count": 1,
            "provider_result_count": 1,
            "rejected_result_count": 1,
        }
    )
    with pytest.raises(ValidationError, match="successful provider response"):
        ProcedureSearchSummary.model_validate(failed_provider_with_results)


def test_procedure_search_summary_preserves_google_fallback_history() -> None:
    summary = ProcedureSearchSummary(
        provider_order=["GOOGLE_AGENT_SEARCH", "KAKAO_DAUM_WEB"],
        provider_summaries=[
            {
                "provider": "GOOGLE_AGENT_SEARCH",
                "attempted_query_count": 1,
                "successful_query_count": 1,
                "failed_query_count": 0,
                "provider_result_count": 1,
            },
            {
                "provider": "KAKAO_DAUM_WEB",
                "attempted_query_count": 1,
                "successful_query_count": 1,
                "failed_query_count": 0,
                "provider_result_count": 1,
            },
        ],
        fallback_query_count=1,
        requested_query_count=1,
        successful_query_count=1,
        failed_query_count=0,
        provider_result_count=2,
        official_candidate_count=1,
        fetched_document_count=1,
        rejected_result_count=1,
        fetch_failure_count=0,
        searched_at=NOW,
    )
    assert summary.fallback_query_count == 1

    invalid_order = summary.model_dump(mode="python")
    invalid_order["provider_order"].reverse()
    invalid_order["provider_summaries"].reverse()
    with pytest.raises(ValidationError, match="Google-first"):
        ProcedureSearchSummary.model_validate(invalid_order)

    invalid_fallback = summary.model_dump(mode="python")
    invalid_fallback["fallback_query_count"] = 0
    with pytest.raises(ValidationError, match="fallback count"):
        ProcedureSearchSummary.model_validate(invalid_fallback)


def test_action_decision_contains_exactly_one_blocker_and_next_action() -> None:
    draft = supervisor_draft()
    assert draft.blocker is not None
    assert draft.next_action is not None

    payload = draft.decision.model_dump()
    payload["next_action"] = None
    with pytest.raises(ValidationError):
        ActionDecisionDraft.model_validate(payload)

    payload = draft.decision.model_dump()
    payload["blockers"] = [payload["blocker"]]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ActionDecisionDraft.model_validate(payload)


def test_next_action_requires_exactly_one_typed_target() -> None:
    payload = supervisor_draft().decision.next_action.model_dump(mode="python")

    missing_target = {key: value for key, value in payload.items() if key != "target"}
    with pytest.raises(ValidationError, match="target"):
        NextAction.model_validate(missing_target)

    with pytest.raises(ValidationError, match="target"):
        NextAction.model_validate({**payload, "target": None})

    support_target = {
        "target_kind": "SUPPORT_PROGRAM",
        "support_program": {
            "support_program_id": 501,
            "wiki_uuid": UUID("00000000-0000-4000-8000-000000000501"),
        },
    }
    action = NextAction.model_validate({**payload, "target": support_target})
    assert action.target.target_kind == "SUPPORT_PROGRAM"

    malformed_support_target = {
        "target_kind": "SUPPORT_PROGRAM",
        "procedure_step": {
            "procedure_step_id": 1,
            "step_code": "RESTORATION_SCOPE_CHECK",
        },
    }
    with pytest.raises(ValidationError):
        NextAction.model_validate({**payload, "target": malformed_support_target})

    both_target_payloads = {
        **support_target,
        "procedure_step": {
            "procedure_step_id": 1,
            "step_code": "RESTORATION_SCOPE_CHECK",
        },
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        NextAction.model_validate({**payload, "target": both_target_payloads})


def test_review_pass_gate_rejects_blocking_issue() -> None:
    issue = ReviewIssue(
        issue_code=ReviewIssueCode.UNSUPPORTED_CLAIM,
        category="FACTUALITY",
        severity="BLOCKING",
        target_component=Component.SUPERVISOR,
        target_call_id=None,
        target_path="/supervisor_draft/decision/next_action/reason",
        reason_summary="근거 없는 지원 자격 단정이 있습니다.",
        evidence_refs=[],
    )
    with pytest.raises(ValidationError, match="PASS cannot contain"):
        ReviewResult(
            reviewed_subject_id=SUBJECT_ID,
            reviewed_subject_digest="sha256:" + "a" * 64,
            verdict=ReviewVerdict.PASS,
            issues=[issue],
            missing_evidence=[],
            recommended_rework_targets=[],
            resolution_reason="차단 문제가 있습니다.",
        )

    with pytest.raises(ValidationError, match="REVISE requires"):
        ReviewResult(
            reviewed_subject_id=SUBJECT_ID,
            reviewed_subject_digest="sha256:" + "a" * 64,
            verdict=ReviewVerdict.REVISE,
            issues=[],
            missing_evidence=[],
            recommended_rework_targets=[],
            resolution_reason="문제가 없습니다.",
        )

    warning = ReviewIssue(
        issue_code=ReviewIssueCode.AMBIGUOUS_LANGUAGE,
        category="LANGUAGE",
        severity="WARNING",
        target_component=Component.SUPERVISOR,
        target_call_id=None,
        target_path="/supervisor_draft/decision/next_action/title",
        reason_summary="표현을 더 간결하게 다듬을 수 있습니다.",
        evidence_refs=[],
    )
    with pytest.raises(ValidationError, match="blocking issue or missing evidence"):
        ReviewResult(
            reviewed_subject_id=SUBJECT_ID,
            reviewed_subject_digest="sha256:" + "a" * 64,
            verdict=ReviewVerdict.REVISE,
            issues=[warning],
            missing_evidence=[],
            recommended_rework_targets=[Component.SUPERVISOR],
            resolution_reason="비차단 표현 개선만 필요합니다.",
        )


def test_review_subject_digest_and_pass_proof_gate() -> None:
    subject = review_subject()
    assert subject.subject_digest == subject.calculate_digest()

    tampered = subject.model_dump()
    tampered["supervisor_draft"]["decision"]["next_action"]["title"] = "변조"
    with pytest.raises(ValidationError, match="subject_digest"):
        ReviewSubject.model_validate(tampered)

    result = ReviewResult(
        reviewed_subject_id=subject.review_subject_id,
        reviewed_subject_digest=subject.subject_digest,
        verdict="PASS",
        issues=[],
        missing_evidence=[],
        recommended_rework_targets=[],
        resolution_reason="근거와 절차가 일치합니다.",
    )
    assert result.verdict == ReviewVerdict.PASS

    proof = ReviewProof.from_passed_review(
        subject=subject,
        result=result,
        review_meta=invocation(Component.REVIEW_TOOL, REVIEW_CALL_ID),
        reviewed_at=NOW,
    )
    outcome = ReviewedPlanOutcome(
        outcome_type="REVIEWED_PLAN",
        review_subject=subject,
        review_proof=proof,
    )
    assert outcome.review_subject.supervisor_draft.next_action is not None
    assert outcome.model_dump(mode="json")["outcome_type"] == "REVIEWED_PLAN"

    stale_outcome = outcome.model_copy(deep=True)
    stale_outcome.review_subject.supervisor_draft.decision.next_action.questions_to_ask.append(
        "검토 뒤 추가된 질문"
    )
    with pytest.raises(ValueError, match="subject_digest"):
        stale_outcome.assert_integrity()
    with pytest.raises(PydanticSerializationError, match="subject_digest"):
        stale_outcome.model_dump(mode="json")

    bad_proof = proof.model_copy(
        update={"reviewed_subject_digest": "sha256:" + "f" * 64}
    )
    with pytest.raises(ValidationError, match="review proof"):
        ReviewedPlanOutcome(
            outcome_type="REVIEWED_PLAN",
            review_subject=subject,
            review_proof=bad_proof,
        )

    changed_subject = subject.model_copy(deep=True)
    changed_subject.supervisor_draft.decision.next_action.questions_to_ask.append(
        "검토 뒤 추가된 질문"
    )
    with pytest.raises(ValidationError, match="subject_digest|changed after review"):
        ReviewedPlanOutcome(
            outcome_type="REVIEWED_PLAN",
            review_subject=changed_subject,
            review_proof=proof,
        )


def test_all_e2e_top_level_contracts_are_json_schema_serializable() -> None:
    models = [
        CaseSnapshot,
        InfoAnalysisResult,
        SupportAnalysisResult,
        ProcedureLookupResult,
        SupervisorDraft,
        ReviewResult,
        ReviewSubject,
        ReviewedPlanOutcome,
    ]
    for model in models:
        assert model.model_json_schema()["type"] == "object"

    outcome_schema = TypeAdapter(AgentRunOutcome).json_schema()
    assert "discriminator" in outcome_schema


def test_conflict_outcome_is_structured_and_snapshot_bound() -> None:
    conflict = ConflictCandidate.create_standalone(
        candidate_id=UUID("00000000-0000-4000-8000-000000000020"),
        snapshot_id=SNAPSHOT_ID,
        case_version=1,
        field_path="lease_status",
        committed_status="CONFIRMED",
        committed_value="ACTIVE",
        proposed_operation="SET",
        proposed_status="CONFIRMED",
        proposed_value="TERMINATION_NOTIFIED",
        source_evidence_refs=["ev-user-1"],
        source_call_id=INFO_CALL_ID,
    )
    assert conflict.is_simulation_only
    assert conflict.conflict_ref.startswith("standalone:")
    assert conflict.conflict_digest == conflict.calculate_digest()

    tampered_conflict = conflict.model_dump(mode="python")
    tampered_conflict["proposed_value"] = "TERMINATED"
    with pytest.raises(ValidationError, match="conflict_digest"):
        ConflictCandidate.model_validate(tampered_conflict)

    stale_conflict = conflict.model_copy(deep=True)
    stale_conflict.source_evidence_refs.append("ev-added-after-digest")
    with pytest.raises(PydanticSerializationError, match="conflict_digest"):
        stale_conflict.model_dump(mode="json")

    outcome = ConflictOutcome(
        outcome_type="CONFLICT",
        run_id=RUN_ID,
        case_id=1,
        trigger=trigger(),
        snapshot_id=SNAPSHOT_ID,
        case_version=1,
        conflicts=[conflict],
        message_code="CONFIRM_CONFLICT",
    )
    parsed = TypeAdapter(AgentRunOutcome).validate_python(outcome.model_dump())
    assert isinstance(parsed, ConflictOutcome)

    with pytest.raises(ValidationError, match="snapshot/version"):
        ConflictOutcome(
            **{
                **outcome.model_dump(exclude={"snapshot_id"}),
                "snapshot_id": UUID("00000000-0000-4000-8000-000000000099"),
            }
        )
