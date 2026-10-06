from sqlmodel import Session

from app.be.models.case_field_history import CaseFieldHistory


def create_case_field_history(session: Session, case_field_history: CaseFieldHistory) -> CaseFieldHistory:
    session.add(case_field_history)
    session.flush()
    return case_field_history
