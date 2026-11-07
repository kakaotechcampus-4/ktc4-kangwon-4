from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.agent.document_tool.models import (
    DOCUMENT_LABELS,
    CheckStep,
    DocumentContext,
    DocumentFieldName,
    DocumentKind,
    DocumentRecord,
    Issue,
)


class DocumentConfirmRequest(BaseModel):
    kind: DocumentKind
    # 사장님이 맞다고 확인한 값 전부. 빈 객체를 보내면 "확인한 값 없음"으로 저장돼 점검에서 값이 빠진 것으로 본다.
    # 화면은 꺼낸 값(fields)을 채워 보여 주고, 사장님이 고친 값까지 합쳐 그대로 보낸다.
    confirmed_fields: dict[DocumentFieldName, str]


class DocumentCheckRequest(BaseModel):
    # 서류 점검 직전에 사장님이 직접 확인한 가게 이름. 생략하면 기존 Case 이름을 쓴다.
    store_name: str | None = Field(default=None, min_length=1, max_length=50)
    # 정산 서류를 내는 사람(사장님) 이름. 이체확인증의 보낸 사람과 맞춰 본다
    applicant_name: str = Field(min_length=1, max_length=50)
    # 사장님이 확인한 실제 폐업일. 폐업 예정일로 대신하지 않으며, 비우면 점검에서 CLOSURE_DATE_UNCONFIRMED가 된다
    closure_date: date | None = None

    @field_validator("store_name", mode="before")
    @classmethod
    def trim_store_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class DocumentFieldResponse(BaseModel):
    name: DocumentFieldName
    value: str
    page: int


class DocumentResponse(BaseModel):
    document_id: UUID
    filename: str
    kind: DocumentKind
    kind_label: str
    # 종류를 모르거나 OCR·사진처럼 AI가 확신하지 못한 서류. 확인 전에는 점검이 끝나지 않는다.
    needs_confirmation: bool
    fields: list[DocumentFieldResponse]
    confirmed_fields: dict[DocumentFieldName, str] | None


class DocumentCheckResponse(BaseModel):
    status: str
    steps: list[CheckStep]
    issues: list[Issue]
    checked_at: datetime


class DocumentListResponse(BaseModel):
    store_name: str | None
    documents: list[DocumentResponse]
    # 서류를 더하거나 빼거나 확인하면 지난 점검은 지워진다(null). 다시 점검해야 제출 파일을 받을 수 있다.
    check: DocumentCheckResponse | None


def _document(record: DocumentRecord) -> DocumentResponse:
    analysis = record.analysis
    return DocumentResponse(
        document_id=record.document_id,
        filename=record.filename,
        kind=analysis.kind,
        kind_label=DOCUMENT_LABELS[analysis.kind],
        needs_confirmation=analysis.needs_confirmation or analysis.kind == DocumentKind.UNKNOWN,
        # quote(서류 원문 조각)는 내려보내지 않는다. 가린 뒤의 글이지만 화면에 쓸 곳이 없다.
        fields=[DocumentFieldResponse(name=f.name, value=f.value, page=f.page) for f in analysis.fields],
        confirmed_fields=record.confirmed_fields,
    )


def document_list_response(context: DocumentContext) -> DocumentListResponse:
    check = context.document_check
    return DocumentListResponse(
        store_name=context.business_name,
        documents=[_document(record) for record in context.documents],
        check=None if check is None else DocumentCheckResponse(
            status=check.status, steps=check.steps, issues=check.issues, checked_at=check.checked_at,
        ),
    )
