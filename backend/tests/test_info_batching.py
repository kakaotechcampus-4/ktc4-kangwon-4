"""Batch transport/grounding boundaries; stub replies do not measure model accuracy."""

import asyncio
import json
from collections import Counter
from uuid import uuid4

import pytest
from test_action_codes import supervisor_request
from test_cafe_procedures import steps
from test_info_replanning import finding, output, select_progress

from app.agent.blocker_candidates import missing_info_fields
from app.agent.info_agent.agent import InfoAnalysisAgent, InfoAnalysisGuardrailError
from app.agent.llm import (
    LLMBudgetExceededError,
    LLMCallBudget,
    LLMRequestError,
    call_budget_scope,
    current_call_budget,
)
from app.agent.procedure_tool.rules import procedure_applicability
from app.agent.schemas import (
    CASE_FIELD_SPECS,
    AgentFieldKey,
    CaseFact,
    FactChangeCandidate,
    InfoAnalysisInput,
    MutationSet,
    ProcedureLookupResult,
    ProcedureProgress,
    canonical_digest,
)


def request(count=8):
    base = supervisor_request()
    next(
        fact for fact in base.case_snapshot.facts if fact.field_path == "lease_status"
    ).value = "LEASED_PAID"
    registry = steps()[:count]
    lookup = base.source_results[0].output.model_dump(mode="json")
    document, evidence = lookup["documents"][0], lookup["evidence_records"][0]
    lookup["documents"], lookup["evidence_records"] = [], []
    codes = [step.procedure_step.step_code for step in registry]
    # The last topic has a second source; splitting must retain both sources.
    for index, code in enumerate([*codes, codes[-1]], 1):
        url, ref = f"https://example.org/batch-{index}", f"batch-evidence-{index}"
        lookup["documents"].append(
            {
                **document,
                "document_id": str(uuid4()),
                "canonical_url": url,
                "evidence_ref": ref,
                "step_codes": [code],
            }
        )
        lookup["evidence_records"].append(
            {**evidence, "evidence_id": ref, "source_ref": url}
        )
    return InfoAnalysisInput(
        input=base.trigger.input.model_copy(
            update={"redacted_text": "카페 폐업 절차를 확인하고 싶습니다."}
        ),
        case_snapshot=base.case_snapshot,
        allowed_field_paths=list(AgentFieldKey),
        known_procedure_steps=registry,
        source_call_id=uuid4(),
        procedure_lookup_call_id=uuid4(),
        procedure_lookup_result=ProcedureLookupResult.model_validate(lookup),
        review_feedback=[],
    )


class Replies:
    def __init__(self, change=None):
        self.change, self.calls = change, []
        self.positions = Counter()

    async def generate(self, model, messages, **kwargs):
        payload = json.loads(
            next(item["content"][11:] for item in messages if item["role"] == "user")
        )
        self.calls.append((payload, kwargs))
        if budget := current_call_budget():
            budget.consume()
        assert kwargs["schema_name"] == "reborn_info_analysis"
        stage = payload["analysis_stage"]
        codes = kwargs["enum_constraints"]["step_code"]
        code = None if stage == "INPUT" else codes[0]
        self.positions[stage, code] += 1
        if stage == "INPUT":
            assert kwargs["enum_constraints"]["evidence_refs"] == []
            result = output([])
        else:
            assert stage == "PROCEDURE" and len(codes) == 1
            assert payload["input"] is None
            documents = payload["procedure_lookup"]["documents"]
            result = output([finding(code, next(
                doc["evidence_ref"] for doc in documents if code in doc["candidate_step_codes"]
            ))])
        if self.change:
            self.change(self.positions[stage, code], result, payload)
        return model.model_validate(result)


@pytest.mark.parametrize("count,topics", [
    (3, {"CONFIRM_RESTORATION_SCOPE"}),
    (4, {"CONFIRM_RESTORATION_SCOPE", "FILE_TAX_BUSINESS_CLOSURE"}),
    (8, {"CONFIRM_RESTORATION_SCOPE", "FILE_TAX_BUSINESS_CLOSURE", "FILE_FOOD_SERVICE_CLOSURE"}),
])
def test_full_input_then_one_topic_calls_keep_aliases_paths_and_original_digest(
    count, topics
):
    req, model = request(count), Replies()
    before = canonical_digest(req)
    result = asyncio.run(InfoAnalysisAgent(model).analyze(req))
    input_payload, input_options = model.calls[0]
    assert input_payload["analysis_stage"] == "INPUT"
    assert set(input_options["enum_constraints"]["step_code"]) == {
        item.procedure_step.step_code for item in req.known_procedure_steps
    }
    assert len(input_payload["known_procedure_steps"]) == count
    projected = {item["procedure_step"]["step_code"]: item for item in input_payload["known_procedure_steps"]}
    for step in req.known_procedure_steps:
        assert projected[step.procedure_step.step_code]["step_name"] == step.step_name
        assert projected[step.procedure_step.step_code]["utterance_aliases"] == step.utterance_aliases
    assert not input_payload.get("procedure_lookup", {}).get("documents")
    details = model.calls[1:]
    assert {options["enum_constraints"]["step_code"][0] for _, options in details} == topics
    assert all(len(options["enum_constraints"]["step_code"]) == 1 for _, options in details)
    assert len(details) == len(result.procedure_findings) == len(topics)
    assert result.based_on_snapshot_id == req.case_snapshot.snapshot_id
    assert result.based_on_procedure_lookup_call_id == req.procedure_lookup_call_id
    assert result.based_on_procedure_lookup_digest == canonical_digest(
        req.procedure_lookup_result
    )
    assert canonical_digest(req) == before
    aliases = InfoAnalysisAgent._procedure_evidence_aliases(req)
    originals = {
        aliases[doc.evidence_ref]: (
            f"/procedure_lookup_result/documents/{index}",
            set(doc.step_codes),
        )
        for index, doc in enumerate(req.procedure_lookup_result.documents)
    }
    for payload, kwargs in details:
        owned = set(kwargs["enum_constraints"]["step_code"])
        docs = payload["procedure_lookup"]["documents"]
        assert {
            item["procedure_step"]["step_code"]
            for item in payload["known_procedure_steps"]
        } == owned
        assert {doc["evidence_ref"] for doc in docs} == {
            alias for alias, (_, codes) in originals.items() if codes & owned
        }
        for doc in docs:
            path, codes = originals[doc["evidence_ref"]]
            assert doc["document_path"] == path
            assert set(doc["candidate_step_codes"]) == codes & owned
        assert all("updated_at" not in fact for fact in payload["snapshot_facts"])
        assert all(
            "registry_version" not in step for step in payload["known_procedure_steps"]
        )


