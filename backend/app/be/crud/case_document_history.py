from sqlmodel import Session, select

from app.be.models.case_document_history import CaseDocumentHistory


def create_case_document_history(session: Session, history: CaseDocumentHistory) -> CaseDocumentHistory:
    session.add(history)
    session.flush()
    return history


def get_case_document_histories_by_case_id(session: Session, case_id: int) -> list[CaseDocumentHistory]:
    return session.exec(select(CaseDocumentHistory).where(CaseDocumentHistory.case_id == case_id)).all()
