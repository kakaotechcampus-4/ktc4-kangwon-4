"""Cafe source/contract boundaries; stubbed model replies do not measure accuracy."""

import asyncio
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_action_codes import (
    NOW,
    REF,
    TAX,
    evidence,
    finding,
    procedure_sources,
    supervisor_request,
)
from test_info_replanning import (
    FOOD,
    Responses,
    output,
    request_for_replanning,
    select_progress,
)
from test_info_replanning import finding as finding_payload

from app.agent.action_catalog import (
    PROCEDURE_LABELS,
    build_action_candidates,
    effective_procedure_progress,
)
from app.agent.blocker_candidates import (
    build_blocker_candidates,
    resolved_blocker_candidates,
)
from app.agent.info_agent.agent import InfoAnalysisAgent, ProcedureFindingDraft
from app.agent.procedure_tool.cafe import (
    build_cafe_procedure_steps,
    build_cafe_reviewed_snapshot,
)
from app.agent.procedure_tool.rules import (
    procedure_applicability,
    procedure_constraints,
)
from app.agent.procedure_tool.stored_tool import StoredProcedureLookupTool
from app.agent.prompts import info_messages, review_messages
from app.agent.schemas import (
    CASE_FIELD_SPECS,
    CaseFact,
    EvidenceRecord,
    MutationSet,
    ProcedureLookupInput,
    ProcedureProgress,
    ProcedureProgressChangeCandidate,
    ProcedureStepRef,
)
from app.agent.schemas import AgentFieldKey as CaseFieldKey


def steps():
    return build_cafe_procedure_steps(
        {code: index for index, code in enumerate(PROCEDURE_LABELS, 1)}
    )


def case(**values):
    snapshot = supervisor_request().case_snapshot
    facts = [item for item in snapshot.facts if item.field_path.value not in values]
    facts.extend(
        CaseFact(
            field_path=CaseFieldKey(key),
            value_type=CASE_FIELD_SPECS[CaseFieldKey(key)][0],
            value=value,
            status="CONFIRMED",
            evidence_refs=[REF],
            updated_at=NOW,
        )
        for key, value in values.items()
    )
    snapshot.facts = facts
    return snapshot


def test_registry_requires_employee_history_even_when_info_omits_missing_fields():
    from app.agent.blocker_candidates import missing_info_fields

    result = missing_info_fields(
        case(), [], MutationSet(fact_changes=[], procedure_progress_changes=[], support_match_updates=[]), known_procedure_steps=steps()
    )
    assert result["questions_for_user"] == ["직원을 고용한 적이 있나요?"]
    assert {item["candidate_id"] for item in result["blockers"]} == {
        "missing:had_employees", "missing:pension_enrolled", "missing:health_insurance_enrolled",
        "missing:employment_insurance_enrolled", "missing:industrial_accident_insurance_enrolled",
    }
    assert missing_info_fields(case(), [], MutationSet(fact_changes=[], procedure_progress_changes=[], support_match_updates=[])) is None


def test_confirmed_negative_histories_do_not_create_repeated_questions():
    from app.agent.blocker_candidates import missing_info_fields

    snapshot = case(
        had_employees=False, pension_enrolled=False,
        health_insurance_enrolled=False, employment_insurance_enrolled=False,
        industrial_accident_insurance_enrolled=False,
    )
    assert missing_info_fields(
        snapshot, [], MutationSet(fact_changes=[], procedure_progress_changes=[], support_match_updates=[]), known_procedure_steps=steps()
    ) is None


def test_fixed_sources_cover_all_topics_and_preserve_review_provenance():
    snapshot = build_cafe_reviewed_snapshot()
    assert len(snapshot.records) == 8
    assert {code for record in snapshot.records for code in record.step_codes} == set(
        PROCEDURE_LABELS
    )
    assert all(
        record.reviewed_by.startswith("agent research:") for record in snapshot.records
    )
    assert all(record.review_valid_days == 90 for record in snapshot.records)
    assert all(record.freshness(date(2026, 10, 18)) == "CURRENT" for record in snapshot.records)
    snapshot.records[0].excerpt = "caller mutation"
    assert build_cafe_reviewed_snapshot().records[0].excerpt != "caller mutation"


