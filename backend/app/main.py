from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlmodel import Session

from app.be.routers.auth import router as auth_router
from app.be.routers.case import router as case_router
from app.be.routers.document import router as document_router
from app.be.db import get_engine, reset_all_tables
from app.be.services import procedure_registry
from app.common.config import get_settings


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
def health():
    return {"status": "ok"}
