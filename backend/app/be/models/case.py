from datetime import date, datetime

from sqlalchemy import BigInteger, Column, Date, DateTime, Enum, ForeignKey, String
from sqlmodel import Field, Relationship

from app.be.models.mixins import TimestampMixin


class Case(TimestampMixin, table=True):
    __tablename__ = "case"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    member_id: int = Field(sa_column=Column(BigInteger, ForeignKey("members.id"), nullable=False, unique=True))

    # AI 판단에 쓰지 않는다.
    store_name: str | None = Field(default=None, sa_column=Column(String(50), nullable=True))
    business_type: str = Field(max_length=50)
    franchise_status: bool = Field(default=False)
    employee_count: int | None = Field(default=None)
    has_business_loan: bool | None = Field(default=None)
    has_service_contracts: bool | None = Field(default=None)

    # 직원 고용 이력과 사업장 4대보험 가입 이력. 모두 "지금"이 아니라 "있었던 적"을 묻는다
    # (blocker_candidates.py:43-47). 지금 직원이 0명이어도 지난달 내보낸 직원의 퇴직금 정산이
    # 남아 있고, 이미 탈퇴한 보험도 상실·탈퇴 신고 대상이기 때문이다.
    #
    # NULL은 "안 물어봤다"는 뜻이고 AI에는 모름으로 넘어간다. false("아니오")와 다르다 —
    # 안 물어본 것을 false로 두면 AI가 해당 절차를 "해당 없음"으로 보고 로드맵에서 빼버린다.
    #
    # 보험은 네 칸을 같이 채워야 한다. AI는 넷 중 하나라도 true면 해당, 넷 다 false여야
    # 해당 없음으로 보고, 섞이면 모름으로 둔다(rules.py:129-136).
    had_employees: bool | None = Field(default=None)
    pension_enrolled: bool | None = Field(default=None)
    health_insurance_enrolled: bool | None = Field(default=None)
    employment_insurance_enrolled: bool | None = Field(default=None)
    industrial_accident_insurance_enrolled: bool | None = Field(default=None)

    case_status: str = Field(
        default="IN_PROGRESS",
        sa_column=Column(Enum("IN_PROGRESS", "COMPLETED", name="case_status_enum"), server_default="IN_PROGRESS", nullable=False),
    )
    lease_status: str = Field(
        sa_column=Column(
            Enum("LEASED_PAID", "LEASED_FREE", "OWNED", name="lease_status_enum"),
            nullable=False,
        ),
    )
    restoration_clause: str = Field(
        default="UNKNOWN",
        sa_column=Column(
            Enum("EXISTS", "NOT_EXISTS", "UNKNOWN", name="restoration_clause_enum"),
            server_default="UNKNOWN",
            nullable=False,
        ),
    )
    restoration_status: str = Field(
        default="UNKNOWN",
        sa_column=Column(
            Enum("UNKNOWN", "NOT_STARTED", "IN_PROGRESS", "COMPLETED", "NOT_REQUIRED", name="restoration_status_enum"),
            server_default="UNKNOWN",
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
    # 정확한 날짜 대신 예상 달만 정했을 때 "YYYY-MM". 날짜가 있으면 비워 둔다
    planned_closure_month: str | None = Field(default=None, sa_column=Column(String(7), nullable=True))
    completed_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))

    member: "Member" = Relationship()
    histories: list["CaseHistory"] = Relationship(back_populates="case")
    field_histories: list["CaseFieldHistory"] = Relationship(back_populates="case")
    blockers: list["Blocker"] = Relationship(back_populates="case")
    case_procedure_steps: list["CaseProcedureStep"] = Relationship(back_populates="case")
    support_item_applications: list["SupportItemApplication"] = Relationship(back_populates="case")
    support_matches: list["SupportMatch"] = Relationship(back_populates="case")
    evidence_records: list["Evidence"] = Relationship(back_populates="case")
    conflict_references: list["ConflictReference"] = Relationship(back_populates="case")
    decision_records: list["DecisionRecord"] = Relationship(back_populates="case")
