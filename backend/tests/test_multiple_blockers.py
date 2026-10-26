"""Multiple priorities and resolution proofs on the existing four-step contract."""

import asyncio

import pytest
from pydantic import ValidationError
from test_action_codes import NOW, REF
from test_blocker_candidates import (
    ChoiceModel,
    candidates,
    missing_questions,
    mutations,
    request_with_all_closure_steps,
    request_with_state,
    subject,
)
from test_procedure_only_graph import graph_run_inputs

from app.agent.action_catalog import resolve_procedure_bindings
from app.agent.blocker_candidates import resolved_blocker_candidates
from app.agent.guardrails import GuardrailViolation
from app.agent.projection import ensure_projection_has_no_obvious_sensitive_text
from app.agent.review_tool import ReviewTool
from app.agent.schemas import ActionDecisionDraft, CaseFact, ProcedureProgress
from app.agent.supervisor.agent import SupervisorAgent, SupervisorGuardrailError


def test_all_valid_blockers_survive_each_model_priority_choice():
    async def run():
        request = request_with_all_closure_steps(demolition_required="REQUIRED")
        expected = {item["candidate_id"] for item in candidates(request)}
        priorities = set()
        for index in range(len(expected)):
            draft = await SupervisorAgent(ChoiceModel(choice=index), max_local_attempts=1).draft(request)
            assert {item.candidate_id for item in draft.decision.blockers} == expected
            assert draft.decision.blocker in draft.decision.blockers
            priorities.add(draft.decision.blocker.candidate_id)
            assert (await ReviewTool(ChoiceModel()).review(subject(request, draft))).verdict == "PASS"
        assert priorities == expected
    asyncio.run(run())


def test_second_information_candidate_can_be_prioritized_with_actions_available():
    async def run():
        request = request_with_state()
        missing_questions(request, "employee_count", "restoration_scope")
        draft = await SupervisorAgent(ChoiceModel(information=True, choice=1), max_local_attempts=1).draft(request)
        assert draft.decision.blocker.candidate_id == "missing:restoration_scope"
        assert draft.decision.next_action is None
        assert {item.candidate_id for item in draft.decision.blockers} == {
            "procedure:1", "procedure:4", "missing:employee_count", "missing:restoration_scope",
        }
        assert (await ReviewTool(ChoiceModel()).review(subject(request, draft))).verdict == "PASS"
    asyncio.run(run())


@pytest.mark.parametrize("problem", ["duplicate", "priority_missing", "empty"])
def test_public_blocker_collection_rejects_invalid_priority_sets(problem):
    async def run():
        request = request_with_state()
        return await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(request)
    decision = asyncio.run(run()).decision
    data = decision.model_dump(mode="json")
    if problem == "duplicate":
        data["blockers"].append(data["blockers"][0])
    elif problem == "priority_missing":
        data["blockers"] = [item for item in data["blockers"] if item != data["blocker"]]
    else:
        data["blockers"] = []
    with pytest.raises(ValidationError):
        ActionDecisionDraft.model_validate(data)
    data.pop("blockers")
    legacy = ActionDecisionDraft.model_validate(data)
    assert legacy.blockers == [legacy.blocker]


def test_review_rejects_an_omitted_secondary_blocker_even_when_model_passes():
    async def run():
        request = request_with_state()
        draft = await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(request)
        draft.decision.blockers = [draft.decision.blocker]
        result = await ReviewTool(ChoiceModel()).review(subject(request, draft))
        assert result.verdict == "REVISE"
        assert any(issue.target_path == "/supervisor_draft/decision/blockers" for issue in result.issues)
    asyncio.run(run())


def test_invalid_model_selection_exhausts_the_bound_without_a_first_candidate():
    async def run():
        model = ChoiceModel(invalid=True)
        with pytest.raises(SupervisorGuardrailError):
            await SupervisorAgent(model, max_local_attempts=3).draft(request_with_state())
        assert model.calls == 3
    asyncio.run(run())


def test_graph_returns_safe_failure_after_invalid_priority_retries():
    graph, request, _, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    model = ChoiceModel(invalid=True)
    graph._supervisor = SupervisorAgent(model, max_local_attempts=3)
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "SAFE_FAILURE", outcome
    assert outcome.failed_component == "SUPERVISOR"
    assert model.calls == 3
    assert graph._review_tool._client.calls == 0


