"""Replanning analyzes supplied remaining topics, not only the latest utterance."""

import asyncio
from copy import deepcopy
from uuid import UUID

import pytest
from app.agent.info_agent.agent import InfoAnalysisAgent, InfoAnalysisGuardrailError
from app.agent.schemas import CaseFieldKey, InfoAnalysisInput, ProcedureLookupResult
from test_action_codes import supervisor_request

TAX = "FILE_TAX_BUSINESS_CLOSURE"
FOOD = "FILE_FOOD_SERVICE_CLOSURE"
RESTORATION = "CONFIRM_RESTORATION_SCOPE"


def request_for_replanning(status="NOT_REQUIRED", scope="NOT_REQUIRED"):
    base = supervisor_request()
    data = base.case_snapshot.model_dump(mode="json")
    for field, value in (("restoration_scope", scope), ("restoration_status", status)):
        data["facts"].append(
            {
                "field_path": field,
                "value_type": "ENUM",
                "value": value,
                "status": "CONFIRMED",
                "evidence_refs": ["synthetic-document"],
                "updated_at": data["captured_at"],
            }
        )
    data["procedure_progress"] = [
        {
            "procedure_step": {"procedure_step_id": 3, "step_code": RESTORATION},
            "status": "COMPLETED",
            "evidence_refs": ["synthetic-document"],
            "updated_at": data["captured_at"],
        }
    ]
    lookup = base.source_results[0].output.model_dump(mode="json")
    steps = [item.model_dump(mode="json") for item in base.known_procedure_steps]
    for index, code in ((2, FOOD), (3, RESTORATION)):
        document = deepcopy(lookup["documents"][0])
        document.update(
            document_id=str(UUID(int=20 + index)),
            canonical_url=f"https://example.org/synthetic-{index}",
            evidence_ref=f"synthetic-{index}",
            step_codes=[code],
        )
        evidence = deepcopy(lookup["evidence_records"][0])
        evidence.update(
            evidence_id=f"synthetic-{index}", source_ref=document["canonical_url"]
        )
        lookup["documents"].append(document)
        lookup["evidence_records"].append(evidence)
        steps.append(
            dict(
                steps[0],
                procedure_step={"procedure_step_id": index, "step_code": code},
                step_name=f"합성 절차 {index}",
            )
        )
    user_input = base.trigger.input.model_dump(mode="json")
    user_input["redacted_text"] = "원상복구 불필요를 확인했습니다."
    return InfoAnalysisInput(
        input=user_input,
        case_snapshot=data,
        allowed_field_paths=list(CaseFieldKey),
        known_procedure_steps=steps,
        source_call_id=UUID(int=40),
        procedure_lookup_call_id=UUID(int=5),
        procedure_lookup_result=lookup,
        review_feedback=[],
    )


def finding(code, alias):
    return {
        "step_code": code,
        "summary": {"text": "합성 테스트 절차입니다.", "evidence_refs": [alias]},
        "relevance": "RELEVANT",
        "decision_authority": "OFFICIAL_AGENCY",
        "requires_confirmation": True,
        "required_actions": [],
        "required_documents": [],
        "application_channel": None,
        "application_url": None,
        "deadline": None,
        "evidence_refs": [alias],
    }


def output(findings, *, missing_detail=False, uncertainties=None):
    return {
        "completion_status": "NEEDS_USER_INPUT" if missing_detail else "COMPLETE",
        "facts": [],
        "procedure_observations": [],
        "procedure_findings": findings,
        "missing_fields": [
            {
                "field_path": "restoration_scope_detail",
                "reason_summary": "합성 누락",
                "blocks": ["SUPERVISOR_DECISION"],
                "question": "어느 부분을 복구하나요?",
            }
        ]
        if missing_detail
        else [],
        "uncertainties": uncertainties or [],
    }


class Responses:
    def __init__(self, *values):
        self.values, self.messages = list(values), []

    async def generate(self, model, messages, **kwargs):
        self.messages.append(messages)
        return model.model_validate(self.values.pop(0))


@pytest.mark.parametrize(
    "summary",
    [
        "폐업일로부터 25일 이내에 신고해야 합니다.",
        "폐업일로부터 25일 이내 신고해야 합니다.",
        "폐업일로부터25일 이내에는 신고해야 합니다.",
        "다음 달 15일까지 신고해야 합니다.",
        "계약해지 통고 후 3개월이 지나면 효력이 발생합니다.",
        "철거 지원금은 100만원을 받을 수 있습니다.",
    ],
)
def test_unsourced_summary_is_rejected_and_corrected(summary):
    rejected = finding(TAX, "doc1")
    rejected["summary"]["text"] = summary
    corrected = finding(TAX, "doc1")
    client = Responses(
        output([rejected, finding(FOOD, "doc2")]),
        output([corrected, finding(FOOD, "doc2")]),
    )
    result = asyncio.run(InfoAnalysisAgent(client).analyze(request_for_replanning()))
    assert len(client.messages) == 2
    assert result.procedure_findings[0].summary.text == corrected["summary"]["text"]
    assert result.procedure_findings[0].deadline is None
    assert result.procedure_findings[0].required_actions == []
    assert len(result.procedure_findings) == 2


