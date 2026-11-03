import asyncio
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from app.agent.action_catalog import PROCEDURE_LABELS
from app.agent.document_tool.documents import DocumentService
from app.agent.document_tool.models import DocumentKind
from app.agent.document_tool.tool import DocumentTool
from app.agent.llm import StructuredLLMClient
from app.agent.procedure_tool.cafe import build_cafe_procedure_steps
from app.agent.procedure_tool.rules import procedure_applicability
from app.agent.roadmap import RoadmapInput, build_roadmap, record_checklist
from app.agent.schemas import CASE_FIELD_SPECS, CaseSnapshot, ProcedureProgress
from document_fixtures import DocumentClient, document_pdf
from pydantic import ValidationError
from test_action_codes import NOW, REF, supervisor_request
from test_document_checks import settlement_context
from test_procedure_only_graph import batch_conflict_graph, graph_run_inputs


def request(**facts):
    snapshot = supervisor_request().case_snapshot.model_dump(mode="python")
    values = {f["field_path"]: f["value"] for f in snapshot["facts"]}
    values.update(lease_status="LEASED_PAID", employee_count=2, had_employees=True,
                  pension_enrolled=True, demolition_required="REQUIRED", restoration_scope="PARTIAL")
    values.update(facts)
    snapshot["facts"] = [{"field_path": k, "value_type": CASE_FIELD_SPECS[k][0], "value": v,
                          "status": "UNKNOWN" if v is None else "CONFIRMED",
                          "evidence_refs": [] if v is None else [REF], "updated_at": NOW}
                         for k, v in values.items()]
    return RoadmapInput(case_snapshot=CaseSnapshot.model_validate(snapshot),
                        known_procedure_steps=build_cafe_procedure_steps(
                            {code: i for i, code in enumerate(PROCEDURE_LABELS, 1)}))


def tasks(value):
    return {t.task_id: t for s in build_roadmap(value).stages for t in s.tasks}


def progress(value, code, status="COMPLETED", **extra):
    ref = next(s.procedure_step for s in value.known_procedure_steps if s.procedure_step.step_code == code)
    value.case_snapshot.procedure_progress.append(ProcedureProgress(
        procedure_step=ref, status=status, evidence_refs=[REF], updated_at=NOW, **extra))


