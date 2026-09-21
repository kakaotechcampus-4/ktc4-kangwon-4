from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.be.db import reset_all_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    reset_all_tables()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}
