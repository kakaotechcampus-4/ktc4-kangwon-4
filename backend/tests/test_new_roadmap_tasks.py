"""결과 화면의 "이번에 새로 생긴 할 일"(시안 M05c).

로드맵은 그때그때 계산해 내보내는 값이라 지나간 것을 되살릴 길이 없다. 그래서 판단마다
할 일 상태를 한 벌 적어 두고(case_history.roadmap_task_status) 직전 것과 견준다.

저장한 것을 다시 읽어야 해서 진짜 MySQL이 필요하다(격리된 mysql:8.0 컨테이너).
"""

from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine
from testcontainers.community.mysql import MySqlContainer

from app.be.crud import case_history as case_history_crud
from app.be.crud.case import get_case_by_member_id
from app.be.crud.member import create_member
from app.be.models.case_history import CaseHistory
from app.be.schemas.case import CaseCreateRequest
from app.be.services import procedure_registry
from app.be.services.case import _new_roadmap_tasks, create_case


@pytest.fixture(scope="module")
def mysql_engine():
    container = MySqlContainer(
        "mysql:8.0", dialect="pymysql", username="test", password="test",
        root_password="test", dbname="new_roadmap_tasks_test",
    ).with_env("TZ", "Asia/Seoul")
    with container:
        engine = create_engine(container.get_connection_url() + "?charset=utf8mb4")
        try:
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                procedure_registry.ensure_cafe_procedure_registry(session)
                session.commit()
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def case_id(mysql_engine):
    with Session(mysql_engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
        create_case(session, member.id, CaseCreateRequest(
            business_type="CAFE", franchise_status=False, employee_count=2,
            lease_status="LEASED_PAID",
        ))
        session.commit()
        return get_case_by_member_id(session, member.id).id


def judged(session, case_id: int, status: dict | None) -> CaseHistory:
    """할 일 상태를 적어 둔 판단 이력 한 줄."""

    return case_history_crud.create_case_history(session, CaseHistory(
        case_id=case_id, raw_input="합성 입력", source="USER_INPUT",
        judgment_status="DONE", roadmap_task_status=status,
    ))


def tasks(status: dict[str, str]) -> dict:
    return {key: {"status": value, "title": f"{key} 제목"} for key, value in status.items()}


def new_tasks(mysql_engine, case_id: int, history_id: int) -> list[str]:
    with Session(mysql_engine) as session:
        history = session.get(CaseHistory, history_id)
        return [task.task_id for task in _new_roadmap_tasks(session, case_id, history)]


def test_a_task_that_became_mine_is_new(mysql_engine, case_id):
    """철거가 필요하다고 확정되면 철거비 할 일이 "확인 필요"에서 할 수 있는 것으로 바뀐다."""

    with Session(mysql_engine) as session:
        judged(session, case_id, tasks({"before_photo": "NEEDS_CONFIRMATION", "dispose_stock": "NOT_STARTED"}))
        session.commit()
        latest = judged(session, case_id, tasks({"before_photo": "NOT_STARTED", "dispose_stock": "NOT_STARTED"}))
        session.commit()
        latest_id = latest.id

    assert new_tasks(mysql_engine, case_id, latest_id) == ["before_photo"]


def test_finishing_a_task_is_not_a_new_task(mysql_engine, case_id):
    """이미 할 수 있던 일이 끝난 것은 새로 생긴 것이 아니다."""

    with Session(mysql_engine) as session:
        judged(session, case_id, tasks({"dispose_stock": "NOT_STARTED"}))
        session.commit()
        latest = judged(session, case_id, tasks({"dispose_stock": "COMPLETED"}))
        session.commit()
        latest_id = latest.id

    assert new_tasks(mysql_engine, case_id, latest_id) == []


def test_a_task_that_stopped_being_mine_is_not_new(mysql_engine, case_id):
    """해당 없어진 할 일은 새로 생긴 것이 아니다. 반대 방향을 세면 안 된다."""

    with Session(mysql_engine) as session:
        judged(session, case_id, tasks({"before_photo": "NOT_STARTED"}))
        session.commit()
        latest = judged(session, case_id, tasks({"before_photo": "NOT_APPLICABLE"}))
        session.commit()
        latest_id = latest.id

    assert new_tasks(mysql_engine, case_id, latest_id) == []


def test_the_first_judgment_has_nothing_to_compare(mysql_engine, case_id):
    """견줄 직전 판단이 없으면 아무것도 안 보여준다. 전부 "새로 생겼다"고 하면 말이 안 된다."""

    with Session(mysql_engine) as session:
        latest = judged(session, case_id, tasks({"before_photo": "NOT_STARTED"}))
        session.commit()
        latest_id = latest.id

    assert new_tasks(mysql_engine, case_id, latest_id) == []


def test_a_judgment_that_wrote_nothing_is_skipped(mysql_engine, case_id):
    """실패한 판단은 할 일을 못 적는다. 그 앞의 적힌 판단과 견준다 — 그게 사장님이 보던 로드맵이다."""

    with Session(mysql_engine) as session:
        judged(session, case_id, tasks({"before_photo": "NEEDS_CONFIRMATION"}))
        session.commit()
        judged(session, case_id, None)
        session.commit()
        latest = judged(session, case_id, tasks({"before_photo": "NOT_STARTED"}))
        session.commit()
        latest_id = latest.id

    assert new_tasks(mysql_engine, case_id, latest_id) == ["before_photo"]


def test_another_case_does_not_leak_in(mysql_engine, case_id):
    with Session(mysql_engine) as session:
        other = create_member(session, oauth_id=str(uuid4()), nickname="다른 사장님")
        create_case(session, other.id, CaseCreateRequest(
            business_type="CAFE", franchise_status=False, employee_count=2, lease_status="OWNED",
        ))
        session.commit()
        other_case_id = get_case_by_member_id(session, other.id).id
        judged(session, other_case_id, tasks({"before_photo": "NEEDS_CONFIRMATION"}))
        session.commit()
        latest = judged(session, case_id, tasks({"before_photo": "NOT_STARTED"}))
        session.commit()
        latest_id = latest.id

    assert new_tasks(mysql_engine, case_id, latest_id) == []


def test_a_real_judgment_writes_the_task_status(mysql_engine, case_id):
    """진짜 저장 함수가 할 일 상태를 적어 두는지 본다.

    위 검사들은 적힌 값을 견주는 규칙만 본다. 적는 쪽이 멈추면 전부 통과하면서 화면에만
    아무것도 안 뜨므로, 저장 경로를 한 번 실제로 지나간다.
    """

    from test_conflict_decision import reviewed_plan_setting_employee_count

    from app.be.crud.case import get_case_by_id
    from app.be.services import decision_record as decision_record_service

    with Session(mysql_engine) as session:
        case = get_case_by_id(session, case_id)
        # 합성 판단이 본 "바뀌기 전 값"에 맞춘다. 다르면 저장 전 대조에서 먼저 걸린다.
        case.employee_count = None
        history = case_history_crud.create_case_history(session, CaseHistory(
            case_id=case_id, raw_input="직원은 2명입니다.", source="USER_INPUT",
            judgment_status="PENDING",
        ))
        session.commit()
        history_id = history.id

        decision_record_service.save_reviewed_plan(
            session, history, reviewed_plan_setting_employee_count()
        )

    with Session(mysql_engine) as session:
        saved = session.get(CaseHistory, history_id).roadmap_task_status
        assert saved is not None
        # 5단계 26항목이 통째로 들어간다. 상태와 제목이 같이 있어야 화면이 이름을 쓸 수 있다.
        assert len(saved) == 26
        assert set(saved["dispose_stock"]) == {"status", "title"}
