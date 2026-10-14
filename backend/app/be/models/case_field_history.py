from sqlalchemy import BigInteger, Column, ForeignKey, String
from sqlmodel import Field, Relationship

from app.be.models.mixins import CreatedAtMixin


class CaseFieldHistory(CreatedAtMixin, table=True):
    __tablename__ = "case_field_history"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False))
    case_history_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("case_history.id"), nullable=True),
        description="이 변경이 어느 제출(CaseHistory)에서 나왔는지. 아직 채워주는 쪽이 없어 지금은 NULL",
    )

    canonical_field: str = Field(max_length=100, description="변경된 필드명")
    before_value: str | None = Field(
        default=None, sa_column=Column(String(1000), nullable=True), description="변경 전 값"
    )
    after_value: str | None = Field(
        default=None, sa_column=Column(String(1000), nullable=True), description="변경 후 값. 비움으로 정정한 경우 NULL"
    )
    source: str = Field(max_length=50, description="변경 출처 — 값 목록 P0 미정")
    reason: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True), description="변경 사유"
    )

    case: "Case" = Relationship(back_populates="field_histories")
