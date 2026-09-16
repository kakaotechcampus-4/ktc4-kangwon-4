from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.database import reset_all_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    # APP_ENV=local일 때만 앱 시작 시 테이블을 drop_all + create_all로 자동 초기화한다.
    # (Spring db-dev 프로필의 ddl-auto: create와 동일한 개념)
    # prod 등 그 외 환경에서는 아무 것도 하지 않음 — 스키마는 alembic으로만 관리한다.
    if settings.APP_ENV == "local":
        reset_all_tables()
    yield


app = FastAPI(title="폐업지원 실행 Agent API", lifespan=lifespan)


@app.get("/health")
def health_check():
    return {"status": "ok"}
