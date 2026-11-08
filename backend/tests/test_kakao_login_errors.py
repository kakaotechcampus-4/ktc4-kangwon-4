"""카카오가 로그인을 거절하거나 고장 났을 때 500 대신 400·502로 나누는지(#257).

잘못되거나 이미 쓴 code는 사장님 쪽 요청 문제라 400, 카카오 장애·연결 실패·응답 모양이
이상한 것과 우리 앱 키·시크릿이 틀린 것(토큰 요청의 401)은 사장님이 풀 수 없어 502다.
실제 카카오는 부르지 않는다.
"""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.be.db import get_db
from app.be.routers import auth as auth_router
from app.be.services import auth as auth_service


def _kakao_answers(monkeypatch, handler):
    """auth 서비스가 만드는 httpx.Client가 진짜 카카오 대신 handler에게 묻게 한다."""
    real_client = httpx.Client
    monkeypatch.setattr(auth_service.httpx, "Client", lambda: real_client(transport=httpx.MockTransport(handler)))


def _unreachable(request):
    raise httpx.ConnectError("카카오에 연결하지 못함", request=request)


@pytest.mark.parametrize("handler, status", [
    (lambda request: httpx.Response(400, json={"error": "invalid_grant"}), 400),
    # 앱 키·시크릿이 틀린 우리 설정 문제(KOE010·KOE101). 다시 로그인해도 안 풀린다
    (lambda request: httpx.Response(401, json={"error": "invalid_client"}), 502),
    (lambda request: httpx.Response(503), 502),
    (_unreachable, 502),
    (lambda request: httpx.Response(200, json={}), 502),
])
def test_token_failure_is_split_into_400_and_502(monkeypatch, handler, status):
    _kakao_answers(monkeypatch, handler)

    with pytest.raises(HTTPException) as error:
        auth_service._fetch_kakao_token("used-code")

    assert error.value.status_code == status


@pytest.mark.parametrize("handler", [
    lambda request: httpx.Response(401),
    lambda request: httpx.Response(500),
    _unreachable,
    lambda request: httpx.Response(200, json={"id": 257, "kakao_account": {}}),
])
def test_user_info_failure_is_502(monkeypatch, handler):
    # 사용자 정보는 방금 카카오가 준 토큰으로 묻는다. 여기서 거절되면 사장님 요청이 아니라 카카오 쪽 문제다
    _kakao_answers(monkeypatch, handler)

    with pytest.raises(HTTPException) as error:
        auth_service._fetch_kakao_user_info("kakao-token")

    assert error.value.status_code == 502


@pytest.mark.parametrize("handler, status", [
    (lambda request: httpx.Response(400, json={"error": "invalid_grant"}), 400),
    (lambda request: httpx.Response(503), 502),
])
def test_login_api_returns_400_or_502(monkeypatch, handler, status):
    # 함수만 보면 라우터가 예외를 감쌀 때 놓친다. 사장님이 받는 POST /login 응답으로 확인한다
    _kakao_answers(monkeypatch, handler)
    monkeypatch.setattr(auth_service, "get_settings", lambda: SimpleNamespace(
        KAKAO_CLIENT_ID="synthetic-client", KAKAO_CLIENT_SECRET="synthetic-secret",
        KAKAO_REDIRECT_URI="https://example.com/login/callback",
    ))
    app = FastAPI()
    app.include_router(auth_router.router)
    # 카카오 단계에서 끝나 DB까지 가지 않는다
    app.dependency_overrides[get_db] = lambda: None

    response = TestClient(app).post("/login", json={"code": "used-code"})

    assert response.status_code == status
