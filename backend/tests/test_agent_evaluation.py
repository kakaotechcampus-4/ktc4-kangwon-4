import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from app.agent.review_tool.models import ReviewProviderOutput
from app.agent.schemas import ReviewSubject, canonical_digest
from app.agent.supervisor import SupervisorAgent
from pydantic import ValidationError
from scripts import evaluate_agent_roles
from scripts.evaluate_agent_roles import baseline_row, decision_digest
from scripts.evaluation_metrics import evaluate_efforts
from test_action_codes import StubModel, supervisor_request


@pytest.mark.parametrize("failure,expected", [
    ("high", ["high"]), ("medium", ["high", "medium"]),
    ("low", ["high", "medium", "low"]), (None, ["high", "medium", "low"]),
])
def test_failed_effort_skips_weaker_calls_but_other_models_start_at_high(failure, expected):
    async def run():
        called, skipped = [], []
        configs = [(f"{prefix}-{effort}", prefix, effort)
                   for prefix in ["first", "second"] for effort in ["high", "medium", "low"]]

        async def evaluate(label, config, repeats):
            called.append(label)
            return {"passed": label != f"first-{failure}"}

        async for label, _prefix, _config, result in evaluate_efforts(configs, evaluate):
            if result is None:
                skipped.append(label)
        assert called == [f"first-{effort}" for effort in expected] + [
            "second-high", "second-medium", "second-low",
        ]
        assert skipped == [f"first-{effort}" for effort in ["high", "medium", "low"] if effort not in expected]

    asyncio.run(run())


def test_decision_digest_accepts_json_and_ignores_key_order():
    assert decision_digest({"action": "CONFIRM", "questions": []}) == decision_digest(
        {"questions": [], "action": "CONFIRM"}
    )
    assert decision_digest({"action": "CONFIRM"}) != decision_digest({"action": None})


def test_baseline_reuse_requires_identical_input_model_effort_and_pass():
    request = supervisor_request()
    dataset = {"supervisor_cases": {"scope_unknown": request.model_dump(mode="json")}}
    config = SimpleNamespace(model="gpt-6.1-sol", reasoning_effort="xhigh")
    row = {"case": "scope_unknown", "repeat": 1, "passed": True,
           "model": config.model, "effort": config.reasoning_effort}
    checkpoint = {"rows": [row], "original_report_sha256": "synthetic-report",
                  "case_input_digests": {"scope_unknown": canonical_digest(request)}}
    reused = baseline_row(checkpoint, dataset, "scope_unknown", 1, config)
    assert reused is not row and reused["reused_from_report_sha256"] == "synthetic-report"
    changed = deepcopy(dataset)
    changed["supervisor_cases"]["scope_unknown"]["draft_version"] += 1
    assert baseline_row(checkpoint, changed, "scope_unknown", 1, config) is None
    config.reasoning_effort = "low"
    assert baseline_row(checkpoint, dataset, "scope_unknown", 1, config) is None
    config.reasoning_effort = "xhigh"
    row["passed"] = False
    assert baseline_row(checkpoint, dataset, "scope_unknown", 1, config) is None


def test_accuracy_validates_every_fixture_before_any_paid_call(tmp_path, monkeypatch):
    async def paid_call(*args, **kwargs):
        pytest.fail("invalid later fixture must stop the suite before its first call")

    monkeypatch.setattr(evaluate_agent_roles, "trial", paid_call)
    inputs = tmp_path / "inputs.json"
    inputs.write_text("{}")
    dataset = {
        "supervisor_cases": {"scope_unknown": supervisor_request().model_dump(mode="json")},
        "accuracy_cases": [{"role": "scope_unknown"}, {"role": "info", "request": {}}],
    }
    args = SimpleNamespace(inputs=inputs, output=tmp_path, validate_only=False, repeats=1)
    with pytest.raises(ValidationError):
        asyncio.run(evaluate_agent_roles.accuracy_suite(args, dataset))


def test_validate_only_cannot_fall_through_to_a_paid_mode():
    with pytest.raises(SystemExit, match="--validate-only requires --accuracy"):
        asyncio.run(evaluate_agent_roles.run(SimpleNamespace(validate_only=True, accuracy=False)))


