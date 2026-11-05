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

    return create_engine(
        get_settings().DATABASE_URL,
        # 기본값(5+10)은 판단이 겹칠 때 금방 바닥난다. 자리가 없으면 판단과 상관없는 조회·로그인도
        # 함께 막혀서, 숨 쉴 자리를 둔다. TODO: 운영 DB가 받아주는 최대 커넥션 수를 확인하고 맞춘다.
        pool_size=10,
        max_overflow=20,
        # 쉬는 동안 MySQL이 끊은 커넥션을 잡으면 첫 요청이 그대로 터진다. 쓰기 전에 한 번 찔러 보고,
        # MySQL이 끊는 시각(기본 8시간)보다 일찍 우리가 먼저 바꾼다.
        pool_pre_ping=True,
        pool_recycle=3600,
    )


def get_db() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session


def release_request_connection(session: Session) -> None:
    """요청이 DB를 다 썼으면 커넥션을 지금 돌려준다.

    요청에 딸린 세션은 응답 뒤 배경 작업까지 끝나야 정리된다. 판단은 AI를 50초 기다리므로,
    그동안 이 요청이 잡은 커넥션 하나도 같이 묶여 있게 된다(승준님 #193). 응답에 쓸 값은
    이미 다 읽었으니 여기서 먼저 돌려준다. 뒤이은 정리는 다시 닫아도 아무 일도 하지 않는다.
    """

    session.close()


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