def test_repeated_unsourced_summary_is_not_returned_as_a_finding():
    rejected = finding(TAX, "doc1")
    rejected["summary"]["text"] = "폐업일로부터 25일 이내에 신고해야 합니다."
    client = Responses(output([rejected, finding(FOOD, "doc2")]))
    with pytest.raises(InfoAnalysisGuardrailError):
        asyncio.run(
            InfoAnalysisAgent(client, max_local_attempts=1).analyze(
                request_for_replanning()
            )
        )


def test_all_unsourced_summaries_are_reported_in_one_retry():
    tax, food = finding(TAX, "doc1"), finding(FOOD, "doc2")
    tax["summary"]["text"] = "25일 이내에 신고합니다."
    food["summary"]["text"] = "15일까지 신고합니다."
    client = Responses(
        output([tax, food]),
        output([finding(TAX, "doc1"), finding(FOOD, "doc2")]),
    )
    result = asyncio.run(InfoAnalysisAgent(client).analyze(request_for_replanning()))
    feedback = " ".join(item["content"] for item in client.messages[1])
    assert f"{TAX}, {FOOD}: summaries" in feedback
    assert len(client.messages) == 2
    assert len(result.procedure_findings) == 2


def test_procedure_names_with_digits_are_not_rejected_as_deadlines():
    tax = finding(TAX, "doc1")
    tax["summary"]["text"] = "4대보험 절차와 정부24에서 확인할 내용을 안내합니다."
    client = Responses(output([tax, finding(FOOD, "doc2")]))
    request = request_for_replanning()
    request.procedure_lookup_result.evidence_records[0].excerpt += tax["summary"][
        "text"
    ]
    result = asyncio.run(InfoAnalysisAgent(client).analyze(request))
    assert len(client.messages) == 1
    assert result.procedure_findings[0].summary.text == tax["summary"]["text"]


@pytest.mark.parametrize(
    "source_text",
    [
        "합성 조건을 충족한 사업장만 다음 달 15일까지 신고합니다.",
        "이 안내가 인용하는 판결의 선고일은 2010.4.29.입니다.",
    ],
)
def test_source_quotation_keeps_qualified_deadlines_and_citation_dates(source_text):
    request = request_for_replanning()
    request.procedure_lookup_result.evidence_records[0].excerpt = source_text
    quoted = finding(TAX, "doc1")
    quoted["summary"]["text"] = source_text
    client = Responses(output([quoted, finding(FOOD, "doc2")]))
    result = asyncio.run(InfoAnalysisAgent(client).analyze(request))
    assert len(client.messages) == 1
    assert result.procedure_findings[0].summary.text == source_text
    assert result.procedure_findings[0].requires_confirmation is True


@pytest.mark.parametrize(
    "wrong_text",
    [
        "부속물을 설치한 경우에는 매수를 청구할 수 있습니다.",
        "다른 절차 문서에만 있는 납부 안내입니다.",
    ],
)
def test_summary_cannot_drop_source_conditions_or_borrow_another_source(wrong_text):
    request = request_for_replanning()
    source_text = (
        "임대인의 동의를 얻어 설치한 부속물인 경우에는 매수를 청구할 수 있습니다."
    )
    request.procedure_lookup_result.evidence_records[0].excerpt = source_text
    request.procedure_lookup_result.evidence_records[
        1
    ].excerpt += "다른 절차 문서에만 있는 납부 안내입니다."
    rejected, corrected = finding(TAX, "doc1"), finding(TAX, "doc1")
    rejected["summary"]["text"] = wrong_text
    corrected["summary"]["text"] = source_text
    client = Responses(
        output([rejected, finding(FOOD, "doc2")]),
        output([corrected, finding(FOOD, "doc2")]),
    )
    result = asyncio.run(InfoAnalysisAgent(client).analyze(request))
    assert len(client.messages) == 2
    assert result.procedure_findings[0].summary.text == source_text


def test_omitted_remaining_procedures_trigger_a_targeted_retry():
    client = Responses(
        output([finding(RESTORATION, "doc3")], missing_detail=True),
        output([finding(TAX, "doc1"), finding(FOOD, "doc2")], missing_detail=True),
    )
    result = asyncio.run(
        InfoAnalysisAgent(client, max_local_attempts=2).analyze(
            request_for_replanning()
        )
    )
    assert {item.procedure_step.step_code for item in result.procedure_findings} == {
        TAX,
        FOOD,
    }
    assert result.completion_status.value == "COMPLETE"
    assert result.missing_fields == result.question_candidates == []
    correction = " ".join(
        item["content"] for item in client.messages[1] if item["role"] == "system"
    )
    assert TAX in correction and FOOD in correction
    assert "entire Case" in correction


