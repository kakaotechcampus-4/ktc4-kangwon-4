from sqlmodel import Session, select

from app.be.models.case import Case


def create_case(session: Session, case: Case) -> Case:
    session.add(case)
    session.flush()
    return case


def get_case_by_member_id(session: Session, member_id: int) -> Case | None:
    return session.exec(select(Case).where(Case.member_id == member_id)).one_or_none()
