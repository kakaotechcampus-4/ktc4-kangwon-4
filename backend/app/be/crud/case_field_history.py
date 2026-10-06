from sqlmodel import Session, select

from app.be.models.case_field_history import CaseFieldHistory


def create_case_field_history(session: Session, case_field_history: CaseFieldHistory) -> CaseFieldHistory:
    session.add(case_field_history)
    session.flush()
    return case_field_history


def get_case_field_histories_by_case_id(session: Session, case_id: int) -> list[CaseFieldHistory]:
    """오래된 것부터 돌려준다 — 같은 필드를 덮어쓰면 마지막이 가장 최근 변경이 된다."""

    return session.exec(
        select(CaseFieldHistory)
        .where(CaseFieldHistory.case_id == case_id)
        .order_by(CaseFieldHistory.created_at, CaseFieldHistory.id)
    ).all()


def get_case_field_histories_by_case_history_id(session: Session, case_history_id: int) -> list[CaseFieldHistory]:
    """특정 제출(CaseHistory) 한 건에서 실제로 바뀐 필드만 돌려준다."""

    return session.exec(
        select(CaseFieldHistory).where(CaseFieldHistory.case_history_id == case_history_id)
    ).all()