def test_input_owns_facts_and_stage_questions_merge_without_losing_blocks():
    def change(index, result, payload):
        extraction = payload["analysis_stage"] == "INPUT"
        if extraction:
            result["facts"] = [{
                "operation": "SET", "field_path": "had_employees", "value_type": "BOOLEAN",
                "value": True, "source_text": payload["input"]["redacted_text"],
                "confidence_bps": 10000, "requires_confirmation": False, "reason_summary": "합성 사실",
            }]
        result["missing_fields"] = [
            {
                "field_path": "demolition_required",
                "reason_summary": "합성 입력 설명" if extraction else "합성 절차 설명",
                "blocks": ["PROCEDURE_LOOKUP" if extraction else "SUPERVISOR_DECISION"],
                "question": "합성 입력 질문" if extraction else "합성 절차 질문",
            }
        ]
        result["uncertainties"] = [] if extraction else [
            {
                "code": "SOURCE_UNAVAILABLE",
                "target_path": "/procedure_lookup_result",
                "reason_summary": "합성 불확실성",
                "evidence_refs": [],
            }
        ]

    model, req = Replies(change), request()
    req.input.redacted_text = "과거 고용한 직원이 있습니다."
    result = asyncio.run(InfoAnalysisAgent(model).analyze(req))
    assert [item.field_path for item in result.fact_candidates] == ["had_employees"]
    assert result.conflicts == []
    assert (
        len(result.missing_fields)
        == len(result.question_candidates)
        == len(result.uncertainties)
        == 1
    )
    assert set(result.missing_fields[0].blocks) == {
        "PROCEDURE_LOOKUP",
        "SUPERVISOR_DECISION",
    }
    assert result.question_candidates[0].text == "합성 입력 질문"
    assert result.missing_fields[0].reason_summary == "합성 입력 설명"
    assert result.completion_status == "NEEDS_USER_INPUT"
    assert model.positions["INPUT", None] == 1
    assert "SETTLE_EMPLOYEE_PAYMENTS" in {item.procedure_step.step_code for item in result.procedure_findings}


@pytest.mark.parametrize("partial,expected", [(False, "COMPLETE"), (True, "PARTIAL")])
def test_completion_status_preserves_partial_analysis(partial, expected):
    def change(index, result, payload):
        if partial and payload["analysis_stage"] == "PROCEDURE" and payload["procedure_analysis_step_codes"] == ["FILE_TAX_BUSINESS_CLOSURE"]:
            result["completion_status"] = "PARTIAL"

    result = asyncio.run(InfoAnalysisAgent(Replies(change)).analyze(request()))
    assert result.completion_status == expected


@pytest.mark.parametrize("count", [3, 8])
def test_finished_topics_with_unknown_histories_do_not_create_extra_batches(count):
    req = request(count)
    req.case_snapshot.procedure_progress = [
        ProcedureProgress(
            procedure_step=step.procedure_step,
            status="COMPLETED",
            evidence_refs=[req.case_snapshot.facts[0].evidence_refs[0]],
            updated_at=req.case_snapshot.captured_at,
        )
        for step in req.known_procedure_steps
    ]
    model = Replies()
    result = asyncio.run(InfoAnalysisAgent(model).analyze(req))
    # Completed rows alone do not establish the full applicable cafe scope.
    assert len(model.calls) == 1 and result.procedure_findings == []


def finished_request(*, employed=False):
    req = request()
    values = {
        "restoration_scope": "NOT_REQUIRED",
        "demolition_required": "NOT_REQUIRED",
        "had_employees": employed,
        "pension_enrolled": employed,
        "health_insurance_enrolled": employed,
        "employment_insurance_enrolled": employed,
        "industrial_accident_insurance_enrolled": employed,
    }
    req.case_snapshot.facts.extend(
        [
            CaseFact(
                field_path=field,
                value_type=CASE_FIELD_SPECS[AgentFieldKey(field)][0],
                value=value,
                status="CONFIRMED",
                evidence_refs=[req.case_snapshot.facts[0].evidence_refs[0]],
                updated_at=req.case_snapshot.captured_at,
            )
            for field, value in values.items()
        ]
    )
    req.case_snapshot.procedure_progress = [
        ProcedureProgress(
            procedure_step=step.procedure_step,
            status="COMPLETED",
            evidence_refs=[req.case_snapshot.facts[0].evidence_refs[0]],
            updated_at=req.case_snapshot.captured_at,
        )
        for step in req.known_procedure_steps
        if procedure_applicability(step, req.case_snapshot) is True
    ]
    return req