@pytest.mark.parametrize(
    "status,scope", [("NOT_REQUIRED", "NOT_REQUIRED"), ("COMPLETED", "FULL")]
)
def test_finished_restoration_does_not_request_scope_detail(status, scope):
    client = Responses(
        output([finding(TAX, "doc1"), finding(FOOD, "doc2")], missing_detail=True)
    )
    result = asyncio.run(
        InfoAnalysisAgent(client).analyze(request_for_replanning(status, scope))
    )
    assert result.missing_fields == result.question_candidates == []


def test_unresolved_restoration_can_still_ask_for_scope_detail():
    request = request_for_replanning("NOT_STARTED", "PARTIAL")
    client = Responses(
        output([finding(TAX, "doc1"), finding(FOOD, "doc2")], missing_detail=True)
    )
    result = asyncio.run(InfoAnalysisAgent(client).analyze(request))
    assert result.missing_fields[0].field_path == CaseFieldKey.RESTORATION_SCOPE_DETAIL


def test_document_specific_uncertainty_avoids_inventing_a_procedure():
    uncertainty = {
        "code": "CONTEXT_MISSING",
        "target_path": "/procedure_lookup_result/documents/1",
        "reason_summary": "합성 문서로는 적용 내용을 확인할 수 없습니다.",
        "evidence_refs": ["doc2"],
    }
    client = Responses(output([finding(TAX, "doc1")], uncertainties=[uncertainty]))
    result = asyncio.run(InfoAnalysisAgent(client).analyze(request_for_replanning()))
    assert len(result.procedure_findings) == 1
    assert result.uncertainties[0].evidence_refs == ["synthetic-2"]


def test_silent_omission_fails_closed_when_retry_budget_is_exhausted():
    client = Responses(output([finding(RESTORATION, "doc3")]))
    with pytest.raises(InfoAnalysisGuardrailError):
        asyncio.run(
            InfoAnalysisAgent(client, max_local_attempts=1).analyze(
                request_for_replanning()
            )
        )
    assert len(client.messages) == 1


def test_prompt_keeps_whole_case_and_progress_even_with_a_narrow_extraction_allowlist():
    request = request_for_replanning()
    request.allowed_field_paths = [CaseFieldKey.RESTORATION_SCOPE_DETAIL]
    projection = InfoAnalysisAgent._prompt_input(request)
    assert {item["field_path"] for item in projection["snapshot_facts"]} >= {
        "business_type",
        "restoration_scope",
    }
    assert projection["snapshot_procedure_progress"][0]["status"] == "COMPLETED"
    assert set(projection["procedure_analysis_step_codes"]) == {TAX, FOOD}


def test_stale_or_unmapped_documents_do_not_force_new_findings():
    request = request_for_replanning()
    raw = request.procedure_lookup_result.model_dump(mode="json")
    raw["documents"][0]["freshness_status"] = raw["evidence_records"][0][
        "freshness_status"
    ] = "STALE"
    raw["documents"][1]["step_codes"] = ["UNREGISTERED_SYNTHETIC_STEP"]
    request.procedure_lookup_result = ProcedureLookupResult.model_validate(raw)
    assert InfoAnalysisAgent._analysis_step_codes(request) == set()


def test_cross_procedure_source_failure_names_allowed_documents_on_retry():
    wrong_food = finding(FOOD, "doc2")
    wrong_food["application_channel"] = {
        "text": "합성 테스트 절차입니다.",
        "evidence_refs": ["doc1"],
    }
    wrong_food["evidence_refs"] = ["doc1", "doc2"]
    client = Responses(
        output([finding(TAX, "doc1"), wrong_food]),
        output([finding(TAX, "doc1"), finding(FOOD, "doc2")]),
    )
    result = asyncio.run(
        InfoAnalysisAgent(client, max_local_attempts=2).analyze(
            request_for_replanning()
        )
    )
    assert len(result.procedure_findings) == 2
    correction = " ".join(
        item["content"] for item in client.messages[1] if item["role"] == "system"
    )
    assert f"{FOOD}: rejected ['doc1']; allowed ['doc2']" in correction
    assert result.procedure_findings[1].application_channel is None


def test_not_required_restoration_does_not_hide_unknown_demolition():
    request = request_for_replanning()
    request.case_snapshot.procedure_progress = []
    assert RESTORATION in InfoAnalysisAgent._analysis_step_codes(request)
    projection = InfoAnalysisAgent._prompt_input(request)
    assert projection["procedure_evidence_by_step"][FOOD] == ["doc2"]
    completed = request_for_replanning("COMPLETED", "FULL")
    completed.case_snapshot.procedure_progress = []
    assert RESTORATION not in InfoAnalysisAgent._analysis_step_codes(completed)


