"""The live harness must not label failures or unreviewed results successful."""

import asyncio
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import evaluate_case_api as evaluation
from scripts.evaluate_case_api import (
    case_response_checks,
    check_configuration,
    stored_blocker_checks,
)


@pytest.mark.parametrize("status", ["PENDING", "CONFLICT", "FAILED", None])
def test_incomplete_or_failed_case_is_not_a_successful_api_evaluation(status):
    checks = case_response_checks({
        "case": {"id": 1}, "judgment_status": status, "blocker": "합성",
        "questions_for_user": ["합성"],
    })
    assert checks["judgment_finished"] is False
    assert all(checks.values()) is False


@pytest.mark.parametrize("status,blocker,action,questions", [
    ("DONE", "합성", {"title": "합성", "reason": "합성 근거"}, None),
    ("NEEDS_MORE_INFO", None, None, ["합성"]),
    ("NEEDS_MORE_INFO", "합성", None, ["합성"]),
])
def test_existing_action_and_question_responses_can_both_pass(status, blocker, action, questions):
    assert all(case_response_checks({
        "case": {"id": 1}, "judgment_status": status, "blocker": blocker,
        "next_action": action, "questions_for_user": questions, "changes": [],
    }).values())


@pytest.mark.parametrize("status,blocker,action,questions", [
    ("DONE", None, {"title": "합성", "reason": "합성 근거"}, None),
    ("DONE", "합성", None, None),
    ("DONE", "합성", {"title": "합성"}, None),
    ("DONE", "합성", {"reason": "합성 근거"}, None),
    ("DONE", "합성", {"title": "합성", "reason": ""}, None),
    ("NEEDS_MORE_INFO", None, None, None),
    ("NEEDS_MORE_INFO", None, None, []),
    ("NEEDS_MORE_INFO", "", None, ["합성"]),
    ("NEEDS_MORE_INFO", None, {"title": "합성", "reason": "합성 근거"}, ["합성"]),
])
def test_missing_or_inconsistent_public_judgment_data_cannot_pass(status, blocker, action, questions):
    assert not all(case_response_checks({
        "case": {"id": 1}, "judgment_status": status, "blocker": blocker,
        "next_action": action, "questions_for_user": questions, "changes": [],
    }).values())


@pytest.fixture
def saved_history():
    return SimpleNamespace(
        id=2, case_id=1, priority_blocker_id=3,
        priority_blocker=SimpleNamespace(
            id=3, case_id=1, created_from_case_history_id=2, description="합성",
        ),
    )


def test_the_committed_priority_blocker_matches_the_case_and_history(saved_history):
    assert all(stored_blocker_checks(saved_history, case_id=1).values())


@pytest.mark.parametrize("field,value,failed_check", [
    ("priority_blocker", None, "stored_priority_blocker_present"),
    ("priority_blocker_id", None, "stored_priority_blocker_present"),
    ("priority_blocker_id", 99, "stored_priority_blocker_present"),
    ("priority_blocker.id", None, "stored_priority_blocker_present"),
    ("case_id", 99, "stored_history_case_matches"),
    ("priority_blocker.case_id", 99, "stored_blocker_case_matches"),
    ("priority_blocker.created_from_case_history_id", 99, "stored_blocker_history_matches"),
    ("id", None, "stored_blocker_history_matches"),
    ("priority_blocker.description", "", "stored_blocker_description_present"),
])
def test_missing_or_unrelated_stored_blockers_cannot_pass(saved_history, field, value, failed_check):
    target, _, attribute = field.rpartition(".")
    setattr(getattr(saved_history, target) if target else saved_history, attribute, value)
    checks = stored_blocker_checks(saved_history, case_id=1)
    assert checks[failed_check] is False
    assert not all(checks.values())


