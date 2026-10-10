from sqlalchemy.orm import joinedload
from sqlmodel import Session, select

from app.be.models.case_history import CaseHistory

# 배치(SYSTEM_BATCH)가 만든 이력에는 next_action·priority_blocker가 없을 수 있어서
# 화면에 보여줄 최신 판단을 찾을 때는 사용자 입력에서 비롯된 것만 본다.
_USER_DRIVEN_SOURCES = ("CASE_CREATED", "USER_INPUT")


def create_case_history(session: Session, case_history: CaseHistory) -> CaseHistory:
    session.add(case_history)
    session.flush()
    return case_history


def get_case_histories_by_case_id(session: Session, case_id: int) -> list[CaseHistory]:
    return session.exec(select(CaseHistory).where(CaseHistory.case_id == case_id)).all()


def get_case_created_history(session: Session, case_id: int) -> CaseHistory | None:
    return session.exec(
        select(CaseHistory).where(CaseHistory.case_id == case_id, CaseHistory.source == "CASE_CREATED")
    ).one_or_none()


def get_latest_user_driven_case_history(session: Session, case_id: int) -> CaseHistory | None:
    """화면에 보여줄 가장 최근 판단 이력. 없으면 None.

    Case 생성 판단(CASE_CREATED)과 결과 입력 판단(USER_INPUT)을 모두 보고 그중 최신을
    고른다. 배치가 생기더라도 이 조회에는 섞이지 않는다.
    """

    return session.exec(
        select(CaseHistory)
        .options(joinedload(CaseHistory.priority_blocker))
        .where(CaseHistory.case_id == case_id)
        .where(CaseHistory.source.in_(_USER_DRIVEN_SOURCES))
        # created_at은 MySQL DATETIME이라 초 단위까지만 저장돼 같은 초에 두 이력이 생기면
        # 동률이 난다. id(auto-increment)는 항상 생성 순서를 정확히 반영하므로 2차 기준으로 쓴다.
        .order_by(CaseHistory.created_at.desc(), CaseHistory.id.desc())
        .limit(1)
    ).first()
