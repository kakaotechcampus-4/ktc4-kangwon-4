from sqlalchemy.orm import joinedload
from sqlmodel import Session, select

from app.be.models.evidence import ConflictReference


def get_pending_conflicts_by_case_id(session: Session, case_id: int) -> list[ConflictReference]:
    """아직 사용자 확인을 기다리는(used_at이 비어있는) 충돌 전부. 없으면 빈 리스트.

    충돌 하나당 row 1개라, 한 번에 여러 필드가 충돌하면 여러 개가 돌아올 수 있다.
    """

    return session.exec(
        select(ConflictReference)
        .options(joinedload(ConflictReference.case_history))
        .where(ConflictReference.case_id == case_id)
        .where(ConflictReference.used_at.is_(None))
        .order_by(ConflictReference.id)
    ).all()