def test_review_diagnostics_preserve_rejection_details(tmp_path, monkeypatch):
    # 정상 초안이 반려돼 평가가 실패해도, 다음 진단에 필요한 상세가 파일에 남아야 한다.
    config = SimpleNamespace(model="synthetic-model", reasoning_effort="xhigh")
    output = ReviewProviderOutput.model_validate({
        "verdict": "REVISE", "missing_evidence": [], "recommended_rework_targets": ["SUPERVISOR"],
        "resolution_reason": "합성 반려 이유를 보존합니다.",
        "issues": [{"issue_code": "AMBIGUOUS_LANGUAGE", "category": "LANGUAGE", "severity": "BLOCKING",
                    "target_component": "SUPERVISOR", "target_call_id": None,
                    "target_path": "/supervisor_draft/decision/next_action/title",
                    "reason_summary": "합성 제목을 확인 행동에 맞게 수정해 주세요.",
                    "evidence_refs": ["synthetic-document"]}],
    })
    primary = SimpleNamespace(generate=AsyncMock(side_effect=StubModel().generate), aclose=AsyncMock())
    reviewer = SimpleNamespace(generate=AsyncMock(return_value=output), aclose=AsyncMock())
    monkeypatch.setattr(evaluate_agent_roles, "StructuredLLMClient", Mock(side_effect=[primary, reviewer]))
    monkeypatch.setattr(evaluate_agent_roles.LLMConfig, "from_env", lambda **kwargs: config)
    monkeypatch.setattr(evaluate_agent_roles.LangfuseTraceSink, "from_env", lambda: None)
    dataset = {
        "supervisor_cases": {"scope_unknown": supervisor_request().model_dump(mode="json")},
        "expected_actions": {"scope_unknown": "CONFIRM_TAX_CLOSURE_REQUIREMENTS"},
        "accuracy_cases": [{"name": "normal_draft", "role": "scope_unknown"}],
    }
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps(dataset))
    args = SimpleNamespace(inputs=inputs, output=tmp_path, validate_only=False, repeats=1)
    with pytest.raises(SystemExit) as stopped:
        asyncio.run(evaluate_agent_roles.accuracy_suite(args, dataset))
    assert stopped.value.code == 1
    report = json.loads((tmp_path / "results.json").read_text())
    [row] = report["trials"]
    assert not report["passed"] and not row["checks"]["review_passed"]
    assert row["result"]["verdict"] == "REVISE"
    assert row["result"]["resolution_reason"] == output.resolution_reason
    assert row["result"]["issues"][0]["reason_summary"] == output.issues[0].reason_summary
    assert row["model_review_outputs"] == [output.model_dump(mode="json")]
    assert row["code_review_result"]["verdict"] == "PASS"
    subject = ReviewSubject.model_validate(row["review_subject"])
    assert row["result"]["reviewed_subject_digest"] == subject.subject_digest
    primary.generate.assert_awaited_once()
    reviewer.generate.assert_awaited_once()


@pytest.mark.parametrize("invalid_first", [False, True])
def test_review_diagnostics_separate_model_and_code_findings(invalid_first):
    async def run():
        request = supervisor_request()
        draft = await SupervisorAgent(StubModel()).draft(request)
        # 세무 절차 대상에 임대인 확인 코드를 붙인, 구조는 온전하지만 의미가 틀린 초안이다.
        draft.decision.next_action.action_code = "CONFIRM_RESTORATION_SCOPE"
        meta = request.source_results[0].meta
        subject = ReviewSubject.create(
            schema_version="agent-io/2.0", review_subject_id=UUID(int=9), review_attempt=1,
            run_id=meta.run_id, case_id=meta.case_id, trigger=request.trigger,
            snapshot=request.case_snapshot, known_procedure_steps=request.known_procedure_steps,
            source_results=request.source_results, supervisor_draft=draft,
        )
        original = subject.model_dump(mode="json")
        output = ReviewProviderOutput(
            verdict="PASS", issues=[], missing_evidence=[], recommended_rework_targets=[],
            resolution_reason="합성 모델은 문제를 놓치고 통과시켰습니다.",
        )
        invalid = ReviewProviderOutput.model_validate(output.model_dump(mode="python") | {"verdict": "REVISE"})
        reviewer = SimpleNamespace(generate=AsyncMock(side_effect=[invalid, output] if invalid_first else [output]))
        row = {"review_results": []}
        result = await evaluate_agent_roles.record_review(subject, reviewer, row)
        # 계약을 어긴 첫 답으로 재요청했을 때도, 첫 답과 마지막 답을 모두 보존한다.
        assert row["model_review_outputs"] == [
            item.model_dump(mode="json") for item in ([invalid, output] if invalid_first else [output])
        ]
        assert row["model_review_outputs"][-1]["verdict"] == "PASS"
        assert row["code_review_result"]["verdict"] == row["result"]["verdict"] == "REVISE"
        assert result.verdict == "REVISE"
        assert any(issue["issue_code"] == "CONTRACT_VIOLATION" for issue in row["code_review_result"]["issues"])
        assert row["review_subject"] == subject.model_dump(mode="json") == original
        assert reviewer.generate.await_count == 1 + int(invalid_first)

    asyncio.run(run())


