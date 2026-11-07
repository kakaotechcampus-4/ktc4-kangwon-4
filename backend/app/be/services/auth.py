from datetime import datetime, timedelta, timezone

import httpx
import jwt
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.be.crud import member as member_crud
from app.common.config import get_settings


def login(session: Session, code: str) -> tuple[str, str, str]:
    kakao_access_token = _fetch_kakao_token(code)
    oauth_id, nickname = _fetch_kakao_user_info(kakao_access_token)

    member = member_crud.get_member_by_oauth_id(session, oauth_id)
    if member is None:
        try:
            member = member_crud.create_member(session, oauth_id, nickname)
        except IntegrityError:
            # 같은 카카오 계정의 첫 로그인이 동시에 와서 다른 요청이 먼저 만들었다(#257).
            # 되돌리고 그 회원으로 이어서 로그인한다
            session.rollback()
            member = member_crud.get_member_by_oauth_id(session, oauth_id)
            if member is None:
                # members의 UNIQUE는 oauth_id 하나뿐이라 여기서는 반드시 찾는다.
                # UNIQUE가 늘어 다른 위반을 잡았다면 원인을 숨기지 않고 그대로 낸다
                raise
    member.nickname = nickname

    access_token = _create_access_token(member.id)
    refresh_token = _create_refresh_token(member.id)

    member.refresh_token = refresh_token
    session.commit()

    return access_token, refresh_token, nickname


def logout(session: Session, member_id: int) -> None:
    member = member_crud.get_member_by_id(session, member_id)
    if member is None:
        raise HTTPException(status_code=401, detail="존재하지 않는 회원입니다.")
    member.refresh_token = None
    session.commit()


def reissue(session: Session, member_id: int, refresh_token: str) -> tuple[str, str]:
    member = member_crud.get_member_by_id(session, member_id)
    if member is None:
        raise HTTPException(status_code=401, detail="존재하지 않는 회원입니다.")
    if member.refresh_token != refresh_token:
        raise HTTPException(status_code=401, detail="유효하지 않은 Refresh 토큰입니다.")

    new_access_token = _create_access_token(member.id)
    new_refresh_token = _create_refresh_token(member.id)

    member.refresh_token = new_refresh_token
    session.commit()

    return new_access_token, new_refresh_token


def _fetch_kakao_token(code: str) -> str:
    settings = get_settings()
    with httpx.Client() as client:
        response = client.post(
            "https://kauth.kakao.com/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": settings.KAKAO_CLIENT_ID,
                "client_secret": settings.KAKAO_CLIENT_SECRET,
                "redirect_uri": settings.KAKAO_REDIRECT_URI,
                "code": code,
            },
        )
        response.raise_for_status()
        return response.json()["access_token"]


def _fetch_kakao_user_info(kakao_access_token: str) -> tuple[str, str]:
    with httpx.Client() as client:
        response = client.get(
            "https://kapi.kakao.com/v2/user/me",
            headers={"Authorization": f"Bearer {kakao_access_token}"},
        )
        response.raise_for_status()
        user_info = response.json()

    oauth_id = str(user_info["id"])
    nickname = user_info["kakao_account"]["profile"]["nickname"]
    return oauth_id, nickname


def _create_access_token(member_id: int) -> str:
    settings = get_settings()
    payload = {
        "sub": str(member_id),
        "token_type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


def _create_refresh_token(member_id: int) -> str:
    settings = get_settings()
    payload = {
        "sub": str(member_id),
        "token_type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")
