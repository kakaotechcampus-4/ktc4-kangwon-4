from sqlmodel import Session

from app.be.models.case import Case


def create_case(session: Session, case: Case) -> Case:
    session.add(case)
    session.flush()
    return case
