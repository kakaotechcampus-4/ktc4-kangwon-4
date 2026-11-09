import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from sqlmodel import Session

from app.be.routers.auth import router as auth_router
from app.be.routers.case import router as case_router
from app.be.routers.document import router as document_router
from app.be.db import get_engine, get_health_engine, reset_all_tables
from app.be.services import judgment as judgment_service
from app.be.services import official_document
from app.be.services import procedure_registry
from app.be.services import reviewed_procedure
from app.common.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().ENVIRONMENT == "dev":
        reset_all_tables()
    # 절차 마스터 표는 Case가 생기기 전부터 있어야 한다. 가입 요청 안에서 적재하면
    # 동시 가입 때 step_code unique에 걸리고, 아무도 가입 안 하면 표가 빈 채로 남는다.
    # 이미 있으면 손대지 않으므로 dev가 아닌 환경에서 다시 떠도 안전하다.
    with Session(get_engine()) as session:
        procedure_registry.ensure_cafe_procedure_registry(session)
        session.commit()
    # 공식 자료 본문도 전체가 함께 쓰는 한 벌이라 같은 이유로 여기서 넣는다(official_document 머리말).
    # 가입 때 넣으면 빈 DB에 동시 가입이 오면 같은 문서를 둘 다 넣다 unique에 걸려 판단이 실패한다.
    # 우리 쪽 자료 문제로 서버가 못 뜨면 안 되므로 실패는 남기기만 하고, 그때는 가입 때 다시 넣는다.
    with Session(get_engine()) as session:
        try:
            official_document.ensure_official_documents(session, reviewed_procedure.load_reviewed_procedures())
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("공식 자료 본문 적재 실패 — 가입 때 다시 시도한다")
    # 지난번에 꺼질 때 돌고 있던 판단은 결과 없이 PENDING으로 남는다. 그대로 두면 그 사장님은
    # 새 제출이 409로 막혀 영영 못 빠져나온다.
    judgment_service.release_abandoned_judgments()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # PUT은 할 일 체크(PUT /cases/checklists/...), DELETE는 서류 빼기(DELETE /cases/documents/{id})에 쓴다
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    expose_headers=["Access-Token", "Refresh-Token"],
)
app.include_router(auth_router)
app.include_router(case_router)
app.include_router(document_router)


@app.get("/health")
def health(engine: Engine = Depends(get_health_engine)):
    # 배포 컨테이너가 이 주소로 살아 있는지 본다(docker-compose.prod.yml). DB가 끊겨도 ok라고 하면
    # 모든 요청이 실패하는데 서버는 건강하다고 남는다. DB 오류 내용은 밖에 내보내지 않는다.
    # 기다리는 한도와 앱 풀을 안 쓰는 이유는 create_health_engine에 있다.
    # version은 이 서버를 빌드한 커밋이다(Dockerfile의 GIT_SHA). 서버에 들어가지 않고 운영 버전을 본다
    version = os.environ.get("APP_VERSION", "unknown")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable", "version": version})
    return {"status": "ok", "version": version}