def test_new_fact_still_requires_a_literal_user_source_span():
    raw = output([finding(TAX, "doc1"), finding(FOOD, "doc2")])
    raw["facts"] = [
        {
            "operation": "SET",
            "field_path": "employee_count",
            "value_type": "INTEGER",
            "value": 2,
            "source_text": "직원 수는 2명입니다.",
            "confidence_bps": 10000,
            "requires_confirmation": False,
            "reason_summary": "합성 새 사실",
        }
    ]
    with pytest.raises(InfoAnalysisGuardrailError):
        asyncio.run(
            InfoAnalysisAgent(Responses(raw), max_local_attempts=1).analyze(
                request_for_replanning()
            )
        )


@pytest.mark.parametrize("already_completed", [True, False])
def test_repeated_committed_progress_is_ignored_but_new_completion_stays_guarded(
    already_completed,
):
    request = request_for_replanning()
    request.input.redacted_text = (
        "임대인에게 확인했습니다. 원상복구와 철거는 모두 필요하지 않습니다."
    )
    if not already_completed:
        request.case_snapshot.procedure_progress[0].status = "NOT_STARTED"
    raw = output(
        [finding(TAX, "doc1"), finding(FOOD, "doc2"), finding(RESTORATION, "doc3")]
    )
    raw["procedure_observations"] = [
        {
            "step_code": RESTORATION,
            "observed_status": "COMPLETED",
            "source_text": request.input.redacted_text,
            "requires_confirmation": False,
            "reason_summary": "모델이 불필요를 완료로 반복 해석한 합성 사례",
        }
    ]
    agent = InfoAnalysisAgent(Responses(raw), max_local_attempts=1)
    if already_completed:
        result = asyncio.run(agent.analyze(request))
        assert result.procedure_progress_observations == []
        assert result.procedure_findings[-1].current_status.value == "COMPLETED"
    else:
        with pytest.raises(InfoAnalysisGuardrailError):
            asyncio.run(agent.analyze(request))


@pytest.mark.parametrize(
    "source_text",
    ["합성 절차 3은 확인이 필요합니다.", "합성 절차 3을 진행 중입니다."],
)
def test_document_based_progress_is_rejected_then_retried_without_losing_findings(
    source_text,
):
    request = request_for_replanning()
    request.input.redacted_text = '{"business_type":"카페"}'
    request.case_snapshot.procedure_progress = []
    before = request.case_snapshot.model_dump(mode="json")
    corrected = output(
        [finding(TAX, "doc1"), finding(FOOD, "doc2"), finding(RESTORATION, "doc3")]
    )
    wrong = deepcopy(corrected)
    wrong["procedure_observations"] = [
        {
            "step_code": RESTORATION,
            "observed_status": "IN_PROGRESS",
            "source_text": source_text,
            "requires_confirmation": True,
            "reason_summary": "공식 안내를 사용자 진행으로 혼동한 합성 사례",
        }
    ]
    # An unsupported observation must still fail when no correction is available.
    with pytest.raises(InfoAnalysisGuardrailError):
        asyncio.run(
            InfoAnalysisAgent(Responses(wrong), max_local_attempts=1).analyze(request)
        )
    client = Responses(wrong, corrected)
    result = asyncio.run(
        InfoAnalysisAgent(client, max_local_attempts=2).analyze(request)
    )
    assert result.procedure_progress_observations == []
    assert len(result.procedure_findings) == 3
    assert request.case_snapshot.model_dump(mode="json") == before
    feedback = " ".join(item["content"] for item in client.messages[1])
    assert f"Rejected procedure_observations for: {RESTORATION}" in feedback
    assert "Still analyze the documents in procedure_findings" in feedback


def test_explicit_user_progress_is_still_extracted():
    request = request_for_replanning()
    request.input.redacted_text = "합성 절차 3을 진행 중입니다."
    request.case_snapshot.procedure_progress = []
    raw = output(
        [finding(TAX, "doc1"), finding(FOOD, "doc2"), finding(RESTORATION, "doc3")]
    )
    raw["procedure_observations"] = [
        {
            "step_code": RESTORATION,
            "observed_status": "IN_PROGRESS",
            "source_text": request.input.redacted_text,
            "requires_confirmation": False,
            "reason_summary": "사용자가 본인의 실행 상태를 명시함",
        }
    ]
    result = asyncio.run(InfoAnalysisAgent(Responses(raw)).analyze(request))
    observation = result.procedure_progress_observations[0]
    assert observation.observed_status == "IN_PROGRESS"
    assert observation.source_span.text == request.input.redacted_text
