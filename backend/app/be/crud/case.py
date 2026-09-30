from sqlalchemy.orm import joinedload
from sqlmodel import Session, select

from app.be.models.case import Case
from app.be.models.case_history import CaseHistory


def create_case(session: Session, case: Case) -> Case:
    session.add(case)
    session.flush()
    return case


def get_case_by_member_id(session: Session, member_id: int) -> Case | None:
    return session.exec(select(Case).where(Case.member_id == member_id)).one_or_none()


def get_latest_case_history_by_case_id_and_source(
    session: Session, case_id: int, source: str
) -> CaseHistory | None:
    """case_id와 source가 모두 일치하는 CaseHistory 중 created_at 기준 가장 최근 1개. 없으면 None.

    priority_blocker/next_action을 채우는 용도로 쓸 때는 source="USER_INPUT"으로
    호출한다 — SYSTEM_BATCH는 이 값들이 없을 수 있다(배치 기능 자체가 아직 미구현이라 지금은 실질적으로 없는 값이지만, 
    나중에 생겨도 이 조회에 안 섞이도록 호출부에서 명시적으로 걸러야 한다).
    """
    return session.exec(
        select(CaseHistory)
        .options(joinedload(CaseHistory.priority_blocker))
        .where(CaseHistory.case_id == case_id)
        .where(CaseHistory.source == source)
        .order_by(CaseHistory.created_at.desc())
        .limit(1)
    ).one_or_none()
