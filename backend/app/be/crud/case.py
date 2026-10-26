from sqlmodel import Session, select

from app.be.models.case import Case


def create_case(session: Session, case: Case) -> Case:
    session.add(case)
    session.flush()
    return case


def get_case_by_member_id(session: Session, member_id: int) -> Case | None:
    return session.exec(select(Case).where(Case.member_id == member_id)).one_or_none()


def lock_case_by_member_id(session: Session, member_id: int) -> Case | None:
    """Case 줄을 잠그고 읽는다. 같은 Case를 동시에 건드리는 요청을 줄 세울 때 쓴다.

    잠금은 이 트랜잭션이 끝날 때 풀린다. 그래서 "확인하고 저장한다"를 한 덩어리로 묶고
    싶은 쪽이 맨 앞에서 이걸로 읽으면, 뒤에 온 요청은 앞사람이 저장을 끝낼 때까지 기다렸다가
    바뀐 상태를 보게 된다.
    """

    return session.exec(select(Case).where(Case.member_id == member_id).with_for_update()).one_or_none()


def get_case_by_id(session: Session, case_id: int) -> Case | None:
    return session.exec(select(Case).where(Case.id == case_id)).one_or_none()
