from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from app.agent.schemas import (
    AgentGraphInput,
    AgentSchema,
    CaseCreatedTrigger,
    CaseFact,
    CaseSnapshot,
    Component,
    EvidenceRecord,
    EvidenceSourceType,
    FactCandidate,
    InfoAnalysisResult,
    InvocationMeta,
    ProcedureFinding,
    ProcedureLookupResult,
    ProcedureProgressObservation,
    ProcedureSearchSummary,
    ProcedureSourceDocument,
    ProcedureStepRef,
    RedactedInput,
    ReviewIssue,
    ReviewSourceResult,
    SourcedText,
    SupervisorAgentInput,
    SupervisorDraft,
    SupportAnalysisResult,
    SupportCheck,
    SupportProgramRef,
    SupportSearchSummary,
    VerifiedTextSpan,
    canonical_digest,
)
from app.agent.supervisor.agent import (
    SupervisorAgent,
    SupervisorGuardrailError,
    SupervisorSemanticDraft,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000201")
RUN_ID = UUID("00000000-0000-4000-8000-000000000202")
CALL_ID = UUID("00000000-0000-4000-8000-000000000203")
CANDIDATE_ID = UUID("00000000-0000-4000-8000-000000000204")
PROCEDURE_CALL_ID = UUID("00000000-0000-4000-8000-000000000205")
PROCEDURE_LOOKUP_ID = UUID("00000000-0000-4000-8000-000000000207")
PROCEDURE_DOCUMENT_ID = UUID("00000000-0000-4000-8000-000000000208")
PROCEDURE_FINDING_ID = UUID("00000000-0000-4000-8000-000000000209")
SUPPORT_PROGRAM_NAME = "폐업 소상공인 재도약 지원사업"


class FakeLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []

    async def generate(
        self,
        response_model: type[AgentSchema],
        messages: list[dict[str, str]],
        **_: Any,
    ) -> AgentSchema:
        self.calls += 1
        assert messages
        self.messages.append(messages)
        return response_model.model_validate(self.payload)


class SequenceLLM(FakeLLM):
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        super().__init__(payloads[0])
        self.payloads = payloads

    async def generate(
        self,
        response_model: type[AgentSchema],
        messages: list[dict[str, str]],
        **_: Any,
    ) -> AgentSchema:
        self.calls += 1
        self.messages.append(messages)
        return response_model.model_validate(self.payloads[self.calls - 1])


def evidence() -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id="ev-input",
        source_type="USER_INPUT",
        source_ref="input-1",
        source_version=None,
        locator="text:10-16",
        excerpt="철거가 필요",
        parent_evidence_refs=[],
        published_at=None,
        retrieved_at=NOW,
        freshness_status="CURRENT",
        content_hash=None,
    )


def snapshot() -> CaseSnapshot:
    return CaseSnapshot(
        snapshot_id=SNAPSHOT_ID,
        case_id=1,
        case_version=2,
        case_status="IN_PROGRESS",
        facts=[
            CaseFact(
                field_path="demolition_required",
                value_type="ENUM",
                value=None,
                status="UNKNOWN",
                evidence_refs=[],
                updated_at=None,
            )
        ],
        procedure_progress=[],
        evidence_records=[],
        captured_at=NOW,
    )


def run_input() -> AgentGraphInput:
    redacted = RedactedInput(
        input_event_id="input-1",
        source_type="USER_INPUT",
        redacted_text="임대인에게 확인했는데 철거가 필요하다고 합니다.",
        redactions=[],
        submitted_at=NOW,
    )
    return AgentGraphInput(
        trigger=CaseCreatedTrigger(
            trigger_type="CASE_CREATED",
            input_event_id="input-1",
            client_event_id="client-1",
            input=redacted,
            submitted_at=NOW,
        ),
        case_snapshot=snapshot(),
    )


def supervisor_input(
    source_results: list[ReviewSourceResult],
    *,
    graph_input: AgentGraphInput | None = None,
    draft_version: int = 1,
    review_feedback: list[ReviewIssue] | None = None,
    fact_overlays: list[Any] | None = None,
    previous_draft: SupervisorDraft | None = None,
) -> SupervisorAgentInput:
    """Build the single request model accepted at the Supervisor boundary."""

    graph_input = graph_input or run_input()
    return SupervisorAgentInput(
        trigger=graph_input.trigger,
        case_snapshot=graph_input.case_snapshot,
        source_results=source_results,
        draft_version=draft_version,
        review_feedback=review_feedback or [],
        fact_overlays=fact_overlays,
        previous_draft=previous_draft,
    )


def procedure_evidence() -> EvidenceRecord:
    return evidence().model_copy(
        update={
            "evidence_id": "ev-procedure",
            "source_type": EvidenceSourceType.OFFICIAL_DOCUMENT,
            "source_ref": "https://www.gov.kr/test/closure",
            "source_version": "test-v1",
            "excerpt": "폐업 신고 전에 공식 기관에 구비서류를 확인합니다.",
            "published_at": NOW,
            "content_hash": "sha256:" + "c" * 64,
        }
    )


