from fastapi import APIRouter
from fastapi.responses import RedirectResponse

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
    )
    return RedirectResponse(url=kakao_auth_url, status_code=303)
