"""로드맵 조회가 AI가 만든 값을 그대로 돌려주는지.

조회는 저장한 Case를 읽어서 만들기 때문에 진짜 MySQL이 필요하다(격리된 mysql:8.0 컨테이너,
Docker와 requirements-dev.txt 필요).

여기서 보는 것은 **BE가 AI에 무엇을 넘기고 받은 것을 어떻게 내보내는가**다. 단계·항목이
맞게 계산되는지는 AI 쪽 검사(app/agent/roadmap.py)가 본다.
"""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine
from testcontainers.community.mysql import MySqlContainer

from app.agent.roadmap import CHECKLIST_IDS, CompletedRoadmapSnapshot
from app.be.crud.case import get_case_by_member_id
from app.be.crud.member import create_member
from app.be.models.case_checklist import CaseChecklist
from app.be.schemas.case import CaseCreateRequest
from app.be.services import case_snapshot as case_snapshot_service
from app.be.services import procedure_registry
from app.be.services.case import create_case, update_case_checklist
from app.be.services.roadmap import build_roadmap_input, get_case_roadmap


@pytest.fixture(scope="module")
def mysql_engine():
    container = MySqlContainer(
        "mysql:8.0", dialect="pymysql", username="test", password="test",
        root_password="test", dbname="case_roadmap_test",
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


def new_case(engine, **overrides) -> int:
    """가입을 한 건 만들고 member_id를 돌려준다."""

    fields = dict(
        business_type="CAFE", franchise_status=False, employee_count=2,
        lease_status="LEASED_PAID",
    )
    fields.update(overrides)
    with Session(engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
        create_case(session, member.id, CaseCreateRequest(**fields))
        return member.id


def roadmap_of(engine, member_id: int):
    with Session(engine) as session:
        return get_case_roadmap(session, member_id)


def test_the_roadmap_comes_back_whole(mysql_engine):
    """칸을 빼지 않고 그대로 내보낸다. 화면이 읽는 칸이 하나라도 빠지면 거기서 막힌다."""

    member_id = new_case(mysql_engine)

    roadmap = roadmap_of(mysql_engine, member_id)

    assert roadmap.supported is True and roadmap.unsupported_reason is None
    assert [stage.stage for stage in roadmap.stages] == [1, 2, 3, 4, 5]
    assert sum(len(stage.tasks) for stage in roadmap.stages) == 26


def test_an_unsupported_store_gets_the_reason_not_an_error(mysql_engine):
    """프랜차이즈 카페는 오류가 아니라 supported=false와 안내 문구로 온다(시우님 #132)."""

    member_id = new_case(mysql_engine, franchise_status=True)

    roadmap = roadmap_of(mysql_engine, member_id)

    assert roadmap.supported is False
    assert roadmap.unsupported_reason is not None
    assert roadmap.stages == []


def test_the_checked_tasks_come_back_as_done(mysql_engine):
    member_id = new_case(mysql_engine)
    with Session(mysql_engine) as session:
        update_case_checklist(session, member_id, "dispose_stock", True)

    roadmap = roadmap_of(mysql_engine, member_id)

    checked = next(
        task for stage in roadmap.stages for task in stage.tasks
        if task.task_id == "dispose_stock"
    )
    assert checked.status == "COMPLETED"


def test_a_checklist_name_the_ai_no_longer_knows_does_not_break_the_roadmap(mysql_engine):
    """AI가 항목 이름을 바꾸면 DB에 예전 이름이 남는다. 하나라도 섞이면 로드맵이 통째로 안 열린다."""

    member_id = new_case(mysql_engine)
    with Session(mysql_engine) as session:
        case = get_case_by_member_id(session, member_id)
        session.add(CaseChecklist(case_id=case.id, task_id="task_the_ai_dropped"))
        session.commit()

    roadmap = roadmap_of(mysql_engine, member_id)

    assert roadmap.supported is True
    with Session(mysql_engine) as session:
        case = get_case_by_member_id(session, member_id)
        assert build_roadmap_input(session, case).completed_checklists <= CHECKLIST_IDS


def test_the_guidance_from_the_reviewed_source_is_passed_through(mysql_engine):
    """할 일에 붙는 안내와 그 근거(#144). 빼고 내보내면 화면이 기한·금액을 못 쓴다."""

    member_id = new_case(mysql_engine)

    roadmap = roadmap_of(mysql_engine, member_id)

    notify = next(
        task for stage in roadmap.stages for task in stage.tasks
        if task.task_id == "notify_employees"
    )
    assert notify.guidance is not None
    assert notify.guidance_source is not None


def test_without_a_reviewed_judgment_there_is_no_next_action(mysql_engine):
    """검수를 통과한 판단만 다음 할 일을 정할 수 있다. 아직 그걸 꺼내 오는 길이 없다."""

    member_id = new_case(mysql_engine)

    roadmap = roadmap_of(mysql_engine, member_id)

    assert (roadmap.next_action, roadmap.next_task_id, roadmap.questions_for_user) == (None, None, [])


def test_a_finished_case_still_gets_its_roadmap(mysql_engine):
    """폐업 정리를 마쳐도 로드맵은 나온다(현석님 #167).

    판단은 진행 중인 Case만 받지만(CaseSnapshot.case_status), 로드맵은 모델을 부르지 않는
    읽기라 그 제한을 받을 이유가 없다. 그래서 AI가 그 용도로 만들어 둔 모양으로 넘긴다.
    """

    member_id = new_case(mysql_engine)
    with Session(mysql_engine) as session:
        update_case_checklist(session, member_id, "vat_submission", True)

    roadmap = roadmap_of(mysql_engine, member_id)

    assert roadmap.supported is True
    assert sum(len(stage.tasks) for stage in roadmap.stages) == 26
    with Session(mysql_engine) as session:
        case = get_case_by_member_id(session, member_id)
        snapshot = build_roadmap_input(session, case).case_snapshot
    assert isinstance(snapshot, CompletedRoadmapSnapshot)


def test_someone_without_a_case_gets_404(mysql_engine):
    with Session(mysql_engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="가입 전 사용자")
        session.commit()
        with pytest.raises(HTTPException) as error:
            get_case_roadmap(session, member.id)

    assert error.value.status_code == 404


def test_the_judgment_snapshot_still_refuses_a_finished_case(mysql_engine):
    """판단용 스냅샷은 완료된 Case를 만들지 않는다.

    로드맵 때문에 두 모양으로 갈라 두었는데, 판단 쪽이 완료 Case를 받아버리면 "AI는 진행
    중인 Case만 판단한다"가 조용히 풀린다. 그 선을 여기서 못 박는다.
    """

    member_id = new_case(mysql_engine)
    with Session(mysql_engine) as session:
        update_case_checklist(session, member_id, "vat_submission", True)

    with Session(mysql_engine) as session:
        case = get_case_by_member_id(session, member_id)
        with pytest.raises(ValidationError):
            case_snapshot_service.build_case_snapshot(session, case.id)
