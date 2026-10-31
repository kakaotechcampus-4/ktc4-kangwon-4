"""결과 제출이 AI 판단까지 이어지는지. DB 연결 없이 호출만 바꿔 끼운다.

접수만 하고 아무도 판단을 부르지 않으면 그 이력은 PENDING에서 안 바뀐다. 그리고 제출
입력을 가입 입력이라고 넘기면 AI가 방금 받은 진행 상황을 "처음 받은 값"으로 읽는다.
그 두 경계만 본다.
"""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks
from sqlmodel import Session

from app.be.crud import case_history as case_history_crud
from app.be.routers import case as case_router
from app.be.schemas.case import CaseResultsSubmitAcceptedResponse, CaseResultsSubmitRequest
from app.be.services import case as case_service
from app.be.services import judgment
from app.be.services import agent_runtime as agent_runtime_service
from app.be.services import case_snapshot as case_snapshot_service
from app.be.services import decision_record as decision_record_service
from app.be.services import reviewed_procedure as reviewed_procedure_service

CASE_ID = 7
HISTORY_ID = 42
SUBMITTED_AT = datetime(2026, 10, 20, 9, 0, 0)


def history(source: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=HISTORY_ID,
        case_id=CASE_ID,
        raw_input="원상복구 끝냈어요",
        source=source,
        created_at=SUBMITTED_AT,
    )


@pytest.fixture
def trigger_of(monkeypatch):
    """판단을 한 번 돌리고, AI 입구에 어느 트리거로 넘어갔는지 돌려준다."""

    captured: dict[str, str] = {}

    def fake_build_planning_input(*, trigger_type, **_kwargs):
        captured["trigger_type"] = trigger_type
        return SimpleNamespace(trigger=trigger_type)

    async def fake_run_case_planning(*_args, **_kwargs):
        return SimpleNamespace(outcome_type="SAFE_FAILURE")

    monkeypatch.setattr(judgment, "build_planning_input", fake_build_planning_input)
    monkeypatch.setattr(judgment, "run_case_planning", fake_run_case_planning)
    monkeypatch.setattr(case_snapshot_service, "build_case_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr(case_snapshot_service, "build_user_input", lambda **_k: None)
    monkeypatch.setattr(agent_runtime_service, "build_known_procedure_steps", lambda *_a: [])
    monkeypatch.setattr(agent_runtime_service, "empty_support_catalog", lambda: None)
    monkeypatch.setattr(reviewed_procedure_service, "load_reviewed_procedures", lambda: None)
    monkeypatch.setattr(decision_record_service, "save_safe_failure", lambda *_a, **_k: None)

    def run(source: str) -> str:
        monkeypatch.setattr(
            case_history_crud, "get_case_history_by_id", lambda *_a: history(source)
        )
        asyncio.run(judgment.run_judgment(MagicMock(spec=Session), HISTORY_ID))
        return captured["trigger_type"]

    return run


def test_signup_input_is_judged_as_a_new_case(trigger_of):
    assert trigger_of("CASE_CREATED") == "CASE_CREATED"


def test_submitted_result_is_judged_as_a_result_report(trigger_of):
    # 이 값이 가입으로 넘어가면 AI가 사장님이 방금 알려준 진행 상황을 처음 받은 값으로 읽는다.
    assert trigger_of("USER_INPUT") == "RESULT_SUBMITTED"


def test_a_source_nobody_creates_stops_instead_of_guessing(trigger_of):
    with pytest.raises(judgment.UnknownJudgmentTriggerError, match="SYSTEM_BATCH"):
        trigger_of("SYSTEM_BATCH")


def test_an_untranslatable_source_tells_the_user_to_contact_support(monkeypatch):
    """다시 눌러도 같은 행의 같은 출처를 또 읽는다. "다시 시도"는 눌러도 안 되는 버튼이다."""

    failed = SimpleNamespace(
        judgment_status="PENDING", failure_code=None,
        recovery_action_code=None, retryable=None, requested_field_paths=None,
    )
    monkeypatch.setattr(case_history_crud, "get_case_history_by_id", lambda *_: failed)

    decision_record_service.mark_judgment_failed(
        MagicMock(spec=Session), HISTORY_ID, judgment.UnknownJudgmentTriggerError("합성 결함")
    )

    assert failed.recovery_action_code == "CONTACT_SUPPORT"
    assert failed.retryable is False


def test_submitting_a_result_schedules_the_judgment(monkeypatch):
    """접수만 하고 끝내면 그 이력은 PENDING에서 영영 안 바뀐다."""

    monkeypatch.setattr(
        case_service,
        "submit_case_results",
        lambda *_a: CaseResultsSubmitAcceptedResponse(case_history_id=HISTORY_ID),
    )
    background_tasks = BackgroundTasks()

    case_router.submit_case_results(
        CaseResultsSubmitRequest(raw_input="원상복구 끝냈어요", case_history_id=5),
        background_tasks,
        member_id=1,
        session=MagicMock(spec=Session),
    )

    assert [task.func for task in background_tasks.tasks] == [
        judgment.run_judgment_in_background
    ]
    # 사장님이 보고 있던 직전 이력(5)이 아니라 방금 접수한 이력을 판단해야 한다.
    assert [task.args for task in background_tasks.tasks] == [(HISTORY_ID,)]
