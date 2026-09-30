from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime
from sqlalchemy.sql import func
from sqlmodel import Field, SQLModel

# 한국은 서머타임이 없어서 +09:00 고정이 영원히 정확하다. ZoneInfo와 달리 시간대 데이터
# 파일이 필요 없어서 slim 도커 이미지에서도 그대로 동작한다.
KST = timezone(timedelta(hours=9), "KST")


def kst_now() -> datetime:
    """저장용 현재 시각(한국 시각).

    MySQL DATETIME은 시간대 정보를 담지 못해서, "DB에는 한국 시각을 넣는다"는 약속을
    코드가 지켜야 한다. 폐업 신고 기한·지원사업 마감이 모두 한국 날짜 기준이라, 저장도
    한국 시각으로 두면 "오늘이 며칠인가"를 변환 없이 계산할 수 있다.

    MySQL의 server_default/onupdate(func.now())는 DB가 값을 넣으므로, 컨테이너 시간대를
    Asia/Seoul로 맞춰야 기준이 어긋나지 않는다(docker-compose.yml의 TZ).
    """

    return datetime.now(KST).replace(tzinfo=None)


class CreatedAtMixin(SQLModel):
    created_at: datetime = Field(
        default_factory=kst_now,
        sa_type=DateTime,
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: datetime = Field(
        default_factory=kst_now,
        sa_type=DateTime,
        sa_column_kwargs={"server_default": func.now(), "onupdate": func.now()},
        nullable=False,
    )