def procedure_source() -> ReviewSourceResult:
    procedure_record = procedure_evidence()
    output = ProcedureLookupResult(
        completion_status="COMPLETE",
        lookup_id=PROCEDURE_LOOKUP_ID,
        documents=[
            ProcedureSourceDocument(
                document_id=PROCEDURE_DOCUMENT_ID,
                title="폐업 신고 안내",
                authority_name="정부24",
                canonical_url=procedure_record.source_ref,
                source_domain="www.gov.kr",
                excerpt=procedure_record.excerpt,
                published_at=procedure_record.published_at,
                retrieved_at=procedure_record.retrieved_at,
                freshness_status=procedure_record.freshness_status,
                content_hash=procedure_record.content_hash,
                evidence_ref=procedure_record.evidence_id,
                search_query="폐업 신고 공식 절차",
                discovery_provider="KAKAO_DAUM_WEB",
            )
        ],
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
        evidence_records=[procedure_record],
        based_on_snapshot_id=SNAPSHOT_ID,
        as_of=NOW.date(),
    )
    return ReviewSourceResult(
        meta=InvocationMeta(
            schema_version="agent-io/2.0",
            run_id=RUN_ID,
            call_id=PROCEDURE_CALL_ID,
            parent_call_id=None,
            case_id=1,
            component=Component.PROCEDURE_TOOL,
            attempt=1,
            requested_at=NOW,
            trace_id="trace-test",
        ),
        output_digest=canonical_digest(output),
        output=output,
    )


def procedure_finding(*, current_status: str | None = None) -> ProcedureFinding:
    record = procedure_evidence()
    return ProcedureFinding(
        finding_id=PROCEDURE_FINDING_ID,
        procedure_step=ProcedureStepRef(
            procedure_step_id=1,
            step_code="STEP_1",
        ),
        step_name="폐업 신고",
        summary=SourcedText(
            text="폐업 신고 방법은 공식 기관 확인이 필요합니다.",
            evidence_refs=[record.evidence_id],
        ),
        relevance="RELEVANT",
        current_status=current_status,
        decision_authority="OFFICIAL_AGENCY",
        requires_confirmation=True,
        required_actions=[
            SourcedText(
                text="공식 기관에 신고 방법을 확인합니다.",
                evidence_refs=[record.evidence_id],
            )
        ],
        required_documents=[],
        application_channel=None,
        application_url=None,
        deadline=None,
        evidence_refs=[record.evidence_id],
    )


def source(
    *,
    include_finding: bool = True,
    finding_current_status: str | None = None,
    observations: list[ProcedureProgressObservation] | None = None,
) -> ReviewSourceResult:
    raw_procedure = procedure_source()
    findings = (
        [procedure_finding(current_status=finding_current_status)]
        if include_finding
        else []
    )
    output = InfoAnalysisResult(
        completion_status="COMPLETE",
        fact_candidates=[
            FactCandidate(
                candidate_id=CANDIDATE_ID,
                operation="SET",
                field_path="demolition_required",
                value_type="ENUM",
                value="REQUIRED",
                source_span=VerifiedTextSpan(
                    input_event_id="input-1",
                    text="철거가 필요",
                    start_offset=10,
                    end_offset=16,
                ),
                source_evidence_refs=["ev-input"],
                confidence_bps=9500,
                requires_confirmation=False,
                reason_summary="임대인 확인 결과가 입력되었습니다.",
            )
        ],
        procedure_progress_observations=observations or [],
        procedure_findings=findings,
        conflicts=[],
        missing_fields=[],
        uncertainties=[],
        question_candidates=[],
        evidence_records=[evidence()],
        parser_version="info-agent/1.0",
        based_on_snapshot_id=SNAPSHOT_ID,
        based_on_procedure_lookup_call_id=PROCEDURE_CALL_ID,
        based_on_procedure_lookup_digest=raw_procedure.output_digest,
    )
    return ReviewSourceResult(
        meta=InvocationMeta(
            schema_version="agent-io/2.0",
            run_id=RUN_ID,
            call_id=CALL_ID,
            parent_call_id=None,
            case_id=1,
            component=Component.INFO_AGENT,
            attempt=1,
            requested_at=NOW,
            trace_id="trace-test",
        ),
        output_digest=canonical_digest(output),
        output=output,
    )


