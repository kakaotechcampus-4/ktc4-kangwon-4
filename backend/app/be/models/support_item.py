from datetime import date, datetime

from sqlalchemy import BigInteger, Column, Date, DateTime, Enum, ForeignKey, String
from sqlmodel import Field, Relationship

from app.be.models.mixins import TimestampMixin


class SupportItem(TimestampMixin, table=True):
    __tablename__ = "support_item"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    uuid: str = Field(max_length=36, unique=True, description="Wiki 원문과 연결하는 키")

    program_name: str = Field(max_length=255)
    application_start_date: date | None = Field(default=None, sa_column=Column(Date, nullable=True))
    application_end_date: date | None = Field(default=None, sa_column=Column(Date, nullable=True))
    source_file_location: str | None = Field(default=None, max_length=500, description="S3 원본 파일 위치")

    applications: list["SupportItemApplication"] = Relationship(back_populates="support_item")


class SupportItemApplication(TimestampMixin, table=True):
    __tablename__ = "support_item_application"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False))
    support_item_id: int = Field(sa_column=Column(BigInteger, ForeignKey("support_item.id"), nullable=False))

    application_status: str = Field(
        default="NOT_CHECKED",
        sa_column=Column(
            Enum(
                "NOT_CHECKED",
                "ELIGIBLE",
                "NOT_ELIGIBLE",
                "APPLIED",
                "SUPPLEMENT_REQUIRED",
                "RESUBMITTED",
                "APPROVED",
                "REJECTED",
                name="application_status_enum",
            ),
            server_default="NOT_CHECKED",
            nullable=False,
        ),
    )
    applied_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))

    case: "Case" = Relationship(back_populates="support_item_applications")
    support_item: "SupportItem" = Relationship(back_populates="applications")
