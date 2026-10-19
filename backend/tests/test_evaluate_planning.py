"""Reporting regressions using synthetic decisions; no provider or database calls."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from app.agent.graph import AgentGraph
from app.agent.procedure_tool.stored_tool import StoredProcedureLookupTool
from app.agent.schemas import ActionDecisionDraft, Blocker, ProcedureLookupInput
from scripts.evaluate_planning import (
    CASES,
    FIXED_TIME,
    SnapshotStore,
    attach_fixture_sources,
    build_case_snapshot,
    build_graph_input,
    decision_summary,
    overall_verdict,
    score,
    verdict,
)


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
    store = SnapshotStore(Path("app/common/reviewed-procedures.ko-KR.json"))
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
