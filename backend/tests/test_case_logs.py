"""기록 탭 API(GET /cases/logs)가 판단 이력에서 사장님·리본 기록을 맞게 만드는지.

진짜 MySQL이 필요하다(격리된 mysql:8.0 컨테이너, Docker와 requirements-dev.txt 필요).
"""

from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine
from testcontainers.community.mysql import MySqlContainer

from app.be.crud import case_history as case_history_crud
from app.be.crud.case_history import get_case_created_history
from app.be.crud.member import create_member
from app.be.models.case_history import CaseHistory
from app.be.schemas.case import CaseCreateRequest
from app.be.services.case import create_case, get_case_logs
from app.be.services.decision_record import mark_judgment_failed

SIGNED_UP = datetime(2026, 10, 14, 9, 0, 0)


@pytest.fixture(scope="module")
def mysql_engine():
    container = MySqlContainer(
        "mysql:8.0", dialect="pymysql", username="test", password="test",
        root_password="test", dbname="case_logs_test",
    ).with_env("TZ", "Asia/Seoul")
    with container:
        engine = create_engine(container.get_connection_url() + "?charset=utf8mb4")
        try:
            SQLModel.metadata.create_all(engine)
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def signed_up(mysql_engine):
    """가입만 한 Case. 가입 이력은 아직 판단 중(PENDING)이다."""

    with Session(mysql_engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
        case, _ = create_case(session, member.id, CaseCreateRequest(
            business_type="CAFE", franchise_status=False, employee_count=2,
            lease_status="LEASED_PAID",
        ))
        get_case_created_history(session, case.id).created_at = SIGNED_UP
        session.commit()
        return member.id, case.id


def finish_sign_up(engine, case_id: int, judged_at: datetime) -> None:
    with Session(engine) as session:
        history = get_case_created_history(session, case_id)
        history.judgment_status = "DONE"
        history.judged_at = judged_at
        session.commit()


def add_history(engine, case_id: int, source: str, status: str, created_at: datetime,
                judged_at: datetime | None = None) -> int:
    with Session(engine) as session:
        history = case_history_crud.create_case_history(session, CaseHistory(
            case_id=case_id, source=source, judgment_status=status,
            raw_input=None if source == "CONFLICT_DECISION" else "결과 글",
            created_at=created_at, judged_at=judged_at,
        ))
        session.commit()
        return history.id


def logs_of(engine, member_id: int) -> list[tuple[str, str, datetime]]:
    with Session(engine) as session:
        return [(log.actor, log.event, log.occurred_at) for log in get_case_logs(session, member_id).logs]


def test_a_finished_sign_up_shows_the_ribbon_judgment_above_the_owner_input(mysql_engine, signed_up):
    member_id, case_id = signed_up
    finish_sign_up(mysql_engine, case_id, datetime(2026, 10, 14, 9, 2, 0))

    assert logs_of(mysql_engine, member_id) == [
        ("RIBBON", "NEXT_ACTION_DECIDED", datetime(2026, 10, 14, 9, 2, 0)),
        ("OWNER", "CASE_CREATED", SIGNED_UP),
    ]


def test_a_judgment_still_running_has_no_ribbon_log(mysql_engine, signed_up):
    member_id, _ = signed_up

    assert logs_of(mysql_engine, member_id) == [("OWNER", "CASE_CREATED", SIGNED_UP)]


@pytest.mark.parametrize(("status", "event"), [
    ("NEEDS_MORE_INFO", "MORE_INFO_REQUESTED"),
    ("CONFLICT", "CONFLICT_FOUND"),
    ("FAILED", "JUDGMENT_FAILED"),
])
def test_each_judgment_result_becomes_its_own_ribbon_event(mysql_engine, signed_up, status, event):
    member_id, case_id = signed_up
    submitted = datetime(2026, 10, 17, 14, 0, 0)
    add_history(mysql_engine, case_id, "USER_INPUT", status, submitted, datetime(2026, 10, 17, 14, 2, 0))

    assert logs_of(mysql_engine, member_id)[:2] == [
        ("RIBBON", event, datetime(2026, 10, 17, 14, 2, 0)),
        ("OWNER", "RESULT_SUBMITTED", submitted),
    ]


def test_logs_come_newest_first_across_every_kind_of_input(mysql_engine, signed_up):
    member_id, case_id = signed_up
    finish_sign_up(mysql_engine, case_id, datetime(2026, 10, 14, 9, 2, 0))
    add_history(mysql_engine, case_id, "USER_INPUT", "CONFLICT",
                datetime(2026, 10, 17, 14, 0, 0), datetime(2026, 10, 17, 14, 2, 0))
    add_history(mysql_engine, case_id, "CONFLICT_DECISION", "PENDING", datetime(2026, 10, 18, 10, 0, 0))

    assert [event for _, event, _ in logs_of(mysql_engine, member_id)] == [
        "CONFLICT_DECIDED",
        "CONFLICT_FOUND",
        "RESULT_SUBMITTED",
        "NEXT_ACTION_DECIDED",
        "CASE_CREATED",
    ]


def test_saving_a_judgment_result_stamps_when_it_finished(mysql_engine, signed_up):
    """판단 저장 코드가 judged_at을 찍지 않으면 리본 기록이 영영 안 생긴다."""

    member_id, case_id = signed_up
    history_id = add_history(mysql_engine, case_id, "USER_INPUT", "PENDING", datetime(2026, 10, 17, 14, 0, 0))

    with Session(mysql_engine) as session:
        mark_judgment_failed(session, history_id)

    assert ("RIBBON", "JUDGMENT_FAILED") in [(actor, event) for actor, event, _ in logs_of(mysql_engine, member_id)]


def test_someone_without_a_case_gets_404(mysql_engine):
    with Session(mysql_engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="가입 전 사용자")
        session.commit()
        with pytest.raises(HTTPException) as error:
            get_case_logs(session, member.id)

    assert error.value.status_code == 404


def test_when_both_happen_in_the_same_second_the_ribbon_log_stays_on_top(mysql_engine, signed_up):
    """DB 시각은 초 단위라 판단이 빨리 끝나면 보낸 시각과 같아질 수 있다. 그래도 보낸 뒤에 판단한 것이다."""

    member_id, case_id = signed_up
    finish_sign_up(mysql_engine, case_id, SIGNED_UP)

    assert [actor for actor, _, _ in logs_of(mysql_engine, member_id)] == ["RIBBON", "OWNER"]
