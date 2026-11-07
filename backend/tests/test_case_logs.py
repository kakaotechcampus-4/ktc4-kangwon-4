"""기록 탭 API(GET /cases/logs)가 판단 이력에서 사장님·리본 기록을 맞게 만드는지.

진짜 MySQL이 필요하다(격리된 mysql:8.0 컨테이너, Docker와 requirements-dev.txt 필요).
"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine
from testcontainers.community.mysql import MySqlContainer

from app.be.db import MYSQL_IMAGE
from app.be.crud import case_history as case_history_crud
from app.be.crud.case_history import get_case_created_history
from app.be.crud.member import create_member
from app.be.models.case_history import CaseHistory
from app.be.models.case_document_history import CaseDocumentHistory
from app.be.schemas.case import CaseCreateRequest
from app.be.services import procedure_registry
from app.be.services.case import create_case, get_case_logs, update_case_checklist, update_case_support_approval
from app.be.services.decision_record import mark_judgment_failed

SIGNED_UP = datetime(2026, 10, 14, 9, 0, 0)


@pytest.fixture(scope="module")
def mysql_engine():
    container = MySqlContainer(
        MYSQL_IMAGE, dialect="pymysql", username="test", password="test",
        root_password="test", dbname="case_logs_test",
    ).with_env("TZ", "Asia/Seoul")
    with container:
        engine = create_engine(container.get_connection_url() + "?charset=utf8mb4")
        try:
            SQLModel.metadata.create_all(engine)
            # 앱이 뜰 때 하는 절차 적재를 그대로 한다(main.lifespan). 없으면 create_case가 멈춘다.
            with Session(engine) as session:
                procedure_registry.ensure_cafe_procedure_registry(session)
                session.commit()
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
        # 비교하기 쉽게 시간대를 뗀다. 시간대가 붙는지는 따로 본다.
        return [(log.actor, log.event, log.occurred_at.replace(tzinfo=None))
                for log in get_case_logs(session, member_id).logs]


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
    ("PENDING", None), ("FAILED", "JUDGMENT_FAILED"),
    ("CONFLICT", "CONFLICT_FOUND"), ("DONE", "NEXT_ACTION_DECIDED"),
    ("NEEDS_MORE_INFO", "MORE_INFO_REQUESTED"),
])
def test_document_judgment_keeps_upload_and_ribbon_logs_without_an_extra_owner_log(mysql_engine, signed_up, status, event):
    member_id, case_id = signed_up
    uploaded = SIGNED_UP + timedelta(days=1)
    judged = uploaded + timedelta(minutes=1) if event else None
    history_id = add_history(mysql_engine, case_id, "DOCUMENT_SUBMITTED", status, uploaded, judged)
    with Session(mysql_engine) as session:
        session.add(CaseDocumentHistory(case_id=case_id, action="UPLOADED", document_kind="LEASE", created_at=uploaded))
        session.add(CaseDocumentHistory(case_id=case_id, action="CHECKED", created_at=uploaded))
        if status == "DONE":
            session.get(CaseHistory, history_id).next_action = "임대인에게 준비사항 확인"
        session.commit()
    logs = items_of(mysql_engine, member_id)
    assert not any(log.event == "DOCUMENT_SUBMITTED" for log in logs)
    assert [(log.actor, log.detail) for log in logs if log.event == "DOCUMENT_UPLOADED"] == [("OWNER", "LEASE")]
    assert [(log.actor, log.event) for log in logs if log.event == "DOCUMENTS_CHECKED"] == [("RIBBON", "DOCUMENTS_CHECKED")]
    judgments = [log for log in logs if log.event in {"NEXT_ACTION_DECIDED", "JUDGMENT_FAILED", "CONFLICT_FOUND", "MORE_INFO_REQUESTED"}]
    assert [(log.actor, log.event, log.detail) for log in judgments] == (
        [("RIBBON", event, "임대인에게 준비사항 확인" if status == "DONE" else None)] if event else []
    )


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


def items_of(engine, member_id: int):
    with Session(engine) as session:
        return get_case_logs(session, member_id).logs


def test_times_go_out_in_korean_time(mysql_engine, signed_up):
    """시간대 없이 주면 브라우저가 자기 시간대로 읽어서, 한국 밖에서 보면 시각이 밀린다."""

    member_id, _ = signed_up

    occurred_at = items_of(mysql_engine, member_id)[0].occurred_at

    assert occurred_at.utcoffset() == timedelta(hours=9)
    assert occurred_at.isoformat() == "2026-10-14T09:00:00+09:00"


def test_a_decided_next_action_carries_its_title(mysql_engine, signed_up):
    member_id, case_id = signed_up
    finish_sign_up(mysql_engine, case_id, datetime(2026, 10, 14, 9, 2, 0))
    with Session(mysql_engine) as session:
        get_case_created_history(session, case_id).next_action = "임대인에게 원상복구 범위 묻기"
        session.commit()

    ribbon = items_of(mysql_engine, member_id)[0]

    assert (ribbon.event, ribbon.detail) == ("NEXT_ACTION_DECIDED", "임대인에게 원상복구 범위 묻기")


def test_checking_and_unchecking_both_show_up(mysql_engine, signed_up):
    member_id, _ = signed_up
    with Session(mysql_engine) as session:
        update_case_checklist(session, member_id, "dispose_stock", True)
        update_case_checklist(session, member_id, "dispose_stock", False)

    checks = [(log.event, log.task_id) for log in items_of(mysql_engine, member_id) if log.task_id]

    assert sorted(checks) == [("CHECKLIST_COMPLETED", "dispose_stock"), ("CHECKLIST_UNCHECKED", "dispose_stock")]


@pytest.mark.parametrize(("approved", "detail"), [(True, "APPROVED"), (False, "REJECTED"), (None, "UNKNOWN")])
def test_the_reported_support_result_shows_up_with_its_value(mysql_engine, signed_up, approved, detail):
    member_id, _ = signed_up
    with Session(mysql_engine) as session:
        update_case_support_approval(session, member_id, approved)

    reported = [log for log in items_of(mysql_engine, member_id) if log.event == "SUPPORT_RESULT_REPORTED"]

    assert [(log.actor, log.detail) for log in reported] == [("OWNER", detail)]


def test_no_support_log_until_the_owner_reports_one(mysql_engine, signed_up):
    member_id, _ = signed_up

    assert all(log.event != "SUPPORT_RESULT_REPORTED" for log in items_of(mysql_engine, member_id))
