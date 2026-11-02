import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from app.agent.schemas import canonical_digest
from scripts.evaluate_agent_roles import baseline_row, decision_digest
from scripts.evaluation_metrics import evaluate_efforts
from test_action_codes import supervisor_request


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
