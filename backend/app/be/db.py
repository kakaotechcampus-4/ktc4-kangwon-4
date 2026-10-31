from collections.abc import Generator
from functools import lru_cache

from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine

import app.be.models  # noqa: F401 — 모든 모델을 SQLModel 메타데이터에 등록
from app.common.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """DB에 처음 붙을 때 엔진을 만든다. 불러오는 것만으로는 설정을 읽지 않는다.

    예전에는 이 줄이 모듈을 읽는 순간 돌아서, DB를 쓰지 않는 코드도 불러오기만 하면
    카카오 열쇠·JWT 열쇠까지 전부 있어야 했다. 그래서 설정 파일이 없는 CI에서는 DB도
    모델도 안 쓰는 테스트가 불러오기 단계에서 통째로 멈췄다.
    """

    return create_engine(get_settings().DATABASE_URL)


def get_db() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session


def reset_all_tables() -> None:
    try:
        SQLModel.metadata.drop_all(get_engine())
    except OperationalError as e:
        # case_history.priority_blocker_id → blocker 순환 FK 때문에 drop_all이 FK constraint를 먼저 DROP하려 하지만, 
        # 첫 실행 시에는 테이블 자체가 없어서 1091(constraint 없음) 에러가 발생한다. 
        # 첫 실행에만 나타나는 무해한 에러이므로 무시하고 create_all로 진행한다.
        if "1091" not in str(e):
            raise
    SQLModel.metadata.create_all(get_engine())
