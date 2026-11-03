"""Case 조회(GET /cases)의 상태별 응답. 준비물은 case_world.py."""

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.be.models.case_history import CaseHistory
from app.be.services.case import get_case

from case_world import case_engine, case_world  # noqa: F401 — 픽스처


def get(engine, member_id: int):
    with Session(engine) as session:
        return get_case(session, member_id)


def test_someone_without_a_case_gets_an_empty_answer_not_404(case_engine, case_world):
    """화면은 이 응답으로 가입 화면에 보낼지 정한다. 404면 그 판단을 에러 처리로 해야 한다."""

    response = get(case_engine, case_world.stranger())

    assert (response.case, response.judgment_status, response.case_history_id) == (None, None, None)


def test_more_questions_still_carry_the_blocker(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    case_world.add_history(case_id, "USER_INPUT", "NEEDS_MORE_INFO")

    response = get(case_engine, member_id)

    assert response.judgment_status == "NEEDS_MORE_INFO"
    assert response.blocker == "원상복구 범위를 모름"
    assert response.questions_for_user == ["원상복구 범위가 어디까지인가요?"]


def test_a_conflict_hides_the_history_id(case_engine, case_world):
    """충돌 중에는 결과 제출이 막혀 있어서, 제출에 쓸 번호를 화면에 주지 않는다."""

    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    case_world.add_conflict(case_id, conflicted)

    response = get(case_engine, member_id)

    assert (response.judgment_status, response.case_history_id) == ("CONFLICT", None)


def test_a_failed_decision_with_conflicts_left_shows_the_conflict_again(case_engine, case_world):
    """결정이 실패하면 충돌은 미결로 남는다. 홈이 실패 카드를 그리면 충돌 확인으로 돌아갈 길이 없다(#163)."""

    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    case_world.add_conflict(case_id, conflicted)
    case_world.add_history(case_id, "CONFLICT_DECISION", "FAILED")

    response = get(case_engine, member_id)

    assert (response.judgment_status, response.case_history_id) == ("CONFLICT", None)
    assert (response.recovery_action_code, response.retryable) == (None, None)


def test_a_decision_still_being_judged_stays_pending(case_engine, case_world):
    """처리 중에는 충돌이 남아 있어도 판단 중으로 보여야 한다(진입 조회와 같은 순서)."""

    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    case_world.add_conflict(case_id, conflicted)
    case_world.add_history(case_id, "CONFLICT_DECISION", "PENDING")

    assert get(case_engine, member_id).judgment_status == "PENDING"


def test_done_without_a_next_action_stops_instead_of_showing_an_empty_card(case_engine, case_world):
    """AI 계약상 DONE이면 다음 행동이 있다. 없으면 저장 코드가 깨진 것이라 빈 화면 대신 멈춘다."""

    member_id, _, signed_up = case_world.sign_up()
    with Session(case_engine) as session:
        session.get(CaseHistory, signed_up).next_action = None
        session.commit()

    with pytest.raises(HTTPException) as error:
        get(case_engine, member_id)

    assert error.value.status_code == 500
