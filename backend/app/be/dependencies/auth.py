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
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="토큰이 만료되었습니다.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")

    token_type = payload.get("token_type")
    if token_type != expected_type:
        raise HTTPException(
            status_code=401,
            detail=f"{expected_type} 토큰이 필요하지만 {token_type} 토큰이 전달되었습니다.",
        )
    return int(payload["sub"])
