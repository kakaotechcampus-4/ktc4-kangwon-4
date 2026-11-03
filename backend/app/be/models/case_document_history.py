from sqlalchemy import BigInteger, Column, Enum, ForeignKey, String
from sqlmodel import Field

from app.be.models.mixins import CreatedAtMixin


class CaseDocumentHistory(CreatedAtMixin, table=True):
    """서류를 올리고 점검한 이력. 한 줄씩 쌓고 지우지 않는다. 기록 탭이 읽는다.

    서류 목록은 서류 폴더의 JSON(#159)에 있지만 올린 시각이 없고, 서류를 빼면 줄이 사라진다.
    """

    __tablename__ = "case_document_history"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False))
    action: str = Field(
        sa_column=Column(Enum("UPLOADED", "CHECKED", name="case_document_action_enum"), nullable=False),
        description="UPLOADED 서류를 올림 / CHECKED 정산 서류 점검을 통과함",
    )
    document_kind: str | None = Field(
        default=None,
        sa_column=Column(String(30), nullable=True),
        description="올린 순간의 서류 종류(예: TRANSFER). 나중에 종류를 고쳐도 바꾸지 않는다. 점검이면 NULL",
    )
