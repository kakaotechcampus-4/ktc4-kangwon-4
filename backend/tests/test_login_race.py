"""같은 카카오 계정의 첫 로그인 두 개가 동시에 와도 둘 다 로그인되고 회원은 하나만 남는지(#257).

둘 다 "회원 없음"을 본 뒤 INSERT하면 oauth_id UNIQUE에 걸린 쪽이 500이 됐다.
카카오는 부르지 않는다.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import jwt
import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from testcontainers.community.mysql import MySqlContainer

from app.be.crud import member as member_crud
from app.be.db import MYSQL_IMAGE
from app.be.models.member import Member
from app.be.services import auth as auth_service


@pytest.fixture
def empty_engine():
    with MySqlContainer(MYSQL_IMAGE, dialect="pymysql", username="test", password="test",
                        root_password="test", dbname="login_race") as mysql:
        engine = create_engine(mysql.get_connection_url() + "?charset=utf8mb4", pool_size=4, max_overflow=0)
        SQLModel.metadata.create_all(engine)
        try:
            yield engine
        finally:
            engine.dispose()


def test_two_first_logins_at_once_both_succeed_with_one_member(empty_engine, monkeypatch):
    monkeypatch.setattr(auth_service, "_fetch_kakao_token", lambda code: "kakao-token")
    monkeypatch.setattr(auth_service, "_fetch_kakao_user_info", lambda token: ("kakao-257", "동시 로그인"))
    # 로그인은 JWT를 만든다. 진짜 설정을 읽으면 `.env`가 없는 곳에서 테스트가 깨진다
    settings = SimpleNamespace(
        JWT_SECRET_KEY="synthetic-jwt-secret-for-tests-0123456789",
        JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30, JWT_REFRESH_TOKEN_EXPIRE_DAYS=14,
    )
    monkeypatch.setattr(auth_service, "get_settings", lambda: settings)

    # 둘 다 "회원 없음"을 본 다음에야 INSERT로 넘어가게 맞춘다.
    # 처음 두 번의 조회만 기다린다. 고친 뒤 실패한 쪽이 다시 조회할 때는 기다리지 않는다.
    gate = Barrier(2, timeout=10)
    first_lookups = iter(range(2))
    original = member_crud.get_member_by_oauth_id

    def look_up_together(session, oauth_id):
        member = original(session, oauth_id)
        if next(first_lookups, None) is not None:
            gate.wait()
        return member

    monkeypatch.setattr(member_crud, "get_member_by_oauth_id", look_up_together)

    def log_in(_):
        with Session(empty_engine) as session:
            return auth_service.login(session, "kakao-code")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(log_in, range(2)))

    with Session(empty_engine) as session:
        members = session.exec(select(Member)).all()
    assert len(members) == 1
    subjects = {jwt.decode(access, settings.JWT_SECRET_KEY, algorithms=["HS256"])["sub"] for access, _, _ in results}
    assert subjects == {str(members[0].id)}
