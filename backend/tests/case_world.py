"""Case 서비스 테스트들이 같이 쓰는 준비물. 진짜 MySQL이 필요하다(Docker, requirements-dev.txt).

conftest.py는 AI팀 로컬 설정용으로 .gitignore에 있어서, 테스트 파일마다 이 모듈에서
`case_engine`·`case_world` 픽스처를 가져다 쓴다.

`case_world`는 실제 판단 대신 판단이 끝난 모양의 이력·충돌·변경을 DB에 직접 만들어 둔다.
서비스가 그 상태를 보고 어떻게 응답하는지만 확인하려는 것이라 AI는 부르지 않는다.
"""

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine
from testcontainers.community.mysql import MySqlContainer

from app.be.crud.case_history import get_case_created_history
from app.be.crud.member import create_member
from app.be.models.blocker import Blocker
from app.be.models.case_field_history import CaseFieldHistory
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import ConflictReference
from app.be.schemas.case import CaseCreateRequest
from app.be.services import procedure_registry
from app.be.services.case import create_case


@pytest.fixture(scope="module")
def case_engine():
    container = MySqlContainer(
        "mysql:8.0", dialect="pymysql", username="test", password="test",
        root_password="test", dbname="case_service_test",
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


@dataclass
class CaseWorld:
    engine: object

    def sign_up(self) -> tuple[int, int, int]:
        """판단이 끝난(DONE) 가입 Case. (member_id, case_id, 가입 이력 id)를 돌려준다."""

        with Session(self.engine) as session:
            member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
            case, _ = create_case(session, member.id, CaseCreateRequest(
                business_type="CAFE", franchise_status=False, employee_count=2,
                lease_status="LEASED_PAID",
            ))
            history = get_case_created_history(session, case.id)
            self._finish_done(session, history)
            session.commit()
            return member.id, case.id, history.id

    def stranger(self) -> int:
        """Case가 없는 회원."""

        with Session(self.engine) as session:
            member = create_member(session, oauth_id=str(uuid4()), nickname="가입 전 사용자")
            session.commit()
            return member.id

    def add_history(self, case_id: int, source: str, status: str) -> int:
        """판단이 status로 끝난 이력. 화면이 읽는 값은 상태에 맞게 채운다."""

        with Session(self.engine) as session:
            history = CaseHistory(
                case_id=case_id, source=source, judgment_status=status,
                raw_input=None if source == "CONFLICT_DECISION" else "결과 글",
            )
            session.add(history)
            session.flush()
            if status == "DONE":
                self._finish_done(session, history)
            elif status == "NEEDS_MORE_INFO":
                history.questions_for_user = ["원상복구 범위가 어디까지인가요?"]
                history.priority_blocker_id = self._blocker(session, history)
            elif status == "FAILED":
                history.recovery_action_code = "RETRY"
                history.retryable = True
                history.requested_field_paths = []
            session.commit()
            return history.id

    def add_conflict(self, case_id: int, history_id: int, field: str = "restoration_scope",
                     status: str = "PENDING") -> int:
        with Session(self.engine) as session:
            conflict = ConflictReference(
                conflict_ref=str(uuid4()), case_id=case_id, case_history_id=history_id,
                canonical_field=field, committed_value="PARTIAL", proposed_value="FULL", status=status,
            )
            session.add(conflict)
            session.commit()
            return conflict.id

    def add_change(self, case_id: int, history_id: int) -> None:
        with Session(self.engine) as session:
            session.add(CaseFieldHistory(
                case_id=case_id, case_history_id=history_id, canonical_field="restoration_scope",
                before_value="UNKNOWN", after_value="FULL", source="INFO_ANALYSIS",
            ))
            session.commit()

    def _finish_done(self, session: Session, history: CaseHistory) -> None:
        history.judgment_status = "DONE"
        history.next_action = "임대인에게 원상복구 범위 묻기"
        history.next_action_reason = "범위에 따라 철거와 지원금 신청이 달라져요"
        history.next_action_questions_to_ask = ["어디까지 원래대로 해야 하나요?"]
        history.priority_blocker_id = self._blocker(session, history)

    def _blocker(self, session: Session, history: CaseHistory) -> int:
        blocker = Blocker(
            case_id=history.case_id, created_from_case_history_id=history.id,
            description="원상복구 범위를 모름", status="ACTIVE",
        )
        session.add(blocker)
        session.flush()
        return blocker.id


@pytest.fixture
def case_world(case_engine) -> CaseWorld:
    return CaseWorld(case_engine)
