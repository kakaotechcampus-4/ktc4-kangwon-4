from sqlmodel import Session, select

from app.be.models.case_history import CaseHistory


def create_case_history(session: Session, case_history: CaseHistory) -> CaseHistory:
    session.add(case_history)
    session.flush()
    return case_history


def get_case_histories_by_case_id(session: Session, case_id: int) -> list[CaseHistory]:
    return session.exec(select(CaseHistory).where(CaseHistory.case_id == case_id)).all()
