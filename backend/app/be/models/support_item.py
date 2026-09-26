from datetime import date, datetime

from sqlalchemy import BigInteger, Column, Date, DateTime, Enum, ForeignKey, String
from sqlmodel import Field, Relationship

from app.be.models.mixins import TimestampMixin


class SupportItem(TimestampMixin, table=True):
    __tablename__ = "support_item"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    uuid: str = Field(max_length=36, unique=True, description="Wiki 원문과 연결하는 키")
    external_notice_id: str | None = Field(default=None, max_length=100, description="기업마당 공고 ID")
    catalog_version: str | None = Field(default=None, max_length=50, description="카탈로그 버전")

    program_name: str = Field(max_length=255)
    application_start_date: date | None = Field(default=None, sa_column=Column(Date, nullable=True))
    application_end_date: date | None = Field(default=None, sa_column=Column(Date, nullable=True))
    source_file_location: str | None = Field(default=None, max_length=500, description="S3 원본 파일 위치")

    applications: list["SupportItemApplication"] = Relationship(back_populates="support_item")
    matches: list["SupportMatch"] = Relationship(back_populates="support_item")


class SupportMatch(TimestampMixin, table=True):
    __tablename__ = "support_match"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False), description="대상 케이스")
    support_item_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("support_item.id"), nullable=False), description="비교 대상 지원사업"
    )

    match_status: str = Field(
        sa_column=Column(
            Enum(
                "POSSIBLY_RELEVANT",
                "NEEDS_CONFIRMATION",
                "NOT_RELEVANT",
                "STALE",
                "UNVERIFIABLE",
                name="support_match_status_enum",
            ),
            nullable=False,
        )
    )
    catalog_version: str | None = Field(default=None, max_length=50, description="매칭 시점의 카탈로그 버전")

    case: "Case" = Relationship(back_populates="support_matches")
    support_item: "SupportItem" = Relationship(back_populates="matches")


class SupportItemApplication(TimestampMixin, table=True):
    __tablename__ = "support_item_application"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False))
    support_item_id: int = Field(sa_column=Column(BigInteger, ForeignKey("support_item.id"), nullable=False))

    application_status: str = Field(
        default="NOT_STARTED",
        sa_column=Column(
            Enum(
                "NOT_STARTED",
                "APPLIED",
                "SUPPLEMENT_REQUIRED",
                "RESUBMITTED",
                "APPROVED",
                "REJECTED",
                name="application_status_enum",
            ),
            server_default="NOT_STARTED",
            nullable=False,
        ),
    )
    applied_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))

    case: "Case" = Relationship(back_populates="support_item_applications")
    support_item: "SupportItem" = Relationship(back_populates="applications")
