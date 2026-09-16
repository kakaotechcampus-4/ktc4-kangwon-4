"""
환경변수 로더 (pydantic-settings 기반).
docker-compose.yml의 DATABASE_URL, APP_ENV 환경변수를 그대로 읽는다.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "mysql+pymysql://root:devpassword@localhost:3306/closure_agent"

    # local: 앱 시작 시 매번 테이블을 drop_all + create_all로 초기화 (Spring db-dev의 ddl-auto: create와 동일)
    # prod: 초기화 없음 — 스키마는 alembic 마이그레이션으로만 관리
    APP_ENV: str = "local"


settings = Settings()
