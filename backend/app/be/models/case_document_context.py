from typing import Optional

from sqlalchemy import JSON, BigInteger, Column, ForeignKey
from sqlmodel import Field, Relationship

from app.be.models.mixins import TimestampMixin


class CaseDocumentContext(TimestampMixin, table=True):
    """Case의 서류함 — 올린 서류 목록과 마지막 점검 결과.

    예전에는 서류 폴더의 JSON 파일에 뒀다. 파일이면 목록 전체를 덮어쓰게 되어, 서류를
    분석하는 수십 초 동안 사장님이 다른 서류를 지우면 그 삭제가 사라졌다(멘토님 #187).
    여기 두면 저장 직전에 줄을 잠그고 다시 읽을 수 있고, 판단 이력과 같은 트랜잭션에
    들어가서 "파일은 썼는데 DB 커밋이 실패"하는 상태도 안 생긴다.

    서류 원본과 가린 PDF는 그대로 폴더에 있다. 여기 담는 것은 목록과 점검 결과뿐이다.
    """

    __tablename__ = "case_document_context"

    # Case 하나에 서류함 하나다. 따로 번호를 두지 않고 case_id를 그대로 기본키로 쓴다.
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), primary_key=True))
    context: dict = Field(sa_column=Column(JSON, nullable=False))
    # 마지막으로 판단에 넘긴 서류함. 지금 서류와 비교해 다시 판단할지 정한다(#173).
    # 판단 이력과 같은 트랜잭션에서 옮긴다 — 둘은 같이 남거나 같이 없어야 한다.
    judged_context: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    case: Optional["Case"] = Relationship()  # noqa: F821
