from typing import Optional

from sqlalchemy import JSON, BigInteger, Column, Enum, ForeignKey, Text
from sqlmodel import Field, Relationship

from app.be.models.mixins import CreatedAtMixin


class CaseHistory(CreatedAtMixin, table=True):
    __tablename__ = "case_history"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False))

    raw_input: str = Field(sa_column=Column(Text, nullable=False), description="입력 원문")
    source: str = Field(
        sa_column=Column(Enum("USER_INPUT", "SYSTEM_BATCH", "CASE_CREATED", name="case_history_source_enum"), nullable=False)
    )
    judgment_status: str = Field(
        sa_column=Column(
            Enum("PENDING", "DONE", "NEEDS_MORE_INFO", "FAILED", name="judgment_status_enum"), nullable=False
        ),
        description="판단 진행 상태. 입력을 받으면 PENDING으로 시작해 판단이 끝나면 갱신된다",
    )
    # AI가 내는 문장에는 길이 제한이 없어서 TEXT로 둔다(blocker.description과 같은 이유).
    next_action: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True), description="nullable, 판단이 발생한 경우에만"
    )
    next_action_reason: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True), description="다음 행동을 해야 하는 이유"
    )
    next_action_questions_to_ask: list | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="사용자가 임대인·기관에 물어볼 질문 목록. 다음 행동이 없으면 NULL",
    )
    next_action_evidence_refs: list | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="다음 행동의 근거 evidence_id 목록. 다음 행동이 없으면 NULL",
    )
    questions_for_user: list | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="행동을 정하기 전 서비스가 사용자에게 되묻는 질문 목록. 없으면 NULL",
    )
    priority_blocker_id: int | None = Field(
        default=None, sa_column=Column(BigInteger, ForeignKey("blocker.id", use_alter=True, name="fk_case_history_priority_blocker"), nullable=True)
    )

    case: "Case" = Relationship(back_populates="histories")
    procedure_step_histories: list["CaseProcedureStepHistory"] = Relationship(back_populates="case_history")
    priority_blocker: Optional["Blocker"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "CaseHistory.priority_blocker_id"}
    )