def support_source() -> ReviewSourceResult:
    official_evidence = evidence().model_copy(
        update={
            "evidence_id": "ev-support-official",
            "source_type": EvidenceSourceType.OFFICIAL_DOCUMENT,
            "source_ref": "official-document:test-v1",
        }
    )
    derived_evidence = evidence().model_copy(
        update={
            "evidence_id": "ev-support-derived",
            "source_type": EvidenceSourceType.REVIEWED_WIKI,
            "source_ref": "reviewed-wiki:test-v1",
            "parent_evidence_refs": [official_evidence.evidence_id],
        }
    )
    output = SupportAnalysisResult(
        completion_status="COMPLETE",
        support_checks=[
            SupportCheck(
                support_program=SupportProgramRef(
                    support_program_id=501,
                    wiki_uuid=UUID("00000000-0000-4000-8000-000000000501"),
                ),
                program_name=SUPPORT_PROGRAM_NAME,
                related_steps=[],
                match_status="NEEDS_CONFIRMATION",
                criteria=[],
                unknown_field_paths=["employee_count"],
                required_documents=[],
                application_channel=None,
                application_url=None,
                application_period=None,
                source_version="test-v1",
                freshness_status="CURRENT",
                checked_at=NOW,
                reason_summary="공식 요건 확인이 필요합니다.",
                evidence_refs=[derived_evidence.evidence_id],
            )
        ],
        no_candidate_reason_code=None,
        uncertainties=[],
        search_summary=SupportSearchSummary(
            wiki_lookup="HIT",
            rag_used=False,
            official_source_checked=True,
            checked_at=NOW,
        ),
        evidence_records=[derived_evidence, official_evidence],
        based_on_snapshot_id=SNAPSHOT_ID,
        based_on_candidate_ids=[],
    )
    return ReviewSourceResult(
        meta=InvocationMeta(
            schema_version="agent-io/2.0",
            run_id=RUN_ID,
            call_id=UUID("00000000-0000-4000-8000-000000000206"),
            parent_call_id=None,
            case_id=1,
            component=Component.SUPPORT_AGENT,
            attempt=1,
            requested_at=NOW,
            trace_id="trace-test",
        ),
        output_digest=canonical_digest(output),
        output=output,
    )


def semantic_payload(*, evidence_id: str = "ev-input") -> dict[str, Any]:
    return {
        "decision_type": "ACTION",
        "selection_summary": "철거 전에 지원 조건과 준비 절차를 확인해야 합니다.",
        "requires_human": True,
        "evidence_refs": [evidence_id],
        "blocker": {
            "blocker_code": "DEMOLITION_PRECHECK_REQUIRED",
            "title": "철거 전 확인 필요",
            "description": "철거를 시작하기 전에 적용 절차와 지원 조건을 확인해야 합니다.",
            "evidence_refs": [evidence_id],
        },
        "next_action": {
            "action_code": "CHECK_DEMOLITION_REQUIREMENTS",
            "title": "철거 전 조건을 공식 기관에 확인하세요",
            "reason": "철거를 먼저 시작하면 확인할 수 없는 조건이 생길 수 있습니다.",
            "questions_to_ask": ["철거 전에 준비해야 할 서류가 무엇인가요?"],
            "target": {
                "target_kind": "PROCEDURE",
                "procedure_step": {
                    "procedure_step_id": 1,
                    "step_code": "STEP_1",
                },
            },
            "evidence_refs": [evidence_id],
        },
        "questions_for_user": [],
        "grounded_claims": [],
    }


def test_supervisor_builds_one_action_and_runtime_owned_mutation() -> None:
    llm = FakeLLM(semantic_payload())
    draft = asyncio.run(
        SupervisorAgent(llm).draft(supervisor_input([source(), procedure_source()]))
    )

    assert draft.decision.decision_type == "ACTION"
    assert draft.blocker is not None
    assert draft.next_action is not None
    assert draft.next_action.sequence == 1
    assert draft.source_call_ids == [CALL_ID, PROCEDURE_CALL_ID]
    assert len(draft.mutations.fact_changes) == 1
    mutation = draft.mutations.fact_changes[0]
    assert mutation.proposed_value == "REQUIRED"
    assert mutation.source_call_id == CALL_ID
    assert mutation.source_fact_candidate_id == CANDIDATE_ID
    assert llm.calls == 1


def test_supervisor_falls_back_to_validated_info_questions_after_model_failure() -> (
    None
):
    info_source = source(include_finding=False)
    output_payload = info_source.output.model_dump(mode="python")
    question_id = UUID("00000000-0000-4000-8000-000000000210")
    output_payload.update(
        {
            "completion_status": "NEEDS_USER_INPUT",
            "missing_fields": [
                {
                    "field_path": "restoration_scope",
                    "reason_summary": "원상복구 범위를 확인하지 못했습니다.",
                    "blocks": ["SUPERVISOR_DECISION"],
                    "question_candidate_id": question_id,
                }
            ],
            "question_candidates": [
                {
                    "question_id": question_id,
                    "text": "임대인에게 원상복구 범위를 확인했나요?",
                    "resolves_field_paths": ["restoration_scope"],
                    "reason_summary": "다음 판단 전에 확인이 필요합니다.",
                }
            ],
        }
    )
    info_output = InfoAnalysisResult.model_validate(output_payload)
    info_source = info_source.model_copy(
        update={
            "output": info_output,
            "output_digest": canonical_digest(info_output),
        }
    )
    invalid = semantic_payload(evidence_id="not-an-evidence-id")

    draft = asyncio.run(
        SupervisorAgent(FakeLLM(invalid), max_local_attempts=1).draft(
            supervisor_input([info_source, procedure_source()])
        )
    )

    assert draft.decision.decision_type == "NEEDS_MORE_INFO"
    assert draft.decision.questions_for_user == [
        "임대인에게 원상복구 범위를 확인했나요?"
    ]
    assert draft.grounded_claims == []


