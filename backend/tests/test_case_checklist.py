"""로드맵 체크리스트와 철거비 승인 결과를 저장하는지.

저장은 진짜 MySQL이 필요하다(격리된 mysql:8.0 컨테이너, Docker와 requirements-dev.txt 필요).
항목 이름 검사는 요청 타입만 보면 되어 DB 없이 돈다.
"""

from typing import get_args
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError
from sqlmodel import Session, SQLModel, create_engine, select
from testcontainers.community.mysql import MySqlContainer

from app.agent.roadmap import CHECKLIST_IDS
from app.be.crud.case import get_case_by_member_id
from app.be.crud.member import create_member
from app.be.models.case_checklist import CaseChecklist, CaseChecklistHistory
from app.be.schemas.case import CaseCreateRequest, ChecklistTaskId
from app.be.services.case import create_case, update_case_checklist, update_case_support_approval


@pytest.fixture(scope="module")
def mysql_engine():
    container = MySqlContainer(
        "mysql:8.0", dialect="pymysql", username="test", password="test",
        root_password="test", dbname="case_checklist_test",
    ).with_env("TZ", "Asia/Seoul")
    with container:
        engine = create_engine(container.get_connection_url() + "?charset=utf8mb4")
        try:
            SQLModel.metadata.create_all(engine)
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def member_id(mysql_engine):
    with Session(mysql_engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
        create_case(session, member.id, CaseCreateRequest(
            business_type="CAFE", franchise_status=False, employee_count=2,
            lease_status="LEASED_PAID",
        ))
        return member.id


def checked_tasks(engine, member_id: int) -> list[str]:
    with Session(engine) as session:
        case = get_case_by_member_id(session, member_id)
        return sorted(row.task_id for row in session.exec(
            select(CaseChecklist).where(CaseChecklist.case_id == case.id)
        ))


def history_of(engine, member_id: int) -> list[tuple[str, bool]]:
    with Session(engine) as session:
        case = get_case_by_member_id(session, member_id)
        return [(row.task_id, row.completed) for row in session.exec(
            select(CaseChecklistHistory).where(CaseChecklistHistory.case_id == case.id)
            .order_by(CaseChecklistHistory.id)
        )]


def check(engine, member_id: int, task_id: str, completed: bool) -> None:
    with Session(engine) as session:
        update_case_checklist(session, member_id, task_id, completed)


def test_checking_and_unchecking_a_task(mysql_engine, member_id):
    check(mysql_engine, member_id, "dispose_stock", True)
    check(mysql_engine, member_id, "notify_landlord", True)
    assert checked_tasks(mysql_engine, member_id) == ["dispose_stock", "notify_landlord"]

    check(mysql_engine, member_id, "dispose_stock", False)
    assert checked_tasks(mysql_engine, member_id) == ["notify_landlord"]


def test_sending_the_same_request_twice_changes_nothing(mysql_engine, member_id):
    """화면이 두 번 눌러도 같은 항목이 두 줄 생기거나 에러가 나지 않는다."""

    check(mysql_engine, member_id, "dispose_stock", True)
    check(mysql_engine, member_id, "dispose_stock", True)
    assert checked_tasks(mysql_engine, member_id) == ["dispose_stock"]

    check(mysql_engine, member_id, "dispose_stock", False)
    check(mysql_engine, member_id, "dispose_stock", False)
    assert checked_tasks(mysql_engine, member_id) == []


@pytest.mark.parametrize("approved", [True, False, None])
def test_support_approval_is_saved_as_told(mysql_engine, member_id, approved):
    with Session(mysql_engine) as session:
        update_case_support_approval(session, member_id, True)
        update_case_support_approval(session, member_id, approved)

    with Session(mysql_engine) as session:
        assert get_case_by_member_id(session, member_id).support_approved is approved


def test_someone_without_a_case_gets_404(mysql_engine):
    with Session(mysql_engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="가입 전 사용자")
        session.commit()
        for call in (
            lambda: update_case_checklist(session, member.id, "dispose_stock", True),
            lambda: update_case_support_approval(session, member.id, True),
        ):
            with pytest.raises(HTTPException) as error:
                call()
            assert error.value.status_code == 404


def test_checkable_tasks_are_exactly_the_roadmap_checklist():
    """AI 로드맵이 체크 항목을 바꾸면 BE가 받는 항목도 같이 바뀌어야 한다."""

    assert set(get_args(ChecklistTaskId)) == CHECKLIST_IDS


@pytest.mark.parametrize("task_id", ["restoration", "intake", "unknown_task"])
def test_tasks_that_are_not_user_checklists_are_rejected(task_id):
    """공식 절차(AI가 판단)나 가입 항목은 사장님이 체크로 완료할 수 없다."""

    with pytest.raises(ValidationError):
        TypeAdapter(ChecklistTaskId).validate_python(task_id)


def test_checking_and_unchecking_both_stay_in_the_history(mysql_engine, member_id):
    """지금 상태는 풀면 지우지만, 기록 탭에는 체크했다가 푼 것까지 남아야 한다."""

    check(mysql_engine, member_id, "dispose_stock", True)
    check(mysql_engine, member_id, "dispose_stock", False)
    check(mysql_engine, member_id, "dispose_stock", True)

    assert history_of(mysql_engine, member_id) == [
        ("dispose_stock", True), ("dispose_stock", False), ("dispose_stock", True),
    ]


def test_a_request_that_changes_nothing_adds_no_history(mysql_engine, member_id):
    check(mysql_engine, member_id, "dispose_stock", False)
    check(mysql_engine, member_id, "dispose_stock", True)
    check(mysql_engine, member_id, "dispose_stock", True)

    assert history_of(mysql_engine, member_id) == [("dispose_stock", True)]


def test_reporting_the_support_result_stamps_when(mysql_engine, member_id):
    with Session(mysql_engine) as session:
        assert get_case_by_member_id(session, member_id).support_approved_at is None
        update_case_support_approval(session, member_id, False)

    with Session(mysql_engine) as session:
        assert get_case_by_member_id(session, member_id).support_approved_at is not None
