from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.be.routers.auth import router as auth_router
from app.be.routers.case import router as case_router
from app.be.db import reset_all_tables
from app.common.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().ENVIRONMENT == "dev":
        reset_all_tables()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["Access-Token", "Refresh-Token"],
)
app.include_router(auth_router)
app.include_router(case_router)


@app.get("/health")
def health():
    return {"status": "ok"}