def test_action_cannot_omit_a_canonical_target() -> None:
    payload = semantic_payload()
    del payload["next_action"]["target"]

    with pytest.raises(ValidationError):
        SupervisorSemanticDraft.model_validate(payload)

    payload = semantic_payload()
    payload["next_action"]["target"] = None
    with pytest.raises(ValidationError):
        SupervisorSemanticDraft.model_validate(payload)


def test_support_action_requires_exact_check_target_and_evidence() -> None:
    payload = semantic_payload()
    payload["next_action"].update(
        {
            "action_code": "APPLY_SUPPORT_PROGRAM",
            "title": f"{SUPPORT_PROGRAM_NAME} 신청 방법을 확인하세요",
            "reason": "기관 확인 전에는 지원 여부를 확정할 수 없습니다.",
            "questions_to_ask": ["신청 전에 어떤 요건을 확인해야 하나요?"],
            "target": {
                "target_kind": "SUPPORT_PROGRAM",
                "support_program": {
                    "support_program_id": 501,
                    "wiki_uuid": "00000000-0000-4000-8000-000000000501",
                },
            },
            "evidence_refs": ["ev-support-derived"],
        }
    )
    payload["evidence_refs"] = ["ev-support-derived"]
    payload["blocker"]["evidence_refs"] = ["ev-support-derived"]
    payload["grounded_claims"] = [
        {
            "claim_type": "SUPPORT_PROGRAM",
            "target_kind": "NEXT_ACTION_TITLE",
            "target_index": None,
            "assertion_level": "NEEDS_CONFIRMATION",
            "evidence_refs": ["ev-support-derived"],
        }
    ]

    draft = asyncio.run(
        SupervisorAgent(FakeLLM(payload)).draft(
            supervisor_input([source(), procedure_source(), support_source()])
        )
    )

    assert draft.decision.next_action is not None
    assert draft.decision.next_action.target.target_kind == "SUPPORT_PROGRAM"
    assert "ev-support-derived" in draft.decision.next_action.evidence_refs


@pytest.mark.parametrize(
    ("action_code", "procedure_instruction"),
    [
        ("RETURN_LICENSE", "허가증을 반납하세요"),
        ("CANCEL_BUSINESS_REPORT", "영업 신고를 취소하세요"),
        ("CHECK_SUPPORT_PROGRAM", "사업 허가를 해지하세요"),
        ("CHECK_SUPPORT_PROGRAM", "면허를 폐기하세요"),
        ("CHECK_SUPPORT_PROGRAM", "다음 행정 단계를 끝내세요"),
    ],
)
def test_support_target_cannot_hide_a_mixed_procedure_action(
    action_code: str,
    procedure_instruction: str,
) -> None:
    payload = semantic_payload(evidence_id="ev-support-derived")
    payload["next_action"].update(
        {
            "action_code": action_code,
            "title": f"{procedure_instruction} {SUPPORT_PROGRAM_NAME}도 확인하세요",
            "reason": "두 작업을 한 번에 진행합니다.",
            "questions_to_ask": ["기관에 어떤 내용을 확인해야 하나요?"],
            "target": {
                "target_kind": "SUPPORT_PROGRAM",
                "support_program": {
                    "support_program_id": 501,
                    "wiki_uuid": "00000000-0000-4000-8000-000000000501",
                },
            },
        }
    )
    payload["blocker"]["evidence_refs"] = ["ev-support-derived"]

    with pytest.raises(SupervisorGuardrailError, match="provenance checks"):
        asyncio.run(
            SupervisorAgent(FakeLLM(payload)).draft(
                supervisor_input([source(), procedure_source(), support_source()])
            )
        )


@pytest.mark.parametrize(
    "support_instruction",
    [
        "지원금을 신청하세요",
        "보조금 접수를 진행하세요",
        "지원사업도 신청하세요",
    ],
)
def test_procedure_target_cannot_hide_a_support_action(
    support_instruction: str,
) -> None:
    payload = semantic_payload()
    payload["next_action"]["title"] = support_instruction

    with pytest.raises(SupervisorGuardrailError, match="provenance checks"):
        asyncio.run(
            SupervisorAgent(FakeLLM(payload)).draft(
                supervisor_input([source(), procedure_source()])
            )
        )


def test_support_target_cannot_name_another_support_program() -> None:
    first_source = support_source()
    first_output = first_source.output
    assert isinstance(first_output, SupportAnalysisResult)
    first_check = first_output.support_checks[0]
    second_check = first_check.model_copy(
        update={
            "support_program": SupportProgramRef(
                support_program_id=502,
                wiki_uuid=UUID("00000000-0000-4000-8000-000000000502"),
            ),
            "program_name": f"{SUPPORT_PROGRAM_NAME} 원스톱폐업지원",
        }
    )
    output = first_output.model_copy(
        update={"support_checks": [first_check, second_check]}
    )
    two_program_source = first_source.model_copy(
        update={"output": output, "output_digest": canonical_digest(output)}
    )
    payload = support_program_payload()
    payload["next_action"]["title"] = (
        f"{second_check.program_name} 신청 방법을 확인하세요"
    )
    payload["grounded_claims"][0]["target_kind"] = "NEXT_ACTION_TITLE"

    with pytest.raises(SupervisorGuardrailError, match="provenance checks"):
        asyncio.run(
            SupervisorAgent(FakeLLM(payload)).draft(
                supervisor_input([source(), procedure_source(), two_program_source])
            )
        )