def test_fixed_source_review_expires_and_incomplete_registry_is_rejected():
    snapshot = build_cafe_reviewed_snapshot()
    assert all(record.freshness(date(2027, 2, 1)) == "STALE" for record in snapshot.records)
    with pytest.raises(ValueError, match="eight"):
        build_cafe_procedure_steps({TAX: 1})


@pytest.mark.parametrize(
    "values,expected",
    [
        ({"employee_count": 0}, None),
        ({"employee_count": 0, "had_employees": True}, True),
        ({"had_employees": False}, False),
        ({"employee_count": 3, "had_employees": False}, None),
        ({"employee_count": 3, "had_employees": True}, True),
        ({"employee_count": 0, "had_employees": False}, False),
    ],
)
def test_staff_settlement_uses_history_instead_of_current_count(values, expected):
    step = next(
        item
        for item in steps()
        if item.procedure_step.step_code == "SETTLE_EMPLOYEE_PAYMENTS"
    )
    assert procedure_applicability(step, case(**values)) is expected


def test_insurance_absence_requires_all_four_history_answers():
    step = next(
        item
        for item in steps()
        if item.procedure_step.step_code == "REPORT_WORKPLACE_INSURANCE_CLOSURE"
    )
    fields = (
        "pension_enrolled",
        "health_insurance_enrolled",
        "employment_insurance_enrolled",
        "industrial_accident_insurance_enrolled",
    )
    assert procedure_applicability(step, case(pension_enrolled=False)) is None
    assert procedure_applicability(step, case(**dict.fromkeys(fields, False))) is False
    assert procedure_applicability(step, case(pension_enrolled=True)) is True


def test_only_known_inapplicable_restoration_is_skipped_before_return():
    registry = steps()
    returned = next(
        item for item in registry if item.procedure_step.step_code == "RETURN_PREMISES"
    )
    unknown = case(lease_status="LEASED_FREE")
    assert procedure_constraints(returned, unknown, known_steps=registry)
    no_work = case(
        lease_status="LEASED_FREE",
        restoration_scope="NOT_REQUIRED",
        demolition_required="NOT_REQUIRED",
    )
    assert procedure_constraints(returned, no_work, known_steps=registry) == []
    needed = case(lease_status="LEASED_PAID", restoration_scope="FULL")
    assert procedure_constraints(returned, needed, known_steps=registry)


def test_restoration_execution_needs_both_scope_facts_even_if_progress_claims_done():
    registry = steps()
    work = next(
        item
        for item in registry
        if item.procedure_step.step_code == "PERFORM_RESTORATION"
    )
    scope = next(
        item
        for item in registry
        if item.procedure_step.step_code == "CONFIRM_RESTORATION_SCOPE"
    )
    partial = case(lease_status="LEASED_FREE", demolition_required="REQUIRED")
    partial.procedure_progress = [
        ProcedureProgress(
            procedure_step=scope.procedure_step,
            status="COMPLETED",
            evidence_refs=[REF],
            updated_at=NOW,
        )
    ]
    assert procedure_constraints(work, partial, known_steps=registry)
    confirmed = case(
        lease_status="LEASED_FREE",
        restoration_scope="FULL",
        demolition_required="REQUIRED",
    )
    assert procedure_constraints(work, confirmed, known_steps=registry) == []


def test_submission_selects_processing_check_and_complete_has_no_repeat_action():
    item = finding(requires_confirmation=False)
    progress = ProcedureProgress(
        procedure_step=item.procedure_step,
        status="IN_PROGRESS",
        requirements_confirmed=True,
        submitted=True,
        evidence_refs=[REF],
        updated_at=NOW,
    )
    rows = build_action_candidates(
        procedure_sources(item), {REF: evidence()}, procedure_progress=[progress]
    )
    assert [row["action_code"] for row in rows] == ["CONFIRM_PROCEDURE_COMPLETION"]
    assert rows[0]["logical_code"] == TAX and rows[0]["phase"] == "PROCESSING"
    progress.status = "COMPLETED"
    assert (
        build_action_candidates(
            procedure_sources(item), {REF: evidence()}, procedure_progress=[progress]
        )
        == []
    )