def test_known_exclusions_need_no_progress_findings_questions_or_observations():
    req = finished_request()
    assert InfoAnalysisAgent._analysis_step_codes(req) == {"FILE_TAX_BUSINESS_CLOSURE"}
    model = Replies()
    result = asyncio.run(InfoAnalysisAgent(model).analyze(req))
    assert len(model.calls) == 2
    assert model.calls[0][0]["analysis_stage"] == "INPUT"
    assert model.calls[1][1]["enum_constraints"]["step_code"] == [
        "FILE_TAX_BUSINESS_CLOSURE"
    ]
    assert (
        result.question_candidates
        == result.missing_fields
        == result.procedure_progress_observations
        == []
    )
    assert [item.procedure_step.step_code for item in result.procedure_findings] == [
        "FILE_TAX_BUSINESS_CLOSURE"
    ]


def test_completed_tax_is_not_a_detail_topic_while_employee_processing_remains():
    req = finished_request(employed=True)
    remaining = {"REPORT_EMPLOYEE_INSURANCE_LOSS", "REPORT_WORKPLACE_INSURANCE_CLOSURE"}
    for progress in req.case_snapshot.procedure_progress:
        if progress.procedure_step.step_code in remaining:
            progress.status = "IN_PROGRESS"
    before = canonical_digest(req)
    model = Replies()
    result = asyncio.run(InfoAnalysisAgent(model).analyze(req))
    assert {item.procedure_step.step_code for item in result.procedure_findings} == remaining
    assert model.positions == {
        ("INPUT", None): 1,
        **{("PROCEDURE", code): 1 for code in remaining},
    }
    assert canonical_digest(req) == before


def test_the_last_pending_completion_opens_tax_guidance_in_the_same_analysis():
    req = finished_request(employed=True)
    code = "REPORT_WORKPLACE_INSURANCE_CLOSURE"
    next(item for item in req.case_snapshot.procedure_progress
         if item.procedure_step.step_code == code).status = "IN_PROGRESS"
    req.input.redacted_text = "가입한 네 보험 모두 사업장 탈퇴·소멸 신고를 제출했고 기관의 처리 완료를 확인했습니다."
    assert InfoAnalysisAgent._analysis_step_codes(req) == {code}
    select_progress(req, code, "COMPLETED", ready=True, submitted=True)
    before = canonical_digest(req)
    model = Replies()
    result = asyncio.run(InfoAnalysisAgent(model).analyze(req))
    assert {item.procedure_step.step_code for item in result.procedure_findings} == {
        code, "FILE_TAX_BUSINESS_CLOSURE",
    }
    tax_payload = next(payload for payload, options in model.calls
                       if options["enum_constraints"]["step_code"] == ["FILE_TAX_BUSINESS_CLOSURE"])
    assert next(item for item in tax_payload["snapshot_procedure_progress"]
                if item["procedure_step"]["step_code"] == code)["status"] == "COMPLETED"
    assert model.positions["INPUT", None] == 1
    assert canonical_digest(req) == before


def test_a_new_tax_observation_keeps_its_detail_even_before_full_scope_completion():
    req = finished_request(employed=True)
    next(item for item in req.case_snapshot.procedure_progress
         if item.procedure_step.step_code == "REPORT_EMPLOYEE_INSURANCE_LOSS").status = "IN_PROGRESS"
    req.input.redacted_text = "사업자 폐업신고 준비사항을 확인하고 신고서를 제출했으며 기관 처리 완료도 확인했습니다."
    code = "FILE_TAX_BUSINESS_CLOSURE"
    assert code not in InfoAnalysisAgent._analysis_step_codes(req)
    report = select_progress(req, code, "COMPLETED", ready=True, submitted=True)
    result = asyncio.run(InfoAnalysisAgent(Replies()).analyze(req))
    assert code in {item.procedure_step.step_code for item in result.procedure_findings}
    observation, = result.procedure_progress_observations
    assert observation.procedure_step.step_code == code
    assert observation.requirements_confirmed and observation.submitted
    assert observation.source_span is None
    assert observation.structured_report == report


@pytest.mark.parametrize("field", [
    "had_employees", "pension_enrolled", "health_insurance_enrolled",
    "employment_insurance_enrolled", "industrial_accident_insurance_enrolled",
])
def test_an_unknown_required_history_does_not_open_completed_tax_details(field):
    req = finished_request()
    req.case_snapshot.facts = [item for item in req.case_snapshot.facts if item.field_path != field]
    assert InfoAnalysisAgent._analysis_step_codes(req) == set()
    result = asyncio.run(InfoAnalysisAgent(Replies()).analyze(req))
    assert result.procedure_findings == []
    missing = missing_info_fields(
        req.case_snapshot, [],
        MutationSet(fact_changes=[], procedure_progress_changes=[], support_match_updates=[]),
        known_procedure_steps=req.known_procedure_steps,
    )
    assert missing["questions_for_user"]
    assert "missing:" + field in {item["candidate_id"] for item in missing["blockers"]}