def test_supervisor_prompt_uses_minimum_content_free_projection() -> None:
    llm = FakeLLM(semantic_payload())

    asyncio.run(
        SupervisorAgent(llm).draft(supervisor_input([source(), procedure_source()]))
    )

    prompt = llm.messages[0][1]["content"]
    assert "임대인에게 확인" not in prompt
    assert "철거가 필요" not in prompt
    assert '"redacted_text"' not in prompt
    assert '"redactions"' not in prompt
    assert '"source_ref"' not in prompt
    assert '"excerpt"' not in prompt
    assert '"locator"' not in prompt
    projection = json.loads(prompt.removeprefix("INPUT_JSON="))
    projected_evidence = projection["component_results"][0]["output"][
        "evidence_records"
    ][0]
    assert projected_evidence == {
        "evidence_id": "ev-input",
        "source_type": "USER_INPUT",
        "source_version": None,
        "parent_evidence_refs": [],
        "freshness_status": "CURRENT",
    }


def test_revision_prompt_uses_semantic_previous_draft_and_rebuilds_provenance() -> None:
    previous = asyncio.run(
        SupervisorAgent(FakeLLM(semantic_payload())).draft(
            supervisor_input([source(), procedure_source()])
        )
    )
    current_call_id = UUID("00000000-0000-4000-8000-000000000299")
    original_source = source()
    current_source = original_source.model_copy(
        update={
            "meta": original_source.meta.model_copy(update={"call_id": current_call_id})
        }
    )
    corrected = semantic_payload()
    corrected["next_action"]["title"] = "공식 기관에 철거 전 필요 서류를 확인하세요"
    llm = FakeLLM(corrected)
    feedback = ReviewIssue(
        issue_code="AMBIGUOUS_LANGUAGE",
        category="LANGUAGE",
        severity="BLOCKING",
        target_component="SUPERVISOR",
        target_call_id=None,
        target_path="/supervisor_draft/decision/next_action/title",
        reason_summary="확인 대상과 내용을 구체적으로 써야 합니다.",
        evidence_refs=[],
    )

    revised = asyncio.run(
        SupervisorAgent(llm).draft(
            supervisor_input(
                [current_source, procedure_source()],
                draft_version=2,
                review_feedback=[feedback],
                previous_draft=previous,
            )
        )
    )

    prompt = json.loads(llm.messages[0][1]["content"].removeprefix("INPUT_JSON="))
    previous_projection = prompt["previous_draft"]
    assert previous_projection["decision"]["next_action"]["title"] == (
        previous.decision.next_action.title
    )
    serialized_projection = json.dumps(previous_projection)
    for runtime_field in (
        "draft_id",
        "created_at",
        "based_on_call_ids",
        "source_call_ids",
        "mutations",
        "candidate_id",
        "claim_id",
    ):
        assert runtime_field not in serialized_projection
    revision_instruction = llm.messages[0][-1]["content"]
    assert "every BLOCKING" in revision_instruction
    assert "runtime rebuilds" in revision_instruction
    assert revised.decision.draft_id != previous.decision.draft_id
    assert revised.source_call_ids == [current_call_id, PROCEDURE_CALL_ID]
    assert revised.decision.based_on_call_ids == [
        current_call_id,
        PROCEDURE_CALL_ID,
    ]
    assert revised.mutations.fact_changes[0].source_call_id == current_call_id


def test_invented_evidence_is_retried_bounded_then_rejected() -> None:
    llm = FakeLLM(semantic_payload(evidence_id="ev-invented"))

    with pytest.raises(SupervisorGuardrailError, match="provenance checks"):
        asyncio.run(
            SupervisorAgent(llm).draft(supervisor_input([source(), procedure_source()]))
        )

    assert llm.calls == 3


def test_conditional_contract_failure_is_corrected_by_local_retry() -> None:
    invalid = semantic_payload()
    invalid["questions_for_user"] = ["ACTION 분기에 있으면 안 되는 질문"]
    llm = SequenceLLM([invalid, semantic_payload()])

    draft = asyncio.run(
        SupervisorAgent(llm).draft(supervisor_input([source(), procedure_source()]))
    )

    assert draft.decision.decision_type == "ACTION"
    assert draft.decision.questions_for_user == []
    assert llm.calls == 2
    assert "deterministic contract validation" in llm.messages[1][-1]["content"]