@pytest.mark.parametrize("phase,expected_action", [
    ("REQUIREMENTS", "CONFIRM_TAX_CLOSURE_REQUIREMENTS"),
    ("EXECUTION", "FILE_TAX_BUSINESS_CLOSURE"),
    ("PROCESSING", "CONFIRM_PROCEDURE_COMPLETION"),
])
def test_blocker_description_tracks_readiness_and_submission_without_reasking_preparation(
    phase, expected_action,
):
    request = supervisor_request()
    step = request.known_procedure_steps[0].procedure_step
    request.case_snapshot.procedure_progress = [ProcedureProgress(
        procedure_step=step, status="IN_PROGRESS",
        requirements_confirmed=phase != "REQUIREMENTS", submitted=phase == "PROCESSING",
        evidence_refs=[REF], updated_at=NOW,
    )]
    rows = build_blocker_candidates(
        request.case_snapshot, request.known_procedure_steps,
        procedure_sources(finding(requires_confirmation=phase == "REQUIREMENTS")),
        MutationSet(fact_changes=[], procedure_progress_changes=[], support_match_updates=[]),
        {REF: evidence()},
    )
    assert len(rows) == 1
    assert rows[0]["actions"][0]["action_code"] == expected_action
    description = rows[0]["blocker"]["description"]
    if phase == "REQUIREMENTS":
        assert "준비사항을 확인할 필요" in description
    else:
        assert "준비사항" not in description
        assert "아직 확인되지 않았습니다" in description
    assert ("제출됐지만" in description) is (phase == "PROCESSING")


@pytest.mark.parametrize("requires_confirmation", [True, False])
@pytest.mark.parametrize("logical,confirmation_code,expected_subject", [
    ("PERFORM_RESTORATION", "CONFIRM_RESTORATION_REQUIREMENTS", "원상복구·철거 작업"),
    ("RETURN_PREMISES", "CONFIRM_PREMISES_RETURN_REQUIREMENTS", "임대인"),
    ("SETTLE_EMPLOYEE_PAYMENTS", "CONFIRM_EMPLOYEE_SETTLEMENT_REQUIREMENTS", "직원 전원"),
])
def test_nonadministrative_candidates_describe_the_actual_work(
    logical, confirmation_code, expected_subject, requires_confirmation,
):
    registry = steps()
    step = next(item for item in registry if item.procedure_step.step_code == logical)
    snapshot = case(
        lease_status="LEASED_PAID", restoration_scope="FULL",
        demolition_required="REQUIRED", had_employees=True,
    )
    snapshot.procedure_progress = [
        ProcedureProgress(
            procedure_step=item.procedure_step, status="COMPLETED",
            evidence_refs=[REF], updated_at=NOW,
        )
        for item in registry
        if item.procedure_step.step_code in {"CONFIRM_RESTORATION_SCOPE", "PERFORM_RESTORATION"}
        and item.procedure_step.step_code != logical
    ]
    sources = procedure_sources(finding(
        procedure_step=step.procedure_step, requires_confirmation=requires_confirmation,
        decision_authority="LANDLORD" if logical == "RETURN_PREMISES" else "USER",
    ))
    if not requires_confirmation:
        snapshot.procedure_progress.append(ProcedureProgress(
            procedure_step=step.procedure_step, status="IN_PROGRESS", requirements_confirmed=True,
            evidence_refs=[REF], updated_at=NOW,
        ))
    rows = build_blocker_candidates(
        snapshot, registry, sources,
        MutationSet(fact_changes=[], procedure_progress_changes=[], support_match_updates=[]),
        {REF: evidence()},
    )
    assert len(rows) == 1
    action = rows[0]["actions"][0]
    assert action["action_code"] == (confirmation_code if requires_confirmation else logical)
    assert action["target"]["procedure_step"] == step.procedure_step.model_dump(mode="json")
    assert expected_subject in action["title"]
    assert expected_subject in action["questions_to_ask"][0]
    text = " ".join([action["title"], action["reason"], *action["questions_to_ask"]])
    assert not any(term in text for term in ("담당 기관", "신고서", "첨부서류", "제출 방법", "접수"))
    if requires_confirmation:
        assert "준비사항" in action["title"]
    else:
        assert "완료가 아직 확인되지 않았습니다" in rows[0]["blocker"]["description"]
        assert "제출됐지만" not in rows[0]["blocker"]["description"]
        if logical == "SETTLE_EMPLOYEE_PAYMENTS":
            assert "정산을 모두 마치셨나요" in action["questions_to_ask"][0]




