"""Replanning analyzes supplied remaining topics, not only the latest utterance."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from test_action_codes import NOW, StubModel, result_fixes_xfail, supervisor_request
from test_blocker_candidates import ChoiceModel, request_with_state
from test_procedure_only_graph import graph_run_inputs

from app.agent.graph import AgentGraph
from app.agent.info_agent.agent import (
    InfoAnalysisAgent,
    InfoAnalysisGuardrailError,
)
from app.agent.review_tool import ReviewIntegrityError, ReviewTool
from app.agent.schemas import (
    CASE_FIELD_SPECS,
    AgentGraphInput,
    CaseFieldKey,
    CaseSnapshot,
    InfoAnalysisInput,
    ProcedureLookupResult,
    ProcedureProgressChangeCandidate,
    ReviewSubject,
    canonical_digest,
)
from app.agent.supervisor.agent import SupervisorAgent
from app.common.agent_dto import ProcedureCompletionConfirmation
from app.common.agent_service import build_planning_input

TAX = "FILE_TAX_BUSINESS_CLOSURE"
FOOD = "FILE_FOOD_SERVICE_CLOSURE"
RESTORATION = "CONFIRM_RESTORATION_SCOPE"


def request_for_replanning(status="NOT_REQUIRED", scope="NOT_REQUIRED"):
    base = supervisor_request()
    data = base.case_snapshot.model_dump(mode="json")
    for field, value in (("restoration_scope", scope), ("restoration_status", status), ("demolition_required", "NOT_REQUIRED")):
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
    request.case_snapshot.facts = [fact for fact in request.case_snapshot.facts if fact.field_path != "demolition_required"]
    request.case_snapshot.procedure_progress = []
    assert RESTORATION in InfoAnalysisAgent._analysis_step_codes(request)
    projection = InfoAnalysisAgent._prompt_input(request)
    assert projection["procedure_evidence_by_step"][FOOD] == ["doc2"]
    completed = request_for_replanning("COMPLETED", "FULL")
    completed.case_snapshot.facts = [fact for fact in completed.case_snapshot.facts if fact.field_path != "demolition_required"]
    completed.case_snapshot.procedure_progress = []
    assert RESTORATION in InfoAnalysisAgent._analysis_step_codes(completed)


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
def test_quoted_progress_is_ignored_if_already_completed_and_otherwise_retained(
    already_completed,
):
    request = request_for_replanning()
    request.input.redacted_text = (
        "임대인에게 원상복구 범위와 철거 필요 여부를 모두 확인했습니다."
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
            "reason_summary": "사용자의 범위 확인 완료 보고",
        }
    ]
    agent = InfoAnalysisAgent(Responses(raw), max_local_attempts=1)
    result = asyncio.run(agent.analyze(request))
    if already_completed:
        assert result.procedure_progress_observations == []
    else:
        observation, = result.procedure_progress_observations
        assert observation.source_span.text == request.input.redacted_text
        assert observation.requires_confirmation is True


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
    assert "Still analyze the official documents" in feedback


def test_explicit_free_text_progress_retains_its_exact_user_source():
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
    result = asyncio.run(InfoAnalysisAgent(Responses(raw), max_local_attempts=1).analyze(request))
    observation, = result.procedure_progress_observations
    assert observation.source_span.text == request.input.redacted_text
    observation.assert_input_integrity(request.input, {item.evidence_id: item for item in result.evidence_records})


@pytest.mark.parametrize("report,status,submitted,held", [
    ("준비사항을 확인했습니다", "IN_PROGRESS", False, False),
    ("제출했습니다", "IN_PROGRESS", True, False),
    ("기관 처리 결과가 완료된 것을 확인했습니다", "COMPLETED", True, False),
    ("처리된 것 같은데 확실하지 않습니다", "COMPLETED", False, True),
])
def test_free_text_filing_report_retains_stages_and_holds_completion_for_owner(report, status, submitted, held):
    request = request_for_replanning()
    request.input.redacted_text = f"사업자등록 폐업신고를 {report}."
    request.known_procedure_steps[0].step_name = "사업자등록 폐업신고"
    before = request.case_snapshot.model_dump_json()
    raw = output([finding(TAX, "doc1"), finding(FOOD, "doc2")])
    raw["procedure_observations"] = [{
        "step_code": TAX, "observed_status": status,
        "source_text": request.input.redacted_text,
        "requirements_confirmed": not held, "submitted": submitted,
        "requires_confirmation": held,
        "reason_summary": "모델이 사용자 실행 보고를 해석한 사례",
    }]
    result = asyncio.run(InfoAnalysisAgent(Responses(raw), max_local_attempts=1).analyze(request))
    observation, = result.procedure_progress_observations
    assert observation.observed_status == status
    assert observation.submitted is submitted
    assert observation.requires_confirmation is (held or status == "COMPLETED")
    observation.assert_input_integrity(request.input, {item.evidence_id: item for item in result.evidence_records})
    assert {item.procedure_step.step_code for item in result.procedure_findings} == {TAX, FOOD}
    assert request.case_snapshot.model_dump_json() == before


@pytest.mark.parametrize("held,tamper", [(False, False), (True, False), (False, True)])
def test_quoted_progress_reaches_review_and_a_forged_event_is_rejected(held, tamper):
    graph, request, _, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    request.trigger.input.redacted_text = "사업자등록 폐업신고를 준비 중입니다."
    raw = output([finding(TAX, "doc1")])
    raw["procedure_observations"] = [{
        "step_code": TAX, "observed_status": "IN_PROGRESS",
        "source_text": request.trigger.input.redacted_text,
        "requires_confirmation": held, "reason_summary": "사용자의 신고 준비 보고",
    }]
    graph._info_agent = InfoAnalysisAgent(Responses(raw), clock=lambda: NOW, max_local_attempts=1)
    before = request.model_dump_json()
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    assert request.model_dump_json() == before
    subject = outcome.review_subject.model_copy(deep=True)
    assert bool(subject.supervisor_draft.mutations.procedure_progress_changes) is not held
    if not tamper:
        return
    source = next(item for item in subject.source_results if item.meta.component == "INFO_AGENT")
    source.output.procedure_progress_observations[0].source_span.input_event_id = "another-event"
    source.output_digest = canonical_digest(source.output)
    forged = ReviewSubject.create(**{
        key: getattr(subject, key) for key in type(subject).model_fields if key != "subject_digest"
    })
    client = StubModel()
    with pytest.raises(ReviewIntegrityError):
        asyncio.run(ReviewTool(client).review(forged))
    assert client.calls == 0


@pytest.mark.parametrize("submitted", [False, True])
def test_completed_procedure_report_does_not_fail_the_remaining_plan(submitted):
    info_request = request_for_replanning()
    template = supervisor_request()
    template.trigger.input.redacted_text = "원상복구 범위 확인을 진행 중입니다."
    request = AgentGraphInput(
        trigger=template.trigger, case_snapshot=info_request.case_snapshot,
    )
    raw = output([finding(TAX, "doc1"), finding(FOOD, "doc2"), finding(RESTORATION, "doc3")])
    raw["procedure_observations"] = [{
        "step_code": RESTORATION, "observed_status": "IN_PROGRESS",
        "source_text": template.trigger.input.redacted_text,
        "submitted": submitted, "requires_confirmation": False,
        "reason_summary": "이미 완료된 절차를 다시 언급한 보고",
    }]
    procedure = AsyncMock()
    procedure.lookup.return_value = info_request.procedure_lookup_result
    graph = AgentGraph(
        info_agent=InfoAnalysisAgent(Responses(raw), max_local_attempts=1),
        procedure_tool=procedure, support_agent=AsyncMock(),
        supervisor=SupervisorAgent(ChoiceModel(), max_local_attempts=1),
        review_tool=ReviewTool(StubModel()),
        known_procedure_steps=info_request.known_procedure_steps, clock=lambda: NOW,
    )
    before = request.model_dump_json()
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    assert outcome.review_subject.supervisor_draft.mutations.procedure_progress_changes == []
    assert outcome.review_subject.supervisor_draft.next_action.target.procedure_step.step_code in {TAX, FOOD}
    assert request.model_dump_json() == before


def completion_report_graph(report, *, information=True):
    info_request = request_for_replanning()
    template = supervisor_request()
    template.trigger.input.redacted_text = report
    request = AgentGraphInput(
        trigger=template.trigger.model_dump() | {"trigger_type": "RESULT_SUBMITTED"},
        case_snapshot=info_request.case_snapshot,
    )
    raw = output([finding(TAX, "doc1"), finding(FOOD, "doc2")])
    raw["procedure_observations"] = [{
        "step_code": TAX, "observed_status": "COMPLETED", "source_text": report,
        "requirements_confirmed": True, "submitted": True,
        "requires_confirmation": False, "reason_summary": "모델이 해석한 기관 처리 완료",
    }]
    procedure = AsyncMock()
    procedure.lookup.return_value = info_request.procedure_lookup_result
    graph = AgentGraph(
        info_agent=InfoAnalysisAgent(Responses(raw), max_local_attempts=1),
        procedure_tool=procedure, support_agent=AsyncMock(),
        supervisor=SupervisorAgent(ChoiceModel(information=information), max_local_attempts=1),
        review_tool=ReviewTool(StubModel()),
        known_procedure_steps=info_request.known_procedure_steps, clock=lambda: NOW,
    )
    return graph, request


@pytest.mark.parametrize("report", [
    "폐업 신고 아직 안 했어요.",
    "사업자등록 폐업 신고의 기관 처리 결과가 완료된 것을 확인했습니다.",
])
@pytest.mark.parametrize("information", [True, False])
def test_completion_report_stays_pending_until_owner_approval_even_when_model_says_done(report, information):
    graph, request = completion_report_graph(report, information=information)
    before = request.model_dump_json()
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    subject = outcome.review_subject
    info = next(item.output for item in subject.source_results if item.meta.component == "INFO_AGENT")
    observation, = info.procedure_progress_observations
    assert observation.observed_status == "COMPLETED"
    assert observation.requires_confirmation is True
    assert subject.supervisor_draft.mutations.procedure_progress_changes == []
    decision = subject.supervisor_draft.decision
    assert any(item.candidate_id == "procedure:1" and "완료 보고" in item.description
               for item in decision.blockers)
    if information:
        assert decision.decision_type == "NEEDS_MORE_INFO"
        assert "완료" in " ".join(decision.questions_for_user)
    else:
        assert decision.decision_type == "ACTION"
        assert decision.next_action.target.procedure_step.step_code == FOOD
    assert request.model_dump_json() == before


def completion_confirmation_request(request, outcome, confirmed):
    subject = outcome.review_subject
    info = next(item.output for item in subject.source_results if item.meta.component == "INFO_AGENT")
    observation, = info.procedure_progress_observations
    return build_planning_input(
        trigger_type="RESULT_SUBMITTED", case_snapshot=request.case_snapshot,
        user_input=request.trigger.input.model_copy(update={
            "input_event_id": "synthetic-completion-choice", "redacted_text": "네" if confirmed else "아니오",
        }),
        client_event_id=request.trigger.client_event_id, trace_id=request.trace_id,
        procedure_completion_confirmation=ProcedureCompletionConfirmation(
            observation=observation, input=subject.trigger.input,
            snapshot=subject.snapshot, confirmed=confirmed,
        ),
    )


@pytest.mark.parametrize("confirmed", [True, False])
def test_owner_completion_choice_uses_original_report_and_does_not_repeat_confirmation(confirmed):
    graph, request = completion_report_graph("기관 처리 결과가 완료된 것을 확인했습니다.")
    pending = asyncio.run(graph.run(request))
    assert pending.outcome_type == "REVIEWED_PLAN", pending
    choice = completion_confirmation_request(request, pending, confirmed)
    raw = output([finding(TAX, "doc1"), finding(FOOD, "doc2")])
    if not confirmed:
        raw["procedure_observations"] = [{
            "step_code": TAX, "observed_status": "COMPLETED", "source_text": "아니오",
            "requires_confirmation": False, "reason_summary": "취소 답변을 완료로 오해한 모델",
        }]
    graph._info_agent = InfoAnalysisAgent(Responses(raw), max_local_attempts=1)
    graph._supervisor = SupervisorAgent(ChoiceModel(), max_local_attempts=1)
    before = choice.model_dump_json()
    outcome = asyncio.run(graph.run(choice))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    draft = outcome.review_subject.supervisor_draft
    assert draft.decision.decision_type == "ACTION"
    assert draft.decision.questions_for_user == []
    if confirmed:
        change, = draft.mutations.procedure_progress_changes
        assert change.procedure_step.step_code == TAX
        assert change.proposed_status == "COMPLETED"
        original = choice.trigger.procedure_completion_confirmation.observation
        assert change.execution_evidence_refs == original.source_evidence_refs
        assert draft.next_action.target.procedure_step.step_code == FOOD
    else:
        assert draft.mutations.procedure_progress_changes == []
        assert draft.next_action.target.procedure_step.step_code in {TAX, FOOD}
    assert choice.model_dump_json() == before


def test_rejecting_completion_keeps_new_submission_report_and_other_facts():
    graph, request = completion_report_graph("기관 처리 결과가 완료된 것을 확인했습니다.")
    pending = asyncio.run(graph.run(request))
    choice = completion_confirmation_request(request, pending, False)
    choice.trigger.input.redacted_text = "아니요, 제출만 했어요. 직원은 2명입니다."
    raw = output([finding(TAX, "doc1"), finding(FOOD, "doc2")])
    raw["procedure_observations"] = [{
        "step_code": TAX, "observed_status": "IN_PROGRESS", "source_text": "아니요, 제출만 했어요.",
        "submitted": True, "requires_confirmation": False, "reason_summary": "완료가 아닌 제출 보고",
    }]
    raw["facts"] = [{
        "operation": "SET", "field_path": "employee_count", "value_type": "INTEGER", "value": 2,
        "source_text": "직원은 2명입니다.", "confidence_bps": 9500,
        "requires_confirmation": False, "reason_summary": "확인 응답과 함께 알려준 직원 수",
    }]
    graph._info_agent = InfoAnalysisAgent(Responses(raw), max_local_attempts=1)
    graph._supervisor = SupervisorAgent(ChoiceModel(), max_local_attempts=1)
    before = choice.model_dump_json()
    outcome = asyncio.run(graph.run(choice))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    mutations = outcome.review_subject.supervisor_draft.mutations
    progress, = mutations.procedure_progress_changes
    assert progress.procedure_step.step_code == TAX
    assert progress.proposed_status == "IN_PROGRESS"
    assert progress.proposed_submitted is True
    fact, = mutations.fact_changes
    assert (fact.field_path, fact.proposed_value) == ("employee_count", 2)
    assert choice.model_dump_json() == before


@pytest.mark.parametrize("tamper", ["input_event", "procedure", "status", "requirements", "submitted", "case"])
def test_completion_confirmation_rejects_changed_original_or_current_state(tamper):
    graph, request = completion_report_graph("기관 처리 결과가 완료된 것을 확인했습니다.")
    pending = asyncio.run(graph.run(request))
    choice = completion_confirmation_request(request, pending, True)
    payload = choice.model_dump()
    confirmation = payload["trigger"]["procedure_completion_confirmation"]
    if tamper == "input_event":
        confirmation["input"]["input_event_id"] = "another-original-report"
        with pytest.raises(ValueError, match="progress span differs"):
            AgentGraphInput.model_validate(payload)
        return
    if tamper == "procedure":
        confirmation["observation"]["procedure_step"]["step_code"] = FOOD
    elif tamper == "case":
        payload["case_snapshot"]["case_id"] = 2
    else:
        payload["case_snapshot"]["procedure_progress"].append({
            "procedure_step": confirmation["observation"]["procedure_step"],
            "status": "IN_PROGRESS" if tamper == "status" else "NOT_STARTED",
            "requirements_confirmed": tamper == "requirements", "submitted": tamper == "submitted",
            "evidence_refs": ["synthetic-document"], "updated_at": NOW,
        })
    changed = AgentGraphInput.model_validate(payload)
    graph._info_agent = InfoAnalysisAgent(
        Responses(output([finding(TAX, "doc1"), finding(FOOD, "doc2")])), max_local_attempts=1,
    )
    before = changed.model_dump_json()
    outcome = asyncio.run(graph.run(changed))
    assert outcome.outcome_type == "SAFE_FAILURE", outcome
    assert outcome.failed_component == "INFO_AGENT"
    assert changed.model_dump_json() == before


def test_independent_review_blocks_unapproved_completion_even_if_model_would_pass():
    graph, request = completion_report_graph("기관 처리 결과가 완료된 것을 확인했습니다.")
    pending = asyncio.run(graph.run(request))
    subject = pending.review_subject.model_copy(deep=True)
    info_source = next(item for item in subject.source_results if item.meta.component == "INFO_AGENT")
    observation, = info_source.output.procedure_progress_observations
    observation.requires_confirmation = False  # Supervisor까지 잘못 통과시킨 경우도 막는다.
    info_source.output_digest = canonical_digest(info_source.output)
    subject.supervisor_draft.mutations.procedure_progress_changes = [ProcedureProgressChangeCandidate(
        candidate_id=uuid4(), procedure_step=observation.procedure_step,
        before_status="NOT_STARTED", proposed_status="COMPLETED",
        proposed_requirements_confirmed=observation.requirements_confirmed,
        proposed_submitted=observation.submitted, reason_summary=observation.reason_summary,
        execution_evidence_refs=observation.source_evidence_refs,
        procedure_analysis_call_id=info_source.meta.call_id,
    )]
    forged = ReviewSubject.create(**{
        key: getattr(subject, key) for key in type(subject).model_fields if key != "subject_digest"
    })
    client = StubModel()
    with pytest.raises(ReviewIntegrityError, match="completion.*confirmation|confirmation.*completion"):
        asyncio.run(ReviewTool(client).review(forged))
    assert client.calls == 0


@pytest.mark.parametrize("committed_status", ["NOT_STARTED", "COMPLETED"])
def test_free_text_restoration_completion_preserves_committed_facts(committed_status):
    request = request_for_replanning(status=committed_status, scope="FULL")
    request.input.redacted_text = "원상복구 작업을 완료했습니다."
    before = request.case_snapshot.model_dump_json()
    raw = output([finding(TAX, "doc1"), finding(FOOD, "doc2")])
    raw["facts"] = [{
        "operation": "SET", "field_path": "restoration_status", "value_type": "ENUM",
        "value": "COMPLETED", "source_text": request.input.redacted_text,
        "confidence_bps": 9500, "requires_confirmation": False,
        "reason_summary": "모델이 자유문장을 원상복구 완료로 해석한 사례",
    }]
    agent = InfoAnalysisAgent(Responses(raw), max_local_attempts=1)
    if committed_status == "COMPLETED":
        result = asyncio.run(agent.analyze(request))
        assert result.fact_candidates == []
        assert result.conflicts == []
    else:
        result = asyncio.run(agent.analyze(request))
        assert result.conflicts[0].proposed_value == "COMPLETED"
    assert request.case_snapshot.model_dump_json() == before


RESTORATION_RESULT = "원상복구 범위는 없고 원상복구 작업은 필요하지 않습니다."


@pytest.mark.parametrize("unsupported_completion", [False, True])
def test_result_sentence_produces_only_the_three_stated_fact_changes(unsupported_completion):
    request = request_for_replanning()
    snapshot = request.case_snapshot.model_dump(mode="json")
    for item in snapshot["facts"]:
        if item["field_path"] in {"restoration_scope", "restoration_status", "demolition_required"}:
            item.update(status="UNKNOWN", value=None, evidence_refs=[], updated_at=None)
    snapshot["procedure_progress"] = []
    text = "임대인에게 확인했습니다. " + RESTORATION_RESULT + " 철거도 필요하지 않습니다."
    request = InfoAnalysisInput.model_validate(request.model_dump() | {
        "case_snapshot": snapshot,
        "input": request.input.model_dump() | {"redacted_text": text},
    })
    response = output([finding(TAX, "doc1"), finding(FOOD, "doc2"), finding(RESTORATION, "doc3")])
    response["facts"] = [
        {"operation": "SET", "field_path": field, "value_type": "ENUM", "value": "NOT_REQUIRED",
         "source_text": quote, "confidence_bps": 9500, "requires_confirmation": False,
         "reason_summary": "합성 임대인 확인 결과"}
        for field, quote in (
            ("restoration_scope", RESTORATION_RESULT),
            ("restoration_status", RESTORATION_RESULT),
            ("demolition_required", "철거도 필요하지 않습니다."),
        )
    ]
    rejected = deepcopy(response)
    rejected["procedure_observations"] = [{
        "step_code": RESTORATION, "observed_status": "COMPLETED",
        "source_text": "사용자가 쓰지 않은 원상복구 완료 문장입니다.", "requires_confirmation": False,
        "reason_summary": "원문에 없는 진행 보고",
    }]
    client = Responses(*([rejected] if unsupported_completion else []), response)
    result = asyncio.run(InfoAnalysisAgent(client).analyze(request))
    assert len(client.messages) == (2 if unsupported_completion else 1)
    if unsupported_completion:
        feedback = " ".join(item["content"] for item in client.messages[1])
        assert "progress must quote the user's own execution report" in feedback
    assert {(fact.field_path, fact.value) for fact in result.fact_candidates} == {
        ("restoration_scope", "NOT_REQUIRED"),
        ("restoration_status", "NOT_REQUIRED"),
        ("demolition_required", "NOT_REQUIRED"),
    }
    assert result.conflicts == []
    assert result.procedure_progress_observations == []


def analyze_facts(facts, text, *, requires_confirmation=False):
    """Run the whole analyzer on one input sentence and return its result.

    requires_confirmation=True stands in for the model marking the facts as
    needing the owner's confirmation; the code now follows that mark as is.
    """
    request = request_for_replanning()
    snapshot = request.case_snapshot.model_dump(mode="json")
    for item in snapshot["facts"]:
        if item["field_path"] in {"restoration_scope", "restoration_status", "demolition_required"}:
            item.update(status="UNKNOWN", value=None, evidence_refs=[], updated_at=None)
    snapshot["procedure_progress"] = []
    request = InfoAnalysisInput.model_validate(request.model_dump() | {
        "case_snapshot": snapshot,
        "input": request.input.model_dump() | {"redacted_text": text},
    })
    response = output(
        [finding(TAX, "doc1"), finding(FOOD, "doc2"), finding(RESTORATION, "doc3")]
    )
    response["facts"] = [
        {"operation": "SET", "field_path": field, "value_type": CASE_FIELD_SPECS[field][0], "value": value,
         "source_text": quote, "confidence_bps": 9500,
         "requires_confirmation": requires_confirmation,
         "reason_summary": "합성 임대인 확인 결과"}
        for field, value, quote in facts
    ]
    return asyncio.run(InfoAnalysisAgent(Responses(response)).analyze(request))


# 코드 검사에 걸린 이유를 재시도에 알려주지 않으면 모델은 같은 답을 반복하고
# 분석 전체가 실패한다. 실제 모델(gpt-6.1-sol)에서 뒤집히는 보고 3번 중 2번이 그랬다.
REVERSED = "원상복구 범위는 없다고 들었는데 임대인은 전부 하라고 했어요."


def held(field, value):
    return {"operation": "SET", "field_path": field, "value_type": "ENUM", "value": value,
            "source_text": REVERSED, "confidence_bps": 8000, "requires_confirmation": True,
            "reason_summary": "합성 임대인 확인 결과"}


@pytest.mark.parametrize("rejected_facts,reason", [
    ([held("restoration_scope", "NOT_REQUIRED"),
      held("restoration_status", "NOT_REQUIRED") | {"requires_confirmation": False}],
     "restoration_status can be confirmed only when restoration_scope"),
    ([held("restoration_scope", "NOT_REQUIRED"), held("restoration_scope", "FULL")],
     "Return at most one fact per field_path"),
])
def test_rejected_facts_tell_the_retry_why(rejected_facts, reason):
    request = request_for_replanning()
    snapshot = request.case_snapshot.model_dump(mode="json")
    for item in snapshot["facts"]:
        if item["field_path"] in {"restoration_scope", "restoration_status", "demolition_required"}:
            item.update(status="UNKNOWN", value=None, evidence_refs=[], updated_at=None)
    snapshot["procedure_progress"] = []
    request = InfoAnalysisInput.model_validate(request.model_dump() | {
        "case_snapshot": snapshot,
        "input": request.input.model_dump() | {"redacted_text": REVERSED},
    })
    findings = [finding(TAX, "doc1"), finding(FOOD, "doc2"), finding(RESTORATION, "doc3")]
    rejected, corrected = output(findings), output(findings)
    rejected["facts"] = rejected_facts
    corrected["facts"] = [held("restoration_scope", "NOT_REQUIRED")]
    client = Responses(rejected, corrected)

    result = asyncio.run(InfoAnalysisAgent(client).analyze(request))

    feedback, = [
        item["content"] for item in client.messages[1]
        if item["content"].startswith("The previous facts were rejected.")
    ]
    assert reason in feedback
    assert "원상복구 범위는 없다" not in feedback  # 사장님 말은 안내에 섞지 않는다
    candidate, = result.fact_candidates
    assert candidate.requires_confirmation


# 뒤집는 말이 없는 문장은 그대로 확정된다. 되묻기가 넓어져 정상 입력까지 다시 묻게
# 되면 사장님이 같은 답을 두 번 하게 되므로 반대쪽도 같이 지킨다.
def test_plain_result_sentence_still_confirms_without_asking_back():
    text = RESTORATION_RESULT + " 철거도 필요하지 않습니다."
    result = analyze_facts([
        ("restoration_scope", "NOT_REQUIRED", RESTORATION_RESULT),
        ("restoration_status", "NOT_REQUIRED", RESTORATION_RESULT),
        ("demolition_required", "NOT_REQUIRED", "철거도 필요하지 않습니다."),
    ], text)
    assert len(result.fact_candidates) == 3
    assert not any(item.requires_confirmation for item in result.fact_candidates)


# 확인이 필요한 사실은 Case에 저장되지 않는다. 그런데 모델은 답을 냈다고 보고 그 필드를
# missing_fields에 넣지 않으므로, 되물을 대상에 따로 넣어주지 않으면 "사실은 보류됐는데
# 아무도 묻지 않는" 상태가 되어 판단이 통째로 실패한다. 실제 실행에서 그렇게 끝났다.
def test_held_fact_still_produces_a_question_for_the_owner():
    from uuid import uuid4

    from app.agent.blocker_candidates import missing_info_fields
    from app.agent.enrichment import build_fact_overlays
    from app.agent.schemas import CaseSnapshot, MutationSet

    text = "임대인에게 물어봤어요. 원상복구 범위는 없다고 들었는데 임대인은 전부 하라고 했어요."
    result = analyze_facts([("restoration_scope", "NOT_REQUIRED", text)], text, requires_confirmation=True)
    candidate, = result.fact_candidates
    assert candidate.requires_confirmation

    base = supervisor_request()
    snapshot = base.case_snapshot.model_dump(mode="json")
    for item in snapshot["facts"]:
        if item["field_path"] in {"restoration_scope", "restoration_status", "demolition_required"}:
            item.update(status="UNKNOWN", value=None, evidence_refs=[], updated_at=None)
    snapshot["procedure_progress"] = []
    snapshot = CaseSnapshot.model_validate(snapshot)
    source = next(
        item for item in base.source_results
        if type(item.output).__name__ == "InfoAnalysisResult"
    ).model_copy(update={"output": result})

    # 보류된 값은 Case에 반영되지 않는다
    assert build_fact_overlays(snapshot, result, uuid4(), uuid_factory=uuid4) == []
    # 그래도 사장님께는 물어본다
    fields = missing_info_fields(
        snapshot,
        [source],
        MutationSet(
            fact_changes=[], procedure_progress_changes=[], support_match_updates=[]
        ),
        None,
    )
    assert fields is not None
    assert fields["decision_type"] == "NEEDS_MORE_INFO"
    assert fields["questions_for_user"] == ["확인한 원상복구 범위가 있으면 알려주세요."]


@pytest.mark.parametrize("field,text", [
    ("restoration_scope", "임대인한테 물어봤는데 원상복구 범위는 없대요."),
    ("demolition_required", "계약서 확인해봤는데 철거도 필요하지 않습니다."),
    ("restoration_scope", "원상복구 범위는 없다고 들었는데 계약서에도 원상복구 범위는 없대요."),
    ("restoration_scope", "원상복구 범위는 없다고 했는데 지금도 원상복구 범위는 없다고 합니다."),
    ("restoration_scope", "원상복구 범위는 없다고 했는데 철거도 필요하지 않습니다."),
    ("demolition_required", "철거도 필요하지 않다고 했는데 원상복구 범위도 없대요."),
    ("restoration_scope", "원상복구 범위는 없다고 했는데 원상복구 작업도 필요하지 않습니다."),
    ("restoration_status", "원상복구 작업은 필요하지 않다고 했는데 원상복구 범위도 없대요."),
])
@result_fixes_xfail()
def test_connective_without_field_reversal_confirms_report(field, text):
    facts = [(field, "NOT_REQUIRED", text)]
    if field == "restoration_status":
        facts.append(("restoration_scope", "NOT_REQUIRED", text))
    result = analyze_facts(facts, text)
    assert not any(candidate.requires_confirmation for candidate in result.fact_candidates)
    assert result.procedure_progress_observations == []


@pytest.mark.parametrize("field,value,text", [
    ("employee_count", 3, "직원은 3명입니다."),
    ("employee_count", 0, "직원을 정리해서 지금은 0명으로 바뀌었어요."),
    pytest.param("employee_count", 3, "직원은 3명인데 지금도 3명입니다.", marks=result_fixes_xfail()),
    pytest.param("employee_count", 3, "직원은 3명이라고 했는데 지금도 3명이라고 합니다.", marks=result_fixes_xfail()),
    pytest.param("restoration_scope_detail", "벽면", "원상복구 범위는 벽면이라고 했는데 지금도 벽면이라고 합니다.", marks=result_fixes_xfail()),
    pytest.param("planned_closure_date", "2026-11-01", "폐업 예정일은 2026-11-01이라고 했는데 지금도 2026-11-01이라고 합니다.", marks=result_fixes_xfail()),
])
def test_plain_or_repeated_report_produces_a_reviewable_change(field, value, text):
    from app.agent.enrichment import build_fact_overlays

    result = analyze_facts([(field, value, text)], text)
    candidate, = result.fact_candidates
    assert not candidate.requires_confirmation
    change, = build_fact_overlays(
        supervisor_request().case_snapshot, result, uuid4(), uuid_factory=uuid4,
    )
    assert change.field_path == field
    assert change.model_dump(mode="json")["proposed_value"] == value


def test_clearing_confirmed_closure_date_keeps_the_conflict_candidate():
    request = request_for_replanning()
    text = "폐업 예정일을 삭제했는데 새 일정은 다시 알려드릴게요."
    snapshot = request.case_snapshot.model_dump(mode="json")
    snapshot["facts"].append({
        "field_path": "planned_closure_date", "value_type": "DATE", "value": "2026-11-01",
        "status": "CONFIRMED", "evidence_refs": ["synthetic-document"],
        "updated_at": snapshot["captured_at"],
    })
    request = InfoAnalysisInput.model_validate(request.model_dump() | {
        "case_snapshot": snapshot,
        "input": request.input.model_dump() | {"redacted_text": text},
    })
    response = output(
        [finding(TAX, "doc1"), finding(FOOD, "doc2"), finding(RESTORATION, "doc3")]
    )
    response["facts"] = [{
        "operation": "CLEAR", "field_path": "planned_closure_date", "value_type": "DATE",
        "value": None, "source_text": text, "confidence_bps": 9500,
        "requires_confirmation": False, "reason_summary": "합성 예정일 삭제 요청",
    }]
    result = asyncio.run(InfoAnalysisAgent(Responses(response), max_local_attempts=1).analyze(request))
    conflict, = result.conflicts
    assert conflict.field_path == "planned_closure_date"
    assert conflict.model_dump(mode="json")["committed_value"] == "2026-11-01"
    assert conflict.proposed_operation == "CLEAR"
    assert conflict.proposed_value is None
    assert conflict.proposed_status == "UNKNOWN"
    assert result.fact_candidates == []


@pytest.mark.parametrize("invalid", [
    None,
    pytest.param("digest", marks=result_fixes_xfail(raises=pytest.fail.Exception)),
    pytest.param("evidence", marks=result_fixes_xfail(raises=pytest.fail.Exception)),
])
def test_confirmed_conflict_overlay_checks_original_before_planning(invalid):
    from app.agent.enrichment import build_confirmed_conflict_overlay
    from app.agent.schemas import ConflictCandidate

    snapshot = supervisor_request().case_snapshot
    original = snapshot.model_dump_json()
    conflict = ConflictCandidate.create(
        conflict_ref="synthetic-conflict", candidate_id=UUID(int=70),
        snapshot_id=snapshot.snapshot_id, field_path="lease_status",
        committed_status="CONFIRMED", committed_value="OWNED",
        proposed_operation="SET", proposed_status="CONFIRMED",
        proposed_value="LEASED_PAID", source_call_id=UUID(int=3),
        source_evidence_refs=["missing-input" if invalid == "evidence" else "synthetic-document"],
    )
    if invalid == "digest":
        conflict = conflict.model_copy(update={"proposed_value": "LEASED_FREE"})
    if invalid is None:
        overlay = build_confirmed_conflict_overlay(snapshot, conflict)
        assert overlay.proposed_value == "LEASED_PAID"
        assert overlay.confirmed_conflict_ref == conflict.conflict_ref
        assert overlay.source_evidence_refs == conflict.source_evidence_refs
    else:
        with pytest.raises(ValueError):
            build_confirmed_conflict_overlay(snapshot, conflict)
    assert snapshot.model_dump_json() == original


def snapshot_from_reviewed_facts(outcome):
    """Explicit memory fixture for the next read; this does not exercise BE storage."""
    subject = outcome.review_subject
    records = {
        item.evidence_id: item for item in subject.snapshot.evidence_records
    }
    for result in subject.source_results:
        records.update({item.evidence_id: item for item in result.output.evidence_records})
    facts = {item.field_path: item.model_dump() for item in subject.snapshot.facts}
    for change in subject.supervisor_draft.mutations.fact_changes:
        facts[change.field_path] = {
            "field_path": change.field_path,
            "value_type": change.value_type,
            "value": change.proposed_value,
            "status": change.proposed_status,
            "evidence_refs": change.source_evidence_refs,
            "updated_at": NOW,
        }
    return CaseSnapshot.model_validate(subject.snapshot.model_dump() | {
        "snapshot_id": uuid4(),
        "facts": list(facts.values()),
        "evidence_records": list(records.values()),
    })


@pytest.mark.parametrize("held_demolition", [False, True])
@result_fixes_xfail()
def test_result_replanning_uses_reviewed_facts_without_repeating_scope_question(
    held_demolition,
):
    async def run():
        template = request_with_state()
        scope_text = "임대인한테 물어봤는데 원상복구 범위는 없대요."
        demolition_text = (
            "철거도 필요하지 않다고 했는데 결국 철거하래요."
            if held_demolition else "철거도 필요하지 않습니다."
        )
        status_text = "원상복구 작업은 필요하지 않습니다."

        def analysis_response(facts):
            response = output([finding(TAX, "doc1"), finding(RESTORATION, "doc1")])
            response["facts"] = [
                {"operation": "SET", "field_path": field, "value_type": "ENUM",
                 "value": "NOT_REQUIRED", "source_text": quote,
                 "confidence_bps": 9500, "requires_confirmation": held,
                 "reason_summary": "합성 임대인 확인 결과"}
                for field, quote, held in facts
            ]
            return response

        info_client = Responses(
            analysis_response([("restoration_scope", scope_text, False)]),
            analysis_response([
                ("demolition_required", demolition_text, held_demolition),
                ("restoration_status", status_text, False),
            ]),
        )
        lookup = template.source_results[0].output

        async def lookup_for_snapshot(request):
            return lookup.model_copy(update={
                "based_on_snapshot_id": request.based_on_snapshot_id,
                "as_of": request.as_of,
            })

        procedure = AsyncMock()
        procedure.lookup.side_effect = lookup_for_snapshot
        support = AsyncMock()
        graph = AgentGraph(
            info_agent=InfoAnalysisAgent(info_client, max_local_attempts=1),
            procedure_tool=procedure,
            support_agent=support,
            supervisor=SupervisorAgent(ChoiceModel(), max_local_attempts=1),
            review_tool=ReviewTool(ChoiceModel(), max_output_attempts=1),
            known_procedure_steps=template.known_procedure_steps,
            clock=lambda: NOW,
            max_review_revisions=0,
        )

        def result_request(snapshot, event, text):
            trigger = template.trigger.model_dump()
            trigger.update(trigger_type="RESULT_SUBMITTED", input_event_id=event)
            trigger["input"].update(input_event_id=event, redacted_text=text)
            return AgentGraphInput(trigger=trigger, case_snapshot=snapshot)

        first_request = result_request(template.case_snapshot, "scope-result", scope_text)
        original = first_request.model_dump_json()
        first = await graph.run(first_request)
        assert first.outcome_type == "REVIEWED_PLAN", first
        first.assert_integrity()
        draft = first.review_subject.supervisor_draft
        assert draft.decision.next_action.questions_to_ask == ["철거가 필요한가요?"]
        assert [change.field_path for change in draft.mutations.fact_changes] == [
            "restoration_scope"
        ]
        assert draft.mutations.procedure_progress_changes == []
        assert first_request.model_dump_json() == original

        next_snapshot = snapshot_from_reviewed_facts(first)
        scope = next(fact for fact in next_snapshot.facts if fact.field_path == "restoration_scope")
        assert scope.value == "NOT_REQUIRED"
        actual_source = next(
            record for record in next_snapshot.evidence_records
            if record.evidence_id == scope.evidence_refs[0]
        )
        assert actual_source.source_type == "USER_INPUT"
        assert actual_source.source_ref == "scope-result"
        assert actual_source.excerpt == scope_text

        if held_demolition:
            graph._supervisor._llm = ChoiceModel(information=True)
        second = await graph.run(result_request(
            next_snapshot, "demolition-result", demolition_text + " " + status_text,
        ))
        assert second.outcome_type == "REVIEWED_PLAN", second
        second.assert_integrity()
        draft = second.review_subject.supervisor_draft
        assert draft.mutations.procedure_progress_changes == []
        assert {change.field_path for change in draft.mutations.fact_changes} == (
            {"restoration_status"} if held_demolition
            else {"restoration_status", "demolition_required"}
        )
        if held_demolition:
            assert draft.decision.decision_type == "NEEDS_MORE_INFO"
            assert draft.decision.next_action is None
            assert draft.decision.questions_for_user == [
                "철거가 필요한지 확인한 내용이 있으면 알려주세요."
            ]
        else:
            assert draft.decision.decision_type == "ACTION"
            assert draft.decision.next_action.action_code == "CONFIRM_TAX_CLOSURE_REQUIREMENTS"
        assert len(info_client.messages) == 2
        assert procedure.lookup.await_count == 2
        support.analyze.assert_not_awaited()

    asyncio.run(run())