def test_scalar_claim_selector_is_mapped_to_final_decision_path() -> None:
    payload = semantic_payload()
    payload["grounded_claims"] = [
        {
            "claim_type": "PROCEDURE",
            "target_kind": "NEXT_ACTION_TITLE",
            "target_index": None,
            "assertion_level": "NEEDS_CONFIRMATION",
            "evidence_refs": ["ev-procedure"],
        }
    ]

    draft = asyncio.run(
        SupervisorAgent(FakeLLM(payload)).draft(
            supervisor_input([source(include_finding=True), procedure_source()])
        )
    )

    assert draft.grounded_claims[0].target_path == (
        "/supervisor_draft/decision/next_action/title"
    )


def test_claim_text_and_path_are_bound_from_selected_runtime_field() -> None:
    payload = semantic_payload()
    payload["grounded_claims"] = [
        {
            "claim_type": "ELIGIBILITY",
            "target_kind": "NEXT_ACTION_REASON",
            "target_index": None,
            "assertion_level": "NEEDS_CONFIRMATION",
            "evidence_refs": ["ev-support-derived"],
        }
    ]

    draft = asyncio.run(
        SupervisorAgent(FakeLLM(payload)).draft(
            supervisor_input([source(), procedure_source(), support_source()])
        )
    )

    assert draft.grounded_claims[0].target_path == (
        "/supervisor_draft/decision/next_action/reason"
    )
    assert draft.grounded_claims[0].text == payload["next_action"]["reason"]


def test_grounded_claim_can_target_a_question_list_item() -> None:
    payload = semantic_payload()
    payload["grounded_claims"] = [
        {
            "claim_type": "PROCEDURE",
            "target_kind": "NEXT_ACTION_QUESTION",
            "target_index": 0,
            "assertion_level": "NEEDS_CONFIRMATION",
            "evidence_refs": ["ev-procedure"],
        }
    ]

    draft = asyncio.run(
        SupervisorAgent(FakeLLM(payload)).draft(
            supervisor_input([source(include_finding=True), procedure_source()])
        )
    )

    assert draft.grounded_claims[0].target_path.endswith("/questions_to_ask/0")


def test_procedure_target_evidence_is_bound_to_next_action() -> None:
    payload = semantic_payload()

    draft = asyncio.run(
        SupervisorAgent(FakeLLM(payload)).draft(
            supervisor_input([source(include_finding=True), procedure_source()])
        )
    )

    assert "ev-procedure" in draft.decision.next_action.evidence_refs


def test_progress_mutation_uses_same_info_finding_and_observation() -> None:
    observation = ProcedureProgressObservation(
        observation_id=UUID("00000000-0000-4000-8000-000000000210"),
        procedure_step=ProcedureStepRef(procedure_step_id=1, step_code="STEP_1"),
        observed_status="IN_PROGRESS",
        source_span=VerifiedTextSpan(
            input_event_id="input-1",
            text="철거가 필요",
            start_offset=10,
            end_offset=16,
        ),
        source_evidence_refs=["ev-input"],
        requires_confirmation=False,
        reason_summary="사용자가 절차 진행을 시작했다고 명시했습니다.",
    )
    info_source = source(include_finding=True, observations=[observation])

    draft = asyncio.run(
        SupervisorAgent(FakeLLM(semantic_payload())).draft(
            supervisor_input([info_source, procedure_source()])
        )
    )

    assert len(draft.mutations.procedure_progress_changes) == 1
    mutation = draft.mutations.procedure_progress_changes[0]
    assert mutation.procedure_analysis_call_id == CALL_ID
    assert mutation.execution_evidence_refs == ["ev-input"]


def test_progress_observation_requiring_confirmation_does_not_create_mutation() -> None:
    observation = ProcedureProgressObservation(
        observation_id=UUID("00000000-0000-4000-8000-000000000211"),
        procedure_step=ProcedureStepRef(procedure_step_id=1, step_code="STEP_1"),
        observed_status="IN_PROGRESS",
        source_span=VerifiedTextSpan(
            input_event_id="input-1",
            text="철거가 필요",
            start_offset=10,
            end_offset=16,
        ),
        source_evidence_refs=["ev-input"],
        requires_confirmation=True,
        reason_summary="진행 여부를 사용자에게 다시 확인해야 합니다.",
    )

    draft = asyncio.run(
        SupervisorAgent(FakeLLM(semantic_payload())).draft(
            supervisor_input(
                [
                    source(include_finding=True, observations=[observation]),
                    procedure_source(),
                ]
            )
        )
    )

    assert draft.mutations.procedure_progress_changes == []


def test_web_finding_alone_does_not_create_progress_mutation() -> None:
    draft = asyncio.run(
        SupervisorAgent(FakeLLM(semantic_payload())).draft(
            supervisor_input([source(include_finding=True), procedure_source()])
        )
    )

    assert draft.mutations.procedure_progress_changes == []


def test_invalid_claim_question_index_is_retried_then_rejected() -> None:
    payload = semantic_payload()
    payload["grounded_claims"] = [
        {
            "claim_type": "PROCEDURE",
            "target_kind": "NEXT_ACTION_QUESTION",
            "target_index": 9,
            "assertion_level": "NEEDS_CONFIRMATION",
            "evidence_refs": ["ev-input"],
        }
    ]
    llm = FakeLLM(payload)

    with pytest.raises(SupervisorGuardrailError, match="provenance checks"):
        asyncio.run(
            SupervisorAgent(llm).draft(supervisor_input([source(), procedure_source()]))
        )

    assert llm.calls == 3


