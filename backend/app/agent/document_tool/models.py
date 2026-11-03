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
