from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.sql import func
from sqlmodel import Field, Relationship, SQLModel


class CaseHistory(SQLModel, table=True):
    __tablename__ = "case_history"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False))

    raw_input: str = Field(sa_column=Column(Text, nullable=False), description="입력 원문")
    source: str = Field(
        sa_column=Column(Enum("USER_INPUT", "SYSTEM_BATCH", name="case_history_source_enum"), nullable=False)
    )
    next_action: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True), description="nullable, 판단이 발생한 경우에만"
    )
    priority_blocker_id: int | None = Field(
        default=None, sa_column=Column(BigInteger, ForeignKey("blocker.id", use_alter=True, name="fk_case_history_priority_blocker"), nullable=True)
    )

    created_at: datetime = Field(default_factory=datetime.now, sa_column=Column(DateTime, server_default=func.now(), nullable=False))

    case: "Case" = Relationship(back_populates="histories")
    procedure_step_histories: list["CaseProcedureStepHistory"] = Relationship(back_populates="case_history")