def test_five_stages_preserve_unknown_values_without_calls_or_input_mutation(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("roadmap must never call an LLM")

    monkeypatch.setattr(StructuredLLMClient, "generate", forbidden)
    value = request()
    original = value.model_dump_json()
    view = build_roadmap(value)
    assert view.supported is True and view.unsupported_reason is None
    assert [s.stage for s in view.stages] == [1, 2, 3, 4, 5]
    assert sum(len(s.tasks) for s in view.stages) == 26
    assert tasks(value)["intake"].status == "COMPLETED"
    assert tasks(value)["closure_date"].status == "NEEDS_CONFIRMATION"
    assert tasks(value)["check_loan"].status == "NEEDS_CONFIRMATION"
    assert view.next_action is None and view.next_task_id is None
    assert value.model_dump_json() == original
    changed = record_checklist(value, "notify_landlord", completed=True)
    assert tasks(changed)["notify_landlord"].status == "COMPLETED"
    assert tasks(value)["notify_landlord"].status == "NOT_STARTED"
    assert not record_checklist(changed, "notify_landlord", completed=False).completed_checklists


@pytest.mark.parametrize("loan,status", [(True, "NOT_STARTED"), (False, "NOT_APPLICABLE"), (None, "NEEDS_CONFIRMATION")])
def test_loan_is_tri_state_and_cannot_remove_other_tasks(loan, status):
    value = request()
    value.has_business_loan = loan
    assert tasks(value)["check_loan"].status == status
    assert tasks(value)["notify_landlord"].status == "NOT_STARTED"


@pytest.mark.parametrize("contracts,status", [(True, "NOT_STARTED"), (False, "NOT_STARTED"), (None, "NEEDS_CONFIRMATION")])
def test_rental_and_utilities_remain_without_service_contracts(contracts, status):
    value = request()
    value.has_service_contracts = contracts
    task = tasks(value)["terminate_contracts"]
    assert task.status == status and "렌탈·공과금" in task.title
    if contracts is False:
        assert "배달앱" not in task.title


@pytest.mark.parametrize("field,bad", [("has_business_loan", 0), ("has_service_contracts", "false"), ("restoration_clause", "NO")])
def test_pr119_inputs_reject_coercion_and_old_draft_names(field, bad):
    with pytest.raises(ValidationError):
        RoadmapInput.model_validate(request().model_dump() | {field: bad})


def test_no_clause_does_not_establish_no_restoration_or_demolition():
    value = request(restoration_scope=None, demolition_required=None)
    value.restoration_clause = "NOT_EXISTS"
    view = tasks(value)
    assert view["restoration"].status != "NOT_APPLICABLE"
    assert view["support_application"].status == "NEEDS_CONFIRMATION"


def test_owned_and_no_current_staff_do_not_erase_past_employment_procedures():
    view = tasks(request(lease_status="OWNED", employee_count=0, had_employees=True))
    assert view["notify_landlord"].status == view["deposit_settlement"].status == "NOT_APPLICABLE"
    assert view["notify_employees"].status == "NOT_APPLICABLE"
    assert view["employee_payments"].status == "NOT_STARTED"
    assert view["employee_insurance"].status == "NOT_STARTED"


@pytest.mark.parametrize("task_id,codes", [
    ("closure_submission", ("FILE_TAX_BUSINESS_CLOSURE", "FILE_FOOD_SERVICE_CLOSURE")),
    ("employee_insurance", ("REPORT_EMPLOYEE_INSURANCE_LOSS", "REPORT_WORKPLACE_INSURANCE_CLOSURE")),
])
def test_grouped_rows_require_every_applicable_procedure(task_id, codes):
    value = request()
    progress(value, codes[0])
    assert tasks(value)[task_id].status == "IN_PROGRESS"
    progress(value, codes[1])
    assert tasks(value)[task_id].status == "COMPLETED"


def test_submission_is_not_completion_and_checklists_cannot_complete_procedures():
    value = request()
    progress(value, "FILE_TAX_BUSINESS_CLOSURE", "IN_PROGRESS", submitted=True)
    assert tasks(value)["closure_submission"].status == "IN_PROGRESS"
    for task_id in ["restoration", "closure_submission", "document_check", "unknown"]:
        with pytest.raises(ValueError):
            record_checklist(value, task_id, completed=True)
    with pytest.raises(ValueError):
        record_checklist(value, "check_loan", completed=True)


def test_work_completion_does_not_invent_document_receipt_or_deposit_settlement():
    value = request()
    progress(value, "PERFORM_RESTORATION")
    progress(value, "RETURN_PREMISES")
    view = tasks(value)
    assert view["restoration_work"].status == view["return_premises"].status == "COMPLETED"
    assert view["contractor_documents"].status == view["deposit_settlement"].status == "NOT_STARTED"


@pytest.mark.parametrize("approved,status", [(None, "NEEDS_CONFIRMATION"), (False, "NOT_APPLICABLE"), (True, "NOT_STARTED")])
def test_reported_agency_decision_controls_settlement_not_submission(approved, status):
    value = request()
    value.support_approved = approved
    view = tasks(value)
    assert view["settlement_submission"].status == status
    assert view["support_application"].status == "NOT_STARTED"
    assert view["support_approval"].status == ("NEEDS_CONFIRMATION" if approved is None else "COMPLETED")


def test_missing_registry_does_not_mark_official_procedures_inapplicable():
    value = request()
    value.known_procedure_steps = []
    assert tasks(value)["closure_submission"].status == "NEEDS_CONFIRMATION"


@pytest.mark.parametrize("facts", [
    {"business_type": "RESTAURANT"}, {"franchise_status": True}, {"business_type": "개인 카페"},
])
def test_unsupported_business_returns_explicit_result_and_cannot_record_checklists(facts):
    value = request(**facts)
    original = value.model_dump_json()
    view = build_roadmap(value)
    assert view.supported is False and "개인 카페" in view.unsupported_reason
    assert (view.case_id, view.snapshot_id) == (value.case_snapshot.case_id, value.case_snapshot.snapshot_id)
    assert view.stages == view.questions_for_user == []
    assert view.next_action is None and view.next_task_id is None
    assert type(view).model_validate_json(view.model_dump_json()) == view
    with pytest.raises(ValueError, match="개인 카페"):
        record_checklist(value, "dispose_stock", completed=True)
    assert value.model_dump_json() == original


@pytest.mark.parametrize("field", ["business_type", "franchise_status", "lease_status"])
def test_unsupported_result_does_not_relax_required_onboarding_facts(field):
    with pytest.raises(ValidationError):
        request(**{field: None})


@pytest.mark.parametrize("count,insured,history,expected", [
    (2, None, None, (5, 0, 3)), (0, None, None, (4, 0, 4)),
    (0, False, None, (4, 2, 2)), (0, False, False, (4, 3, 1)),
    (2, True, None, (7, 0, 1)),
])
def test_pr119_onboarding_history_reproduces_all_five_agreed_applicability_rows(count, insured, history, expected):
    value = request(
        employee_count=count, had_employees=history, restoration_scope=None, demolition_required=None,
        pension_enrolled=insured, health_insurance_enrolled=insured,
        employment_insurance_enrolled=insured, industrial_accident_insurance_enrolled=insured,
    )
    states = [procedure_applicability(step, value.case_snapshot, []) for step in value.known_procedure_steps]
    assert tuple(states.count(state) for state in (True, False, None)) == expected
    view = tasks(value)
    assert view["employee_insurance"].status == (
        "NOT_APPLICABLE" if insured is False else "NEEDS_CONFIRMATION" if insured is None else "NOT_STARTED"
    )


def test_partial_insurance_answer_stays_unknown_even_without_current_staff():
    view = tasks(request(
        employee_count=0, had_employees=None, pension_enrolled=False,
        health_insurance_enrolled=None, employment_insurance_enrolled=None,
        industrial_accident_insurance_enrolled=None,
    ))
    assert view["employee_insurance"].status == view["employee_payments"].status == "NEEDS_CONFIRMATION"


def test_roadmap_import_and_checklists_work_without_optional_pdf_dependency():
    script = """
import importlib.abc
import sys

class NoPDF(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pymupdf', 'fitz'}:
            raise ModuleNotFoundError('optional PDF dependency deliberately unavailable')

sys.meta_path.insert(0, NoPDF())
sys.path.insert(0, '.')
from app.agent.roadmap import RoadmapInput, build_roadmap, record_checklist

context = RoadmapInput.model_validate_json(sys.stdin.read())
assert build_roadmap(context).supported
context = record_checklist(context, 'dispose_stock', completed=True)
assert 'dispose_stock' in context.completed_checklists
assert 'app.agent.document_tool.checks' not in sys.modules
assert 'app.agent.document_tool.documents' not in sys.modules
"""
    subprocess.run(
        [sys.executable, "-c", script], input=request().model_dump_json(), text=True,
        cwd=Path(__file__).resolve().parents[1], capture_output=True, check=True,
    )


def test_caller_procedure_bindings_use_db_references_without_name_guessing():
    value = request()
    bindings = {}
    for i, step in enumerate(value.known_procedure_steps, 1):
        logical = step.procedure_step.step_code
        step.procedure_step.step_code = f"DB_{i}"
        bindings[logical] = step.procedure_step
    assert tasks(value)["closure_submission"].status == "NEEDS_CONFIRMATION"
    view = build_roadmap(value, procedure_bindings=bindings)
    task = next(t for s in view.stages for t in s.tasks if t.task_id == "closure_submission")
    assert task.status == "NOT_STARTED" and len(task.procedure_steps) == 2


def test_existing_reviewed_plan_is_required_and_bound_to_same_snapshot():
    graph, planning_input, *_ = graph_run_inputs("CASE_CREATED")
    outcome = asyncio.run(graph.run(planning_input))
    value = RoadmapInput(case_snapshot=planning_input.case_snapshot, reviewed_plan=outcome)
    view = build_roadmap(value)
    assert view.next_action == outcome.review_subject.supervisor_draft.decision.next_action
    assert view.next_action.action_code == "CONFIRM_TAX_CLOSURE_REQUIREMENTS"
    assert view.next_task_id == "closure_submission"
    value.case_snapshot.snapshot_id = uuid4()
    with pytest.raises(ValueError, match="stale"):
        build_roadmap(value)


def test_reviewed_fact_changes_are_projected_without_committing_them():
    graph, planning_input, *_ = batch_conflict_graph((False, True))
    outcome = asyncio.run(graph.run(planning_input))
    value = RoadmapInput(case_snapshot=outcome.review_subject.snapshot, reviewed_plan=outcome)
    original = value.model_dump_json()
    assert tasks(value)["notify_landlord"].status == "NOT_STARTED"
    assert next(f.value for f in value.case_snapshot.facts if f.field_path == "lease_status") == "OWNED"
    assert value.model_dump_json() == original


def test_completed_case_can_be_read_without_relaxing_agent_judgment_input():
    data = request().model_dump(mode="python")
    data["case_snapshot"]["case_status"] = "COMPLETED"
    with pytest.raises(ValidationError):
        CaseSnapshot.model_validate(data["case_snapshot"])
    value = RoadmapInput.model_validate(data)
    view = build_roadmap(value)
    assert view.next_action is None and len(view.stages) == 5
    assert tasks(value)["income_tax"].status == "NOT_STARTED"


def test_unreviewed_or_changed_review_packages_are_rejected():
    graph, planning_input, *_ = graph_run_inputs("CASE_CREATED")
    outcome = asyncio.run(graph.run(planning_input))
    with pytest.raises(ValidationError):
        RoadmapInput(case_snapshot=planning_input.case_snapshot, reviewed_plan=outcome.review_subject.supervisor_draft)
    value = RoadmapInput(case_snapshot=planning_input.case_snapshot, reviewed_plan=outcome)
    value.known_procedure_steps = request().known_procedure_steps
    with pytest.raises(ValueError, match="registry"):
        build_roadmap(value)
    value.known_procedure_steps = []
    value.reviewed_plan.review_proof.reviewed_subject_digest = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="proof"):
        build_roadmap(value)