def test_pending_fact_overlays_are_used_without_an_explicit_mutation_set():
    req = finished_request()
    field = "pension_enrolled"
    ref = req.case_snapshot.facts[0].evidence_refs[0]
    req.case_snapshot.facts = [item for item in req.case_snapshot.facts if item.field_path != field]
    req.case_snapshot.facts.append(CaseFact(
        field_path=field, value_type="BOOLEAN", value=None, status="UNKNOWN",
        evidence_refs=[], updated_at=None,
    ))
    assert InfoAnalysisAgent._analysis_step_codes(req) == set()
    req.fact_overlays = [FactChangeCandidate(
        candidate_id=uuid4(), operation="SET", source_fact_candidate_id=uuid4(),
        source_type="CONFIRMED_CONFLICT", field_path=field, value_type="BOOLEAN",
        before_status="UNKNOWN", before_value=None,
        proposed_status="CONFIRMED", proposed_value=False,
        candidate_status="READY_FOR_REVIEW", reason_summary="합성 승인된 가입 이력",
        source_evidence_refs=[ref], source_call_id=None,
        confirmed_conflict_ref="synthetic-insurance-history",
    )]
    assert InfoAnalysisAgent._analysis_step_codes(req) == {"FILE_TAX_BUSINESS_CLOSURE"}


def test_four_temporary_steps_cannot_open_the_completed_tax_exception():
    req = finished_request()
    req.known_procedure_steps = req.known_procedure_steps[:4]
    for step in req.known_procedure_steps:
        step.registry_version = "temp"
    model = Replies()
    result = asyncio.run(InfoAnalysisAgent(model).analyze(req))
    assert result.procedure_findings == []
    assert model.positions == {("INPUT", None): 1}


@pytest.mark.parametrize("value", [False, None])
def test_unknown_or_excluded_history_stays_out_of_details_but_in_the_full_input_registry(
    value,
):
    req = request()
    all_codes = {step.procedure_step.step_code for step in req.known_procedure_steps}
    baseline = {"CONFIRM_RESTORATION_SCOPE", "FILE_TAX_BUSINESS_CLOSURE", "FILE_FOOD_SERVICE_CLOSURE"}
    assert InfoAnalysisAgent._analysis_step_codes(req) == baseline
    ref = req.case_snapshot.facts[0].evidence_refs[0]
    req.case_snapshot.facts.append(
        CaseFact(
            field_path="had_employees",
            value_type="BOOLEAN",
            value=True,
            status="CONFIRMED",
            evidence_refs=[ref],
            updated_at=req.case_snapshot.captured_at,
        )
    )
    assert InfoAnalysisAgent._analysis_step_codes(req) == baseline | {"SETTLE_EMPLOYEE_PAYMENTS"}
    req.fact_overlays = [
        FactChangeCandidate(
            candidate_id=uuid4(),
            operation="SET" if value is not None else "CLEAR",
            source_fact_candidate_id=uuid4(),
            source_type="CONFIRMED_CONFLICT",
            field_path="had_employees",
            value_type="BOOLEAN",
            before_status="CONFIRMED",
            before_value=True,
            proposed_status="CONFIRMED" if value is not None else "UNKNOWN",
            proposed_value=value,
            candidate_status="READY_FOR_REVIEW",
            reason_summary="합성 승인된 이력 변경",
            source_evidence_refs=[ref],
            source_call_id=None,
            confirmed_conflict_ref="synthetic-confirmed-history",
        )
    ]
    assert InfoAnalysisAgent._analysis_step_codes(req) == baseline
    model = Replies()
    asyncio.run(InfoAnalysisAgent(model).analyze(req))
    assert set(model.calls[0][1]["enum_constraints"]["step_code"]) == all_codes
    assert len(model.calls[0][0]["known_procedure_steps"]) == 8
    missing = missing_info_fields(
        req.case_snapshot, [],
        MutationSet(fact_changes=req.fact_overlays, procedure_progress_changes=[], support_match_updates=[]),
        known_procedure_steps=req.known_procedure_steps,
    )
    expected_question = (
        "직원을 고용한 적이 있나요?" if value is None
        else "이번 폐업 대상 사업장의 국민연금 가입 이력이 있나요? 이미 탈퇴했어도 알려주세요."
    )
    assert missing["questions_for_user"] == [expected_question]


def test_procedure_fact_violation_retries_that_topic_without_reextracting_valid_input():
    def change(index, result, payload):
        if payload["analysis_stage"] == "PROCEDURE" and payload["procedure_analysis_step_codes"] == ["FILE_FOOD_SERVICE_CLOSURE"] and index == 1:
            result["facts"] = [
                {
                    "operation": "SET",
                    "field_path": "had_employees",
                    "value_type": "BOOLEAN",
                    "value": True,
                    "source_text": "과거 고용한 직원이 있습니다.",
                    "confidence_bps": 10000,
                    "requires_confirmation": False,
                    "reason_summary": "합성 사실",
                }
            ]

    model = Replies(change)
    result = asyncio.run(
        InfoAnalysisAgent(model, max_local_attempts=2).analyze(request())
    )
    assert len(model.calls) == 5 and len(result.procedure_findings) == 3
    assert model.positions == {
        ("INPUT", None): 1,
        ("PROCEDURE", "CONFIRM_RESTORATION_SCOPE"): 1,
        ("PROCEDURE", "FILE_TAX_BUSINESS_CLOSURE"): 1,
        ("PROCEDURE", "FILE_FOOD_SERVICE_CLOSURE"): 2,
    }
    assert result.fact_candidates == []


