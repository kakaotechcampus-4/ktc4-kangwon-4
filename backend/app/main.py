from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.be.routers.auth import router as auth_router
from app.be.routers.case import router as case_router
from app.be.db import reset_all_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    reset_all_tables()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)
app.include_router(case_router)


@app.get("/health")
def health():
    return {"status": "ok"}
