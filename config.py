"""
config.py
─────────────────────────────────────────────────────────────
.env 파일에 붙여넣은 API 키들을 로드하고, agent별로 필요한 키가
빠짐없이 채워졌는지 확인해주는 설정 모듈.

사용법:
    from config import settings

    settings.proxy_token
    settings.chat_proxy_url
    ...

실행하면 어떤 키가 비어있는지 바로 확인할 수 있습니다:
    python config.py
─────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 1. LLM / Foundation Model (mlapi.run 프록시 경유, OpenAI 직접 호출 아님)
    proxy_token: Optional[str] = Field(default=None, alias="PROXY_TOKEN")
    chat_proxy_url: Optional[str] = Field(default=None, alias="CHAT_PROXY_URL")
    embedding_proxy_url: Optional[str] = Field(default=None, alias="EMBEDDING_PROXY_URL")
    openai_model: Optional[str] = Field(default="openai/gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_embedding_model: Optional[str] = Field(
        default="openai/text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    voyage_api_key: Optional[str] = Field(default=None, alias="VOYAGE_API_KEY")

    # 2. 공용 (정보분석 · 행정 · 철거 · 지원금)
    data_go_kr_service_key: Optional[str] = Field(default=None, alias="DATA_GO_KR_SERVICE_KEY")

    # 3. 지원금
    bizinfo_api_key: Optional[str] = Field(default=None, alias="BIZINFO_API_KEY")

    # 4. 인프라
    database_url: Optional[str] = Field(default=None, alias="DATABASE_URL")
    redis_url: Optional[str] = Field(default=None, alias="REDIS_URL")

    # 5. 인증 — 카카오 OAuth + 자체 발급 JWT (pyjwt, 2026-09 BE 확정. BE기술스택.html §1 참고)
    kakao_client_id: Optional[str] = Field(default=None, alias="KAKAO_CLIENT_ID")
    kakao_client_secret: Optional[str] = Field(default=None, alias="KAKAO_CLIENT_SECRET")
    kakao_redirect_uri: Optional[str] = Field(default=None, alias="KAKAO_REDIRECT_URI")
    jwt_secret_key: Optional[str] = Field(default=None, alias="JWT_SECRET_KEY")

    # 6. Observability — Langfuse (셀프호스팅, EC2에 함께 배포)
    langfuse_public_key: Optional[str] = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: Optional[str] = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    langfuse_host: Optional[str] = Field(default="http://localhost:3000", alias="LANGFUSE_HOST")


# agent별로 반드시 있어야 동작하는 키 매핑
# (여기 없는 키는 전부 선택사항: 없어도 서버는 뜨지만 해당 기능만 비활성화됨)
# CODEF/POPBILL(세무), WORK24(재취업·재창업), UPSTAGE(OCR), LANGSMITH는 삭제함.
# - CODEF·POPBILL: 유료 API 배제 원칙에 따라 애초에 신청하지 않기로 함
# - WORK24: 재취업·재창업 기능은 이번 MVP 스펙아웃 대상
# - UPSTAGE: 문서처리/OCR도 별도 서비스 없이 CHAT_PROXY_URL의 멀티모달 모델(이미지 입력)로 통합
# - LANGSMITH: 서드파티 SaaS라 사용자 원문이 외부로 나감 + AWS 크레딧이 있어 셀프호스팅 가능한
#   Langfuse로 대체 (EC2에 함께 배포, 데이터가 우리 인프라 밖으로 안 나감)
REQUIRED_BY_AGENT: dict[str, list[str]] = {
    "LLM (전체 공통)": ["proxy_token", "chat_proxy_url"],
    "정보분석 / 행정": ["data_go_kr_service_key"],
    "철거 보조": ["data_go_kr_service_key"],
    "지원금": ["bizinfo_api_key", "data_go_kr_service_key"],
    "인증 (카카오 로그인)": ["kakao_client_id", "kakao_client_secret", "jwt_secret_key"],
}


def check_settings(s: "Settings") -> bool:
    """agent별 필수 키가 채워졌는지 콘솔에 출력. 전부 채워졌으면 True 반환."""
    print("\n[.env 설정 확인]")
    all_ok = True
    for agent, keys in REQUIRED_BY_AGENT.items():
        missing = [k.upper() for k in keys if not getattr(s, k)]
        if missing:
            all_ok = False
            print(f"  ⚠️  {agent:16s} → 누락된 키: {', '.join(missing)}")
        else:
            print(f"  ✅ {agent:16s} → 준비 완료")
    print()
    return all_ok


settings = Settings()

if __name__ == "__main__":
    check_settings(settings)
