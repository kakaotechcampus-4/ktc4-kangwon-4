"""/health가 DB까지 보는지. 배포 컨테이너가 이 주소로 살아 있는지 판단한다(docker-compose.prod.yml).
응답에는 이 서버가 어느 커밋으로 빌드됐는지(APP_VERSION)도 같이 싣는다.

Docker 없이 돈다. 되는 DB는 메모리 SQLite, 안 되는 DB는 아무도 듣지 않는 포트와,
연결만 받고 아무 말도 안 하는 가짜 서버다.
"""

import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app.be.db import HEALTH_DB_TIMEOUT_SECONDS, create_health_engine, get_health_engine
from app.main import app


def _health_with(engine):
    app.dependency_overrides[get_health_engine] = lambda: engine
    return TestClient(app).get("/health")


@pytest.fixture(autouse=True)
def _clear_overrides(monkeypatch):
    # 개발자 PC나 CI에 값이 있어도 검사가 흔들리지 않게, 기본은 "빌드할 때 커밋을 안 넘긴 서버"로 둔다
    monkeypatch.delenv("APP_VERSION", raising=False)
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def silent_db():
    """TCP 연결은 받지만 MySQL 첫 인사도 보내지 않는 서버. 승준님이 #219에서 재현한 상황이다.

    8초가 지나면 스스로 끊는다. 한도가 빠져도 검사가 멈추지 않고 "8초 걸렸다"로 실패하게 한다.
    """

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    accepted = []
    stop = threading.Event()

    def accept():
        server.settimeout(0.1)
        hang_up_at = time.monotonic() + 8
        while not stop.is_set():
            if accepted and time.monotonic() > hang_up_at:
                for connection in accepted:
                    connection.close()
            try:
                accepted.append(server.accept()[0])
            except TimeoutError:
                pass

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield server.getsockname()[1]
    stop.set()
    thread.join()
    for connection in accepted:
        connection.close()
    server.close()


def test_health_is_ok_when_the_db_answers():
    # SQLite에는 MySQL 시간 한도 설정이 없어서, 응답 모양만 본다. 한도는 아래 두 검사가 본다
    response = _health_with(create_engine("sqlite://"))

    assert (response.status_code, response.json()) == (200, {"status": "ok", "version": "unknown"})


def test_health_tells_which_commit_the_server_was_built_from(monkeypatch):
    # 배포할 때 넣은 커밋이 보여야 서버에 들어가지 않고도 운영 버전을 확인할 수 있다
    monkeypatch.setenv("APP_VERSION", "bcf99d0")

    response = _health_with(create_engine("sqlite://"))

    assert (response.status_code, response.json()) == (200, {"status": "ok", "version": "bcf99d0"})


def test_health_is_unavailable_when_the_db_does_not_answer(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "bcf99d0")
    response = _health_with(create_health_engine("mysql+pymysql://reborn:secret@127.0.0.1:1/closure_agent"))

    # DB가 죽었을 때도 어느 버전이 죽었는지는 보여 준다. 되돌릴지 정할 때 쓴다
    assert (response.status_code, response.json()) == (503, {"status": "unavailable", "version": "bcf99d0"})
    # 접속 주소·계정이 응답에 새지 않는다
    assert "127.0.0.1" not in response.text and "reborn" not in response.text


def test_health_gives_up_on_a_db_that_connects_but_never_speaks(silent_db):
    # 한도가 없으면 이 요청은 끝나지 않는다. compose healthcheck가 5초에 포기하므로 그 안에 끝나야 한다
    engine = create_health_engine(f"mysql+pymysql://reborn:secret@127.0.0.1:{silent_db}/closure_agent")

    started = time.monotonic()
    response = _health_with(engine)
    waited = time.monotonic() - started

    assert (response.status_code, response.json()) == (503, {"status": "unavailable", "version": "unknown"})
    assert HEALTH_DB_TIMEOUT_SECONDS <= waited < 5
