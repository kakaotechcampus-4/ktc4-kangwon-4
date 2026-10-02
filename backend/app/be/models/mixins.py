from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, text
from sqlmodel import Field, SQLModel

# 한국은 서머타임이 없어서 +09:00 고정이 영원히 정확하다. ZoneInfo와 달리 시간대 데이터
# 파일이 필요 없어서 slim 도커 이미지에서도 그대로 동작한다.
KST = timezone(timedelta(hours=9), "KST")


def kst_now() -> datetime:
    """저장용 현재 시각(한국 시각).

    MySQL DATETIME은 시간대 정보를 담지 못해서, "DB에는 한국 시각을 넣는다"는 약속을
    코드가 지켜야 한다. 폐업 신고 기한·지원사업 마감이 모두 한국 날짜 기준이라, 저장도
    한국 시각으로 두면 "오늘이 며칠인가"를 변환 없이 계산할 수 있다.

    고정 오프셋이라 서버 시간대와 무관하게 늘 한국 시각을 돌려준다.
    """

    return datetime.now(KST).replace(tzinfo=None)


class CreatedAtMixin(SQLModel):
    # 생성·수정 시각은 MySQL이 직접 넣는다(CURRENT_TIMESTAMP). 파이썬이 값을 만들어 넣으면
    # ORM을 거치지 않는 수정(직접 SQL, DB 툴, 배치)에서 시각이 안 바뀌기 때문이다.
    # MySQL의 CURRENT_TIMESTAMP는 컨테이너 시간대를 따르므로 docker-compose.yml에
    # TZ: Asia/Seoul을 맞춰둔다.
    created_at: datetime | None = Field(
        default=None,
        sa_type=DateTime,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        nullable=False,
    )


class TimestampMixin(CreatedAtMixin):
    # ON UPDATE CURRENT_TIMESTAMP를 DDL에 직접 넣어, 어느 경로로 수정하든 MySQL이 갱신하게 한다.
    # SQLAlchemy의 onupdate는 ORM이 보내는 UPDATE문에만 끼어들어서 그 밖의 수정은 놓친다.
    updated_at: datetime | None = Field(
        default=None,
        sa_type=DateTime,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")},
        nullable=False,
    )
