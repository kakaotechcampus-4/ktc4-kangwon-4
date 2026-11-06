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
from case_world import case_engine, case_world  # noqa: F401 — 픽스처


@pytest.fixture
def on_this_engine(case_engine, monkeypatch):  # noqa: F811
    monkeypatch.setattr(judgment_service, "get_engine", lambda: case_engine)
    # 이 함수는 DB에 남은 처리 중 기록을 전부 본다. 앞 검사가 남긴 것이 섞이면 센 수가
    # 달라지므로 여기서 치우고 시작한다.
    with Session(case_engine) as session:
        for history in case_history_crud.get_pending_case_histories(session):
            history.judgment_status = "DONE"
        session.commit()
    return case_engine


def _age(engine, history_id: int, minutes: int) -> None:
    """그 판단이 몇 분 전에 들어온 것으로 돌려 놓는다."""

    with Session(engine) as session:
        history = case_history_crud.get_case_history_by_id(session, history_id)
        history.created_at = kst_now() - timedelta(minutes=minutes)
        session.commit()


def _status(engine, history_id: int) -> str:
    with Session(engine) as session:
        return case_history_crud.get_case_history_by_id(session, history_id).judgment_status


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


def test_a_judgment_abandoned_minutes_ago_is_released_too(on_this_engine, case_world):  # noqa: F811
    # 결과를 보내고 3분 뒤에 배포하면 그 판단도 서버와 같이 죽는다. 시간으로 거르면 이것이
    # 다음 배포 때까지 안 풀린다(현석님·승준님 #194). 서버가 막 떴으면 전부 죽은 판단이다.
    _, case_id, _ = case_world.sign_up()
    just_now = case_world.add_history(case_id, "USER_INPUT", "PENDING")
    _age(on_this_engine, just_now, minutes=3)

    assert judgment_service.release_abandoned_judgments() == 1
    assert _status(on_this_engine, just_now) == "FAILED"


def test_a_finished_judgment_is_left_alone(on_this_engine, case_world):  # noqa: F811
    _, case_id, _ = case_world.sign_up()
    done = case_world.add_history(case_id, "USER_INPUT", "DONE")
    _age(on_this_engine, done, minutes=30)

    assert judgment_service.release_abandoned_judgments() == 0
    assert _status(on_this_engine, done) == "DONE"


def test_a_judgment_that_finished_in_between_is_not_overwritten(
    on_this_engine, case_world, monkeypatch  # noqa: F811
):
    # 대상을 읽은 뒤 실패를 쓰기 전에 그 판단이 정상으로 끝날 수 있다(승준님 #194).
    # 그 결과를 FAILED로 덮으면 안 된다.
    _, case_id, _ = case_world.sign_up()
    racing = case_world.add_history(case_id, "USER_INPUT", "PENDING")
    read_pending = case_history_crud.get_pending_case_histories

    def read_then_let_it_finish(session):
        rows = read_pending(session)
        with Session(on_this_engine) as other:
            finished = case_history_crud.get_case_history_by_id(other, racing)
            finished.judgment_status = "DONE"
            other.commit()
        return rows

    monkeypatch.setattr(case_history_crud, "get_pending_case_histories", read_then_let_it_finish)

    assert judgment_service.release_abandoned_judgments() == 0
    assert _status(on_this_engine, racing) == "DONE"
