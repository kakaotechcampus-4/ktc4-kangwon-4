from sqlalchemy import JSON, BigInteger, Column, ForeignKey, String
from sqlmodel import Field, Relationship

from app.be.models.mixins import CreatedAtMixin


class CaseFieldHistory(CreatedAtMixin, table=True):
    __tablename__ = "case_field_history"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False))
    case_history_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("case_history.id"), nullable=True),
        description="이 변경이 어느 제출(CaseHistory)에서 나왔는지",
    )
    source_evidence_refs: list | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description=(
            "이 변경의 근거 evidence_id 목록. 다음 판단 스냅샷에서 이 필드의 근거로 되돌려 준다. "
            "이 값이 없으면 바뀐 값에도 최초 폼 입력이 근거로 붙어 AI가 출처를 잘못 알게 된다"
        ),
    )

    canonical_field: str = Field(max_length=100, description="변경된 필드명")
    before_value: str | None = Field(
        default=None,
        sa_column=Column(String(1000), nullable=True),
        description="변경 전 값. 값이 없었으면 NULL — Case의 미확인 enum 'UNKNOWN'과 구분한다",
    )
    after_value: str | None = Field(
        default=None, sa_column=Column(String(1000), nullable=True), description="변경 후 값. 비움으로 정정한 경우 NULL"
    )
    source: str = Field(max_length=50, description="변경 출처 — 값 목록 P0 미정")
    reason: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True), description="변경 사유"
    )

    case: "Case" = Relationship(back_populates="field_histories")
