"""Progress cannot prove a different step or an unknown insurance aggregate."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from test_action_codes import NOW, REF, evidence, finding, procedure_sources
from test_cafe_procedures import case, steps

from app.agent.blocker_candidates import build_blocker_candidates
from app.agent.procedure_tool.rules import (
    procedure_constraints,
    procedure_plan_constraints,
)
from app.agent.schemas import (
    MutationSet,
    ProcedureProgress,
    ProcedureProgressChangeCandidate,
)


@pytest.mark.parametrize("status", ["IN_PROGRESS", "COMPLETED"])
def test_aggregate_insurance_needs_each_enrollment_history_before_submitting_or_completing(status):
    registry = steps()
    step = next(item for item in registry if item.procedure_step.step_code == "REPORT_WORKPLACE_INSURANCE_CLOSURE")
    mutation = ProcedureProgressChangeCandidate(
        candidate_id=UUID(int=950), procedure_step=step.procedure_step,
        before_status="NOT_STARTED", proposed_status=status, proposed_submitted=True,
        reason_summary="합성 처리 보고", execution_evidence_refs=[REF],
        procedure_analysis_call_id=UUID(int=951),
    )
    mutations = MutationSet(fact_changes=[], procedure_progress_changes=[mutation], support_match_updates=[])
    unknown = case(pension_enrolled=True)
    violations = procedure_plan_constraints(registry, unknown, mutations, SimpleNamespace(next_action=None))
    assert any("all four enrollment histories" in reason for _, reason in violations)
    known = case(pension_enrolled=True, health_insurance_enrolled=False,
                 employment_insurance_enrolled=False, industrial_accident_insurance_enrolled=False)
    assert procedure_plan_constraints(registry, known, mutations, SimpleNamespace(next_action=None)) == []


def test_wrong_code_with_the_same_id_cannot_satisfy_a_restoration_prerequisite():
    registry = steps()
    work = next(item for item in registry if item.procedure_step.step_code == "PERFORM_RESTORATION")
    returned = next(item for item in registry if item.procedure_step.step_code == "RETURN_PREMISES")
    snapshot = case(lease_status="LEASED_PAID", restoration_scope="FULL", demolition_required="REQUIRED")
    snapshot.procedure_progress = [ProcedureProgress(
        procedure_step=work.procedure_step.model_copy(update={"step_code": "WRONG_CODE"}),
        status="COMPLETED", evidence_refs=[REF], updated_at=NOW,
    )]
    assert procedure_constraints(returned, snapshot, known_steps=registry)
    snapshot.procedure_progress[0].procedure_step = work.procedure_step
    assert procedure_constraints(returned, snapshot, known_steps=registry) == []


@pytest.mark.parametrize("all_known", [False, True])
@pytest.mark.parametrize("requires_confirmation", [False, True])
@pytest.mark.parametrize("logical,confirmation_code", [
    ("REPORT_WORKPLACE_INSURANCE_CLOSURE", "CONFIRM_WORKPLACE_INSURANCE_CLOSURE_REQUIREMENTS"),
    ("REPORT_EMPLOYEE_INSURANCE_LOSS", "CONFIRM_EMPLOYEE_INSURANCE_LOSS_REQUIREMENTS"),
])
def test_insurance_execution_needs_all_histories_but_requirements_checks_remain_valid(
    all_known, requires_confirmation, logical, confirmation_code,
):
    registry = steps()
    target = next(item for item in registry if item.procedure_step.step_code == logical)
    staff_loss = next(item for item in registry
                     if item.procedure_step.step_code == "REPORT_EMPLOYEE_INSURANCE_LOSS")
    known = {"had_employees": True, "pension_enrolled": True}
    if all_known:
        known.update(health_insurance_enrolled=False, employment_insurance_enrolled=False,
                     industrial_accident_insurance_enrolled=False)
    snapshot = case(**known)
    snapshot.procedure_progress = [ProcedureProgress(
        procedure_step=staff_loss.procedure_step, status="COMPLETED",
        evidence_refs=[REF], updated_at=NOW,
    )] if logical == "REPORT_WORKPLACE_INSURANCE_CLOSURE" else []
    sources = procedure_sources(finding(
        procedure_step=target.procedure_step, requires_confirmation=requires_confirmation,
    ))
    candidates = build_blocker_candidates(
        snapshot, registry, sources,
        MutationSet(fact_changes=[], procedure_progress_changes=[], support_match_updates=[]),
        {REF: evidence()},
    )
    actions = [action["action_code"] for row in candidates for action in row["actions"]]
    assert actions == (
        [confirmation_code] if requires_confirmation
        else [logical] if all_known else []
    )
