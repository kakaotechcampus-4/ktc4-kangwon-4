"""서버가 판단 도중에 꺼져 남은 판단을 풀어 주는지 본다.

판단은 웹 서버 안에서 돈다. 배포하거나 서버가 꺼지면 돌던 판단이 그대로 사라지고 이력은
PENDING으로 남는데, Case는 "직전 제출을 아직 처리 중"이라며 새 제출을 409로 막는다.
풀어 주는 곳이 없으면 그 사장님은 영영 아무것도 못 한다.
"""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.be.crud import case_history as case_history_crud
from app.be.models.mixins import kst_now
from app.be.schemas.case import CaseResultsSubmitRequest
from app.be.services import case as case_service
from app.be.services import judgment as judgment_service
from tests.case_world import CaseWorld, case_engine, case_world  # noqa: F401


@pytest.fixture
def on_this_engine(case_engine, monkeypatch):  # noqa: F811
    monkeypatch.setattr(judgment_service, "get_engine", lambda: case_engine)
    return case_engine


def _age(engine, history_id: int, minutes: int) -> None:
    """그 판단이 몇 분 전에 들어온 것으로 돌려 놓는다."""

    with Session(engine) as session:
        history = case_history_crud.get_case_history_by_id(session, history_id)
        history.created_at = kst_now() - timedelta(minutes=minutes)
        session.commit()


def test_an_abandoned_judgment_lets_the_owner_submit_again(on_this_engine, case_world):  # noqa: F811
    member_id, case_id, signup = case_world.sign_up()
    _age(on_this_engine, signup, minutes=60)  # 멈춘 판단이 그대로 최신이어야 한다
    stuck = case_world.add_history(case_id, "USER_INPUT", "PENDING")
    _age(on_this_engine, stuck, minutes=30)

    with Session(on_this_engine) as session:
        with pytest.raises(HTTPException) as blocked:
            case_service.submit_case_results(
                session, member_id,
                CaseResultsSubmitRequest(case_history_id=stuck, raw_input="그 뒤로 어떻게 하죠"),
            )
    assert blocked.value.status_code == 409

    assert judgment_service.release_abandoned_judgments() == 1

    with Session(on_this_engine) as session:
        history = case_history_crud.get_case_history_by_id(session, stuck)
        assert history.judgment_status == "FAILED"
        # 서버가 꺼져서 끊긴 것이라 같은 글을 다시 보내면 된다. 문의로 보내지 않는다.
        assert history.recovery_action_code == "RETRY"
        assert history.retryable is True

        # 이제 사장님이 다시 보낼 수 있다.
        case_service.submit_case_results(
            session, member_id,
            CaseResultsSubmitRequest(case_history_id=stuck, raw_input="그 뒤로 어떻게 하죠"),
        )


def test_a_judgment_that_is_still_running_is_left_alone(on_this_engine, case_world):  # noqa: F811
    _, case_id, _ = case_world.sign_up()
    running = case_world.add_history(case_id, "USER_INPUT", "PENDING")
    _age(on_this_engine, running, minutes=3)  # AI 상한 7분 안쪽 — 아직 돌고 있을 수 있다

    assert judgment_service.release_abandoned_judgments() == 0

    with Session(on_this_engine) as session:
        assert case_history_crud.get_case_history_by_id(session, running).judgment_status == "PENDING"


def test_a_finished_judgment_is_left_alone(on_this_engine, case_world):  # noqa: F811
    _, case_id, _ = case_world.sign_up()
    done = case_world.add_history(case_id, "USER_INPUT", "DONE")
    _age(on_this_engine, done, minutes=30)

    assert judgment_service.release_abandoned_judgments() == 0

    with Session(on_this_engine) as session:
        assert case_history_crud.get_case_history_by_id(session, done).judgment_status == "DONE"
