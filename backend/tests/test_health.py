"""/health가 DB까지 보는지. 배포 컨테이너가 이 주소로 살아 있는지 판단한다(docker-compose.prod.yml).

Docker 없이 돈다. 되는 DB는 메모리 SQLite, 안 되는 DB는 아무도 듣지 않는 포트의 MySQL이다.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app.be.db import get_db
from app.main import app


def _client_with(url: str) -> TestClient:
    engine = create_engine(url)

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = session
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_health_is_ok_when_the_db_answers():
    response = _client_with("sqlite://").get("/health")

    assert (response.status_code, response.json()) == (200, {"status": "ok"})


def test_health_is_unavailable_when_the_db_does_not_answer():
    response = _client_with("mysql+pymysql://reborn:secret@127.0.0.1:1/closure_agent?connect_timeout=1").get("/health")

    assert (response.status_code, response.json()) == (503, {"status": "unavailable"})
    # 접속 주소·계정이 응답에 새지 않는다
    assert "127.0.0.1" not in response.text and "reborn" not in response.text
