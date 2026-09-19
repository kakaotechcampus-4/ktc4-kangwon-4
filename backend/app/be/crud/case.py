from sqlmodel import Session, select

from app.be.models.blocker import Blocker
from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
from app.be.models.procedure_step import CaseProcedureStep


def get_case_by_id_and_member(session: Session, *, case_id: int, member_id: int) -> Case | None:
    """소유권 조건을 포함한 단일 조회 경로. 이 조건 없이 Case를 select하는 코드를 다른 곳에 두지 않는다."""
    return session.exec(
        select(Case).where(Case.id == case_id, Case.member_id == member_id)
    ).one_or_none()


def list_recent_case_history(session: Session, *, case_id: int, limit: int) -> list[CaseHistory]:
    rows = session.exec(
        select(CaseHistory)
        .where(CaseHistory.case_id == case_id)
        .order_by(CaseHistory.created_at.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))  # 오래된 순으로 반환


def list_active_blockers(session: Session, *, case_id: int) -> list[Blocker]:
    return list(
        session.exec(
            select(Blocker).where(Blocker.case_id == case_id, Blocker.status == "ACTIVE")
        ).all()
    )


def list_case_procedure_progress(session: Session, *, case_id: int) -> list[CaseProcedureStep]:
    return list(
        session.exec(select(CaseProcedureStep).where(CaseProcedureStep.case_id == case_id)).all()
    )
