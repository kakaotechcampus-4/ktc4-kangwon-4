"""Reporting regressions using synthetic decisions; no provider or database calls."""

import hashlib
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from app.agent.schemas import ActionDecisionDraft, Blocker
from scripts.evaluate_planning import (
    CASES,
    FIXED_TIME,
    build_case_snapshot,
    decision_summary,
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
                mutations=SimpleNamespace(fact_changes=[]),
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


def test_intake_snapshot_uses_a_db_compatible_evidence_hash():
    snapshot, text = build_case_snapshot(CASES["benchmark_case1"])

    assert snapshot.evidence_records[0].content_hash == hashlib.sha256(text.encode()).hexdigest()