def test_resolution_uses_confirmed_facts_and_exact_procedure_references():
    request = request_with_state(restoration_scope="FULL", demolition_required="NOT_REQUIRED")
    snapshot = request.case_snapshot
    snapshot.active_blocker_candidate_ids = [
        "missing:restoration_scope", "procedure:4", "procedure:1", "procedure:999",
    ]
    bindings = resolve_procedure_bindings(request.known_procedure_steps, None)
    snapshot.procedure_progress = [ProcedureProgress(
        procedure_step={"procedure_step_id": 1, "step_code": "ANOTHER_CODE"},
        status="COMPLETED", evidence_refs=[REF], updated_at=NOW,
    )]
    assert resolved_blocker_candidates(snapshot, request.known_procedure_steps, mutations(), bindings) == [
        "missing:restoration_scope", "procedure:4",
    ]
    snapshot.procedure_progress[0].procedure_step = request.known_procedure_steps[0].procedure_step
    assert resolved_blocker_candidates(snapshot, request.known_procedure_steps, mutations(), bindings) == [
        "missing:restoration_scope", "procedure:4", "procedure:1",
    ]


def test_unknown_eligibility_is_not_a_resolution_but_confirmed_exclusion_is():
    request = request_with_state()
    step = request.known_procedure_steps[0].model_copy(deep=True)
    step.eligibility_conditions = [{"condition_key": "has_employee", "condition_value": "true"}]
    # Revalidate the fixture so it has the same typed registry as production.
    step = type(step).model_validate(step.model_dump())
    snapshot = request.case_snapshot
    snapshot.active_blocker_candidate_ids = ["procedure:1"]
    assert resolved_blocker_candidates(snapshot, [step], mutations(), {}) == []
    snapshot.facts.append(CaseFact(
        field_path="employee_count", value_type="INTEGER", value=0,
        status="CONFIRMED", evidence_refs=[REF], updated_at=NOW,
    ))
    assert resolved_blocker_candidates(snapshot, [step], mutations(), {}) == ["procedure:1"]


@pytest.mark.parametrize("problem", ["unknown", "unsupported", "invalid_boolean", "dependency"])
def test_unknown_invalid_and_dependency_failures_never_prove_exclusion(problem):
    request = request_with_state()
    step = request.known_procedure_steps[0].model_dump()
    if problem == "dependency":
        step["dependencies"] = [{
            "prerequisite_procedure_step_id": 999, "dependency_type": "SEQUENTIAL",
        }]
    else:
        step["eligibility_conditions"] = [{
            "condition_key": "unsupported" if problem == "unsupported" else "has_employee",
            "condition_value": "TRUE" if problem == "invalid_boolean" else "true",
        }]
    step = type(request.known_procedure_steps[0]).model_validate(step)
    request.case_snapshot.active_blocker_candidate_ids = ["procedure:1"]
    assert resolved_blocker_candidates(request.case_snapshot, [step], mutations(), {}) == []


def test_independent_review_rejects_a_fabricated_resolution():
    async def run():
        request = request_with_state()
        request.case_snapshot.active_blocker_candidate_ids = ["procedure:1"]
        draft = await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(request)
        assert draft.resolved_blocker_candidate_ids == []
        draft.resolved_blocker_candidate_ids = ["procedure:1"]
        result = await ReviewTool(ChoiceModel()).review(subject(request, draft))
        assert result.verdict == "REVISE"
        assert any(issue.target_path == "/supervisor_draft/resolved_blocker_candidate_ids" for issue in result.issues)
    asyncio.run(run())


@pytest.mark.parametrize("identifier", [
    "abcde010-1234-4567-abcd-123456abcdef", "ABCDE010-1234-4567-ABCD-123456ABCDEF",
])
def test_phone_shaped_digits_in_a_uuid_do_not_block_a_projection(identifier):
    ensure_projection_has_no_obvious_sensitive_text({
        "lookup_id": identifier, "documents": [{"document_id": identifier}],
        "procedure_findings": [{"finding_id": identifier}],
    })


@pytest.mark.parametrize("text", [
    "010-1234-5678", "연락처는 010-1234-5678입니다.",
    "abcde010-1234-4567-abcd-123456abcdef 연락처 010-1234-5678",
    "식별자 abcde010-1234-4567-abcd-123456abcdef",
    "abcde010-1234-4567-abcd-123456abcdeg",
])
def test_uuid_exception_preserves_phone_checks_in_prose_and_non_uuid_values(text):
    with pytest.raises(GuardrailViolation, match="PHONE_NUMBER"):
        ensure_projection_has_no_obvious_sensitive_text({"text": text})
