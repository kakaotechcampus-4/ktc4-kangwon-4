from sqlmodel import Session, select

from app.be.models.support_item import SupportItem, SupportMatch


def get_support_item_by_id(session: Session, support_item_id: int) -> SupportItem | None:
    return session.exec(select(SupportItem).where(SupportItem.id == support_item_id)).one_or_none()


def get_support_match(session: Session, case_id: int, support_item_id: int) -> SupportMatch | None:
    return session.exec(
        select(SupportMatch)
        .where(SupportMatch.case_id == case_id)
        .where(SupportMatch.support_item_id == support_item_id)
    ).one_or_none()


def create_support_match(session: Session, support_match: SupportMatch) -> SupportMatch:
    session.add(support_match)
    session.flush()
    return support_match