@pytest.mark.parametrize("alias", [False, True])
@pytest.mark.parametrize("ready", [False, True])
def test_existing_restoration_completion_resolves_work_and_unblocks_return(alias, ready):
    registry = steps()
    bindings = {step.procedure_step.step_code: step.procedure_step for step in registry}
    if alias:
        for logical in ("PERFORM_RESTORATION", "RETURN_PREMISES"):
            step = next(item for item in registry if item.procedure_step == bindings[logical])
            step.procedure_step = step.procedure_step.model_copy(update={"step_code": "DB_" + logical})
            bindings[logical] = step.procedure_step
    restoration = bindings["PERFORM_RESTORATION"]
    returned = next(step for step in registry if step.procedure_step == bindings["RETURN_PREMISES"])
    snapshot = case(lease_status="LEASED_PAID", restoration_scope="FULL",
                    demolition_required="NOT_REQUIRED", restoration_status="COMPLETED")
    snapshot.active_blocker_candidate_ids = [f"procedure:{restoration.procedure_step_id}"]
    if ready:
        snapshot.procedure_progress = [ProcedureProgress(
            procedure_step=restoration, status="IN_PROGRESS", requirements_confirmed=True,
            evidence_refs=[REF], updated_at=NOW,
        )]
    changes = MutationSet(fact_changes=[], procedure_progress_changes=[], support_match_updates=[])
    before = snapshot.model_dump_json()
    rows = build_blocker_candidates(snapshot, registry, procedure_sources(finding(
        procedure_step=restoration, requires_confirmation=not ready,
        current_status="IN_PROGRESS" if ready else "NOT_STARTED", decision_authority="USER",
    )), changes, {REF: evidence()}, bindings)
    assert rows == []
    assert procedure_constraints(returned, snapshot, known_steps=registry, procedure_bindings=bindings) == []
    assert resolved_blocker_candidates(snapshot, registry, changes, bindings) == snapshot.active_blocker_candidate_ids
    assert snapshot.model_dump_json() == before
    next(fact for fact in snapshot.facts if fact.field_path == "demolition_required").value = "REQUIRED"
    assert all(item.status != "COMPLETED" for item in effective_procedure_progress(
        snapshot, changes, known_steps=registry, procedure_bindings=bindings,
    ))