def test_late_missing_topic_is_rejected_by_the_full_original_coverage_check():
    def change(index, result, payload):
        if payload["analysis_stage"] == "PROCEDURE" and payload["procedure_analysis_step_codes"] == ["FILE_TAX_BUSINESS_CLOSURE"]:
            result["procedure_findings"].pop()

    model = Replies(change)
    with pytest.raises(InfoAnalysisGuardrailError):
        asyncio.run(InfoAnalysisAgent(model, max_local_attempts=1).analyze(request()))
    assert len(model.calls) == 4


@pytest.mark.parametrize("kind", ["procedure_findings", "procedure_observations"])
def test_outside_batch_step_is_rejected_even_when_it_is_in_the_global_registry(kind):
    req = request()
    outside = max(step.procedure_step.step_code for step in req.known_procedure_steps)

    def change(index, result, payload):
        if payload["analysis_stage"] == "INPUT":
            return
        if kind == "procedure_findings":
            result[kind].append(finding(outside, "doc1"))
        else:
            result[kind] = [
                {
                    "step_code": outside,
                    "observed_status": "IN_PROGRESS",
                    "source_text": req.input.redacted_text,
                    "requires_confirmation": False,
                    "reason_summary": "합성 진행",
                }
            ]

    model = Replies(change)
    with pytest.raises(InfoAnalysisGuardrailError):
        asyncio.run(InfoAnalysisAgent(model, max_local_attempts=1).analyze(req))
    assert model.positions["INPUT", None] == 1
    assert any(payload["analysis_stage"] == "PROCEDURE" for payload, _ in model.calls)


def reported_fact(field, value, text):
    return {
        "operation": "SET", "field_path": field,
        "value_type": CASE_FIELD_SPECS[AgentFieldKey(field)][0].value,
        "value": value, "source_text": text, "confidence_bps": 10000,
        "requires_confirmation": False, "reason_summary": "합성 사용자 보고",
    }


def scoped_request(scope="PARTIAL", demolition="NOT_REQUIRED"):
    req = request()
    values = {"restoration_scope": scope, "demolition_required": demolition}
    req.case_snapshot.facts = [item for item in req.case_snapshot.facts if item.field_path not in values]
    req.case_snapshot.facts.extend(CaseFact(
        field_path=field, value_type="ENUM", value=value, status="CONFIRMED",
        evidence_refs=[req.case_snapshot.facts[0].evidence_refs[0]],
        updated_at=req.case_snapshot.captured_at,
    ) for field, value in values.items())
    return req


def scope_change(req, field, value):
    before = next(item for item in req.case_snapshot.facts if item.field_path == field)
    return FactChangeCandidate(
        candidate_id=uuid4(), operation="CLEAR" if value is None else "SET",
        source_fact_candidate_id=uuid4(), source_type="CONFIRMED_CONFLICT",
        field_path=field, value_type="ENUM", before_status=before.status, before_value=before.value,
        proposed_status="UNKNOWN" if value is None else "CONFIRMED", proposed_value=value,
        candidate_status="READY_FOR_REVIEW", reason_summary="합성 승인된 범위 변경",
        source_evidence_refs=before.evidence_refs, source_call_id=None,
        confirmed_conflict_ref="synthetic-scope-selection",
    )


@pytest.mark.parametrize("scope", ["FULL", "PARTIAL", "NOT_REQUIRED"])
@pytest.mark.parametrize("demolition", ["REQUIRED", "NOT_REQUIRED"])
def test_both_confirmed_scope_facts_need_no_further_scope_detail(scope, demolition):
    assert "CONFIRM_RESTORATION_SCOPE" not in InfoAnalysisAgent._analysis_step_codes(
        scoped_request(scope, demolition)
    )


@pytest.mark.parametrize("observed", [False, True])
def test_mixed_approved_scope_uses_three_topics_unless_new_scope_progress_needs_proof(observed):
    req = scoped_request()
    req.fact_overlays = [scope_change(req, "restoration_scope", "FULL")]
    if observed:
        req.input.redacted_text = "임대인에게 원상복구 범위는 전체이고 철거는 필요 없다는 확인을 마쳤습니다."
        select_progress(req, "CONFIRM_RESTORATION_SCOPE", "COMPLETED")
    else:
        req.input = None
    expected = {"PERFORM_RESTORATION", "FILE_FOOD_SERVICE_CLOSURE", "FILE_TAX_BUSINESS_CLOSURE"}
    assert InfoAnalysisAgent._analysis_step_codes(req) == expected
    assert InfoAnalysisAgent._analysis_step_codes(req, mutations=MutationSet(
        fact_changes=req.fact_overlays, procedure_progress_changes=[], support_match_updates=[],
    )) == expected
    before = canonical_digest(req)

    model = Replies()
    result = asyncio.run(InfoAnalysisAgent(model).analyze(req))
    if observed:
        expected.add("CONFIRM_RESTORATION_SCOPE")
    assert {item.procedure_step.step_code for item in result.procedure_findings} == expected
    assert sum(count for (stage, _), count in model.positions.items() if stage == "PROCEDURE") == len(expected)
    assert canonical_digest(req) == before
    assert result.based_on_procedure_lookup_digest == canonical_digest(req.procedure_lookup_result)