def test_the_harness_rejects_a_silent_role_or_effort_mismatch():
    with pytest.raises(ValueError):
        check_configuration({
            "shared": {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh"},
            "supervisor": {"model": "gpt-6.1-sol", "reasoning_effort": "high"},
            "info": {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh"},
        })


@pytest.mark.parametrize("service_name", ["first_judgment_service", "judgment_service"])
def test_api_harness_patches_the_service_used_by_either_router_version(service_name):
    # Isolate BE module imports/settings and run no HTTP request, DB or model.
    script = """
import asyncio, sys
from types import SimpleNamespace
from unittest.mock import patch
from app.be import db
from app.be.routers import case as case_router
from scripts import evaluate_case_api as evaluation

original_engine, engine = object(), object()
service = SimpleNamespace(_engine=original_engine)
other = 'judgment_service' if sys.argv[1] == 'first_judgment_service' else 'first_judgment_service'
client = evaluation.httpx.AsyncClient
def checked_client(**kwargs):
    assert service._engine is engine and db._engine is engine
    return client(**kwargs)
with patch.object(case_router, sys.argv[1], service, create=True), \\
     patch.object(case_router, other, None, create=True), \\
     patch.object(evaluation.SQLModel.metadata, 'create_all'), \\
     patch.object(evaluation.httpx, 'AsyncClient', side_effect=checked_client):
    assert asyncio.run(evaluation.exercise_api(engine, repeats=0, jwt_secret='synthetic')) == []
assert service._engine is original_engine
"""
    result = subprocess.run(
        [sys.executable, "-c", script, service_name], capture_output=True, text=True, check=False,
        env={**os.environ, "ENVIRONMENT": "dev", "DATABASE_URL": "sqlite://",
             "KAKAO_CLIENT_ID": "synthetic", "KAKAO_CLIENT_SECRET": "synthetic",
             "KAKAO_REDIRECT_URI": "http://localhost/synthetic", "JWT_SECRET_KEY": "synthetic"},
    )
    assert result.returncode == 0, result.stderr


def test_interrupted_api_evaluation_keeps_the_completed_trial_and_live_call_metadata(
    monkeypatch, tmp_path,
):
    class Container:
        def __init__(self, *args, **kwargs):
            self.stopped = False

        def with_env(self, *args):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stopped = True

        def get_connection_url(self):
            return "mysql+pymysql://synthetic:synthetic@localhost/test"

    container = Container()
    monkeypatch.setattr(evaluation, "MySqlContainer", lambda *args, **kwargs: container)
    monkeypatch.setattr(evaluation, "model_configuration", lambda: {
        role: {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh"}
        for role in ("shared", "info", "supervisor")
    })
    monkeypatch.setattr(evaluation, "create_engine", lambda _: SimpleNamespace(dispose=lambda: None))
    calls = [{"role": "info", "schema_name": "reborn_info_analysis", "http_status": 503,
              "model": "gpt-6.1-sol", "reasoning_effort": "xhigh"}]

    async def interrupted(engine, **kwargs):
        kwargs["on_calls"](calls)
        kwargs["on_trial"]({"repeat": 1, "verdict": "FAIL", "calls": calls,
                             "stored_failure": {"failure_code": "COMPONENT_UNAVAILABLE"}})
        raise asyncio.CancelledError

    monkeypatch.setattr(evaluation, "exercise_api", interrupted)
    args = SimpleNamespace(output=tmp_path / "api-report", repeats=3, validate_only=False)
    with pytest.raises(asyncio.CancelledError):
        evaluation.run(args)

    assert container.stopped is True
    assert (args.output / "manifest.json").is_file()
    assert (args.output / "trial-001.json").is_file()
    report = json.loads((args.output / "results.json").read_text())
    assert report["verdict"] == "INCOMPLETE"
    assert len(report["trials"]) == 1
    assert report["trials"][0]["stored_failure"]["failure_code"] == "COMPONENT_UNAVAILABLE"
    assert json.loads((args.output / "calls.json").read_text())["calls"][0]["http_status"] == 503
    assert not list(args.output.glob("*.tmp"))