@pytest.mark.parametrize("count,history,held", [(3, False, True), (3, True, False), (0, False, False)])
@pytest.mark.parametrize("known_count", [False, True])
def test_new_staff_and_history_facts_are_held_only_when_the_same_input_conflicts(count, history, held, known_count):
    from app.agent.enrichment import build_fact_overlays

    request = request_for_replanning()
    request.allowed_field_paths = list(CASE_FIELD_SPECS)
    if known_count:
        request.case_snapshot.facts.append(CaseFact(
            field_path="employee_count", value_type="INTEGER", value=count,
            status="CONFIRMED", evidence_refs=[REF], updated_at=NOW,
        ))
    text = f"직원은 {count}명이고 고용한 적이 {'있습니다' if history else '없습니다'}."
    request.input.redacted_text = text
    reply = output([finding_payload(TAX, "doc1"), finding_payload(FOOD, "doc2")])
    reply["facts"] = [{
        "operation": "SET", "field_path": key, "value_type": kind, "value": value,
        "source_text": text, "confidence_bps": 10000, "requires_confirmation": False,
        "reason_summary": "합성 직원 보고",
    } for key, kind, value in [("employee_count", "INTEGER", count), ("had_employees", "BOOLEAN", history)]]
    result = asyncio.run(InfoAnalysisAgent(Responses(reply)).analyze(request))
    assert len(result.fact_candidates) == (1 if known_count else 2)
    assert all(item.requires_confirmation is held for item in result.fact_candidates)
    changes = build_fact_overlays(request.case_snapshot, result, uuid4())
    assert len(changes) == (0 if held else 1 if known_count else 2)
    if held:
        from test_action_codes import source
        from test_blocker_candidates import ChoiceModel, subject

        from app.agent.review_tool import ReviewTool
        from app.agent.supervisor.agent import SupervisorAgent

        context = supervisor_request()
        context.case_snapshot, context.known_procedure_steps = request.case_snapshot, request.known_procedure_steps
        context.trigger.input = request.input
        context.source_results = [source(request.procedure_lookup_result, component="PROCEDURE_TOOL", call_id=5),
                                  source(result, call_id=request.source_call_id.int)]
        draft = asyncio.run(SupervisorAgent(ChoiceModel(information=True), max_local_attempts=1).draft(context))
        assert draft.decision.decision_type == "NEEDS_MORE_INFO"
        assert draft.mutations.fact_changes == []
        assert asyncio.run(ReviewTool(ChoiceModel()).review(subject(context, draft))).verdict == "PASS"


@pytest.mark.parametrize("stored,stored_value,reported,reported_value,held", [
    ("employee_count", 2, "had_employees", False, True),
    ("had_employees", False, "employee_count", 3, False),
])
def test_new_negative_history_is_held_but_a_new_staff_count_is_preserved(stored, stored_value, reported, reported_value, held):
    from test_action_codes import source

    from app.agent.blocker_candidates import missing_info_fields
    from app.agent.enrichment import build_fact_overlays

    request = request_for_replanning()
    request.allowed_field_paths = list(CASE_FIELD_SPECS)
    request.case_snapshot.facts.append(CaseFact(
        field_path=stored, value_type=CASE_FIELD_SPECS[stored][0], value=stored_value,
        status="CONFIRMED", evidence_refs=[REF], updated_at=NOW,
    ))
    text = "고용한 적이 없습니다." if reported == "had_employees" else "지금 직원은 3명입니다."
    request.input.redacted_text = text
    reply = output([finding_payload(TAX, "doc1"), finding_payload(FOOD, "doc2")])
    reply["facts"] = [{
        "operation": "SET", "field_path": reported, "value_type": CASE_FIELD_SPECS[reported][0],
        "value": reported_value, "source_text": text, "confidence_bps": 10000,
        "requires_confirmation": False, "reason_summary": "합성 직원 보고",
    }]
    result = asyncio.run(InfoAnalysisAgent(Responses(reply)).analyze(request))
    candidate, = result.fact_candidates
    assert candidate.requires_confirmation is held
    changes = build_fact_overlays(request.case_snapshot, result, uuid4())
    assert len(changes) == (0 if held else 1)
    questions = missing_info_fields(request.case_snapshot, [source(result)], MutationSet(
        fact_changes=changes, procedure_progress_changes=[], support_match_updates=[],
    ))
    assert questions["blocker"]["candidate_id"] == "missing:had_employees"


def test_info_and_review_prompts_accept_quoted_or_selected_progress_and_keep_aggregate_meaning():
    info = info_messages({})[0]["content"]
    review = review_messages({})[0]["content"]
    for prompt in (info, review):
        assert "submitted" in prompt
        assert "원문 보고" in prompt
        assert "명시적 선택이 우선" in prompt
        assert "선택값만" not in prompt
        assert "기관 처리 완료" in prompt
        assert "직원 전원" in prompt
        assert any(term in prompt for term in ("가입기관 전체", "해당 기관 전체"))
    assert "공식자료만으로 진행을 추론·변경하지 마세요" in info
    assert "일부를 전체 완료로 해석하면 반려" in review



