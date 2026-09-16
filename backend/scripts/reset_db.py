"""
로컬 개발 전용 — 지금 존재하는 모든 테이블을 지우고 app/be/models 기준으로 다시 만든다.
JPA의 ddl-auto=create-drop과 동일한 개념. Alembic 마이그레이션 이력과는 무관하게
DB 스키마만 강제로 최신 모델 상태로 맞춘다.

참고: APP_ENV=local이면 app/main.py가 앱 기동 시 이 초기화를 자동으로 실행하므로,
평소 개발 중에는 이 스크립트를 직접 실행할 필요가 없다. docker-compose 없이
DB만 따로 초기화하고 싶을 때 등 수동으로 실행하고 싶을 때만 사용한다.

절대 배포/운영 DB에 실행하지 말 것 — 기존 데이터가 전부 삭제된다.
alembic으로 관리하는 팀 공용 DB에도 쓰지 말 것 (마이그레이션 이력과 어긋난다).

사용법:
    cd backend
    python -m scripts.reset_db
"""
from app.core.config import settings
from app.core.database import reset_all_tables


def reset_db() -> None:
    confirm = input(
        f"'{settings.DATABASE_URL}'의 모든 테이블을 삭제하고 다시 만듭니다. "
        f"기존 데이터가 전부 사라집니다. 계속할까요? (yes 입력): "
    )
    if confirm.strip().lower() != "yes":
        print("취소되었습니다.")
        return

    print("기존 테이블 삭제 중...")
    print("모델 기준으로 테이블 재생성 중...")
    reset_all_tables()
    print("완료.")


if __name__ == "__main__":
    reset_db()
