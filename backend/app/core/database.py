"""
SQLModel engine/session 설정.
FastAPI Depends(get_db)로 라우터에서 세션을 주입받는다.
SQLModel은 SQLAlchemy 기반이라 engine 자체는 SQLAlchemy의 create_engine을 그대로 쓴다.
"""
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)


def get_db():
    with Session(engine) as session:
        yield session


def reset_all_tables() -> None:
    """
    지금 존재하는 모든 테이블을 지우고 app/be/models 기준으로 다시 만든다.
    JPA의 ddl-auto=create와 동일한 개념. 확인 절차 없이 즉시 실행하므로,
    사람이 직접 실행하는 곳(scripts/reset_db.py)에서만 감싸서 쓰거나
    APP_ENV=local 자동 초기화(app/main.py)에서만 호출한다.
    """
    import app.be.models  # noqa: F401  # SQLModel.metadata에 모델을 등록시키기 위한 import

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
