from sqlmodel import Session, select

from app.be.models.member import Member


def get_member_by_oauth_id(session: Session, oauth_id: str) -> Member | None:
    return session.exec(select(Member).where(Member.oauth_id == oauth_id)).one_or_none()


def create_member(session: Session, oauth_id: str, nickname: str) -> Member:
    member = Member(oauth_id=oauth_id, nickname=nickname)
    session.add(member)
    session.flush()  # DB에 INSERT를 보내 auto increment id를 확보
    return member


def get_member_by_id(session: Session, id: int) -> Member | None:
    return session.get(Member, id)
