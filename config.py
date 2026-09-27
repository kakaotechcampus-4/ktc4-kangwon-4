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

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 1. LLM / Foundation Model (mlapi.run 프록시 경유, OpenAI 직접 호출 아님)
    proxy_token: str | None = Field(default=None, alias="PROXY_TOKEN")
    chat_proxy_url: str | None = Field(default=None, alias="CHAT_PROXY_URL")
    embedding_proxy_url: str | None = Field(default=None, alias="EMBEDDING_PROXY_URL")
    openai_model: str | None = Field(
        default="openai/gpt-4.1-mini", alias="OPENAI_MODEL"
    )
    # 현재 팀 endpoint의 gpt-4.1-mini에는 reasoning_effort를 보내지 않습니다.
    # 이를 지원하는 endpoint/model로 바꿀 때만 명시합니다.
    openai_reasoning_effort: str | None = Field(
        default=None, alias="OPENAI_REASONING_EFFORT"
    )
    openai_embedding_model: str | None = Field(
        default="openai/text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )

    # 2. 공용 (정보분석 · 행정 · 철거 · 지원금)
    data_go_kr_service_key: str | None = Field(
        default=None, alias="DATA_GO_KR_SERVICE_KEY"
    )

    # 3. 지원금
    bizinfo_api_key: str | None = Field(default=None, alias="BIZINFO_API_KEY")

    # 4. 인프라
    database_url: str | None = Field(default=None, alias="DATABASE_URL")

    # 5. 인증 — 카카오 OAuth + 자체 발급 JWT (pyjwt, 2026-09 BE 확정. BE기술스택.html §1 참고)
    kakao_client_id: str | None = Field(default=None, alias="KAKAO_CLIENT_ID")
    kakao_client_secret: str | None = Field(default=None, alias="KAKAO_CLIENT_SECRET")
    kakao_redirect_uri: str | None = Field(default=None, alias="KAKAO_REDIRECT_URI")
    jwt_secret_key: str | None = Field(default=None, alias="JWT_SECRET_KEY")

    # 6. Observability — Langfuse (SDK가 읽는 이름은 LANGFUSE_BASE_URL)
    langfuse_public_key: str | None = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    langfuse_base_url: str | None = Field(
        default="https://cloud.langfuse.com", alias="LANGFUSE_BASE_URL"
    )


# 독립적으로 실행하는 현재 경로별 필수 키 매핑입니다.
# 공식 절차 registry는 credential 없이 동작하고, data.go.kr/Law/Kakao/Google 키는
# 해당 resolver 또는 fallback을 실제 연결할 때만 필요합니다.
# CODEF/POPBILL(세무), WORK24(재취업·재창업), UPSTAGE(OCR), LANGSMITH, ANTHROPIC_API_KEY,
# VOYAGE_API_KEY는 삭제함.
# - CODEF·POPBILL: 유료 API 배제 원칙에 따라 애초에 신청하지 않기로 함
# - WORK24: 재취업·재창업 기능은 이번 MVP 스펙아웃 대상
# - UPSTAGE: 문서처리/OCR도 별도 서비스 없이 CHAT_PROXY_URL의 멀티모달 모델(이미지 입력)로 통합
# - LANGSMITH: 서드파티 SaaS라 사용자 원문이 외부로 나감 + AWS 크레딧이 있어 셀프호스팅 가능한
#   Langfuse로 대체 (EC2에 함께 배포, 데이터가 우리 인프라 밖으로 안 나감)
# - ANTHROPIC_API_KEY·VOYAGE_API_KEY: LLM/임베딩 모두 OpenAI(mlapi.run 경유)로 확정되어
#   (docs/tech-stack.md §3) 실제로 어느 코드에서도 참조하지 않는 죽은 설정이라 제거(2026-09)
REQUIRED_BY_AGENT: dict[str, list[str]] = {
    "Standalone Agent Graph": ["proxy_token", "chat_proxy_url"],
    "지원 공고 discovery": ["bizinfo_api_key"],
    "인증 (카카오 로그인)": [
        "kakao_client_id",
        "kakao_client_secret",
        "jwt_secret_key",
    ],
}


def check_settings(s: Settings) -> bool:
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
