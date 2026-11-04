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
from app.be.schemas.case import (
    CaseConflictsDecisionRequest,
    CaseCreateRequest,
    CaseResultsSubmitRequest,
    ChecklistTaskId,
)
from app.be.services import procedure_registry
from app.be.services.case import (
    create_case,
    get_case,
    submit_case_conflicts_decision,
    submit_case_results,
    update_case_checklist,
    update_case_support_approval,
)


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
            # 앱이 뜰 때 하는 절차 적재를 그대로 한다(main.lifespan). 없으면 create_case가 멈춘다.
            with Session(engine) as session:
                procedure_registry.ensure_cafe_procedure_registry(session)
                session.commit()
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


def test_browsers_may_send_put_to_the_checklist_api():
    """CORS가 GET·POST만 열려 있으면 브라우저가 PUT 요청을 보내기 전 확인(preflight)에서 막는다."""

    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).options(
        "/cases/checklists/dispose_stock",
        headers={"Origin": "https://example.com", "Access-Control-Request-Method": "PUT"},
    )

    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]


def test_reporting_the_vat_filing_closes_the_case(mysql_engine, member_id):
    """시안: [신고했어요] → "폐업 정리를 모두 마쳤어요". FE는 case_status만 보고 완료 화면을 그린다."""

    check(mysql_engine, member_id, "vat_submission", True)

    with Session(mysql_engine) as session:
        case = get_case_by_member_id(session, member_id)
        assert case.case_status == "COMPLETED" and case.completed_at is not None
        assert get_case(session, member_id).case.case_status == "COMPLETED"


def test_unchecking_the_vat_filing_reopens_the_case(mysql_engine, member_id):
    """실수로 눌렀다가 풀면 다시 진행 중이다."""

    check(mysql_engine, member_id, "vat_submission", True)
    check(mysql_engine, member_id, "vat_submission", False)

    with Session(mysql_engine) as session:
        case = get_case_by_member_id(session, member_id)
        assert (case.case_status, case.completed_at) == ("IN_PROGRESS", None)


def test_other_tasks_do_not_close_the_case(mysql_engine, member_id):
    check(mysql_engine, member_id, "income_tax", True)

    with Session(mysql_engine) as session:
        assert get_case_by_member_id(session, member_id).case_status == "IN_PROGRESS"


def test_a_closed_case_takes_no_more_results_or_decisions(mysql_engine, member_id):
    """AI는 진행 중인 Case만 판단한다. 완료 뒤 판단을 돌리면 AI 입력 검사에서 거절된다."""

    check(mysql_engine, member_id, "vat_submission", True)

    with Session(mysql_engine) as session:
        latest = get_case(session, member_id).case_history_id
        for call in (
            lambda: submit_case_results(
                session, member_id, CaseResultsSubmitRequest(raw_input="결과 글", case_history_id=latest)
            ),
            lambda: submit_case_conflicts_decision(
                session, member_id, CaseConflictsDecisionRequest(
                    decisions=[{"conflict_reference_id": 1, "side": "PROPOSED"}]
                ),
            ),
        ):
            with pytest.raises(HTTPException) as error:
                call()
            assert error.value.status_code == 409
            assert error.value.detail == "폐업 정리를 마친 Case입니다."
            session.rollback()


def signed_up(engine, **overrides) -> int:
    fields = dict(business_type="CAFE", franchise_status=False, employee_count=2, lease_status="LEASED_PAID")
    fields.update(overrides)
    with Session(engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
        create_case(session, member.id, CaseCreateRequest(**fields))
        return member.id


def rejected(engine, member_id: int, task_id: str) -> int:
    with pytest.raises(HTTPException) as error:
        check(engine, member_id, task_id, True)
    return error.value.status_code


def test_a_task_that_does_not_apply_to_this_store_is_rejected(mysql_engine):
    """대출이 없다고 한 가게에 "은행 상환 조건 확인"은 해당 없음이다(승준님 #149)."""

    member_id = signed_up(mysql_engine, has_business_loan=False)

    assert rejected(mysql_engine, member_id, "check_loan") == 422
    assert checked_tasks(mysql_engine, member_id) == []
    assert history_of(mysql_engine, member_id) == []


def test_the_same_task_is_accepted_when_it_applies(mysql_engine):
    member_id = signed_up(mysql_engine, has_business_loan=True)

    check(mysql_engine, member_id, "check_loan", True)

    assert checked_tasks(mysql_engine, member_id) == ["check_loan"]


def test_a_demolition_task_waits_until_demolition_is_known(mysql_engine, member_id):
    """가입 직후엔 철거 필요 여부를 몰라서 철거비 항목은 "확인 필요"다. AI가 정한 뒤에 체크한다."""

    assert rejected(mysql_engine, member_id, "before_photo") == 422
    assert checked_tasks(mysql_engine, member_id) == []


def test_an_unsupported_store_cannot_check_anything(mysql_engine):
    """프랜차이즈 카페는 로드맵이 없다(supported=false). 체크할 항목도 없다."""

    member_id = signed_up(mysql_engine, franchise_status=True)

    assert rejected(mysql_engine, member_id, "dispose_stock") == 422


def test_unchecking_is_always_allowed(mysql_engine):
    """잘못 들어간 체크를 못 푸는 일이 없어야 한다. 해당 없는 항목이 저장돼 있어도 풀린다."""

    member_id = signed_up(mysql_engine, has_business_loan=False)
    with Session(mysql_engine) as session:
        case = get_case_by_member_id(session, member_id)
        session.add(CaseChecklist(case_id=case.id, task_id="check_loan"))
        session.commit()

    check(mysql_engine, member_id, "check_loan", False)

    assert checked_tasks(mysql_engine, member_id) == []