def support_program_payload(*, grounded: bool = True) -> dict[str, Any]:
    payload = semantic_payload()
    payload["next_action"].update(
        {
            "action_code": "CHECK_SUPPORT_PROGRAM_REQUIREMENTS",
            "title": "지원사업 신청 요건을 확인하세요",
            "reason": f"{SUPPORT_PROGRAM_NAME} 신청 요건을 공식 기관에 확인해야 합니다.",
            "questions_to_ask": ["신청 전에 어떤 요건을 확인해야 하나요?"],
            "target": {
                "target_kind": "SUPPORT_PROGRAM",
                "support_program": {
                    "support_program_id": 501,
                    "wiki_uuid": "00000000-0000-4000-8000-000000000501",
                },
            },
            "evidence_refs": ["ev-support-derived"],
        }
    )
    payload["grounded_claims"] = []
    if grounded:
        payload["grounded_claims"] = [
            {
                "claim_type": "SUPPORT_PROGRAM",
                "target_kind": "NEXT_ACTION_REASON",
                "target_index": None,
                "assertion_level": "NEEDS_CONFIRMATION",
                "evidence_refs": ["ev-support-derived"],
            }
        ]
    return payload


def test_ungrounded_support_program_mention_is_corrected_by_local_retry() -> None:
    llm = SequenceLLM(
        [support_program_payload(grounded=False), support_program_payload()]
    )

    draft = asyncio.run(
        SupervisorAgent(llm).draft(
            supervisor_input([source(), procedure_source(), support_source()])
        )
    )

    assert llm.calls == 2
    assert draft.grounded_claims[0].target_path.endswith("/next_action/reason")
    assert "Every visible support-program name" in llm.messages[1][-1]["content"]


def test_transitive_official_source_supports_grounded_program_claim() -> None:
    llm = FakeLLM(support_program_payload())

    draft = asyncio.run(
        SupervisorAgent(llm).draft(
            supervisor_input([source(), procedure_source(), support_source()])
        )
    )

    assert llm.calls == 1
    assert draft.grounded_claims[0].evidence_refs == ["ev-support-derived"]


@pytest.mark.parametrize(
    "reason",
    [
        f"{SUPPORT_PROGRAM_NAME} 지원 대상입니다.",
        f"{SUPPORT_PROGRAM_NAME} 지원 대상일 수 있어 공식 기관 확인이 필요합니다.",
    ],
)
def test_support_program_claim_cannot_mask_explicit_eligibility_language(
    reason: str,
) -> None:
    payload = support_program_payload()
    payload["next_action"]["reason"] = reason
    payload["grounded_claims"][0]["assertion_level"] = "INFORMATION"
    llm = FakeLLM(payload)

    with pytest.raises(SupervisorGuardrailError, match="provenance checks"):
        asyncio.run(
            SupervisorAgent(llm).draft(
                supervisor_input([source(), procedure_source(), support_source()])
            )
        )

    assert llm.calls == 3


def test_confirmation_only_eligibility_claim_accepts_nonfinal_wording() -> None:
    payload = support_program_payload()
    payload["next_action"]["reason"] = (
        f"{SUPPORT_PROGRAM_NAME} 지원 대상 여부는 공식 기관 확인이 필요합니다."
    )
    payload["grounded_claims"][0].update(
        claim_type="ELIGIBILITY",
        assertion_level="NEEDS_CONFIRMATION",
    )
    llm = FakeLLM(payload)

    draft = asyncio.run(
        SupervisorAgent(llm).draft(
            supervisor_input([source(), procedure_source(), support_source()])
        )
    )

    assert llm.calls == 1
    assert draft.grounded_claims[0].claim_type == "ELIGIBILITY"
    assert draft.grounded_claims[0].assertion_level == "NEEDS_CONFIRMATION"


def test_non_current_confirmation_claim_requires_visible_caveat() -> None:
    payload = semantic_payload(evidence_id="ev-procedure")
    payload["next_action"]["reason"] = "부가세는 100만원입니다."
    payload["grounded_claims"] = [
        {
            "claim_type": "TAX",
            "target_kind": "NEXT_ACTION_REASON",
            "target_index": None,
            "assertion_level": "NEEDS_CONFIRMATION",
            "evidence_refs": ["ev-procedure"],
        }
    ]
    sources = [source(), procedure_source()]
    draft = asyncio.run(
        SupervisorAgent(FakeLLM(payload)).draft(supervisor_input(sources))
    )
    non_current = procedure_evidence().model_copy(
        update={"freshness_status": "UNKNOWN"}
    )

    with pytest.raises(
        SupervisorGuardrailError,
        match="explicit confirmation caveat",
    ):
        SupervisorAgent._validate_pre_review_claim_safety(
            draft,
            {"ev-procedure": non_current},
            sources,
        )


