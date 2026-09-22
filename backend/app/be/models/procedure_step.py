from sqlalchemy import JSON, BigInteger, Column, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlmodel import Field, Relationship

from app.be.models.mixins import CreatedAtMixin, TimestampMixin


class ProcedureStep(TimestampMixin, table=True):
    __tablename__ = "procedure_step"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    step_code: str = Field(max_length=100, unique=True)
    responsible_agency: str | None = Field(default=None, max_length=255)
    deadline_rule: str | None = Field(default=None, max_length=255)
    required_documents: dict | list | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    requires_professional: bool = Field(default=False)
    professional_type: str | None = Field(default=None, max_length=100)
    caution_note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    applicable_business_type: str = Field(
        default="ALL",
        sa_column=Column(Enum("ALL", "CAFE", name="applicable_business_type_enum"), server_default="ALL", nullable=False),
    )

    case_procedure_steps: list["CaseProcedureStep"] = Relationship(back_populates="procedure_step")
    case_procedure_step_histories: list["CaseProcedureStepHistory"] = Relationship(back_populates="procedure_step")


class CaseProcedureStep(TimestampMixin, table=True):
    __tablename__ = "case_procedure_step"
    __table_args__ = (UniqueConstraint("case_id", "procedure_step_id", name="uk_case_procedure_step"),)

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False))
    procedure_step_id: int = Field(sa_column=Column(BigInteger, ForeignKey("procedure_step.id"), nullable=False))
    status: str = Field(
        default="NOT_STARTED",
        sa_column=Column(
            Enum("NOT_STARTED", "IN_PROGRESS", "COMPLETED", name="procedure_step_status_enum"),
            server_default="NOT_STARTED",
            nullable=False,
        ),
    )

    case: "Case" = Relationship(back_populates="case_procedure_steps")
    procedure_step: "ProcedureStep" = Relationship(back_populates="case_procedure_steps")


class CaseProcedureStepHistory(CreatedAtMixin, table=True):
    __tablename__ = "case_procedure_step_history"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False))
    procedure_step_id: int = Field(sa_column=Column(BigInteger, ForeignKey("procedure_step.id"), nullable=False))
    case_history_id: int | None = Field(
        default=None, sa_column=Column(BigInteger, ForeignKey("case_history.id"), nullable=True)
    )

    previous_status: str = Field(
        sa_column=Column(Enum("NOT_STARTED", "IN_PROGRESS", "COMPLETED", name="prev_step_status_enum"), nullable=False)
    )
    new_status: str = Field(
        sa_column=Column(Enum("NOT_STARTED", "IN_PROGRESS", "COMPLETED", name="new_step_status_enum"), nullable=False)
    )

    case: "Case" = Relationship(back_populates="case_procedure_step_histories")
    procedure_step: "ProcedureStep" = Relationship(back_populates="case_procedure_step_histories")
    case_history: "CaseHistory" = Relationship(back_populates="procedure_step_histories")


class StepDependency(TimestampMixin, table=True):
    __tablename__ = "step_dependency"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    procedure_step_id: int = Field(sa_column=Column(BigInteger, ForeignKey("procedure_step.id"), nullable=False))
    prerequisite_procedure_step_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("procedure_step.id"), nullable=False)
    )
    dependency_type: str = Field(max_length=50)


class StepEligibility(TimestampMixin, table=True):
    __tablename__ = "step_eligibility"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    procedure_step_id: int = Field(sa_column=Column(BigInteger, ForeignKey("procedure_step.id"), nullable=False))
    condition_key: str = Field(max_length=100)
    condition_value: str = Field(max_length=255)
