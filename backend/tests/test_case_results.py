"""결과 알려주기 흐름의 세 API. 준비물은 case_world.py.

- POST /cases/results — 결과 제출 접수
- GET /cases/results — /case의 "결과 알려주기" 진입 조회
- GET /cases/results/status — 제출 뒤 처리 상태 조회
"""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session

from app.be.models.case_history import CaseHistory
from app.be.schemas.case import CaseResultsSubmitRequest
from app.be.services.case import (
    get_case_results_entry,
    get_case_results_submit_status,
    submit_case_results,
)

from case_world import case_engine, case_world  # noqa: F401 — 픽스처


def submit(engine, member_id: int, case_history_id: int):
    with Session(engine) as session:
        return submit_case_results(
            session, member_id, CaseResultsSubmitRequest(raw_input="전체 철거래요", case_history_id=case_history_id)
        )


def entry(engine, member_id: int):
    with Session(engine) as session:
        return get_case_results_entry(session, member_id)


def status(engine, member_id: int, case_history_id: int):
    with Session(engine) as session:
        return get_case_results_submit_status(session, member_id, case_history_id)


def error_of(call) -> tuple[int, str]:
    with pytest.raises(HTTPException) as error:
        call()
    return error.value.status_code, error.value.detail


# ---------- POST /cases/results ----------

def test_a_result_on_the_latest_judgment_is_accepted(case_engine, case_world):
    member_id, _, signed_up = case_world.sign_up()

    accepted = submit(case_engine, member_id, signed_up)

    with Session(case_engine) as session:
        history = session.get(CaseHistory, accepted.case_history_id)
        assert (history.source, history.judgment_status, history.raw_input) == ("USER_INPUT", "PENDING", "전체 철거래요")


def test_submitting_without_a_case_is_404(case_engine, case_world):
    assert error_of(lambda: submit(case_engine, case_world.stranger(), 1))[0] == 404


def test_submitting_while_a_conflict_waits_is_409(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    case_world.add_conflict(case_id, conflicted)

    assert error_of(lambda: submit(case_engine, member_id, conflicted)) == (409, "확인 대기 중인 충돌이 있습니다.")


def test_submitting_while_the_last_one_is_judged_is_409(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    running = case_world.add_history(case_id, "USER_INPUT", "PENDING")

    assert error_of(lambda: submit(case_engine, member_id, running)) == (409, "직전 제출을 아직 처리 중입니다.")


def test_submitting_on_an_old_judgment_is_409(case_engine, case_world):
    member_id, case_id, signed_up = case_world.sign_up()
    case_world.add_history(case_id, "USER_INPUT", "DONE")

    assert error_of(lambda: submit(case_engine, member_id, signed_up)) == (409, "최신 판단에 대해 요청을 주지 않았습니다.")


# ---------- GET /cases/results ----------

def test_entry_shows_pending_before_the_conflict_while_a_decision_is_judged(case_engine, case_world):
    """결정을 받아도 충돌은 판단이 성공해야 닫힌다. 처리 중을 먼저 보지 않으면 확인 화면이 다시 뜬다."""

    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    case_world.add_conflict(case_id, conflicted)
    deciding = case_world.add_history(case_id, "CONFLICT_DECISION", "PENDING")

    response = entry(case_engine, member_id)

    assert (response.judgment_status, response.case_history_id) == ("PENDING", deciding)


def test_entry_shows_the_waiting_conflict(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    conflict_id = case_world.add_conflict(case_id, conflicted)

    response = entry(case_engine, member_id)

    assert response.judgment_status == "CONFLICT"
    assert [item.id for item in response.conflicts] == [conflict_id]
    assert response.raw_input == "결과 글"


def test_entry_shows_the_conflict_again_after_a_failed_decision(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    case_world.add_conflict(case_id, conflicted)
    case_world.add_history(case_id, "CONFLICT_DECISION", "FAILED")

    assert entry(case_engine, member_id).judgment_status == "CONFLICT"


def test_entry_shows_the_next_action_when_done(case_engine, case_world):
    member_id, _, signed_up = case_world.sign_up()

    response = entry(case_engine, member_id)

    assert (response.judgment_status, response.case_history_id) == ("DONE", signed_up)
    assert response.next_action.title == "임대인에게 원상복구 범위 묻기"


def test_entry_shows_how_to_recover_when_failed(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    case_world.add_history(case_id, "USER_INPUT", "FAILED")

    response = entry(case_engine, member_id)

    assert (response.judgment_status, response.recovery_action_code, response.retryable) == ("FAILED", "RETRY", True)


# ---------- GET /cases/results/status ----------

def test_status_of_an_old_submission_is_409(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    old = case_world.add_history(case_id, "USER_INPUT", "DONE")
    case_world.add_history(case_id, "USER_INPUT", "DONE")

    assert error_of(lambda: status(case_engine, member_id, old)) == (409, "최신 판단에 대해 요청을 주지 않았습니다.")


def test_status_while_judged_is_pending(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    running = case_world.add_history(case_id, "USER_INPUT", "PENDING")

    assert status(case_engine, member_id, running).result == "PENDING"


def test_status_can_follow_a_conflict_decision(case_engine, case_world):
    """결정 접수도 같은 조회로 결과를 기다린다. 가입·결과 제출 이력만 보면 결정 번호를 못 찾는다."""

    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    case_world.add_conflict(case_id, conflicted)
    deciding = case_world.add_history(case_id, "CONFLICT_DECISION", "PENDING")

    assert status(case_engine, member_id, deciding).result == "PENDING"


def test_status_reports_updated_with_the_changes(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    done = case_world.add_history(case_id, "USER_INPUT", "DONE")
    case_world.add_change(case_id, done)

    response = status(case_engine, member_id, done)

    assert response.result == "UPDATED"
    assert [(c.field, c.stored_value, c.new_value) for c in response.changes] == [("restoration_scope", "UNKNOWN", "FULL")]


def test_status_reports_no_change_when_nothing_moved(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    done = case_world.add_history(case_id, "USER_INPUT", "DONE")

    assert status(case_engine, member_id, done).result == "NO_CHANGE"


def test_status_stops_on_a_conflict_without_any_open_conflict(case_engine, case_world):
    """CONFLICT인데 보여줄 충돌이 없으면 빈 확인 화면 대신 멈춘다(저장 코드가 깨진 경우)."""

    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")

    assert error_of(lambda: status(case_engine, member_id, conflicted))[0] == 500


def test_results_text_is_limited_to_2000_characters():
    """묶은 글 전체를 2,000자로 센다. 넘으면 FastAPI가 422를 준다(제한이 없을 땐 TEXT 칸을 넘어 500)."""

    CaseResultsSubmitRequest(raw_input="가" * 2000, case_history_id=1)
    with pytest.raises(ValidationError):
        CaseResultsSubmitRequest(raw_input="가" * 2001, case_history_id=1)