@pytest.mark.parametrize("field", ["restoration_scope", "demolition_required"])
@pytest.mark.parametrize("cleared", [False, True])
def test_unknown_or_cleared_scope_fact_keeps_scope_analysis(field, cleared):
    req = scoped_request()
    if cleared:
        req.fact_overlays = [scope_change(req, field, None)]
    else:
        req.case_snapshot.facts = [item for item in req.case_snapshot.facts if item.field_path != field]
        req.case_snapshot.facts.append(CaseFact(
            field_path=field, value_type="ENUM", value=None, status="UNKNOWN",
            evidence_refs=[], updated_at=None,
        ))
    assert "CONFIRM_RESTORATION_SCOPE" in InfoAnalysisAgent._analysis_step_codes(req)
    before = canonical_digest(req)
    result = asyncio.run(InfoAnalysisAgent(Replies()).analyze(req))
    assert "CONFIRM_RESTORATION_SCOPE" in {item.procedure_step.step_code for item in result.procedure_findings}
    assert canonical_digest(req) == before


def test_completed_restoration_status_keeps_its_existing_scope_completion_behavior():
    req = scoped_request()
    req.case_snapshot.facts = [item for item in req.case_snapshot.facts
                               if item.field_path not in {"restoration_status", "demolition_required"}]
    req.case_snapshot.facts.append(CaseFact(
        field_path="restoration_status", value_type="ENUM", value="COMPLETED", status="CONFIRMED",
        evidence_refs=[req.case_snapshot.facts[0].evidence_refs[0]], updated_at=req.case_snapshot.captured_at,
    ))
    assert "CONFIRM_RESTORATION_SCOPE" not in InfoAnalysisAgent._analysis_step_codes(req)


def test_new_scope_and_completed_work_open_return_in_the_same_analysis():
    req = request()
    req.input.redacted_text = "임대인에게 전체 원상복구와 철거가 필요하다고 확인했습니다. 확인한 준비사항과 범위대로 원상복구와 철거 작업을 모두 마쳤습니다."
    report = select_progress(req, "PERFORM_RESTORATION", "COMPLETED", ready=True)
    before = canonical_digest(req)

    def change(index, result, payload):
        if payload["analysis_stage"] == "INPUT":
            text = payload["input"]["redacted_text"]
            result["facts"] = [reported_fact(field, value, text) for field, value in (
                ("restoration_scope", "FULL"), ("demolition_required", "REQUIRED"),
            )]

    model = Replies(change)
    assert "PERFORM_RESTORATION" not in InfoAnalysisAgent._analysis_step_codes(req)
    assert "RETURN_PREMISES" not in InfoAnalysisAgent._analysis_step_codes(req)
    result = asyncio.run(InfoAnalysisAgent(model).analyze(req))
    assert model.positions["INPUT", None] == 1
    assert {item.procedure_step.step_code for item in result.procedure_findings} == {
        "PERFORM_RESTORATION", "RETURN_PREMISES",
        "FILE_FOOD_SERVICE_CLOSURE", "FILE_TAX_BUSINESS_CLOSURE",
    }
    observation, = result.procedure_progress_observations
    assert observation.procedure_step.step_code == "PERFORM_RESTORATION"
    assert observation.observed_status == "COMPLETED"
    assert observation.source_span is None
    assert observation.structured_report == report
    returned = next(payload for payload, options in model.calls
                    if options["enum_constraints"]["step_code"] == ["RETURN_PREMISES"])
    assert returned["input"] is None
    assert {item["field_path"]: item["proposed_value"] for item in returned["fact_overlays"]} == {
        "restoration_scope": "FULL", "demolition_required": "REQUIRED",
    }
    assert next(item for item in returned["snapshot_procedure_progress"]
                if item["procedure_step"]["step_code"] == "PERFORM_RESTORATION")["status"] == "COMPLETED"
    assert canonical_digest(req) == before


def test_new_employee_and_insurance_history_opens_all_applicable_details():
    req = request()
    req.input.redacted_text = "과거 직원을 고용했고 국민연금·건강보험·고용보험·산재보험 사업장에 모두 가입한 이력이 있습니다."
    fields = (
        "had_employees", "pension_enrolled", "health_insurance_enrolled",
        "employment_insurance_enrolled", "industrial_accident_insurance_enrolled",
    )

    def change(index, result, payload):
        if payload["analysis_stage"] == "INPUT":
            result["facts"] = [reported_fact(field, True, payload["input"]["redacted_text"]) for field in fields]

    model = Replies(change)
    result = asyncio.run(InfoAnalysisAgent(model).analyze(req))
    assert {item.field_path.value for item in result.fact_candidates} == set(fields)
    assert {item.procedure_step.step_code for item in result.procedure_findings} == {
        "CONFIRM_RESTORATION_SCOPE", "FILE_TAX_BUSINESS_CLOSURE", "FILE_FOOD_SERVICE_CLOSURE",
        "SETTLE_EMPLOYEE_PAYMENTS", "REPORT_EMPLOYEE_INSURANCE_LOSS", "REPORT_WORKPLACE_INSURANCE_CLOSURE",
    }
    assert model.positions["INPUT", None] == 1
    workplace = next((payload, options) for payload, options in model.calls
                     if options["enum_constraints"]["step_code"] == ["REPORT_WORKPLACE_INSURANCE_CLOSURE"])
    documents = workplace[0]["procedure_lookup"]["documents"]
    assert len(documents) == 2
    assert {item["document_path"] for item in documents} == {
        "/procedure_lookup_result/documents/7", "/procedure_lookup_result/documents/8",
    }
    assert set(workplace[1]["enum_constraints"]["evidence_refs"]) == {item["evidence_ref"] for item in documents}


