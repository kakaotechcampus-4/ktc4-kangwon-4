import jwt
from fastapi import Header, HTTPException

from app.common.config import get_settings


def get_current_member_id(access_token: str = Header(alias="Access-Token")) -> int:
    return _decode_token(access_token, expected_type="access")


def get_refresh_member_id(refresh_token: str = Header(alias="Refresh-Token")) -> int:
    return _decode_token(refresh_token, expected_type="refresh")


def _decode_token(token: str, expected_type: str) -> int:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("token_type") != expected_type:
        raise HTTPException(status_code=401, detail="Invalid token")
    return int(payload["sub"])
