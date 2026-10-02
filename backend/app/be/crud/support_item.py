from sqlmodel import Session, select

from app.be.models.support_item import SupportItem


def get_support_item_by_id(session: Session, support_item_id: int) -> SupportItem | None:
    return session.exec(select(SupportItem).where(SupportItem.id == support_item_id)).one_or_none()