def test_same_status_readiness_mutation_survives_without_mutating_snapshot():
    snapshot = case()
    ref = ProcedureStepRef(procedure_step_id=1, step_code=TAX)
    snapshot.procedure_progress = [
        ProcedureProgress(
            procedure_step=ref,
            status="IN_PROGRESS",
            evidence_refs=[REF],
            updated_at=NOW,
        )
    ]
    change = ProcedureProgressChangeCandidate(
        candidate_id=uuid4(),
        procedure_step=ref,
        before_status="IN_PROGRESS",
        proposed_status="IN_PROGRESS",
        proposed_requirements_confirmed=True,
        reason_summary="합성 요건 확인 보고",
        execution_evidence_refs=[REF],
        procedure_analysis_call_id=uuid4(),
    )
    result = effective_procedure_progress(
        snapshot,
        MutationSet(
            fact_changes=[],
            procedure_progress_changes=[change],
            support_match_updates=[],
        ),
    )
    assert result[0].requirements_confirmed
    assert not snapshot.procedure_progress[0].requirements_confirmed


@pytest.mark.parametrize("reported,expected", [(False, True), (True, False)])
def test_readiness_is_derived_from_user_selection_not_finding_boolean(
    reported, expected
):
    request = request_for_replanning()
    text = "사업자 폐업신고 준비사항과 서류를 확인했습니다."
    request.input.redacted_text = text
    findings = [finding_payload(TAX, "doc1"), finding_payload(FOOD, "doc2")]
    findings[0]["requires_confirmation"] = False
    draft = output(findings)
    if reported:
        select_progress(request, TAX, "IN_PROGRESS", ready=True)
    outcome = asyncio.run(InfoAnalysisAgent(Responses(draft)).analyze(request))
    assert (
        next(
            item
            for item in outcome.procedure_findings
            if item.procedure_step.step_code == TAX
        ).requires_confirmation
        is expected
    )


def test_followup_keeps_only_verbatim_official_guidance():
    raw = finding_payload(TAX, REF)
    raw["followup_guidance"] = [
        {"text": "합성 테스트 절차입니다.", "evidence_refs": [REF]},
        {"text": "만들어낸 납부일", "evidence_refs": [REF]},
    ]
    result = InfoAnalysisAgent._retain_exact_procedure_details(
        ProcedureFindingDraft.model_validate(raw),
        {REF: evidence()},
    )
    assert [item.text for item in result.followup_guidance] == [
        "합성 테스트 절차입니다."
    ]


def test_repeated_date_uses_committed_python_date_without_creating_a_conflict():
    request = request_for_replanning()
    text = "폐업 예정일은 2026-11-30입니다."
    request.input.redacted_text = text
    request.case_snapshot.facts.append(
        CaseFact(
            field_path="planned_closure_date",
            value_type="DATE",
            value=date(2026, 11, 30),
            status="CONFIRMED",
            evidence_refs=[REF],
            updated_at=NOW,
        )
    )
    draft = output([finding_payload(TAX, "doc1"), finding_payload(FOOD, "doc2")])
    draft["facts"] = [
        {
            "operation": "SET",
            "field_path": "planned_closure_date",
            "value_type": "DATE",
            "value": "2026-11-30",
            "source_text": text,
            "confidence_bps": 10000,
            "requires_confirmation": False,
            "reason_summary": "합성 동일 일자 보고",
        }
    ]
    result = asyncio.run(InfoAnalysisAgent(Responses(draft)).analyze(request))
    assert result.fact_candidates == result.conflicts == []


