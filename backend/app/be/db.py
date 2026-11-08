from collections.abc import Generator
from functools import lru_cache

from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

import app.be.models  # noqa: F401 — 모든 모델을 SQLModel 메타데이터에 등록
from app.common.config import get_settings

# 운영 DB(docker-compose.prod.yml)와 같은 MySQL. 테스트·SQL 뽑기(scripts/dump_schema_sql.py)가 이걸 띄운다.
# 8.0처럼 열어 두면 받을 때마다 그때 최신판이 깔려 운영과 테스트가 모르게 갈린다(다물님 #217).
# 운영보다 낮추면 안 된다. MySQL은 데이터 폴더를 낮은 버전으로 되돌리지 못해서 운영 DB가 안 뜬다.
# 바꿀 때는 docker-compose.prod.yml·docker-compose.yml의 image도 같이 바꾼다.
MYSQL_IMAGE = "mysql:8.0.46"


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
        # 함께 막혀서, 숨 쉴 자리를 둔다.
        # 운영 DB의 max_connections는 151(MySQL 기본값)이고, 지금은 uvicorn 프로세스가 하나라
        # (Dockerfile CMD에 --workers 없음) 최대 30은 충분히 안쪽이다(현석님 #193).
        # 워커를 늘리면 30 × 워커 수가 151을 넘지 않는지 보면 된다 — 5개면 150이라 이미 빠듯하다.
        pool_size=10,
        max_overflow=20,
        # 쉬는 동안 MySQL이 끊은 커넥션을 잡으면 첫 요청이 그대로 터진다. 쓰기 전에 한 번 찔러 보고,
        # MySQL이 끊는 시각(기본 8시간)보다 일찍 우리가 먼저 바꾼다.
        pool_pre_ping=True,
        pool_recycle=3600,
    )


# /health가 DB를 기다리는 한도. compose healthcheck가 5초에 포기하므로 연결 2초 + 읽기 2초로 그 안에 끝낸다.
HEALTH_DB_TIMEOUT_SECONDS = 2


def create_health_engine(url: str) -> Engine:
    """/health만 쓰는 엔진. 기다리는 시간에 끝이 있고, 앱의 커넥션 자리를 쓰지 않는다.

    PyMySQL은 읽기 한도(read_timeout)가 기본으로 없어서, DB가 연결만 받고 말이 없으면
    끝없이 기다린다. healthcheck는 5초에 포기해도 서버의 이 작업은 남아 10초마다 쌓인다(승준님 #219).
    connect_timeout은 TCP 연결까지만이라 첫 인사부터 모든 읽기는 read_timeout이 끊는다.

    매번 새로 열고 닫는다(NullPool). 앱 풀을 같이 쓰면 DB는 멀쩡한데 자리가 꽉 찼을 때도
    자리를 30초 기다리다 503이 되어 컨테이너가 unhealthy로 찍힌다(현종님 #219).
    """

    timeout = HEALTH_DB_TIMEOUT_SECONDS
    return create_engine(
        url,
        poolclass=NullPool,
        connect_args={"connect_timeout": timeout, "read_timeout": timeout, "write_timeout": timeout},
    )


@lru_cache
def get_health_engine() -> Engine:
    return create_health_engine(get_settings().DATABASE_URL)


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
