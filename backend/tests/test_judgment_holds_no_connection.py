"""AI를 기다리는 동안 DB 커넥션을 쥐고 있지 않은지 지킨다.

판단은 AI 응답을 50초쯤 기다린다. 그동안 커넥션을 쥐고 있으면 자리가 금방 바닥나서,
판단과 상관없는 사장님의 조회·로그인까지 막힌다(실측은 tests/test_pool_capacity.py).

배경 함수만 따로 부르면 0개로 보이지만, 실제 요청에는 요청에 딸린 세션이 하나 더 있고
그 세션은 배경 작업이 끝나야 정리된다(승준님 #193). 그래서 실제 HTTP 요청으로도 본다.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.be.db import get_db
from app.be.routers.auth import get_current_member_id
from app.be.schemas.case import CaseCreateRequest
from app.be.services import conflict_decision as conflict_decision_service
from app.be.services import judgment as judgment_service
from app.main import app
from case_world import case_engine, case_world  # noqa: F401 — 픽스처


@pytest.fixture
def held_while_waiting(case_engine, monkeypatch):  # noqa: F811
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


@pytest.fixture
def isolated_lifespan(case_engine, monkeypatch):  # noqa: F811
    # get_db 교체는 startup에 적용되지 않는다. 같은 격리 DB를 쓰고 개발 DB 초기화를 막는다.
    monkeypatch.setattr("app.main.get_engine", lambda: case_engine)
    monkeypatch.setattr(judgment_service, "get_engine", lambda: case_engine)
    monkeypatch.setattr("app.main.get_settings", lambda: SimpleNamespace(ENVIRONMENT="prod"))


@pytest.fixture
def client(case_engine, member_id, isolated_lifespan):  # noqa: F811
    """진짜 라우터·인증 의존성·BackgroundTasks를 그대로 타는 손님."""

    def db():
        with Session(case_engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_member_id] = lambda: member_id
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


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


@pytest.fixture
def member_id(case_world):  # noqa: F811
    return case_world.sign_up()[0]


def test_a_real_post_also_leaves_no_connection_held(
    held_while_waiting, client, member_id, case_world, case_engine  # noqa: F811
):
    # 요청에 딸린 세션까지 포함해서 본다. 배경 함수만 부르면 이 한 개가 안 보인다.
    from app.be.crud import case as case_crud

    with Session(case_engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        history_id = case_world.add_history(case.id, "USER_INPUT", "DONE")

    response = client.post(
        "/cases/results", json={"case_history_id": history_id, "raw_input": "철거 끝냈어요"}
    )

    assert response.status_code == 200
    assert held_while_waiting == [0]


def test_retrying_over_http_also_leaves_no_connection_held(
    held_while_waiting, client, member_id, case_world, case_engine  # noqa: F811
):
    # 홈의 [다시 판단하기](POST /cases/retry)도 같은 판단을 뒤에서 건다(#196)
    from app.be.crud import case as case_crud

    with Session(case_engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
    case_world.add_history(case.id, "USER_INPUT", "FAILED")

    response = client.post("/cases/retry")

    assert response.status_code == 200
    assert held_while_waiting == [0]


def test_signing_up_over_http_also_leaves_no_connection_held(
    held_while_waiting, case_engine, isolated_lifespan  # noqa: F811
):
    from app.be.crud.member import create_member

    with Session(case_engine) as session:
        from uuid import uuid4

        member = create_member(session, oauth_id=str(uuid4()), nickname="가입 손님")
        session.commit()
        new_member_id = member.id

    def db():
        with Session(case_engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_member_id] = lambda: new_member_id
    try:
        with TestClient(app) as test_client:
            response = test_client.post("/cases", json=CaseCreateRequest(
                business_type="CAFE", franchise_status=False, employee_count=2,
                lease_status="LEASED_PAID",
            ).model_dump())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert held_while_waiting == [0]
