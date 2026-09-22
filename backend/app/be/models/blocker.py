from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Enum, ForeignKey, String
from sqlmodel import Field, Relationship

from app.be.models.mixins import TimestampMixin


class Blocker(TimestampMixin, table=True):
    __tablename__ = "blocker"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False))

    created_from_case_history_id: int = Field(
        sa_column=Column(
            BigInteger, ForeignKey("case_history.id"), nullable=False, comment="이 blocker를 생성시킨 판단 로그"
        )
    )
    resolved_from_case_history_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger, ForeignKey("case_history.id"), nullable=True, comment="이 blocker를 해소시킨 판단 로그, 해소 전까지 None"
        ),
    )

    description: str = Field(max_length=500)
    status: str = Field(
        default="ACTIVE",
        sa_column=Column(Enum("ACTIVE", "RESOLVED", name="blocker_status_enum"), server_default="ACTIVE"),
    )

    resolved_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))

    case: "Case" = Relationship(back_populates="blockers")
