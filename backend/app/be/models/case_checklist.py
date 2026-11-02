from sqlalchemy import BigInteger, Column, ForeignKey, String, UniqueConstraint
from sqlmodel import Field

from app.be.models.mixins import CreatedAtMixin


class CaseChecklist(CreatedAtMixin, table=True):
    """사장님이 체크한 로드맵 항목. 줄이 있으면 체크됨, 체크를 풀면 줄을 지운다."""

    __tablename__ = "case_checklist"
    __table_args__ = (UniqueConstraint("case_id", "task_id", name="uk_case_checklist"),)

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False))
    task_id: str = Field(
        sa_column=Column(String(50), nullable=False),
        description="체크한 항목. AI 로드맵의 CHECKLIST_IDS 중 하나(예: dispose_stock)",
    )
