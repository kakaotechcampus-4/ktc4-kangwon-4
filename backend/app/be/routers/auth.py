from fastapi import APIRouter, Depends, Response
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.be.db import get_db
from app.be.schemas.auth import LoginRequest
from app.be.services import auth as auth_service
from app.common.config import get_settings

router = APIRouter()


@router.get("/login/form")
def login_form():
    settings = get_settings()
    kakao_auth_url = (
        "https://kauth.kakao.com/oauth/authorize"
        f"?client_id={settings.KAKAO_CLIENT_ID}"
        f"&redirect_uri={settings.KAKAO_REDIRECT_URI}"
        "&response_type=code"
        "&scope=profile_nickname"
    )
    return RedirectResponse(url=kakao_auth_url, status_code=303)


@router.post("/login")
def login(login_request: LoginRequest, response: Response, session: Session = Depends(get_db)):
    access_token, refresh_token, nickname = auth_service.login(session, login_request.code)
    response.headers["Access-Token"] = access_token
    response.headers["Refresh-Token"] = refresh_token
    return {"nickname": nickname}
