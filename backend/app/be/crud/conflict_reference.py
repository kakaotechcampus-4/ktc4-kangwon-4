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


def get_pending_conflicts_by_case_history_id(session: Session, case_history_id: int) -> list[ConflictReference]:
    """그 제출 한 건에서 나온, 아직 사용자 확인을 기다리는 충돌 전부. 없으면 빈 리스트.

    Case 전체가 아니라 제출 단위로 보는 조회가 따로 필요하다. 처리 상태 조회는 "어느 제출의
    결과냐"를 먼저 맞춰 보고 그 제출의 결과만 돌려줘야 하는데, Case 전체로 찾으면 다른 제출의
    충돌을 내 요청의 응답인 것처럼 줄 수 있다.
    """

    return session.exec(
        select(ConflictReference)
        .where(ConflictReference.case_history_id == case_history_id)
        .where(ConflictReference.used_at.is_(None))
        .order_by(ConflictReference.id)
    ).all()
