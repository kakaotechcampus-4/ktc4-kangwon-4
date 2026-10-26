"""Reporting regressions using synthetic decisions; no provider or database calls."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from app.agent.graph import AgentGraph
from app.agent.procedure_tool.stored_tool import StoredProcedureLookupTool
from app.agent.schemas import (
    ActionDecisionDraft,
    Blocker,
    ProcedureLookupInput,
)
from scripts import evaluate_planning as evaluation
from scripts.evaluate_planning import (
    CASES,
    CORE_EXPECTATIONS,
    FIXED_TIME,
    SnapshotStore,
    attach_fixture_sources,
    build_case_snapshot,
    build_graph_input,
    decision_summary,
    expectation_checks,
    overall_verdict,
    score,
    verdict,
)


def summary(blocker, procedure_changes=()):
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
                mutations=SimpleNamespace(fact_changes=[], procedure_progress_changes=procedure_changes),
            ),
        ),
    )
    return decision_summary(outcome)


def test_action_with_one_blocker_remains_reportable():
    report = json.loads(json.dumps(summary(
        Blocker(description="합성 조건 미충족", evidence_refs=["synthetic-evidence"])
    )))

    assert "합성 조건 미충족" not in json.dumps(report, ensure_ascii=False)
    assert report["blocker_digest"] is not None
    assert report["action_code"] == "FILE_TAX_BUSINESS_CLOSURE"
    assert report["next_action_digest"] is not None


def test_progress_report_keeps_structured_flags_and_action_target_without_prose():
    change = SimpleNamespace(
        candidate_id=UUID(int=3),
        procedure_step=SimpleNamespace(procedure_step_id=2, step_code="FILE_FOOD_SERVICE_CLOSURE"),
        before_status="NOT_STARTED", proposed_status="IN_PROGRESS",
        before_requirements_confirmed=True, proposed_requirements_confirmed=True,
        before_submitted=False, proposed_submitted=True,
        reason_summary="신고서를 제출했지만 처리 완료는 확인하지 않았습니다.",
        execution_evidence_refs=["synthetic-evidence"], procedure_analysis_call_id=UUID(int=4),
    )
    report = summary(Blocker(description="합성", evidence_refs=["synthetic-evidence"]), [change])
    assert report["action_target_step_code"] == "FILE_TAX_BUSINESS_CLOSURE"
    assert report["procedure_changes"] == [{
        "step_code": "FILE_FOOD_SERVICE_CLOSURE",
        "before_status": "NOT_STARTED", "proposed_status": "IN_PROGRESS",
        "before_requirements_confirmed": True, "proposed_requirements_confirmed": True,
        "before_submitted": False, "proposed_submitted": True,
    }]
    assert change.reason_summary not in json.dumps(report, ensure_ascii=False)


def progress_row(case, *, changes, action=None):
    expected = CORE_EXPECTATIONS[case]
    action = action or expected["actions"][0]
    return {
        "status": "REVIEWED_PLAN", "decision_type": "ACTION", "action_code": action,
        "action_target_step_code": expected["action_targets"][action],
        "graph_input_digest": "synthetic:" + case, "calls_by_role": {"shared": 1}, "review_proof_valid": True,
        "fact_changes": [], "procedure_changes": changes,
        "calls": [{"http_status": 200, "schema_name": name, "model": "gpt-6.1-sol",
                   "reasoning_effort": "xhigh", "role": "shared"} for name in (
            "ContentSafetyDecision", "reborn_info_analysis", "reborn_supervisor_draft",
            "reborn_review_output",
        )],
    }


@pytest.mark.parametrize("case,code,status,submitted", [
    ("restoration_work_completed", "PERFORM_RESTORATION", "COMPLETED", False),
    ("administrative_submitted", "FILE_FOOD_SERVICE_CLOSURE", "IN_PROGRESS", True),
    ("employee_partial_processing", "REPORT_EMPLOYEE_INSURANCE_LOSS", "IN_PROGRESS", False),
])
def test_progress_expectations_require_status_submission_and_correct_action_target(case, code, status, submitted):
    change = {
        "step_code": code, "proposed_status": status,
        "proposed_requirements_confirmed": True, "proposed_submitted": submitted,
    }
    row = progress_row(case, changes=[change])
    assert all(expectation_checks(row, CORE_EXPECTATIONS[case]).values())
    row["action_target_step_code"] = "CONFIRM_RESTORATION_SCOPE"
    assert expectation_checks(row, CORE_EXPECTATIONS[case])["expected_action_target"] is False
    row["action_target_step_code"] = CORE_EXPECTATIONS[case]["action_targets"][row["action_code"]]
    change["proposed_submitted"] = not submitted
    assert expectation_checks(row, CORE_EXPECTATIONS[case])["expected_procedure_states"] is False


@pytest.mark.parametrize("case", ["restoration_work_completed", "administrative_submitted"])
def test_a_required_progress_update_cannot_disappear(case):
    row = progress_row(case, changes=[])
    assert expectation_checks(row, CORE_EXPECTATIONS[case])["expected_procedure_states"] is False


@pytest.mark.parametrize("action", CORE_EXPECTATIONS["employee_partial_processing"]["actions"])
def test_partial_employee_processing_can_keep_aggregate_unchanged_and_choose_either_valid_action(action):
    row = progress_row("employee_partial_processing", changes=[], action=action)
    assert all(expectation_checks(row, CORE_EXPECTATIONS["employee_partial_processing"]).values())
    row["decision_type"] = "COMPLETED"
    assert expectation_checks(row, CORE_EXPECTATIONS["employee_partial_processing"])["expected_decision"] is False


@pytest.mark.parametrize("case,code,status,submitted", [
    ("administrative_submitted", "FILE_FOOD_SERVICE_CLOSURE", "COMPLETED", True),
    ("employee_partial_processing", "REPORT_EMPLOYEE_INSURANCE_LOSS", "COMPLETED", False),
    ("employee_partial_processing", "REPORT_EMPLOYEE_INSURANCE_LOSS", "IN_PROGRESS", True),
])
def test_submission_or_one_employee_cannot_be_graded_as_full_processing_completion(case, code, status, submitted):
    row = progress_row(case, changes=[{
        "step_code": code, "proposed_status": status,
        "proposed_requirements_confirmed": True, "proposed_submitted": submitted,
    }])
    assert expectation_checks(row, CORE_EXPECTATIONS[case])["expected_procedure_states"] is False


@pytest.mark.parametrize("case,code,status,submitted", [
    ("restoration_work_completed", "PERFORM_RESTORATION", "COMPLETED", False),
    ("administrative_submitted", "FILE_FOOD_SERVICE_CLOSURE", "IN_PROGRESS", True),
    ("employee_partial_processing", "REPORT_EMPLOYEE_INSURANCE_LOSS", "IN_PROGRESS", False),
])
def test_every_repeat_must_meet_the_fixed_progress_expectation(case, code, status, submitted):
    row = progress_row(case, changes=[{
        "step_code": code, "proposed_status": status,
        "proposed_requirements_confirmed": True, "proposed_submitted": submitted,
    }])
    rows = [json.loads(json.dumps(row)) for _ in range(3)]
    assert verdict(rows, CORE_EXPECTATIONS[case])["verdict"] == "PASS"
    rows[1]["procedure_changes"][0]["proposed_submitted"] = not submitted
    assert verdict(rows, CORE_EXPECTATIONS[case])["verdict"] == "FAIL"


@pytest.mark.parametrize("case,code,status,submitted", [
    ("restoration_work_completed", "PERFORM_RESTORATION", "COMPLETED", False),
    ("administrative_submitted", "FILE_FOOD_SERVICE_CLOSURE", "IN_PROGRESS", True),
    ("employee_partial_processing", "REPORT_EMPLOYEE_INSURANCE_LOSS", "IN_PROGRESS", False),
])
def test_progress_fixtures_preserve_the_text_and_use_explicit_user_selections(case, code, status, submitted):
    from app.agent.procedure_tool.cafe import build_cafe_procedure_steps

    registry = build_cafe_procedure_steps({
        item: index for index, item in enumerate(sorted(evaluation.CAFE_TRACKED_CODES), 1)
    })
    request = evaluation.build_progress_case(case, registry)
    report, = request.trigger.input.procedure_reports
    assert isinstance(report, evaluation.agent_schemas.ProcedureProgressReport)
    assert report.procedure_step == next(
        step.procedure_step for step in registry if step.procedure_step.step_code == code
    )
    assert report.status == status
    assert report.requirements_confirmed is True
    assert report.submitted is submitted
    assert request.trigger.input.redacted_text == {
        "restoration_work_completed": "확인한 범위대로 원상복구와 철거 작업을 모두 마쳤습니다.",
        "administrative_submitted": "식품영업 폐업신고서를 구청에 제출해 접수됐지만 기관 처리 완료는 아직 확인 못했습니다.",
        "employee_partial_processing": "직원 두 명 중 한 명만 4대보험 자격상실 처리가 끝났고 다른 직원은 남아 있습니다.",
    }[case]
    # The selected delta has not already been applied to the prior read view.
    prior = next(item for item in request.case_snapshot.procedure_progress
                 if item.procedure_step == report.procedure_step)
    assert prior.status == "NOT_STARTED"
    assert prior.requirements_confirmed is True and prior.submitted is False


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
        "procedure_changes": [],
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


def test_dataset_tax_completion_check_reads_the_shared_progress_summary():
    result = score(row(must_not=["TAX_FILING_COMPLETED_WITHOUT_PROOF"]), {
        **plan(), "procedure_changes": [{
            "step_code": "FILE_TAX_BUSINESS_CLOSURE", "proposed_status": "COMPLETED",
        }],
    })
    assert result["result"] == "WRONG"


def dataset_row():
    return {
        "event_id": "synthetic", "trigger_type": "RESULT_SUBMITTED",
        "case_create_request": CASES["benchmark_case1"], "current_facts": {},
        "raw_input": "private submitted text", "difficulty": "synthetic",
        "scenario_family": "synthetic", **row(),
    }


@pytest.mark.parametrize("field,value", [
    ("event_id", 1), ("difficulty", None), ("scenario_family", []),
    ("trigger_type", "CASE_CREATED"), ("expected_branch", "unknown branch"),
    ("expected_branch", []), ("raw_input", None), ("raw_input", 1),
    ("case_create_request", []),
    ("case_create_request", {**CASES["benchmark_case1"], "employee_count": "2"}),
    ("current_facts", []), ("current_facts", {"demolition_required": True}),
    ("expected_fact_changes", []),
    ("expected_fact_changes", {"restoration_scope": "invalid enum"}),
    ("must_not", "SILENT_FACT_OVERWRITE"), ("must_not", [None]),
])
def test_dataset_rejects_bad_types_before_building_an_agent_input(field, value, monkeypatch, tmp_path):
    dataset = tmp_path / "synthetic.jsonl"
    dataset.write_text("\n" + json.dumps(dataset_row() | {field: value}) + "\n")

    def unexpected_build(*args, **kwargs):
        pytest.fail("invalid rows must not reach Agent input construction")

    monkeypatch.setattr(evaluation, "build_graph_input", unexpected_build)
    with pytest.raises(SystemExit) as error:
        evaluation.load_dataset(dataset)
    assert "line 2:" in str(error.value)
    assert field in str(error.value)
    assert "private submitted text" not in str(error.value)


@pytest.mark.parametrize("field", list(dataset_row()))
def test_dataset_requires_all_used_fields(field, tmp_path):
    data = dataset_row()
    del data[field]
    dataset = tmp_path / "synthetic.jsonl"
    dataset.write_text(json.dumps(data))

    with pytest.raises(SystemExit, match="line 1:"):
        evaluation.load_dataset(dataset)


@pytest.mark.parametrize("text", ["", "[]", "{invalid JSON with private text"])
def test_dataset_rejects_empty_or_malformed_rows_without_echoing_input(text, tmp_path):
    dataset = tmp_path / "synthetic.jsonl"
    dataset.write_text(text)
    with pytest.raises(SystemExit) as error:
        evaluation.load_dataset(dataset)
    assert "private text" not in str(error.value)


def test_dataset_retains_start_set_id_and_prior_fact_format(tmp_path):
    data = dataset_row() | {
        "start_set_id": "starting-state", "current_facts": {"restoration_scope": "PARTIAL"},
    }
    del data["event_id"]
    dataset = tmp_path / "synthetic.jsonl"
    dataset.write_text(json.dumps(data))

    request, expected = evaluation.load_dataset(dataset)["starting-state"]
    assert request.trigger.trigger_type == "RESULT_SUBMITTED"
    assert request.trigger.input.redacted_text == data["raw_input"]
    assert expected == data


@pytest.mark.parametrize("suite", ["core"])
def test_external_dataset_cannot_be_combined_with_a_fixed_suite(suite):
    with pytest.raises(SystemExit, match="fixed suite cannot be combined"):
        asyncio.run(evaluation.run(SimpleNamespace(
            suite=suite, dataset=Path("unused.jsonl"), graph_input=None,
            case=None, result_input=None,
        )))


@pytest.mark.parametrize("expected_changes,branch,status,verdict_", [
    ({}, "REPLAN_OR_NEEDS_MORE_INFO", "REVIEWED_PLAN", "PASS"),
    ({"demolition_required": "REQUIRED"}, "REPLAN_OR_NEEDS_MORE_INFO", "REVIEWED_PLAN", "FAIL"),
    ({}, "CONFLICT", "CONFLICT", "PASS"),
    ({}, "CONFLICT", "REVIEWED_PLAN", "FAIL"),
])
def test_external_dataset_grading_controls_the_final_result(
    expected_changes, branch, status, verdict_, monkeypatch, tmp_path,
):
    dataset = tmp_path / "synthetic.jsonl"
    dataset.write_text(json.dumps({
        "event_id": "synthetic", "trigger_type": "RESULT_SUBMITTED",
        "case_create_request": CASES["benchmark_case1"], "current_facts": {},
        "raw_input": "확인한 내용이 없습니다.", "difficulty": "synthetic",
        "scenario_family": "synthetic", **row(branch=branch, changes=expected_changes),
    }, ensure_ascii=False) + "\n")
    monkeypatch.setattr(evaluation, "SnapshotStore", lambda _: SimpleNamespace(
        raw=b"{}", snapshot_version="synthetic", records=list,
    ))
    monkeypatch.setattr(evaluation.LLMConfig, "from_env", lambda **_: SimpleNamespace(
        model="synthetic", reasoning_effort="xhigh",
    ))
    trial = AsyncMock(return_value={
        "case": "synthetic", "status": status, "graph_input_digest": "same",
        "calls_by_role": {"shared": 1}, "fact_changes": [], "procedure_changes": [],
    })
    monkeypatch.setattr(evaluation, "trial", trial)
    args = SimpleNamespace(
        dataset=dataset, graph_input=None, case=None, result_input=None,
        procedure_snapshot=tmp_path / "unused.json", support_catalog=None,
        expect=[], output=tmp_path / "report", validate_only=False, repeats=1,
    )
    if verdict_ == "FAIL":
        with pytest.raises(SystemExit) as failure:
            asyncio.run(evaluation.run(args))
        assert failure.value.code == 1
    else:
        asyncio.run(evaluation.run(args))
    report = json.loads((args.output / "results.json").read_text())
    assert report["verdict"] == verdict_
    assert report["per_case"]["synthetic"]["reliability"] == "PASS"
    assert report["per_case"]["synthetic"]["all_reviewed_plan"] is (status == "REVIEWED_PLAN")
    assert report["dataset_score"]["results"] == {"WRONG" if verdict_ == "FAIL" else "PASS": 1}
    assert trial.await_count == 1


def test_behavior_evaluation_allows_wording_changes_but_requires_expected_fact_updates():
    expected = CORE_EXPECTATIONS["scope_benign_connective"]
    base = {
        "status": "REVIEWED_PLAN", "decision_type": "NEEDS_MORE_INFO",
        "questions_for_user_count": 1, "graph_input_digest": "same",
        "calls_by_role": {"shared": 1, "info": 1, "supervisor": 1}, "review_proof_valid": True,
        "calls": [{"http_status": 200, "schema_name": name, "model": "gpt-6.1-sol",
                   "reasoning_effort": "xhigh", "role": "shared"} for name in (
            "ContentSafetyDecision", "reborn_info_analysis", "reborn_supervisor_draft",
            "reborn_review_output",
        )],
        "fact_changes": [{"field_path": "restoration_scope", "proposed_status": "CONFIRMED",
                          "proposed_value": "NOT_REQUIRED"}],
    }
    rows = [{**base, "blocker_digest": wording} for wording in ("first", "second", "third")]
    assert verdict(rows, expected)["verdict"] == "PASS"
    assert verdict(rows, expected)["consistency"] == "FAIL"
    rows[1]["fact_changes"] = []
    assert verdict(rows, expected)["verdict"] == "FAIL"


def test_forbidden_change_or_skipped_supervisor_is_an_evaluation_failure():
    row = {
        "status": "REVIEWED_PLAN", "decision_type": "NEEDS_MORE_INFO",
        "questions_for_user_count": 1,
        "fact_changes": [{"field_path": "restoration_scope"}],
        "calls": [],
    }
    checks = expectation_checks(row, CORE_EXPECTATIONS["scope_reversed"])
    assert checks["no_forbidden_changes"] is False
    assert checks["required_components_called"] is False


def test_empty_evaluation_never_passes():
    assert verdict([], CORE_EXPECTATIONS["intake"])["verdict"] == "FAIL"


def test_review_observer_preserves_the_real_result_and_logs_paths_without_prose():
    marker = "private review rationale and source text"
    result = SimpleNamespace(
        verdict="REVISE",
        issues=[SimpleNamespace(issue_code="CASE_MISMATCH", category="CASE_MISMATCH", severity="BLOCKING",
                                target_component="SUPERVISOR",
                                target_path="/supervisor_draft/mutations/fact_changes",
                                reason_summary=marker, evidence_refs=[marker])],
        missing_evidence=[SimpleNamespace(claim_path="/supervisor_draft/decision/selection_summary",
                                         reason_summary=marker)],
    )
    tool = SimpleNamespace(review=AsyncMock(return_value=result))
    records, snapshots = [], []
    subject = SimpleNamespace(review_attempt=2, private_text=marker)
    observed = evaluation.recording_review(
        tool, records, lambda: snapshots.append(json.loads(json.dumps(records))),
    )
    assert asyncio.run(observed(subject)) is result
    tool.review.assert_awaited_once_with(subject)
    assert records == [{
        "review_attempt": 2, "verdict": "REVISE",
        "issues": [{"issue_code": "CASE_MISMATCH", "category": "CASE_MISMATCH", "severity": "BLOCKING",
                    "target_component": "SUPERVISOR",
                    "target_path": "/supervisor_draft/mutations/fact_changes"}],
        "missing_evidence_paths": ["/supervisor_draft/decision/selection_summary"],
    }]
    assert snapshots == [records]
    assert marker not in json.dumps(records)


def test_review_observer_propagates_an_error_without_recording_a_false_verdict():
    records, published = [], []
    error = RuntimeError("private provider failure")
    tool = SimpleNamespace(review=AsyncMock(side_effect=error))
    observed = evaluation.recording_review(tool, records, lambda: published.append(True))
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(observed(SimpleNamespace(review_attempt=1)))
    assert caught.value is error
    assert records == published == []


def test_transport_records_only_the_closed_safety_stage_without_input_text():
    calls = []

    async def run():
        transport = evaluation.RecordingTransport("shared", calls)
        await transport._inner.aclose()
        transport._inner = httpx.MockTransport(lambda _: httpx.Response(200))
        try:
            for stage in ("INPUT", "OUTPUT", "private-invalid-stage"):
                await transport.handle_async_request(httpx.Request(
                    "POST", "https://example.org/synthetic", json={
                        "messages": [{"role": "user", "content": "INPUT_JSON=" + json.dumps({
                            "stage": stage, "content": {"redacted_text": "private-input-text"},
                        })}],
                        "response_format": {"json_schema": {"name": "ContentSafetyDecision"}},
                    },
                ))
        finally:
            await transport.aclose()

    asyncio.run(run())
    assert [call.get("safety_stage") for call in calls] == ["INPUT", "OUTPUT", None]
    assert "private-input-text" not in json.dumps(calls)
    assert "private-invalid-stage" not in json.dumps(calls)


def test_transport_publishes_503_metadata_before_a_trial_finishes_without_body_or_token():
    calls, snapshots = [], []

    async def run():
        transport = evaluation.RecordingTransport(
            "info", calls, lambda: snapshots.append(json.loads(json.dumps(calls))),
        )
        await transport._inner.aclose()
        transport._inner = httpx.MockTransport(lambda _: httpx.Response(503))
        try:
            response = await transport.handle_async_request(httpx.Request(
                "POST", "https://example.org/synthetic", headers={"Authorization": "Bearer private-token"},
                json={"model": "gpt-6.1-sol", "reasoning_effort": "xhigh",
                      "messages": [{"role": "user", "content": "private-submitted-text"}],
                      "response_format": {"json_schema": {"name": "reborn_info_analysis"}}},
            ))
            assert response.status_code == 503
        finally:
            await transport.aclose()

    asyncio.run(run())
    assert len(snapshots) == 2
    assert "http_status" not in snapshots[0][0]
    assert snapshots[-1][0]["http_status"] == 503
    assert snapshots[-1][0]["schema_name"] == "reborn_info_analysis"
    assert "headers_latency_ms" in snapshots[-1][0]
    assert "private-token" not in json.dumps(snapshots)
    assert "private-submitted-text" not in json.dumps(snapshots)


def test_failed_evaluation_writes_metadata_and_exits_nonzero(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluation, "SnapshotStore", lambda _: SimpleNamespace(
        raw=b"{}", snapshot_version="synthetic", records=list,
    ))
    monkeypatch.setattr(evaluation.LLMConfig, "from_env", lambda **_: SimpleNamespace(
        model="synthetic", reasoning_effort="xhigh",
    ))
    monkeypatch.setattr(evaluation, "trial", AsyncMock(return_value={
        "case": "benchmark_case1", "status": "SAFE_FAILURE", "graph_input_digest": "same",
        "calls_by_role": {"shared": 1}, "failure_code": "COMPONENT_UNAVAILABLE",
    }))
    args = SimpleNamespace(
        graph_input=None, case=["benchmark_case1"], result_input=None,
        procedure_snapshot=tmp_path / "unused.json", support_catalog=None,
        expect=[], output=tmp_path / "report", validate_only=False, repeats=1,
    )
    with pytest.raises(SystemExit) as failure:
        asyncio.run(evaluation.run(args))
    assert failure.value.code == 1
    report = json.loads((args.output / "results.json").read_text())
    assert report["verdict"] == "FAIL"
    assert "redacted_text" not in json.dumps(report)


@pytest.mark.parametrize("status", [401, 403])
def test_credentials_stop_repeats_even_when_graph_converts_the_error_to_safe_failure(
    status, monkeypatch, tmp_path,
):
    monkeypatch.setattr(evaluation, "SnapshotStore", lambda _: SimpleNamespace(
        raw=b"{}", snapshot_version="synthetic", records=list,
    ))
    monkeypatch.setattr(evaluation.LLMConfig, "from_env", lambda **_: SimpleNamespace(
        model="synthetic", reasoning_effort="xhigh",
    ))
    trial = AsyncMock(return_value={
        "case": "benchmark_case1", "status": "SAFE_FAILURE", "graph_input_digest": "same",
        "calls_by_role": {"info": 1}, "failure_code": "COMPONENT_UNAVAILABLE",
        "calls": [{"role": "info", "http_status": status}],
    })
    monkeypatch.setattr(evaluation, "trial", trial)
    args = SimpleNamespace(
        graph_input=None, case=["benchmark_case1"], result_input=None,
        procedure_snapshot=tmp_path / "unused.json", support_catalog=None,
        expect=[], output=tmp_path / "report", validate_only=False, repeats=3,
    )
    with pytest.raises(SystemExit):
        asyncio.run(evaluation.run(args))
    assert trial.await_count == 1
    assert (args.output / "trial-001.json").is_file()


def test_unmerged_core_contract_fails_before_sources_or_model_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluation, "agent_schemas", SimpleNamespace())
    unused = AsyncMock(side_effect=AssertionError("missing DTOs must fail before a model call"))
    monkeypatch.setattr(evaluation.runtime_module.StructuredLLMClient, "generate", unused)
    with pytest.raises(SystemExit, match="core requires the planning feature DTOs") as failure:
        asyncio.run(evaluation.run(SimpleNamespace(suite="core", graph_input=None)))
    message = str(failure.value)
    assert "ProcedureProgressReport.procedure_step" in message
    assert "RedactedInput.procedure_reports" in message
    assert "ProcedureProgressObservation.structured_report" in message
    unused.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("version", [None, "cafe-official-sources/2026-10-18"])
def test_cafe_source_preserves_actual_procedure_conditions_and_dependencies(tmp_path, version):
    from app.agent.procedure_tool.cafe import (
        build_cafe_procedure_steps,
        build_cafe_reviewed_snapshot,
    )

    snapshot = build_cafe_reviewed_snapshot()
    if version is not None:
        snapshot.snapshot_version = version
    path = tmp_path / "reviewed.json"
    path.write_text(snapshot.model_dump_json(), encoding="utf-8")
    registry = evaluation.build_registry(SnapshotStore(path))
    expected = build_cafe_procedure_steps({
        step.procedure_step.step_code: step.procedure_step.procedure_step_id for step in registry
    })
    assert registry == expected
    assert sum(len(step.eligibility_conditions) for step in registry) == 8
    assert sum(len(step.dependencies) for step in registry) == 2


def test_cafe_source_requires_its_actual_factory_instead_of_generic_rules(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "app.agent.procedure_tool.cafe", None)
    with pytest.raises(ValueError, match="requires the cafe procedure feature"):
        evaluation.build_registry(SimpleNamespace(snapshot_version=evaluation.CAFE_SOURCE_VERSION))
    # An earlier source version remains usable by the independent safety suite.
    assert evaluation.build_registry(SimpleNamespace(snapshot_version="synthetic/old", records=list)) == []
    assert evaluation.build_registry(SimpleNamespace(snapshot_version=evaluation.CAFE_SOURCE_VERSION + "-unknown", records=list)) == []


@pytest.mark.parametrize("case", ["conflict_mixed", "conflict_keep_all"])
def test_core_conflicts_restore_the_pending_report_after_attaching_official_sources(case):
    request = evaluation.build_core_request(case, [])
    store = SnapshotStore(Path(__file__).resolve().parents[1] / "app/common/reviewed-procedures.ko-KR.json")
    request = attach_fixture_sources(request, store)
    restored = evaluation.AgentGraphInput.model_validate_json(request.model_dump_json())
    packet = restored.trigger.pending_input
    assert packet is not None and packet.fact_candidates[0].value == "2026-11-02"
    assert packet.original_input.redacted_text.endswith("폐업 예정일은 2026-11-02입니다.")
    packet.assert_integrity(restored.case_snapshot, restored.trigger.conflicts)
    assert attach_fixture_sources(restored, store) == restored
    for change in ("omit", "tamper"):
        raw = restored.model_dump(mode="json")
        if change == "omit":
            raw["trigger"].pop("pending_input")
        else:
            raw["trigger"]["pending_input"]["fact_candidates"][0]["value"] = "2026-11-03"
        with pytest.raises(ValidationError, match="pending input"):
            evaluation.AgentGraphInput.model_validate_json(json.dumps(raw))



@pytest.mark.parametrize("case", ["conflict_mixed", "conflict_keep_all"])
def test_core_conflict_grading_requires_the_retained_date_without_accepting_rejected_facts(case):
    expected = CORE_EXPECTATIONS[case]
    row = progress_row("administrative_submitted", changes=[])
    changes = [{"field_path": field, "proposed_status": "CONFIRMED", "proposed_value": value}
               for field, value in expected["required_facts"].items()]
    assert verdict([row | {"fact_changes": changes}], expected)["verdict"] == "PASS"
    without_date = [item for item in changes if item["field_path"] != "planned_closure_date"]
    for invalid in (
        without_date,
        without_date + [{"field_path": "planned_closure_date", "proposed_status": "CONFIRMED", "proposed_value": "2026-11-03"}],
        changes + [{"field_path": "demolition_required", "proposed_status": "CONFIRMED", "proposed_value": "REQUIRED"}],
    ):
        assert verdict([row | {"fact_changes": invalid}], expected)["verdict"] == "FAIL"


def test_code_change_during_an_otherwise_successful_trial_fails_the_run(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluation, "SnapshotStore", lambda _: SimpleNamespace(
        raw=b"{}", snapshot_version="synthetic", records=list,
    ))
    monkeypatch.setattr(evaluation.LLMConfig, "from_env", lambda **_: SimpleNamespace(
        model="synthetic", reasoning_effort="xhigh",
    ))
    hashes = iter(["sha256:before", "sha256:after"])
    monkeypatch.setattr(evaluation, "evaluation_code_digest", lambda: next(hashes))
    monkeypatch.setattr(evaluation, "trial", AsyncMock(return_value={
        "case": "benchmark_case1", "status": "REVIEWED_PLAN", "graph_input_digest": "same",
        "calls_by_role": {"shared": 1},
    }))
    args = SimpleNamespace(
        graph_input=None, case=["benchmark_case1"], result_input=None,
        procedure_snapshot=tmp_path / "unused.json", support_catalog=None,
        expect=[], output=tmp_path / "report", validate_only=False, repeats=1,
    )
    with pytest.raises(SystemExit) as failure:
        asyncio.run(evaluation.run(args))
    assert failure.value.code == 1
    report = json.loads((args.output / "results.json").read_text())
    assert report["code_unchanged"] is False and report["verdict"] == "FAIL"
    assert report["per_case"]["benchmark_case1"]["verdict"] == "PASS"


def test_cli_validation_error_does_not_print_the_rejected_input(tmp_path):
    import os
    import subprocess
    import sys

    marker = "private-submitted-validation-text"
    graph = tmp_path / "invalid.json"
    graph.write_text(json.dumps({"redacted_text": marker}))
    report = subprocess.run(
        [sys.executable, "-B", "-m", "scripts.evaluate_planning", "--graph-input", str(graph),
         "--procedure-snapshot", "app/common/reviewed-procedures.ko-KR.json",
         "--output", str(tmp_path / "unused-report"), "--validate-only"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "CHAT_PROXY_URL": "https://validation.invalid", "PROXY_TOKEN": "synthetic-validation-only",
             "OPENAI_MODEL": "gpt-6.1-sol", "OPENAI_REASONING_EFFORT": "xhigh"},
    )
    assert report.returncode == 1
    assert marker not in report.stdout + report.stderr
    assert json.loads(report.stdout)["error_type"] == "ValidationError"
    assert not (tmp_path / "unused-report").exists()


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
