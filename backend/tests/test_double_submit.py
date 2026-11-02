"""같은 Case에 결과 제출이 동시에 두 번 오면 하나만 접수되는지. 진짜 MySQL이 필요하다.

"처리 중인지 확인"과 "새 이력 저장" 사이에 다른 요청이 끼는 상황이라, DB를 흉내 내면
재현되지 않는다. 격리된 mysql:8.0 컨테이너에 세션 두 개를 띄워 실제로 겹치게 만든다.
Docker와 requirements-dev.txt가 있어야 돈다(FE 합의문 2026-10-22 3-3).
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select
from testcontainers.community.mysql import MySqlContainer

from app.be.crud import case_history as case_history_crud
from app.be.crud.case_history import get_case_created_history
from app.be.crud.member import create_member
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import ConflictReference
from app.be.schemas.case import (
    CaseConflictsDecisionRequest,
    CaseCreateRequest,
    CaseResultsSubmitRequest,
)
from app.be.services.case import create_case, submit_case_conflicts_decision, submit_case_results


@pytest.fixture(scope="module")
def mysql_engine():
    container = MySqlContainer(
        "mysql:8.0", dialect="pymysql", username="test", password="test",
        root_password="test", dbname="double_submit_test",
    ).with_env("TZ", "Asia/Seoul")
    with container:
        engine = create_engine(container.get_connection_url() + "?charset=utf8mb4")
        try:
            SQLModel.metadata.create_all(engine)
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def case_ready_for_a_result(mysql_engine):
    """판단이 끝난 Case 하나. 이 상태에서는 결과 제출이 접수 가능하다."""

    with Session(mysql_engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
        case, _ = create_case(session, member.id, CaseCreateRequest(
            business_type="카페", franchise_status=False, employee_count=2,
            lease_status="LEASED_PAID",
        ))
        history = get_case_created_history(session, case.id)
        history.judgment_status = "DONE"
        session.commit()
        return member.id, history.id, case.id


def submit(engine, member_id: int, case_history_id: int) -> str:
    with Session(engine) as session:
        try:
            submit_case_results(
                session, member_id,
                CaseResultsSubmitRequest(raw_input="철거해야 한대요", case_history_id=case_history_id),
            )
            return "접수됨"
        except HTTPException as error:
            return f"거절됨 {error.status_code}"


@pytest.fixture
def both_threads_pass_the_checks_first(monkeypatch):
    """두 요청이 "확인"을 모두 마친 뒤에야 "저장"으로 넘어가게 맞춘다.

    경합은 그 사이에서만 일어난다. 스레드 두 개를 그냥 동시에 띄우면 앞사람이 저장까지
    끝내 버려서 재현되지 않는다. 잠금이 걸려 있으면 뒤에 온 쪽이 여기까지 오지도 못하므로,
    기다리다 시간이 지나면 그냥 진행한다.
    """

    from threading import BrokenBarrierError

    gate = Barrier(2, timeout=2)
    original = case_history_crud.create_case_history

    def create_after_the_other_thread_checked(session, case_history):
        try:
            gate.wait()
        except BrokenBarrierError:
            pass
        return original(session, case_history)

    monkeypatch.setattr(
        case_history_crud, "create_case_history", create_after_the_other_thread_checked
    )


def test_two_submissions_at_the_same_time_accept_only_one(
    mysql_engine, case_ready_for_a_result, both_threads_pass_the_checks_first
):
    """둘 다 접수되면 판단이 두 번 돌아 서로의 결과를 덮고, 같은 충돌을 두 번 확인하게 된다."""

    member_id, case_history_id, case_id = case_ready_for_a_result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(
            future.result()
            for future in [
                pool.submit(submit, mysql_engine, member_id, case_history_id) for _ in range(2)
            ]
        )

    assert results == ["거절됨 409", "접수됨"]

    with Session(mysql_engine) as session:
        pending = session.exec(
            select(CaseHistory).where(
                CaseHistory.case_id == case_id, CaseHistory.judgment_status == "PENDING"
            )
        ).all()

    assert len(pending) == 1


@pytest.fixture
def case_waiting_for_a_decision(mysql_engine):
    """결과 제출이 충돌로 끝나 사장님 결정을 기다리는 Case 하나."""

    with Session(mysql_engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
        case, _ = create_case(session, member.id, CaseCreateRequest(
            business_type="카페", franchise_status=False, employee_count=2,
            lease_status="LEASED_PAID",
        ))
        get_case_created_history(session, case.id).judgment_status = "DONE"
        submitted = case_history_crud.create_case_history(session, CaseHistory(
            case_id=case.id, raw_input="전체 철거래요", source="USER_INPUT",
            judgment_status="CONFLICT",
        ))
        conflict = ConflictReference(
            conflict_ref=str(uuid4()), case_id=case.id, case_history_id=submitted.id,
            canonical_field="restoration_scope", committed_value="PARTIAL", proposed_value="FULL",
        )
        session.add(conflict)
        session.commit()
        return member.id, conflict.id, case.id


def decide(engine, member_id: int, conflict_reference_id: int) -> str:
    with Session(engine) as session:
        try:
            submit_case_conflicts_decision(
                session, member_id,
                CaseConflictsDecisionRequest(
                    decisions=[{"conflict_reference_id": conflict_reference_id, "side": "PROPOSED"}]
                ),
            )
            return "접수됨"
        except HTTPException as error:
            return f"거절됨 {error.status_code}"


def test_two_decisions_at_the_same_time_accept_only_one(
    mysql_engine, case_waiting_for_a_decision, both_threads_pass_the_checks_first
):
    """결정도 둘 다 접수되면 판단이 두 번 돌아 서로의 결과를 덮는다."""

    member_id, conflict_reference_id, case_id = case_waiting_for_a_decision

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(
            future.result()
            for future in [
                pool.submit(decide, mysql_engine, member_id, conflict_reference_id) for _ in range(2)
            ]
        )

    assert results == ["거절됨 409", "접수됨"]

    with Session(mysql_engine) as session:
        pending = session.exec(
            select(CaseHistory).where(
                CaseHistory.case_id == case_id, CaseHistory.source == "CONFLICT_DECISION",
                CaseHistory.judgment_status == "PENDING",
            )
        ).all()

    assert len(pending) == 1
