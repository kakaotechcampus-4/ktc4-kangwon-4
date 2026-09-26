from sqlalchemy import BigInteger, Column, Enum, ForeignKey, String, Text
from sqlmodel import Field, Relationship

from app.be.models.mixins import CreatedAtMixin


class CaseHistory(CreatedAtMixin, table=True):
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

    case: "Case" = Relationship(back_populates="histories")
    procedure_step_histories: list["CaseProcedureStepHistory"] = Relationship(back_populates="case_history")