def test_employee_history_conflict_pauses_before_applicability_checks_of_the_reported_settlement():
    req = request()
    req.input.redacted_text = "과거 직원을 고용했고 직원 전체의 임금·퇴직급여 정산도 모두 마쳤습니다."
    select_progress(req, "SETTLE_EMPLOYEE_PAYMENTS", "COMPLETED")
    req.case_snapshot.facts.append(CaseFact(
        field_path="had_employees", value_type="BOOLEAN", value=False, status="CONFIRMED",
        evidence_refs=[req.case_snapshot.facts[0].evidence_refs[0]], updated_at=req.case_snapshot.captured_at,
    ))
    before = canonical_digest(req)

    def change(index, result, payload):
        if payload["analysis_stage"] == "INPUT":
            text = payload["input"]["redacted_text"]
            result["facts"] = [reported_fact("had_employees", True, text)]

    model = Replies(change)
    result = asyncio.run(InfoAnalysisAgent(model, max_local_attempts=1).analyze(req))
    conflict, = result.conflicts
    assert conflict.field_path == "had_employees"
    assert conflict.committed_value is False and conflict.proposed_value is True
    assert result.fact_candidates == []
    assert model.positions == {("INPUT", None): 1}
    assert canonical_digest(req) == before




@pytest.mark.parametrize("code,status,submitted,text", [
    ("FILE_FOOD_SERVICE_CLOSURE", "IN_PROGRESS", True,
     "식품영업 폐업신고 준비사항을 확인하고 신고서를 구청에 제출해 접수됐지만 기관 처리 완료는 아직 확인하지 못했습니다."),
    ("REPORT_EMPLOYEE_INSURANCE_LOSS", "IN_PROGRESS", False,
     "과거 직원 두 명을 고용했고 4대보험 모두 가입 이력이 있습니다. 자격상실 신고 준비사항을 확인했으며 한 명만 처리가 끝났고 다른 직원은 남아 있습니다."),
    ("FILE_TAX_BUSINESS_CLOSURE", "COMPLETED", True,
     "준비사항을 확인하고 사업자 폐업신고를 제출했으며 기관 처리 완료도 확인했습니다."),
])
def test_selected_submission_and_partial_staff_flags_reach_details_and_completed_tax_guidance(
    code, status, submitted, text,
):
    req = request()
    req.input.redacted_text = text
    report = select_progress(req, code, status, ready=True, submitted=submitted)
    before = canonical_digest(req)

    def change(index, result, payload):
        if payload["analysis_stage"] == "INPUT":
            if code == "REPORT_EMPLOYEE_INSURANCE_LOSS":
                result["facts"] = [reported_fact(field, True, text) for field in (
                    "had_employees", "pension_enrolled", "health_insurance_enrolled",
                    "employment_insurance_enrolled", "industrial_accident_insurance_enrolled",
                )]
        elif code == "FILE_TAX_BUSINESS_CLOSURE" and payload["procedure_analysis_step_codes"] == [code]:
            document = payload["procedure_lookup"]["documents"][0]
            result["procedure_findings"][0]["followup_guidance"] = [{
                "text": document["excerpt"], "evidence_refs": [document["evidence_ref"]],
            }]

    model = Replies(change)
    result = asyncio.run(InfoAnalysisAgent(model).analyze(req))
    observation, = result.procedure_progress_observations
    assert observation.observed_status == status
    assert observation.requirements_confirmed is True and observation.submitted is submitted
    assert observation.source_span is None
    assert observation.structured_report == report
    detail = next(payload for payload, options in model.calls
                  if payload["analysis_stage"] == "PROCEDURE" and options["enum_constraints"]["step_code"] == [code])
    progress = next(item for item in detail["snapshot_procedure_progress"] if item["procedure_step"]["step_code"] == code)
    assert progress["status"] == status
    assert progress["requirements_confirmed"] is True and progress["submitted"] is submitted
    current = next(item for item in result.procedure_findings if item.procedure_step.step_code == code)
    # The finding keeps the committed before-state; observations carry changes.
    assert current.current_status == "NOT_STARTED"
    assert current.requires_confirmation is False
    if code == "FILE_TAX_BUSINESS_CLOSURE":
        assert len(current.followup_guidance) == 1
    assert model.positions["INPUT", None] == 1
    assert canonical_digest(req) == before


