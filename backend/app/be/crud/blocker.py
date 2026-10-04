from sqlmodel import Session, select

from app.be.models.blocker import Blocker


def create_blocker(session: Session, blocker: Blocker) -> Blocker:
    session.add(blocker)
    session.flush()
    return blocker


def get_blockers_by_case_id(session: Session, case_id: int) -> list[Blocker]:
    return session.exec(select(Blocker).where(Blocker.case_id == case_id)).all()