def test_overconfident_eligibility_wording_remains_blocked() -> None:
    payload = support_program_payload()
    payload["next_action"]["reason"] = f"{SUPPORT_PROGRAM_NAME} 지원 대상입니다."
    payload["grounded_claims"][0].update(
        claim_type="ELIGIBILITY",
        assertion_level="NEEDS_CONFIRMATION",
    )
    llm = FakeLLM(payload)

    with pytest.raises(SupervisorGuardrailError, match="provenance checks"):
        asyncio.run(
            SupervisorAgent(llm).draft(
                supervisor_input([source(), procedure_source(), support_source()])
            )
        )

    assert llm.calls == 3


def test_overconfident_program_claim_is_retried_then_rejected() -> None:
    payload = support_program_payload()
    payload["next_action"]["reason"] = f"{SUPPORT_PROGRAM_NAME} 지원 가능합니다."
    llm = FakeLLM(payload)

    with pytest.raises(SupervisorGuardrailError, match="provenance checks"):
        asyncio.run(
            SupervisorAgent(llm).draft(
                supervisor_input([source(), procedure_source(), support_source()])
            )
        )

    assert llm.calls == 3


def test_semantic_schema_rejects_action_without_exactly_one_next_action() -> None:
    payload = semantic_payload()
    payload["next_action"] = None

    with pytest.raises(ValidationError, match="one blocker and one next action"):
        SupervisorSemanticDraft.model_validate(payload)


def test_eligibility_claim_cannot_be_information_level() -> None:
    payload = semantic_payload()
    payload["grounded_claims"] = [
        {
            "claim_type": "ELIGIBILITY",
            "target_path": "/supervisor_draft/decision/next_action/title",
            "text": payload["next_action"]["title"],
            "assertion_level": "INFORMATION",
            "evidence_refs": ["ev-input"],
        }
    ]

    with pytest.raises(
        ValidationError, match="eligibility claims require confirmation"
    ):
        SupervisorSemanticDraft.model_validate(payload)


def test_case_complete_fails_closed_for_bounded_web_lookup() -> None:
    agent = SupervisorAgent(FakeLLM(semantic_payload()))
    sources = [source(include_finding=True), procedure_source()]

    with pytest.raises(
        SupervisorGuardrailError, match="authoritative procedure coverage"
    ):
        agent._ensure_complete_is_supported(
            supervisor_input(sources),
            sources,
        )


def test_supervisor_rejects_info_finding_without_raw_lookup_provenance() -> None:
    info_source = source(include_finding=True)
    raw_source = procedure_source()
    info_output = info_source.output.model_copy(
        update={
            "based_on_procedure_lookup_digest": "sha256:" + "0" * 64,
        }
    )
    tampered_info = info_source.model_copy(
        update={
            "output": info_output,
            "output_digest": canonical_digest(info_output),
        }
    )

    with pytest.raises(SupervisorGuardrailError, match="digest does not match"):
        asyncio.run(
            SupervisorAgent(FakeLLM(semantic_payload())).draft(
                supervisor_input([tampered_info, raw_source])
            )
        )


# --- Supervisor도 근거를 짧은 손잡이로 고르게 한다 -------------------------
#
# 정보분석과 같은 실패가 여기서도 나왔다. 실측에서 Review가 "blocker가 제공된
# 목록에 없는 근거 ID를 참조한다"며 반려했고, 그 반려가 Supervisor 재작업을
# 세 번 돌려 실행을 끝냈다. 고르게 할 목록이 이미 있으니 그 항목에 짧은 이름을
# 붙여 주면 옮겨 적다 틀릴 자리가 없어진다.


def test_the_model_picks_evidence_by_a_short_handle() -> None:
    llm = FakeLLM(semantic_payload(evidence_id="e1"))

    asyncio.run(
        SupervisorAgent(llm).draft(supervisor_input([source(), procedure_source()]))
    )

    sent = llm.messages[0][-1]["content"]
    assert '"evidence_ref": "e1"' in sent or '"evidence_ref":"e1"' in sent
    # The stored identifier is not what the model has to reproduce.
    assert '"evidence_ref": "ev-input"' not in sent
    assert '"evidence_ref":"ev-input"' not in sent


def test_a_supervisor_handle_is_resolved_back_to_the_real_evidence_id() -> None:
    draft = asyncio.run(
        SupervisorAgent(FakeLLM(semantic_payload(evidence_id="e1"))).draft(
            supervisor_input([source(), procedure_source()])
        )
    )

    # Handles stay inside the runtime; the draft carries the real IDs.
    assert draft.decision.evidence_refs == ["ev-input"]
    assert draft.blocker is not None
    assert draft.blocker.evidence_refs == ["ev-input"]


def test_a_supervisor_handle_that_was_never_offered_is_still_refused() -> None:
    with pytest.raises(SupervisorGuardrailError):
        asyncio.run(
            SupervisorAgent(FakeLLM(semantic_payload(evidence_id="e9"))).draft(
                supervisor_input([source(), procedure_source()])
            )
        )
