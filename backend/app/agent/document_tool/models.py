"""Python contracts for document extraction, confirmation and settlement review."""

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class DocumentKind(StrEnum):
    LEASE = "LEASE"
    BUSINESS_REGISTRATION = "BUSINESS_REGISTRATION"
    BUSINESS_LICENSE = "BUSINESS_LICENSE"
    CONSTRUCTION_STATEMENT = "CONSTRUCTION_STATEMENT"
    TAX_INVOICE = "TAX_INVOICE"
    BEFORE_PHOTO = "BEFORE_PHOTO"
    AFTER_PHOTO = "AFTER_PHOTO"
    TRANSFER = "TRANSFER"
    CLOSURE_CERTIFICATE = "CLOSURE_CERTIFICATE"
    BANK_COPY = "BANK_COPY"
    CLOSURE_RECEIPT = "CLOSURE_RECEIPT"
    CARD_SALES = "CARD_SALES"
    CASH_SALES = "CASH_SALES"
    PURCHASE_INVOICE = "PURCHASE_INVOICE"
    DEPOSIT_STATEMENT = "DEPOSIT_STATEMENT"
    UNKNOWN = "UNKNOWN"


DOCUMENT_LABELS = dict(zip(DocumentKind, (
    "임대차계약서", "사업자등록 자료", "영업신고증", "철거공사내역서", "전자세금계산서",
    "철거 전 사진", "철거 후 사진", "이체확인증", "폐업사실증명원", "통장 사본",
    "폐업신고 접수증", "카드 매출 내역", "현금영수증 매출", "매입 세금계산서",
    "보증금 공제 내역", "종류 확인 필요",
), strict=True))


DocumentFieldName = Literal[
        "business_name", "supplier", "buyer", "sender", "recipient", "account_holder",
        "amount", "supply_amount", "tax_amount", "date", "closure_date", "restoration_clause",
]


class ExtractedField(Model):
    name: DocumentFieldName
    value: str = Field(min_length=1)
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)


class DocumentAnalysis(Model):
    kind: DocumentKind
    fields: list[ExtractedField]
    needs_confirmation: bool = False


class OCRTranscript(Model):
    text: str = Field(max_length=60_000)


class DocumentRecord(Model):
    document_id: UUID
    filename: str
    content_hash: str
    analysis: DocumentAnalysis
    redaction_count: int = Field(ge=0)
    cache_key: str
    artifact_hash: str
    ocr_used: bool = False
    confirmed_fields: dict[DocumentFieldName, Annotated[str, Field(min_length=1)]] | None = None


class Issue(Model):
    code: str
    document_ids: list[UUID] = Field(default_factory=list)
    message: str


class CheckStep(Model):
    name: str
    status: Literal["WAITING", "RUNNING", "DONE", "NEEDS_CONFIRMATION", "ERROR"]


class DocumentCheck(Model):
    status: Literal["COMPLETE", "ISSUES", "ERROR"]
    steps: list[CheckStep]
    issues: list[Issue]
    document_digest: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentContext(Model):
    case_id: UUID = Field(default_factory=uuid4)
    documents: list[DocumentRecord] = Field(default_factory=list)
    document_check: DocumentCheck | None = None
    closure_date: date | None = None
    business_name: str | None = Field(default=None, repr=False)
    applicant_name: str | None = Field(default=None, repr=False)


class ReviewDecision(Model):
    verdict: Literal["PASS", "REVISE"]
    issues: list[str]


# 상호·거래 상대·예금주 같은 이름은 판단에 필요하지 않아 다시 판단하는 글에 넣지 않는다.
# 날짜(일반 날짜·폐업일)도 넣지 않는다. AI가 저장하는 날짜는 폐업 예정일뿐이라, 이미 지난
# 폐업일이 예정일로 들어갈 수 있다(#137 승준님 리뷰). 날짜 대조는 서류 점검(checks.py)이 한다.
REPLAN_FIELD_LABELS: dict[DocumentFieldName, str] = {
    "amount": "금액", "supply_amount": "공급가액", "tax_amount": "세액", "restoration_clause": "원상복구 조항",
}


def document_input_text(context: DocumentContext) -> str | None:
    """서류를 올린 뒤 기존 판단 흐름(DOCUMENT_SUBMITTED)에 넘길 글. 값마다 한 줄이다.

    사장님 확인값 목록이 있으면 그 목록에 있는 값만 쓴다(checks.py와 같다). 빈 목록이면 넣을
    값이 없고, 목록에 없는 칸을 서류에서 꺼낸 값으로 채우지 않는다. 목록이 없으면 꺼낸 값을
    쓰되, 확인이 필요한 서류는 넣지 않는다.
    서류 원문 인용(quote)이 아니라 꺼낸 값(value)을 쓴다. 인용에는 "가나철거 합계금액 …"처럼
    이름이 같이 들어 있을 수 있고, 뒤의 민감정보 검사는 이름을 보지 않는다.
    정보분석 Agent는 이 글을 사장님 입력(USER_INPUT)으로 읽으므로, 서류 값이 기존 사실을
    바로 덮지 않고 기존의 변경 후보·충돌 확인 흐름을 탄다.
    pymupdf 없이 BE가 import할 수 있게 checks.py가 아니라 이 파일에 둔다.
    """

    lines: list[str] = []
    for record in context.documents:
        analysis, confirmed = record.analysis, record.confirmed_fields
        if confirmed is None and analysis.needs_confirmation:
            continue
        label = DOCUMENT_LABELS[analysis.kind]
        for name, field_label in REPLAN_FIELD_LABELS.items():
            if confirmed is not None:
                if name in confirmed:
                    lines.append(f"{label} {field_label}(사장님 확인): {confirmed[name]}")
                continue
            values = [f.value for f in analysis.fields if f.name == name]
            lines.extend(f"{label} {field_label}: {value}" for value in dict.fromkeys(values))
    if not lines:
        return None
    return "\n".join(["사장님이 올린 서류에서 꺼낸 내용입니다.", *lines])