@pytest.mark.parametrize("queries", [["조회어와 무관"], ["조회어와 무관", "다른 조회어"]])
def test_registered_codes_select_sources_without_korean_query_matching(queries):
    snapshot = build_cafe_reviewed_snapshot()
    records = [
        EvidenceRecord(
            evidence_id=record.record_id,
            source_type="OFFICIAL_DOCUMENT",
            source_ref=record.canonical_url,
            source_version=snapshot.snapshot_version,
            locator=None,
            excerpt=record.excerpt,
            parent_evidence_refs=[],
            published_at=record.published_at,
            retrieved_at=record.retrieved_at,
            freshness_status="CURRENT",
            content_hash=record.content_hash,
        )
        for record in snapshot.records
    ]
    store = SimpleNamespace(
        snapshot_version=snapshot.snapshot_version, records=lambda: snapshot.records
    )
    target = ProcedureStepRef(procedure_step_id=99, step_code="BE_PAYROLL")
    tool = StoredProcedureLookupTool(
        store, procedure_bindings={"SETTLE_EMPLOYEE_PAYMENTS": target}
    )
    request = ProcedureLookupInput(
        lookup_goal="BUSINESS_CLOSURE",
        evidence_records=records,
        search_queries=queries,
        procedure_step_codes=[target.step_code],
        as_of=date(2026, 10, 18),
        locale="ko-KR",
        source_policy="OFFICIAL_ONLY",
        max_results_per_query=10,
        based_on_snapshot_id=uuid4(),
        review_feedback=[],
    )
    result = asyncio.run(tool.lookup(request))
    assert len(result.documents) == 2
    assert result.warnings == []
    assert all(item.step_codes == [target.step_code] for item in result.documents)
    request.procedure_step_codes = ["UNKNOWN_STEP"]
    assert asyncio.run(tool.lookup(request)).completion_status == "NO_RESULTS"
    tool = StoredProcedureLookupTool(store)
    request.procedure_step_codes = list(PROCEDURE_LABELS)
    request.max_results_per_query = 5
    result = asyncio.run(tool.lookup(request))
    assert len(result.documents) == 8
    assert {code for doc in result.documents for code in doc.step_codes} == set(
        PROCEDURE_LABELS
    )
    request.procedure_step_codes = []
    request.search_queries = ["폐업 세무 영업 원상복구 직원 보험"]
    assert len(asyncio.run(tool.lookup(request)).documents) == 5



def test_model_can_prioritize_required_insurance_history_and_keeps_every_cafe_blocker():
    from test_blocker_candidates import ChoiceModel

    from app.agent.review_tool import ReviewTool
    from app.agent.schemas import ReviewSubject
    from app.agent.supervisor.agent import SupervisorAgent

    async def run():
        request = supervisor_request()
        request.known_procedure_steps = sorted(build_cafe_procedure_steps({
            code: index for index, code in enumerate([TAX, *sorted(set(PROCEDURE_LABELS) - {TAX})], 1)
        }), key=lambda item: item.procedure_step.procedure_step_id)
        original = request.model_dump_json()
        draft = await SupervisorAgent(ChoiceModel(choice=2, information=True), clock=lambda: NOW).draft(request)
        assert draft.decision.decision_type == "NEEDS_MORE_INFO"
        assert draft.decision.blocker.candidate_id == "missing:health_insurance_enrolled"
        assert draft.decision.blocker in draft.decision.blockers
        assert {item.candidate_id for item in draft.decision.blockers} == {
            "procedure:1", "missing:had_employees", "missing:pension_enrolled",
            "missing:health_insurance_enrolled", "missing:employment_insurance_enrolled",
            "missing:industrial_accident_insurance_enrolled",
        }
        subject = ReviewSubject.create(
            schema_version="agent-io/2.0", review_subject_id=uuid4(), review_attempt=1,
            run_id=request.source_results[0].meta.run_id, case_id=request.case_snapshot.case_id,
            trigger=request.trigger, snapshot=request.case_snapshot,
            known_procedure_steps=request.known_procedure_steps, source_results=request.source_results,
            supervisor_draft=draft,
        )
        assert (await ReviewTool(ChoiceModel()).review(subject)).verdict == "PASS"
        assert request.model_dump_json() == original

    asyncio.run(run())