@pytest.mark.parametrize("failure", ["stale", "missing_source", "excluded"])
@pytest.mark.parametrize("max_local_attempts", [1, 3])
def test_a_reported_step_without_valid_applicability_or_source_cannot_disappear(
    failure, max_local_attempts,
):
    req = request()
    code = "SETTLE_EMPLOYEE_PAYMENTS" if failure == "excluded" else "PERFORM_RESTORATION"
    req.input.redacted_text = "직원 전체의 임금·퇴직급여 정산을 마쳤습니다." if failure == "excluded" else "원상복구와 철거 작업을 진행했습니다."
    select_progress(req, code, "IN_PROGRESS")
    if failure == "excluded":
        req.case_snapshot.facts.append(CaseFact(
            field_path="had_employees", value_type="BOOLEAN", value=False, status="CONFIRMED",
            evidence_refs=[req.case_snapshot.facts[0].evidence_refs[0]], updated_at=req.case_snapshot.captured_at,
        ))
    else:
        lookup = req.procedure_lookup_result.model_dump(mode="json")
        target_refs = {doc["evidence_ref"] for doc in lookup["documents"] if code in doc["step_codes"]}
        if failure == "stale":
            for doc in lookup["documents"]:
                if doc["evidence_ref"] in target_refs:
                    doc["freshness_status"] = "STALE"
            for evidence in lookup["evidence_records"]:
                if evidence["evidence_id"] in target_refs:
                    evidence["freshness_status"] = "STALE"
        else:
            lookup["documents"] = [doc for doc in lookup["documents"] if doc["evidence_ref"] not in target_refs]
            lookup["evidence_records"] = [item for item in lookup["evidence_records"] if item["evidence_id"] not in target_refs]
        req.procedure_lookup_result = ProcedureLookupResult.model_validate(lookup)
    before = canonical_digest(req)

    model = Replies()
    with pytest.raises(InfoAnalysisGuardrailError):
        asyncio.run(InfoAnalysisAgent(model, max_local_attempts=max_local_attempts).analyze(req))
    assert model.positions == {("INPUT", None): 1}
    assert canonical_digest(req) == before


def test_input_failure_never_starts_details_and_keeps_the_same_attempt_limit():
    def change(index, result, payload):
        result["facts"] = [reported_fact("had_employees", True, "입력에 존재하지 않는 문장")]

    model = Replies(change)
    with pytest.raises(InfoAnalysisGuardrailError):
        asyncio.run(InfoAnalysisAgent(model, max_local_attempts=3).analyze(request()))
    assert model.positions == {("INPUT", None): 3}


def test_input_retries_do_not_reset_the_attempt_limit_for_details():
    def change(index, result, payload):
        if payload["analysis_stage"] == "INPUT" and index < 3:
            result["facts"] = [reported_fact("had_employees", True, "입력에 존재하지 않는 문장")]
        elif payload["analysis_stage"] == "PROCEDURE":
            result["procedure_findings"] = []

    model = Replies(change)
    with pytest.raises(InfoAnalysisGuardrailError):
        asyncio.run(InfoAnalysisAgent(model, max_local_attempts=3).analyze(request()))
    assert model.positions["INPUT", None] == 3
    assert {key: count for key, count in model.positions.items() if key[0] == "PROCEDURE"} == {
        ("PROCEDURE", "CONFIRM_RESTORATION_SCOPE"): 1,
        ("PROCEDURE", "FILE_FOOD_SERVICE_CLOSURE"): 1,
        ("PROCEDURE", "FILE_TAX_BUSINESS_CLOSURE"): 1,
    }


def test_failed_batch_cancels_and_awaits_siblings_preserving_the_typed_exception():
    failure = LLMRequestError(
        "synthetic unavailable", code="PROVIDER_UNAVAILABLE", retryable=True
    )

    class Failing:
        def __init__(self):
            self.started, self.active, self.cleaned = 0, 0, 0
            self.ready = asyncio.Event()

        async def generate(self, model, messages, **kwargs):
            payload = json.loads(next(item["content"][11:] for item in messages if item["role"] == "user"))
            if payload["analysis_stage"] == "INPUT":
                return model.model_validate(output([]))
            self.started += 1
            self.active += 1
            first = self.started == 1
            try:
                if first:
                    await self.ready.wait()
                    raise failure
                self.ready.set()
                await asyncio.Event().wait()
            finally:
                self.active -= 1
                self.cleaned += 1

    async def run():
        model = Failing()
        with pytest.raises(LLMRequestError) as caught:
            await InfoAnalysisAgent(model).analyze(request())
        assert caught.value is failure
        assert model.active == 0 and model.cleaned == model.started

    asyncio.run(run())


def test_at_most_two_batches_run_concurrently_with_the_same_budget():
    class Concurrent(Replies):
        active = peak = 0

        async def generate(self, *args, **kwargs):
            assert current_call_budget() is budget
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.005)
                return await super().generate(*args, **kwargs)
            finally:
                self.active -= 1

    async def run():
        with call_budget_scope(budget):
            await InfoAnalysisAgent(model).analyze(request())

    model, budget = Concurrent(), LLMCallBudget(4)
    asyncio.run(run())
    assert model.peak == 2 and model.active == 0 and budget.spent == 4


def test_batches_share_the_callers_budget_and_cancellation_boundary():
    async def limited():
        with call_budget_scope(budget):
            await InfoAnalysisAgent(model).analyze(request())

    budget, model = LLMCallBudget(2), Replies()
    with pytest.raises(LLMBudgetExceededError):
        asyncio.run(limited())
    assert budget.spent == 2

    class SlowSecond(Replies):
        active = 0

        async def generate(self, *args, **kwargs):
            self.active += 1
            try:
                if self.calls:
                    await asyncio.sleep(1)
                return await super().generate(*args, **kwargs)
            finally:
                self.active -= 1

    async def expired():
        model = SlowSecond()
        try:
            async with asyncio.timeout(0.02):
                await InfoAnalysisAgent(model).analyze(request())
        except TimeoutError:
            assert model.active == 0
            raise

    with pytest.raises(TimeoutError):
        asyncio.run(expired())
