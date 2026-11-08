"""OAuth state는 선택값이며, 값 안의 URL 구분자가 카카오 쿼리를 바꾸면 안 된다."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.be.routers import auth


@pytest.fixture
def client(monkeypatch):
    # 인증 설정만 가짜로 주입한다. 실제 설정·DB·카카오·모델은 읽거나 부르지 않는다.
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(
        KAKAO_CLIENT_ID="synthetic-client",
        KAKAO_REDIRECT_URI="https://example.com/login/callback",
    ))
    app = FastAPI()
    app.include_router(auth.router)
    return TestClient(app)


def query_of(client, params):
    response = client.get("/login/form", params=params, follow_redirects=False)
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert (location.scheme, location.netloc, location.path) == (
        "https", "kauth.kakao.com", "/oauth/authorize",
    )
    assert location.fragment == ""
    return parse_qs(location.query)


@pytest.mark.parametrize("state", [
    "748a1872-c339-42bc-aab9-69a25957b437",
    "abc&scope=account_email",
    "abc#def",
    "with spaces",
    "폐업 확인",
    "a+b%2F|/cases?tab=todo&step=2",
])
def test_state_reaches_kakao_unchanged_without_changing_other_parameters(client, state):
    assert query_of(client, {"state": state}) == {
        "client_id": ["synthetic-client"],
        "redirect_uri": ["https://example.com/login/callback"],
        "response_type": ["code"],
        "scope": ["profile_nickname"],
        "state": [state],
    }


@pytest.mark.parametrize("params", [{}, {"state": ""}])
def test_missing_or_empty_state_keeps_the_existing_optional_contract(client, params):
    assert "state" not in query_of(client, params)
