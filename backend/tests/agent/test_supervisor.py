from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from app.agent.schemas import (
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
    ProcedureLookupResult,
    ProcedureStepEvaluation,
    ProcedureStepRef,
    RedactedInput,
    ReviewIssue,
    ReviewSourceResult,
    SupervisorRunInput,
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
SUPPORT_PROGRAM_NAME = "소상공인 재도약 지원사업"


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


def run_input() -> SupervisorRunInput:
    redacted = RedactedInput(
        input_event_id="input-1",
        source_type="USER_INPUT",
        redacted_text="임대인에게 확인했는데 철거가 필요하다고 합니다.",
        redactions=[],
        submitted_at=NOW,
    )
    return SupervisorRunInput(
        trigger=CaseCreatedTrigger(
            trigger_type="CASE_CREATED",
            input_event_id="input-1",
            client_event_id="client-1",
            input=redacted,
            submitted_at=NOW,
        ),
        case_snapshot=snapshot(),
    )


def source() -> ReviewSourceResult:
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
        procedure_progress_observations=[],
        conflicts=[],
        missing_fields=[],
        uncertainties=[],
        question_candidates=[],
        evidence_records=[evidence()],
        parser_version="info-agent/1.0",
        based_on_snapshot_id=SNAPSHOT_ID,
    )
    return ReviewSourceResult(
        meta=InvocationMeta(
            schema_version="agent-io/1.0",
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


def procedure_source(*, current_statuses: list[str | None]) -> ReviewSourceResult:
    procedure_evidence = evidence().model_copy(
        update={
            "evidence_id": "ev-procedure",
            "source_type": EvidenceSourceType.PROCEDURE_MASTER,
            "source_ref": "procedure-master:test-v1",
        }
    )
    evaluations = [
        ProcedureStepEvaluation(
            procedure_step=ProcedureStepRef(
                procedure_step_id=index,
                step_code=f"STEP_{index}",
            ),
            step_name=f"절차 {index}",
            is_active=True,
            applicability="APPLICABLE",
            readiness="READY",
            current_status=current_status,
            conditions=[],
            prerequisites=[],
            unavailable_reasons=[],
            requires_professional=False,
            professional_type=None,
            decision_authority="USER",
            evidence_refs=[procedure_evidence.evidence_id],
        )
        for index, current_status in enumerate(current_statuses, start=1)
    ]
    output = ProcedureLookupResult(
        completion_status="COMPLETE",
        procedure_data_version="test-v1",
        step_evaluations=evaluations,
        evidence_records=[procedure_evidence],
        based_on_snapshot_id=SNAPSHOT_ID,
        based_on_candidate_ids=[],
    )
    return ReviewSourceResult(
        meta=InvocationMeta(
            schema_version="agent-io/1.0",
            run_id=RUN_ID,
            call_id=UUID("00000000-0000-4000-8000-000000000205"),
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
            schema_version="agent-io/1.0",
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
            "target_procedure": None,
            "evidence_refs": [evidence_id],
        },
        "questions_for_user": [],
        "grounded_claims": [],
    }


def test_supervisor_builds_one_action_and_runtime_owned_mutation() -> None:
    llm = FakeLLM(semantic_payload())
    draft = asyncio.run(SupervisorAgent(llm).draft(run_input(), [source()]))

    assert draft.decision.decision_type == "ACTION"
    assert draft.blocker is not None
    assert draft.next_action is not None
    assert draft.next_action.sequence == 1
    assert draft.source_call_ids == [CALL_ID]
    assert len(draft.mutations.fact_changes) == 1
    mutation = draft.mutations.fact_changes[0]
    assert mutation.proposed_value == "REQUIRED"
    assert mutation.source_call_id == CALL_ID
    assert mutation.source_fact_candidate_id == CANDIDATE_ID
    assert llm.calls == 1


def test_supervisor_prompt_uses_minimum_content_free_projection() -> None:
    llm = FakeLLM(semantic_payload())

    asyncio.run(SupervisorAgent(llm).draft(run_input(), [source()]))

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
        SupervisorAgent(FakeLLM(semantic_payload())).draft(run_input(), [source()])
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
            run_input(),
            [current_source],
            draft_version=2,
            review_feedback=[feedback],
            previous_draft=previous,
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
    assert revised.source_call_ids == [current_call_id]
    assert revised.decision.based_on_call_ids == [current_call_id]
    assert revised.mutations.fact_changes[0].source_call_id == current_call_id


def test_invented_evidence_is_retried_bounded_then_rejected() -> None:
    llm = FakeLLM(semantic_payload(evidence_id="ev-invented"))

    with pytest.raises(SupervisorGuardrailError, match="provenance checks"):
        asyncio.run(SupervisorAgent(llm).draft(run_input(), [source()]))

    assert llm.calls == 3


def test_conditional_contract_failure_is_corrected_by_local_retry() -> None:
    invalid = semantic_payload()
    invalid["questions_for_user"] = ["ACTION 분기에 있으면 안 되는 질문"]
    llm = SequenceLLM([invalid, semantic_payload()])

    draft = asyncio.run(SupervisorAgent(llm).draft(run_input(), [source()]))

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
            run_input(), [source(), procedure_source(current_statuses=[None])]
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
            run_input(), [source(), support_source()]
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
            run_input(), [source(), procedure_source(current_statuses=[None])]
        )
    )

    assert draft.grounded_claims[0].target_path.endswith("/questions_to_ask/0")


