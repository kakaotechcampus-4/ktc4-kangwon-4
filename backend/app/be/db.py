from collections.abc import Generator

from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine

import app.be.models  # noqa: F401 — 모든 모델을 SQLModel 메타데이터에 등록
from app.common.config import get_settings

_engine = create_engine(get_settings().DATABASE_URL)


def get_db() -> Generator[Session, None, None]:
    with Session(_engine) as session:
        yield session


def reset_all_tables() -> None:
    try:
        SQLModel.metadata.drop_all(_engine)
    except OperationalError as e:
        # case_history.priority_blocker_id → blocker 순환 FK 때문에 drop_all이 FK constraint를 먼저 DROP하려 하지만, 
        # 첫 실행 시에는 테이블 자체가 없어서 1091(constraint 없음) 에러가 발생한다. 
        # 첫 실행에만 나타나는 무해한 에러이므로 무시하고 create_all로 진행한다.
        if "1091" not in str(e):
            raise
    SQLModel.metadata.create_all(_engine)
