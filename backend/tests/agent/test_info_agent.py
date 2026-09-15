from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from app.agent.info_agent.agent import (
    InfoAnalysisAgent,
    InfoAnalysisDraft,
    InfoAnalysisGuardrailError,
    InfoProviderOutput,
)
from app.agent.schemas import (
    AgentSchema,
    CaseFact,
    CaseSnapshot,
    EvidenceRecord,
    InfoAnalysisInput,
    InfoAnalysisResult,
    KnownProcedureStep,
    ProcedureLookupResult,
    ProcedureSearchSummary,
    ProcedureSourceDocument,
    ProcedureStepRef,
    RedactedInput,
    canonical_digest,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000101")
PROCEDURE_CALL_ID = UUID("00000000-0000-4000-8000-000000000102")


class FakeLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []
        self.response_models: list[type[AgentSchema]] = []

    async def generate(
        self,
        response_model: type[AgentSchema],
        messages: list[dict[str, str]],
        **_: Any,
    ) -> AgentSchema:
        self.calls += 1
        assert messages
        self.messages.append(messages)
        self.response_models.append(response_model)
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
        assert messages
        self.messages.append(messages)
        self.response_models.append(response_model)
        return response_model.model_validate(self.payloads[self.calls - 1])


def snapshot(*, demolition_value: str | None = None) -> CaseSnapshot:
    return CaseSnapshot(
        snapshot_id=SNAPSHOT_ID,
        case_id=1,
        case_version=1,
        case_status="IN_PROGRESS",
        facts=[
            CaseFact(
                field_path="demolition_required",
                value_type="ENUM",
                value=demolition_value,
                status="CONFIRMED" if demolition_value is not None else "UNKNOWN",
                evidence_refs=["ev-existing"] if demolition_value is not None else [],
                updated_at=NOW if demolition_value is not None else None,
            )
        ],
        procedure_progress=[],
        evidence_records=(
            [
                {
                    "evidence_id": "ev-existing",
                    "source_type": "USER_INPUT",
                    "source_ref": "old-input",
                    "source_version": None,
                    "locator": "text:0-4",
                    "excerpt": "철거 불필요",
                    "parent_evidence_refs": [],
                    "published_at": None,
                    "retrieved_at": NOW,
                    "freshness_status": "CURRENT",
                    "content_hash": None,
                }
            ]
            if demolition_value is not None
            else []
        ),
        captured_at=NOW,
    )


def procedure_result() -> ProcedureLookupResult:
    excerpt = (
        "사업자는 폐업 신고서를 제출합니다. 폐업 신고는 정부24에서 확인할 수 "
        "있습니다. 참고 문자열 https://external.example/apply"
    )
    source_url = "https://www.gov.kr/mw/closure"
    source_hash = "sha256:" + "b" * 64
    evidence = EvidenceRecord(
        evidence_id="procedure:web:gov-closure",
        source_type="OFFICIAL_DOCUMENT",
        source_ref=source_url,
        source_version=None,
        locator="body:text",
        excerpt=excerpt,
        parent_evidence_refs=[],
        published_at=None,
        retrieved_at=NOW,
        freshness_status="UNKNOWN",
        content_hash=source_hash,
    )
    return ProcedureLookupResult(
        completion_status="COMPLETE",
        lookup_id=UUID("00000000-0000-4000-8000-000000000103"),
        documents=[
            ProcedureSourceDocument(
                document_id=UUID("00000000-0000-4000-8000-000000000104"),
                title="폐업 신고 안내",
                authority_name="정부24",
                canonical_url=source_url,
                source_domain="www.gov.kr",
                excerpt=excerpt,
                published_at=None,
                retrieved_at=NOW,
                freshness_status="UNKNOWN",
                content_hash=source_hash,
                evidence_ref=evidence.evidence_id,
                search_query="사업자 폐업 신고 절차",
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
        evidence_records=[evidence],
        based_on_snapshot_id=SNAPSHOT_ID,
        as_of=NOW.date(),
    )


def request(*, existing: str | None = None) -> InfoAnalysisInput:
    text = "임대인에게 확인했는데 철거가 필요하다고 합니다."
    return InfoAnalysisInput(
        input=RedactedInput(
            input_event_id="input-1",
            source_type="USER_INPUT",
            redacted_text=text,
            redactions=[],
            submitted_at=NOW,
        ),
        case_snapshot=snapshot(demolition_value=existing),
        allowed_field_paths=["demolition_required", "restoration_scope"],
        known_procedure_steps=[
            KnownProcedureStep(
                procedure_step=ProcedureStepRef(
                    procedure_step_id=1,
                    step_code="CONFIRM_RESTORATION_SCOPE",
                ),
                step_name="원상복구 범위 확인",
                utterance_aliases=["임대인 확인"],
            )
        ],
        procedure_lookup_call_id=PROCEDURE_CALL_ID,
        procedure_lookup_result=procedure_result(),
        review_feedback=[],
    )


def extraction_payload(*, source_text: str = "철거가 필요") -> dict[str, Any]:
    return {
        "completion_status": "COMPLETE",
        "facts": [
            {
                "operation": "SET",
                "field_path": "demolition_required",
                "value_type": "ENUM",
                "value": "REQUIRED",
                "source_text": source_text,
                "confidence_bps": 9600,
                "requires_confirmation": False,
                "reason_summary": "사용자가 임대인 확인 결과를 직접 전달했습니다.",
            }
        ],
        "procedure_observations": [],
        "procedure_findings": [],
        "missing_fields": [],
        "uncertainties": [],
    }


def test_extracts_only_grounded_canonical_fact_and_runtime_evidence() -> None:
    llm = FakeLLM(extraction_payload())
    result = asyncio.run(InfoAnalysisAgent(llm).analyze(request()))

    assert result.completion_status == "COMPLETE"
    assert len(result.fact_candidates) == 1
    candidate = result.fact_candidates[0]
    assert candidate.field_path == "demolition_required"
    assert candidate.value == "REQUIRED"
    assert candidate.source_span.text == "철거가 필요"
    assert result.evidence_records[0].excerpt == "철거가 필요"
    assert candidate.source_evidence_refs == [result.evidence_records[0].evidence_id]
    assert llm.calls == 1
    assert result.based_on_procedure_lookup_call_id == PROCEDURE_CALL_ID
    assert result.based_on_procedure_lookup_digest == canonical_digest(
        procedure_result()
    )


def test_info_input_rejects_duplicate_canonical_step_codes_and_aliases() -> None:
    payload = request().model_dump(mode="python")
    payload["known_procedure_steps"].append(
        {
            "procedure_step": {
                "procedure_step_id": 2,
                "step_code": "CONFIRM_RESTORATION_SCOPE",
            },
            "step_name": "다른 이름",
            "utterance_aliases": ["다른 별칭"],
        }
    )
    with pytest.raises(ValidationError, match="step_code"):
        InfoAnalysisInput.model_validate(payload)

    payload = request().model_dump(mode="python")
    payload["known_procedure_steps"].append(
        {
            "procedure_step": {
                "procedure_step_id": 2,
                "step_code": "OTHER_STEP",
            },
            "step_name": "다른 이름",
            "utterance_aliases": ["임대인 확인"],
        }
    )
    with pytest.raises(ValidationError, match="aliases"):
        InfoAnalysisInput.model_validate(payload)


def test_incomplete_procedure_lookup_cannot_be_erased_by_info_complete() -> None:
    base = request()
    empty_lookup = ProcedureLookupResult(
        completion_status="NO_RESULTS",
        lookup_id=UUID("00000000-0000-4000-8000-000000000105"),
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
    incomplete_request = base.model_copy(
        update={"procedure_lookup_result": empty_lookup}
    )

    result = asyncio.run(
        InfoAnalysisAgent(FakeLLM(extraction_payload())).analyze(incomplete_request)
    )

    assert result.completion_status == "PARTIAL"
    assert any(item.code == "SOURCE_UNAVAILABLE" for item in result.uncertainties)


def test_analyzes_fetched_procedure_evidence_and_binds_known_step() -> None:
    payload = extraction_payload()
    payload["facts"] = []
    payload["procedure_findings"] = [
        {
            "step_code": "CONFIRM_RESTORATION_SCOPE",
            "summary": {
                "text": "공식 안내에서 폐업 신고서 제출을 설명합니다.",
                "evidence_refs": ["procedure:web:gov-closure"],
            },
            "relevance": "UNDETERMINED",
            "decision_authority": "OFFICIAL_AGENCY",
            "requires_confirmation": True,
            "required_actions": [
                {
                    "text": "폐업 신고서를 제출합니다",
                    "evidence_refs": ["procedure:web:gov-closure"],
                }
            ],
            "required_documents": [],
            "application_channel": None,
            "application_url": {
                "text": "https://www.gov.kr/mw/closure",
                "evidence_refs": ["procedure:web:gov-closure"],
            },
            "deadline": None,
            "evidence_refs": ["procedure:web:gov-closure"],
        }
    ]
    llm = FakeLLM(payload)

    result = asyncio.run(InfoAnalysisAgent(llm).analyze(request()))

    assert result.procedure_findings[0].procedure_step.step_code == (
        "CONFIRM_RESTORATION_SCOPE"
    )
    assert result.procedure_findings[0].requires_confirmation is True
    assert "사업자는 폐업 신고서를 제출합니다" in llm.messages[0][1]["content"]
    assert "untrusted data" in llm.messages[0][0]["content"]

    duplicate_payload = result.model_dump(mode="python")
    duplicate_finding = dict(duplicate_payload["procedure_findings"][0])
    duplicate_finding["procedure_step"] = {
        "procedure_step_id": 2,
        "step_code": "OTHER_STEP",
    }
    duplicate_finding["step_name"] = "다른 절차"
    duplicate_payload["procedure_findings"].append(duplicate_finding)
    with pytest.raises(ValidationError, match="finding_id"):
        InfoAnalysisResult.model_validate(duplicate_payload)


def test_rejects_procedure_detail_not_present_in_official_excerpt() -> None:
    payload = extraction_payload()
    payload["facts"] = []
    payload["procedure_findings"] = [
        {
            "step_code": "CONFIRM_RESTORATION_SCOPE",
            "summary": {
                "text": "공식 안내 요약",
                "evidence_refs": ["procedure:web:gov-closure"],
            },
            "relevance": "UNDETERMINED",
            "decision_authority": "OFFICIAL_AGENCY",
            "requires_confirmation": True,
            "required_actions": [
                {
                    "text": "존재하지 않는 수수료를 납부합니다",
                    "evidence_refs": ["procedure:web:gov-closure"],
                }
            ],
            "required_documents": [],
            "application_channel": None,
            "application_url": None,
            "deadline": None,
            "evidence_refs": ["procedure:web:gov-closure"],
        }
    ]

    with pytest.raises(InfoAnalysisGuardrailError, match="grounding checks"):
        asyncio.run(InfoAnalysisAgent(FakeLLM(payload)).analyze(request()))


def test_unknown_freshness_cannot_be_promoted_to_relevant() -> None:
    payload = extraction_payload()
    payload["facts"] = []
    payload["procedure_findings"] = [
        {
            "step_code": "CONFIRM_RESTORATION_SCOPE",
            "summary": {
                "text": "공식 안내 요약",
                "evidence_refs": ["procedure:web:gov-closure"],
            },
            "relevance": "RELEVANT",
            "decision_authority": "OFFICIAL_AGENCY",
            "requires_confirmation": True,
            "required_actions": [
                {
                    "text": "폐업 신고서를 제출합니다",
                    "evidence_refs": ["procedure:web:gov-closure"],
                }
            ],
            "required_documents": [],
            "application_channel": None,
            "application_url": None,
            "deadline": None,
            "evidence_refs": ["procedure:web:gov-closure"],
        }
    ]

    with pytest.raises(InfoAnalysisGuardrailError, match="grounding checks"):
        asyncio.run(InfoAnalysisAgent(FakeLLM(payload)).analyze(request()))


def test_required_document_submission_stage_must_exist_in_official_excerpt() -> None:
    payload = extraction_payload()
    payload["facts"] = []
    payload["procedure_findings"] = [
        {
            "step_code": "CONFIRM_RESTORATION_SCOPE",
            "summary": {
                "text": "공식 안내 요약",
                "evidence_refs": ["procedure:web:gov-closure"],
            },
            "relevance": "UNDETERMINED",
            "decision_authority": "OFFICIAL_AGENCY",
            "requires_confirmation": True,
            "required_actions": [],
            "required_documents": [
                {
                    "name": "폐업 신고서",
                    "submission_stage": "폐업 후 30일 이내",
                    "evidence_refs": ["procedure:web:gov-closure"],
                }
            ],
            "application_channel": None,
            "application_url": None,
            "deadline": None,
            "evidence_refs": ["procedure:web:gov-closure"],
        }
    ]

    with pytest.raises(InfoAnalysisGuardrailError, match="grounding checks"):
        asyncio.run(InfoAnalysisAgent(FakeLLM(payload)).analyze(request()))


def test_application_url_must_be_a_fetched_canonical_source_url() -> None:
    payload = extraction_payload()
    payload["facts"] = []
    payload["procedure_findings"] = [
        {
            "step_code": "CONFIRM_RESTORATION_SCOPE",
            "summary": {
                "text": "공식 안내 요약",
                "evidence_refs": ["procedure:web:gov-closure"],
            },
            "relevance": "UNDETERMINED",
            "decision_authority": "OFFICIAL_AGENCY",
            "requires_confirmation": True,
            "required_actions": [],
            "required_documents": [],
            "application_channel": None,
            "application_url": {
                "text": "https://external.example/apply",
                "evidence_refs": ["procedure:web:gov-closure"],
            },
            "deadline": None,
            "evidence_refs": ["procedure:web:gov-closure"],
        }
    ]

    with pytest.raises(InfoAnalysisGuardrailError, match="grounding checks"):
        asyncio.run(InfoAnalysisAgent(FakeLLM(payload)).analyze(request()))


def test_rejects_free_form_value_for_enum_field() -> None:
    payload = extraction_payload()
    payload["facts"][0]["value"] = "철거가 필요하다고 함"

    provider_output = InfoProviderOutput.model_validate(payload)
    assert provider_output.facts[0].value == "철거가 필요하다고 함"

    with pytest.raises(ValidationError, match="demolition_required must be one of"):
        InfoAnalysisDraft.model_validate(payload)


def test_semantic_failure_is_corrected_inside_bounded_local_retry() -> None:
    invalid = extraction_payload()
    invalid["facts"][0]["value"] = "철거가 필요하다고 함"
    llm = SequenceLLM([invalid, extraction_payload()])

    result = asyncio.run(InfoAnalysisAgent(llm).analyze(request()))

    assert result.fact_candidates[0].value == "REQUIRED"
    assert llm.calls == 2
    assert llm.response_models == [InfoProviderOutput, InfoProviderOutput]
    correction = llm.messages[1][-1]["content"]
    assert "semantic or grounding validation" in correction
    assert "canonical_field_registry" in correction


def test_semantic_failure_exhausts_bounded_local_retry() -> None:
    invalid = extraction_payload()
    invalid["completion_status"] = "NEEDS_USER_INPUT"
    llm = FakeLLM(invalid)

    with pytest.raises(
        InfoAnalysisGuardrailError,
        match="semantic or grounding checks",
    ):
        asyncio.run(InfoAnalysisAgent(llm).analyze(request()))

    assert llm.calls == 2
    assert llm.response_models == [InfoProviderOutput, InfoProviderOutput]


def test_hallucinated_source_span_retries_bounded_then_fails() -> None:
    llm = FakeLLM(extraction_payload(source_text="계약서에 철거 조항이 있습니다"))

    with pytest.raises(InfoAnalysisGuardrailError, match="grounding checks"):
        asyncio.run(InfoAnalysisAgent(llm).analyze(request()))

    assert llm.calls == 2


def test_unredacted_sensitive_input_is_rejected_before_model_call() -> None:
    component_input = request()
    component_input.input.redacted_text = (
        "Bearer abcdefghijklmnop 토큰이 포함된 입력입니다."
    )
    llm = FakeLLM(extraction_payload())

    with pytest.raises(InfoAnalysisGuardrailError, match="sensitive-data preflight"):
        asyncio.run(InfoAnalysisAgent(llm).analyze(component_input))

    assert llm.calls == 0


def test_existing_confirmed_value_is_not_overwritten_and_becomes_conflict() -> None:
    llm = FakeLLM(extraction_payload())
    result = asyncio.run(
        InfoAnalysisAgent(llm).analyze(request(existing="NOT_REQUIRED"))
    )

    assert result.fact_candidates == []
    assert len(result.conflicts) == 1
    assert result.conflicts[0].committed_value == "NOT_REQUIRED"
    assert result.conflicts[0].proposed_value == "REQUIRED"
    assert result.completion_status == "NEEDS_USER_INPUT"
    assert len(result.question_candidates) == 1