def test_document_tool_missing_added_stale_and_removed_results_are_reused(tmp_path):
    async def run():
        client = DocumentClient()
        service = DocumentService(tmp_path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")
        tool = DocumentTool(service)
        documents = await settlement_context(service, transfer=False)
        documents = tool.check_documents(documents)
        value = request()
        value.support_approved, value.documents = True, documents
        calls = len(client.calls)
        assert tasks(value)["document_check"].status == "NEEDS_CONFIRMATION"
        assert len(client.calls) == calls
        documents = await tool.add_document(documents, "transfer.pdf", document_pdf(
            DocumentKind.TRANSFER, amount="3,300,000원", sender="김리본", recipient="그린철거"))
        value.documents = tool.check_documents(documents)
        assert value.documents.document_check.status == "COMPLETE"
        calls = len(client.calls)
        assert tasks(value)["document_check"].status == "COMPLETED"
        assert len(client.calls) == calls
        value.documents.business_name = "바뀐 상호"
        assert tasks(value)["document_check"].status == "NEEDS_CONFIRMATION"
        value.documents = tool.remove_document(documents, documents.documents[-1].document_id)
        assert tasks(value)["document_check"].status == "NOT_STARTED"
        assert tasks(value)["settlement_submission"].status == "NOT_STARTED"
    asyncio.run(run())