def test_target_procedure_evidence_is_bound_to_next_action() -> None:
    payload = semantic_payload()
    payload["next_action"]["target_procedure"] = {
        "procedure_step_id": 1,
        "step_code": "STEP_1",
    }

    draft = asyncio.run(
        SupervisorAgent(FakeLLM(payload)).draft(
            run_input(),
            [source(), procedure_source(current_statuses=[None])],
        )
    )

    assert "ev-procedure" in draft.decision.next_action.evidence_refs


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
        asyncio.run(SupervisorAgent(llm).draft(run_input(), [source()]))

    assert llm.calls == 3


def support_program_payload(*, grounded: bool = True) -> dict[str, Any]:
    payload = semantic_payload()
    payload["next_action"]["reason"] = (
        f"{SUPPORT_PROGRAM_NAME} 신청 요건을 공식 기관에 확인해야 합니다."
    )
    payload["next_action"]["evidence_refs"] = ["ev-support-derived"]
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
        SupervisorAgent(llm).draft(run_input(), [source(), support_source()])
    )

    assert llm.calls == 2
    assert draft.grounded_claims[0].target_path.endswith("/next_action/reason")
    assert "Every visible support-program name" in llm.messages[1][-1]["content"]


def test_transitive_official_source_supports_grounded_program_claim() -> None:
    llm = FakeLLM(support_program_payload())

    draft = asyncio.run(
        SupervisorAgent(llm).draft(run_input(), [source(), support_source()])
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
            SupervisorAgent(llm).draft(run_input(), [source(), support_source()])
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
        SupervisorAgent(llm).draft(run_input(), [source(), support_source()])
    )

    assert llm.calls == 1
    assert draft.grounded_claims[0].claim_type == "ELIGIBILITY"
    assert draft.grounded_claims[0].assertion_level == "NEEDS_CONFIRMATION"


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
            SupervisorAgent(llm).draft(run_input(), [source(), support_source()])
        )

    assert llm.calls == 3


def test_overconfident_program_claim_is_retried_then_rejected() -> None:
    payload = support_program_payload()
    payload["next_action"]["reason"] = f"{SUPPORT_PROGRAM_NAME} 지원 가능합니다."
    llm = FakeLLM(payload)

    with pytest.raises(SupervisorGuardrailError, match="provenance checks"):
        asyncio.run(
            SupervisorAgent(llm).draft(run_input(), [source(), support_source()])
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


def test_case_complete_rejects_incomplete_applicable_master_step() -> None:
    agent = SupervisorAgent(FakeLLM(semantic_payload()))

    with pytest.raises(SupervisorGuardrailError, match="applicable procedure"):
        agent._ensure_complete_is_supported(
            run_input(),
            [procedure_source(current_statuses=["COMPLETED", None])],
        )


def test_case_complete_accepts_complete_authoritative_master_coverage() -> None:
    agent = SupervisorAgent(FakeLLM(semantic_payload()))

    agent._ensure_complete_is_supported(
        run_input(),
        [procedure_source(current_statuses=["COMPLETED", "COMPLETED"])],
    )
