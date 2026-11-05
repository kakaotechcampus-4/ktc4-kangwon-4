"""AI를 기다리는 동안 DB 커넥션을 쥐고 있지 않은지 지킨다.

판단은 AI 응답을 50초쯤 기다린다. 그동안 커넥션을 쥐고 있으면 자리가 금방 바닥나서,
판단과 상관없는 사장님의 조회·로그인까지 막힌다(실측은 tests/test_pool_capacity.py).
여기서는 기다리는 그 순간에 쥔 커넥션이 0개인지만 본다.
"""

import asyncio

import pytest
from sqlalchemy import text

from app.be.services import conflict_decision as conflict_decision_service
from app.be.services import judgment as judgment_service
from tests.case_world import CaseWorld, case_engine, case_world  # noqa: F401


@pytest.fixture
def held_while_waiting(case_engine, monkeypatch):
    """AI를 기다리는 순간에 쥐고 있던 커넥션 수를 담아 돌려준다."""

    held: list[int] = []

    def watch(service):
        monkeypatch.setattr(service, "get_engine", lambda: case_engine)

        async def fake_agent(*args, **kwargs):
            held.append(case_engine.pool.checkedout())
            raise RuntimeError("여기서 멈춘다 — 이 검사는 커넥션만 본다")

        monkeypatch.setattr(service, "_ask_agent", fake_agent)

    watch(judgment_service)
    watch(conflict_decision_service)
    return held


def test_judgment_releases_its_connection_before_asking_the_agent(
    held_while_waiting, case_world  # noqa: F811
):
    _, case_id, _ = case_world.sign_up()
    history_id = case_world.add_history(case_id, "USER_INPUT", "PENDING")

    asyncio.run(judgment_service.run_judgment_in_background(history_id))

    assert held_while_waiting == [0]


def test_conflict_decision_releases_its_connection_before_asking_the_agent(
    held_while_waiting, case_engine, monkeypatch  # noqa: F811
):
    # 충돌 결정은 보관해 둔 원본이 있어야 입력을 만들 수 있다. 여기서 보려는 것은 그 복원이
    # 아니라 "읽기가 끝나면 세션을 닫고 AI를 부르는가"라서, 읽기는 커넥션만 한 번 쓰고 끝낸다.
    def read_with_a_real_query(session, _case_history_id, _choices):
        session.exec(text("SELECT 1"))
        assert case_engine.pool.checkedout() == 1
        return None, []

    monkeypatch.setattr(conflict_decision_service, "_read_decision_input", read_with_a_real_query)

    asyncio.run(conflict_decision_service.run_conflict_decision_in_background(1, {}))

    assert held_while_waiting == [0]
