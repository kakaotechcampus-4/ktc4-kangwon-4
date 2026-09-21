from functools import lru_cache


class Settings:
    DATABASE_URL: str = "mysql+pymysql://root:devpassword@localhost:3306/closure_agent"


@lru_cache
def get_settings() -> Settings:
    return Settings()
