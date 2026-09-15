from datetime import date, datetime

from sqlalchemy import BigInteger, Column, Date, DateTime, Enum, ForeignKey, String
from sqlalchemy.sql import func
from sqlmodel import Field, Relationship, SQLModel


class Case(SQLModel, table=True):
    __tablename__ = "case"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    member_id: int = Field(sa_column=Column(BigInteger, ForeignKey("members.id"), nullable=False))

    business_type: str = Field(max_length=50)
    franchise_status: bool = Field(default=False)
    employee_count: int = Field(default=0)

    case_status: str = Field(
        default="IN_PROGRESS",
        sa_column=Column(Enum("IN_PROGRESS", "COMPLETED", name="case_status_enum"), server_default="IN_PROGRESS"),
    )
    lease_status: str = Field(
        sa_column=Column(
            Enum("LEASED_PAID", "LEASED_FREE", "OWNED", name="lease_status_enum"),
            nullable=False,
        ),
    )
    restoration_status: str = Field(
        sa_column=Column(
            Enum("NOT_STARTED", "IN_PROGRESS", "COMPLETED", "NOT_REQUIRED", name="restoration_status_enum"),
            nullable=False,
        ),
    )
    restoration_scope: str = Field(
        default="UNKNOWN",
        sa_column=Column(
            Enum("UNKNOWN", "PARTIAL", "FULL", "NOT_REQUIRED", name="restoration_scope_enum"),
            server_default="UNKNOWN",
            nullable=False,
        ),
    )
    restoration_scope_detail: str | None = Field(default=None, sa_column=Column(String(1000), nullable=True))
    demolition_required: str = Field(
        default="UNKNOWN",
        sa_column=Column(
            Enum("UNKNOWN", "REQUIRED", "NOT_REQUIRED", name="demolition_required_enum"),
            server_default="UNKNOWN",
            nullable=False,
        ),
    )

    planned_closure_date: date | None = Field(default=None, sa_column=Column(Date, nullable=True))
    completed_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now()))
    updated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now())
    )

    member: "Member" = Relationship()
    histories: list["CaseHistory"] = Relationship(back_populates="case")
    blockers: list["Blocker"] = Relationship(back_populates="case")
    case_procedure_steps: list["CaseProcedureStep"] = Relationship(back_populates="case")
    case_procedure_step_histories: list["CaseProcedureStepHistory"] = Relationship(back_populates="case")
    support_item_applications: list["SupportItemApplication"] = Relationship(back_populates="case")
