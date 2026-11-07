"""Reporting regressions using synthetic decisions; no provider or database calls."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.agent.graph import AgentGraph
from app.agent.procedure_tool.stored_tool import StoredProcedureLookupTool
from app.agent.schemas import (
    ActionDecisionDraft,
    Blocker,
    FactChangeCandidate,
    ProcedureLookupInput,
    ReviewResult,
)
from scripts.evaluate_planning import (
    CASES,
    FIXED_TIME,
    SnapshotStore,
    attach_fixture_sources,
    build_case_snapshot,
    build_graph_input,
    build_registry,
    decision_summary,
    load_dataset,
    metrics_by_case,
    overall_verdict,
    review_metadata,
    score,
    verdict,
)


def test_shared_official_documents_create_one_registry_entry_per_procedure():
    records = [
        SimpleNamespace(step_codes=["FILE_TAX_BUSINESS_CLOSURE"], title="합성 자료 1"),
        SimpleNamespace(step_codes=["FILE_TAX_BUSINESS_CLOSURE", "FILE_FOOD_SERVICE_CLOSURE"], title="합성 자료 2"),
        SimpleNamespace(step_codes=["PERFORM_RESTORATION", "RETURN_PREMISES"], title="합성 자료 3"),
    ]
    registry = build_registry(SimpleNamespace(records=lambda: records))
    assert [step.procedure_step.step_code for step in registry] == [
        "FILE_TAX_BUSINESS_CLOSURE", "FILE_FOOD_SERVICE_CLOSURE",
        "PERFORM_RESTORATION", "RETURN_PREMISES",
    ]
    assert len({step.procedure_step.procedure_step_id for step in registry}) == 4
    assert len({step.step_name for step in registry}) == 4
    names = [name for step in registry for name in (step.step_name, *step.utterance_aliases)]
    assert len(set(names)) == len(names)


def summary(blocker):
    decision = ActionDecisionDraft(
        decision_type="ACTION",
        draft_id=UUID(int=1),
        draft_version=1,
        selection_summary="확인된 합성 절차 진행",
        requires_human=False,
        evidence_refs=["synthetic-evidence"],
        based_on_call_ids=[UUID(int=2)],
        created_at=FIXED_TIME,
        blocker=blocker,
        next_action={
            "action_code": "FILE_TAX_BUSINESS_CLOSURE",
            "sequence": 1,
            "title": "합성 절차 진행",
            "reason": "합성 자료에서 확인한 절차",
            "questions_to_ask": [],
            "target": {
                "target_kind": "PROCEDURE",
                "procedure_step": {
                    "procedure_step_id": 1,
                    "step_code": "FILE_TAX_BUSINESS_CLOSURE",
                },
            },
            "evidence_refs": ["synthetic-evidence"],
        },
        questions_for_user=[],
    )
    # The report reads a reviewed outcome; proof validation belongs to the runtime.
    outcome = SimpleNamespace(
        outcome_type="REVIEWED_PLAN",
        review_subject=SimpleNamespace(
            review_attempt=1,
            supervisor_draft=SimpleNamespace(
                decision=decision,
                mutations=SimpleNamespace(fact_changes=[], procedure_progress_changes=[]),
            ),
        ),
    )
    return decision_summary(outcome)


def test_action_with_one_blocker_remains_reportable():
    report = json.loads(json.dumps(summary(
        Blocker(description="합성 조건 미충족", evidence_refs=["synthetic-evidence"])
    )))

    assert report["blocker"] == "합성 조건 미충족"
    assert report["blocker_digest"] is not None
    assert report["action_code"] == "FILE_TAX_BUSINESS_CLOSURE"
    assert report["next_action_digest"] is not None


@pytest.mark.parametrize("same_blocker", [False, True])
def test_comparison_distinguishes_different_blockers(same_blocker):
    first = Blocker(description="합성 조건 미충족", evidence_refs=["synthetic-evidence"])
    second = Blocker(
        description="합성 조건 미충족" if same_blocker else "다른 합성 조건 미충족",
        evidence_refs=["synthetic-evidence"],
    )
    rows = [
        {
            "status": "REVIEWED_PLAN",
            "graph_input_digest": "synthetic-input",
            "calls_by_role": {"supervisor": 1},
            **summary(item),
        }
        for item in (first, second)
    ]

    result = verdict(rows)

    assert result["same_blocker"] is same_blocker
    assert result["same_next_action"] is True
    assert result["reliability"] == "PASS"
    assert result["verdict"] == ("PASS" if same_blocker else "FAIL")


def test_blocker_comparison_ignores_per_run_evidence_ids():
    first = summary(Blocker(description="합성 조건 미충족", evidence_refs=["run-one"]))
    second = summary(Blocker(description="합성 조건 미충족", evidence_refs=["run-two"]))

    assert first["blocker"] == "합성 조건 미충족"
    assert first["blocker_digest"] == second["blocker_digest"]


def test_prior_facts_are_confirmed_with_their_own_evidence():
    snapshot, _ = build_case_snapshot(
        CASES["benchmark_case1"], {"demolition_required": "REQUIRED", "restoration_scope": None}
    )
    facts = {fact.field_path.value: fact for fact in snapshot.facts}

    assert facts["demolition_required"].status == "CONFIRMED"
    assert facts["demolition_required"].evidence_refs == ["synthetic-prior-result-input"]
    assert facts["restoration_scope"].status == "UNKNOWN"
    assert facts["lease_status"].evidence_refs == ["synthetic-fe-case-input"]


def row(branch="REPLAN_OR_NEEDS_MORE_INFO", changes=None, must_not=()):
    return {
        "expected_branch": branch,
        "expected_fact_changes": changes or {},
        "must_not": list(must_not),
    }


def plan(*changes):
    return {
        "status": "REVIEWED_PLAN",
        "fact_changes": [{"field_path": f, "proposed_value": v} for f, v in changes],
        "procedure_progress_changes": [],
    }


@pytest.mark.parametrize(
    ("expected", "result", "verdict_"),
    [
        (row(changes={"demolition_required": "REQUIRED"}),
         plan(("demolition_required", "REQUIRED")), "PASS"),
        # An unexpected scored change is the silent overwrite this product must not do.
        (row(changes={"demolition_required": "REQUIRED"}),
         plan(("demolition_required", "REQUIRED"), ("restoration_scope", "FULL")), "WRONG"),
        (row(branch="CONFLICT"), plan(), "WRONG"),
        (row(branch="CONFLICT"), {"status": "CONFLICT"}, "PASS"),
        (row(), {"status": "CONFLICT"}, "WRONG"),
        (row(), {"status": "SAFE_FAILURE", "failure_code": "PROVIDER_UNAVAILABLE"}, "RUN_FAILED"),
    ],
)
def test_score_follows_the_agreed_rule(expected, result, verdict_):
    assert score(expected, result)["result"] == verdict_


def test_free_text_detail_is_recorded_not_scored():
    result = score(row(changes={"restoration_scope": "PARTIAL"}),
                   plan(("restoration_scope", "PARTIAL"), ("restoration_scope_detail", "바닥만")))

    assert result["result"] == "PASS"
    assert result["detail_changed"] is True


def test_state_checked_must_not_fails_and_text_ones_go_to_a_person():
    result = score(
        row(must_not=["PLANNED_CLOSURE_DATE_CHANGED", "SILENT_FACT_OVERWRITE", "FABRICATED_EVIDENCE"]),
        plan(("planned_closure_date", "2026-11-10")),
    )

    assert result["result"] == "WRONG"
    assert result["human_check"] == ["FABRICATED_EVIDENCE"]


def test_a_wrong_dataset_row_fails_the_run_even_if_repeats_agree():
    per_case = {"G01": {"verdict": "PASS"}}
    wrong = [{"score": {"result": "WRONG"}}]
    passed = [{"score": {"result": "PASS"}}]

    assert overall_verdict(per_case, wrong) == "FAIL"
    assert overall_verdict(per_case, passed) == "PASS"
    assert overall_verdict(per_case, None) == "PASS"


def test_fixture_inputs_carry_the_reviewed_sources_the_lookup_accepts():
    store = SnapshotStore(
        Path(__file__).resolve().parents[1] / "app/common/reviewed-procedures.ko-KR.json"
    )
    request = attach_fixture_sources(build_graph_input(CASES["benchmark_case1"]), store)

    def found(graph_input):
        lookup = ProcedureLookupInput(
            lookup_goal="BUSINESS_CLOSURE",
            evidence_records=[item for item in graph_input.case_snapshot.evidence_records
                              if item.source_type == "OFFICIAL_DOCUMENT"],
            search_queries=AgentGraph._procedure_queries(graph_input),
            as_of=FIXED_TIME.date(), locale="ko-KR",
            source_policy="OFFICIAL_ONLY", max_results_per_query=5,
            based_on_snapshot_id=graph_input.case_snapshot.snapshot_id, review_feedback=[],
        )
        return asyncio.run(StoredProcedureLookupTool(store).lookup(lookup)).evidence_records

    # Without the sources the lookup returns nothing, which left Info with no findings.
    assert found(build_graph_input(CASES["benchmark_case1"])) == []
    assert found(request) != []
    # Attaching twice does not duplicate a source.
    assert attach_fixture_sources(request, store) == request


@pytest.mark.parametrize(("status", "error", "expected"), [
    ("REVIEWED_PLAN", False, "PASS"), ("SAFE_FAILURE", False, "FAIL"),
    ("ERROR", True, "FAIL"), ("REVIEWED_PLAN", True, "FAIL"),
])
def test_zero_provider_calls_do_not_replace_outcome_validation(status, error, expected):
    item = {"status": status, "graph_input_digest": "same-input", "calls_by_role": {}}
    if error:
        item["error"] = {"code": "SYNTHETIC_FAILURE"}
    assert verdict([item, dict(item)])["verdict"] == expected
    assert item["calls_by_role"] == {}


@pytest.mark.parametrize("expected", [False, True])
def test_only_expected_dataset_conflicts_pass_and_count_as_successful(expected):
    item = {"status": "CONFLICT", "case": "conflict", "graph_input_digest": "same",
            "score": {"result": "PASS" if expected else "WRONG"},
            "calls_by_role": {}, "provider_usage": []}
    per_case = {"conflict": verdict([item])}
    assert overall_verdict(per_case, [item]) == ("PASS" if expected else "FAIL")
    assert per_case["conflict"]["all_reviewed_plan"] is False
    assert metrics_by_case([item], {})["conflict"]["successful_runs"] == int(expected)


def test_metrics_keep_different_cases_separate_without_hiding_failures():
    base = {
        "status": "REVIEWED_PLAN", "calls_by_role": {"all": 1},
        "provider_usage": [{"requested_model": "synthetic", "prompt_tokens": 100,
                            "completion_tokens": 20, "cached_prompt_tokens": 0}],
    }
    rows = [
        {**base, "case": "A", "elapsed_ms": 10},
        {**base, "case": "A", "elapsed_ms": 30, "score": {"result": "WRONG"}},
        {**base, "case": "B", "elapsed_ms": 1000},
    ]
    report = metrics_by_case(rows, {"synthetic": (1000, 0, 1000)})
    assert report["A"]["runs"] == 2 and report["B"]["runs"] == 1
    assert report["A"]["median_latency_ms"] == 20
    assert report["A"]["p95_latency_ms"] == 30 and report["B"]["p95_latency_ms"] == 1000
    assert report["A"]["successful_runs"] == 1
    assert report["A"]["cost_per_success_krw"] == pytest.approx(0.24)
    assert "behavior_passed" not in rows[1]


INPUTS = Path(__file__).resolve().parents[2] / "docs/agent/evaluations/2026-11-07-planning-inputs.jsonl"
HELD_OUT = INPUTS.with_name("2026-11-07-planning-held-out.jsonl")


def test_frozen_planning_inputs_keep_held_out_cases_separate_and_cover_the_buttons():
    main, held_out = load_dataset(INPUTS), load_dataset(HELD_OUT)
    assert len(main) == 20 and len(held_out) == 4 and not main.keys() & held_out.keys()
    answers = [request.trigger.restoration_answer for request, _ in main.values()
               if request.trigger.restoration_answer is not None]
    assert {(answer.restoration_scope, answer.demolition_required) for answer in answers} == {
        (scope, demolition) for scope in ("FULL", "PARTIAL", "NOT_REQUIRED", "UNKNOWN")
        for demolition in ("REQUIRED", "NOT_REQUIRED", "UNKNOWN")
    }
    assert all(row["expected_action_codes"] and row["forbidden_fact_changes"]
               for _, row in [*main.values(), *held_out.values()])


@pytest.mark.parametrize("broken", ["action", "question", "mutation"])
def test_frozen_partial_answer_expectations_fail_if_a_required_boundary_is_broken(broken):
    _, expected = load_dataset(INPUTS)["S04"]
    result = {**plan(("restoration_scope", "PARTIAL"), ("demolition_required", "REQUIRED")),
              "decision_type": "NEEDS_MORE_INFO", "action_code": None,
              "questions_for_user": ["확인한 원상복구 범위의 구체적인 내용을 알려주세요."]}
    assert score(expected, result)["result"] == "PASS"
    if broken == "action":
        result.update(decision_type="ACTION", action_code="PERFORM_RESTORATION")
    elif broken == "question":
        result["questions_for_user"] = []
    else:
        result["fact_changes"].append({"field_path": "restoration_scope_detail", "proposed_value": "바닥"})
    assert score(expected, result)["result"] == "WRONG"


def test_frozen_correction_requires_the_expected_conflict_field():
    _, expected = load_dataset(INPUTS)["F05"]
    result = {"status": "CONFLICT", "conflicts": [{"field_path": "restoration_scope"}]}
    assert score(expected, result)["result"] == "PASS"
    result["conflicts"] = [{"field_path": "demolition_required"}]
    assert score(expected, result)["result"] == "WRONG"


def test_structured_dataset_rejects_text_that_disagrees_with_the_selected_values(tmp_path):
    data = json.loads(INPUTS.read_text().splitlines()[0])
    data["raw_input"] = "선택한 값과 다른 글"
    path = tmp_path / "mismatch.jsonl"
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n")
    with pytest.raises(ValueError):
        load_dataset(path)


def test_contradictory_scope_can_also_ask_about_the_still_unknown_demolition():
    _, expected = load_dataset(INPUTS)["F04"]
    result = {**plan(), "decision_type": "NEEDS_MORE_INFO", "action_code": None,
              "questions_for_user": ["확인한 원상복구 범위가 있으면 알려주세요.", "철거가 필요한가요?"]}
    assert score(expected, result)["result"] == "PASS"
    result["fact_changes"] = [{"field_path": "restoration_scope", "proposed_value": "FULL"}]
    assert score(expected, result)["result"] == "WRONG"


@pytest.mark.parametrize("broken", ["omitted", "status", "submitted"])
def test_submission_is_not_completion_checks_the_recorded_progress_and_submission(broken):
    _, expected = load_dataset(INPUTS)["F06"]
    progress = {"step_code": "FILE_TAX_BUSINESS_CLOSURE", "proposed_status": "IN_PROGRESS",
                "proposed_submitted": True}
    result = {**plan(), "action_code": "CONFIRM_PROCEDURE_COMPLETION",
              "procedure_progress_changes": [progress]}
    assert score(expected, result)["result"] == "PASS"
    if broken == "omitted":
        result["procedure_progress_changes"] = []
    elif broken == "status":
        progress["proposed_status"] = "COMPLETED"
    else:
        progress["proposed_submitted"] = False
    assert score(expected, result)["result"] == "WRONG"


@pytest.mark.parametrize("action_code", [None, "CONFIRM_RESTORATION_SCOPE"])
def test_review_metadata_preserves_failure_location_without_copying_private_free_text(action_code):
    private = "synthetic-private-note@example.test"
    target_path = ("/supervisor_draft/decision/questions_for_user/0" if action_code is None
                   else "/supervisor_draft/decision/next_action/title")
    reviewed = ReviewResult(
        reviewed_subject_id=UUID(int=1), reviewed_subject_digest="sha256:" + "0" * 64,
        verdict="REVISE", issues=[{
            "issue_code": "CASE_MISMATCH", "category": "FACTUALITY", "severity": "BLOCKING",
            "target_component": "SUPERVISOR", "target_call_id": None,
            "target_path": target_path,
            "reason_summary": private, "evidence_refs": ["synthetic-evidence"],
        }], missing_evidence=[], recommended_rework_targets=["SUPERVISOR"], resolution_reason=private,
    )
    changes = [FactChangeCandidate(
        candidate_id=UUID(int=index + 1), operation="SET", source_fact_candidate_id=UUID(int=10),
        source_type="INFO_ANALYSIS", field_path=field, value_type=kind, before_status="UNKNOWN",
        before_value=None, proposed_status="CONFIRMED", proposed_value=value,
        candidate_status="READY_FOR_REVIEW", reason_summary=private,
        source_evidence_refs=["synthetic-evidence"], source_call_id=UUID(int=20), confirmed_conflict_ref=None,
    ) for index, (field, kind, value) in enumerate([
        ("restoration_scope", "ENUM", "NOT_REQUIRED"), ("pension_enrolled", "BOOLEAN", False),
        ("employee_count", "INTEGER", 2), ("restoration_scope_detail", "STRING", private),
        ("planned_closure_date", "DATE", "2026-11-30"),
    ])]
    subject = SimpleNamespace(review_attempt=2, supervisor_draft=SimpleNamespace(decision=SimpleNamespace(
        decision_type="NEEDS_MORE_INFO" if action_code is None else "ACTION",
        next_action=None if action_code is None else SimpleNamespace(action_code=action_code, title=private),
        questions_for_user=[private] if action_code is None else [],
    ), mutations=SimpleNamespace(fact_changes=changes)))
    report = review_metadata(subject, reviewed)
    assert report["review_attempt"] == 2 and report["draft_action_code"] == action_code
    assert report["issues"] == [{"issue_code": "CASE_MISMATCH", "severity": "BLOCKING",
                                  "target_component": "SUPERVISOR",
                                  "target_path": target_path}]
    assert report["recommended_rework_targets"] == ["SUPERVISOR"]
    assert report["issue_codes"] == ["CASE_MISMATCH"] and report["verdict"] == "REVISE"
    assert [change.get("proposed_value") for change in report["draft_fact_changes"][:3]] == ["NOT_REQUIRED", False, 2]
    assert all("proposed_value" not in change for change in report["draft_fact_changes"][3:])
    assert [change["field_path"] for change in report["draft_fact_changes"]][-2:] == [
        "restoration_scope_detail", "planned_closure_date",
    ]
    assert private not in json.dumps(report)