@pytest.mark.parametrize("warning,blocking", [(False, False), (True, False), (False, True)])
def test_fixed_review_inputs_skip_supervisor(tmp_path, monkeypatch, warning, blocking):
    request = supervisor_request()
    draft = asyncio.run(SupervisorAgent(StubModel()).draft(request))
    if blocking:
        draft.decision.next_action.action_code = "CONFIRM_RESTORATION_SCOPE"
    meta = request.source_results[0].meta
    subject = ReviewSubject.create(
        schema_version="agent-io/2.0", review_subject_id=UUID(int=9), review_attempt=1,
        run_id=meta.run_id, case_id=meta.case_id, trigger=request.trigger,
        snapshot=request.case_snapshot, known_procedure_steps=request.known_procedure_steps,
        source_results=request.source_results, supervisor_draft=draft,
    ).model_dump(mode="json")
    output = ReviewProviderOutput.model_validate({
        "verdict": "PASS", "missing_evidence": [], "recommended_rework_targets": [],
        "resolution_reason": "합성 테스트의 정상 PASS입니다.",
        "issues": [{"issue_code": "AMBIGUOUS_LANGUAGE", "category": "LANGUAGE", "severity": "WARNING",
                    "target_component": "SUPERVISOR", "target_call_id": None,
                    "target_path": "/supervisor_draft/decision/next_action/reason",
                    "reason_summary": "합성 문구 개선 제안이며 진행을 막지는 않습니다.",
                    "evidence_refs": ["synthetic-document"]}] if warning else [],
    })
    config = SimpleNamespace(model="synthetic-model", reasoning_effort="xhigh")
    primary = SimpleNamespace(generate=AsyncMock(side_effect=AssertionError("Supervisor model must not run")),
                              aclose=AsyncMock())
    reviewer = SimpleNamespace(generate=AsyncMock(return_value=output), aclose=AsyncMock())
    supervisor = AsyncMock(side_effect=AssertionError("Supervisor must not rebuild a fixed draft"))
    monkeypatch.setattr(evaluate_agent_roles.SupervisorAgent, "draft", supervisor)
    monkeypatch.setattr(evaluate_agent_roles, "StructuredLLMClient", Mock(side_effect=[primary, reviewer] * 2))
    monkeypatch.setattr(evaluate_agent_roles.LLMConfig, "from_env", lambda **kwargs: config)
    monkeypatch.setattr(evaluate_agent_roles.LangfuseTraceSink, "from_env", lambda: None)
    expected = "REVISE" if blocking else "PASS"
    dataset = {"synthetic_data": True, "accuracy_cases": [
        {"name": "fixed_draft", "role": "review", "request": subject, "expected": {"verdict": expected}},
    ]}
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps(dataset))
    args = SimpleNamespace(inputs=inputs, output=tmp_path / "run", accuracy=True, validate_only=False, repeats=2)
    asyncio.run(evaluate_agent_roles.run(args))
    report = json.loads((args.output / "results.json").read_text())
    assert report["passed"] and report["code_unchanged"]
    assert len(report["trials"]) == 2
    for row in report["trials"]:
        assert row["review_subject"] == subject
        assert row["result"]["verdict"] == row["code_review_result"]["verdict"] == expected
        assert bool(row["result"]["issues"]) == (warning or blocking)
        assert bool(row["code_review_result"]["issues"]) == blocking
        assert row["model_review_outputs"] == [output.model_dump(mode="json")]
    args.validate_only = True
    asyncio.run(evaluate_agent_roles.accuracy_suite(args, dataset))
    supervisor.assert_not_awaited()
    primary.generate.assert_not_awaited()
    assert reviewer.generate.await_count == 2


@pytest.mark.parametrize("invalid", ["empty_subject", "changed_digest", "missing_verdict", "changes_with_fixed_subject"])
def test_fixed_review_inputs_validate_before_calls(tmp_path, monkeypatch, invalid):
    request = supervisor_request()
    draft = asyncio.run(SupervisorAgent(StubModel()).draft(request))
    meta = request.source_results[0].meta
    subject = ReviewSubject.create(
        schema_version="agent-io/2.0", review_subject_id=UUID(int=9), review_attempt=1,
        run_id=meta.run_id, case_id=meta.case_id, trigger=request.trigger,
        snapshot=request.case_snapshot, known_procedure_steps=request.known_procedure_steps,
        source_results=request.source_results, supervisor_draft=draft,
    ).model_dump(mode="json")
    expected = {"verdict": "PASS"}
    if invalid == "empty_subject":
        subject = {}
    elif invalid == "changed_digest":
        subject["subject_digest"] = "sha256:" + "0" * 64
    elif invalid == "missing_verdict":
        expected = {}
    case = {"role": "review", "request": subject, "expected": expected}
    if invalid == "changes_with_fixed_subject":
        case["changes"] = {"title": "고정 초안에는 덧붙일 수 없는 수정"}
    dataset = {
        "supervisor_cases": {"scope_unknown": request.model_dump(mode="json")},
        "accuracy_cases": [{"role": "scope_unknown"}, case],
    }
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps(dataset))
    args = SimpleNamespace(inputs=inputs, output=tmp_path, validate_only=False, repeats=1)
    paid_call = AsyncMock(side_effect=AssertionError("invalid later fixture must stop all paid calls"))
    monkeypatch.setattr(evaluate_agent_roles, "trial", paid_call)
    monkeypatch.setattr(evaluate_agent_roles.LLMConfig, "from_env", lambda **kwargs: SimpleNamespace())
    with pytest.raises((ValidationError, ValueError)):
        asyncio.run(evaluate_agent_roles.accuracy_suite(args, dataset))
    paid_call.assert_not_awaited()
