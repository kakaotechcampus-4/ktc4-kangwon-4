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
    InfoAnalysisInput,
    KnownProcedureStep,
    ProcedureStepRef,
    RedactedInput,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000101")


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
