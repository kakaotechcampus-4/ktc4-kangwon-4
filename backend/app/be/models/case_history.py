from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, BigInteger, Boolean, Column, DateTime, Enum, ForeignKey, String, Text
from sqlmodel import Field, Relationship

from app.be.models.mixins import CreatedAtMixin


class CaseHistory(CreatedAtMixin, table=True):
    __tablename__ = "case_history"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False))

    # 입력 원문. USER_INPUT·CASE_CREATED는 사장님이 쓴 문장이 항상 들어가고, SYSTEM_BATCH는 배치 지시문이
    # 들어갈 수 있다. 문장 없이 고른 값만 있는 CONFLICT_DECISION만 NULL이다.
    raw_input: str | None = Field(default=None, sa_column=Column(Text, nullable=True), description="입력 원문")
    conflict_snapshot: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description=(
            "충돌이 났을 때의 Case 상태 전체. 사용자가 고른 뒤 AI에 그대로 돌려줘야 한다"
            " — AI가 받은 것이 자기가 준 것과 같은지 대조하고, 다르면 STALE로 거절한다."
            " 충돌을 낸 판단에만 값이 있다."
        ),
    )
    retained_info_result: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description=(
            "같은 글에서 충돌이 아니었던 사실·진행 보고. 확인 뒤 재판단에 그대로 돌려줘야"
            " 반영된다 — AI는 원문을 다시 읽지 않으므로, 이걸 빠뜨리면 사장님이 함께 말한"
            " 내용이 사라진다. 충돌을 낸 판단에만 값이 있고, 그 전 이력은 NULL이다."
        ),
    )
    source: str = Field(
        sa_column=Column(
            Enum("USER_INPUT", "SYSTEM_BATCH", "CASE_CREATED", "CONFLICT_DECISION", name="case_history_source_enum"),
            nullable=False,
        )
    )
    judgment_status: str = Field(
        sa_column=Column(
            Enum(
                "PENDING", "DONE", "NEEDS_MORE_INFO", "CONFLICT", "FAILED",
                name="judgment_status_enum",
            ),
            nullable=False,
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
    failure_code: str | None = Field(
        default=None,
        sa_column=Column(String(100), nullable=True),
        description=(
            "AI가 돌려준 실패 종류(REVIEW_RETRY_EXHAUSTED, LOOP_LIMIT_REACHED 등). "
            "AI가 값을 늘려도 따라 고치지 않도록 enum이 아닌 문자열로 둔다. "
            "실패가 아니거나 AI가 결과를 내기 전에 끊겼으면 NULL"
        ),
    )
    recovery_action_code: str | None = Field(
        default=None,
        sa_column=Column(
            Enum("RETRY", "RESUBMIT_INPUT", "CONTACT_SUPPORT", "NONE", name="recovery_action_code_enum"),
            nullable=True,
        ),
        description="판단이 실패했을 때 화면이 안내할 다음 행동. 실패가 아니면 NULL",
    )
    requested_field_paths: list | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="판단을 멈추게 한 Case 필드 목록. 실패가 아니면 NULL",
    )
    retryable: bool | None = Field(
        default=None,
        sa_column=Column(Boolean, nullable=True),
        description="재시도하면 성공할 가능성이 있는지. 실패가 아니면 NULL",
    )
    judged_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
        description="판단이 끝난 시각. 판단 중(PENDING)이면 NULL",
    )
    priority_blocker_id: int | None = Field(
        default=None, sa_column=Column(BigInteger, ForeignKey("blocker.id", use_alter=True, name="fk_case_history_priority_blocker"), nullable=True)
    )

    case: "Case" = Relationship(back_populates="histories")
    procedure_step_histories: list["CaseProcedureStepHistory"] = Relationship(back_populates="case_history")
    priority_blocker: Optional["Blocker"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "CaseHistory.priority_blocker_id"}
    )
