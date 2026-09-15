from datetime import date, datetime

from sqlalchemy import BigInteger, Column, Date, DateTime, Enum, ForeignKey, String
from sqlalchemy.sql import func
from sqlmodel import Field, Relationship, SQLModel


class SupportItem(SQLModel, table=True):
    __tablename__ = "support_item"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    uuid: str = Field(max_length=36, unique=True, description="Wiki 원문과 연결하는 키")

    program_name: str = Field(max_length=255)
    application_start_date: date | None = Field(default=None, sa_column=Column(Date, nullable=True))
    application_end_date: date | None = Field(default=None, sa_column=Column(Date, nullable=True))
    source_file_location: str | None = Field(default=None, max_length=500, description="Wiki 원문 위치")

    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now()))
    updated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now())
    )

    applications: list["SupportItemApplication"] = Relationship(back_populates="support_item")


class SupportItemApplication(SQLModel, table=True):
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

    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now()))
    updated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now())
    )

    case: "Case" = Relationship(back_populates="support_item_applications")
    support_item: "SupportItem" = Relationship(back_populates="applications")
