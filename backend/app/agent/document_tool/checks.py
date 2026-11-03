"""Deterministic checks on grounded fields, and verified artifact packaging."""

import hashlib
import io
import json
import re
import unicodedata
from contextlib import suppress
from datetime import date
from decimal import Decimal, InvalidOperation
from zipfile import ZIP_DEFLATED, ZipFile

import pymupdf

from app.agent.document_tool.documents import (
    DocumentError,
    DocumentService,
    redact_text,
)
from app.agent.document_tool.models import (
    DOCUMENT_LABELS,
    CheckStep,
    DocumentCheck,
    DocumentContext,
    DocumentKind,
    Issue,
)

CHECK_NAMES = (
    "서류 종류 나누기", "상호·금액·날짜 꺼내기", "필요한 서류가 다 있는지",
    "서류끼리 금액 맞춰보기", "개인정보 가리기", "확인할 일 정리",
)
# 2026 희망리턴패키지 점포철거비 공고(2026-01-19) 원문의 2차 정산 서류: 공사내역서,
# 전자세금계산서, 이체확인증, 철거 전·후 사진. 폐업 예정자는 폐업사실증명원도 낸다.
# 통장 사본은 목록에 없어 필수로 보지 않는다(올리면 예금주 대조만 한다).
# TODO: 카드 결제(카드전표·카드대금 완납확인증) 대체 경로는 서류 종류가 없어 아직 받지 못한다.
SETTLEMENT_GROUPS = (
    {DocumentKind.CONSTRUCTION_STATEMENT}, {DocumentKind.TAX_INVOICE},
    {DocumentKind.BEFORE_PHOTO, DocumentKind.AFTER_PHOTO}, {DocumentKind.TRANSFER},
    {DocumentKind.CLOSURE_CERTIFICATE},
)


def document_digest(case: DocumentContext) -> str:
    value = {"case_id": str(case.case_id), "documents": sorted(
        (record.model_dump(mode="json") for record in case.documents), key=lambda row: row["cache_key"],
    ), "applicant_name": case.applicant_name, "business_name": case.business_name,
        "closure_date": str(case.closure_date)}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def normalized(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def money(value: str) -> Decimal:
    cleaned = normalized(value).replace(",", "").removesuffix("원").removeprefix("₩")
    if not re.fullmatch(r"\d+(?:\.0+)?", cleaned):
        raise InvalidOperation
    return Decimal(cleaned)


def document_date(value: str) -> date:
    value = normalized(value).replace("년", "-").replace("월", "-").removesuffix("일")
    parts = value.strip(".").replace(".", "-").split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError("Unrecognized date format")
    return date(*(int(part) for part in parts))


def check_settlement(case: DocumentContext, service: DocumentService, *, progress=None) -> DocumentCheck:
    issues = []
    steps = [CheckStep(name=name, status="WAITING") for name in CHECK_NAMES]

    def stage(index, status):
        steps[index].status = status
        if progress is not None:
            with suppress(Exception):
                progress([step.model_copy(deep=True) for step in steps])

    def issue(code, message, records=()):
        issues.append(Issue(code=code, message=message, document_ids=[r.document_id for r in records]))

    def identity(value):
        return normalized(redact_text(value, service.private_values))

    by_kind = {}
    for record in case.documents:
        service.artifact(case.case_id, record)
        by_kind.setdefault(record.analysis.kind, []).append(record)
    stage(0, "RUNNING")
    if any(record.analysis.needs_confirmation or record.analysis.kind == DocumentKind.UNKNOWN
           for record in case.documents):
        issue("DOCUMENT_KIND_UNCONFIRMED", "서류 종류 또는 추출한 값을 확인해 주세요.")
    stage(0, "NEEDS_CONFIRMATION" if issues else "DONE")
    stage(1, "RUNNING")
    for kind, records in by_kind.items():
        if len(records) > 1:
            issue("MULTIPLE_DOCUMENTS", "같은 종류의 서류가 여러 개입니다. 점검할 자료를 선택해 주세요.", records)
    stage(1, "DONE")
    stage(2, "RUNNING")
    present = set(by_kind)
    missing = set.union(*SETTLEMENT_GROUPS) - present
    for kind in sorted(missing):
        issue("MISSING_" + kind, "정산 점검 목록에서 빠진 서류: " + DOCUMENT_LABELS[kind])
    stage(2, "NEEDS_CONFIRMATION" if missing else "DONE")
    stage(3, "RUNNING")
    amounts, fields = {}, {}
    for kind, records in by_kind.items():
        if len(records) == 1:
            record = records[0]
            fields[kind] = (record.confirmed_fields if record.confirmed_fields is not None
                            else {field.name: field.value for field in record.analysis.fields})
    for kind in (DocumentKind.CONSTRUCTION_STATEMENT, DocumentKind.TAX_INVOICE, DocumentKind.TRANSFER):
        if kind not in fields:
            continue
        values = fields[kind]
        try:
            if "amount" in values:
                amounts[kind] = money(values["amount"])
            elif kind == DocumentKind.TAX_INVOICE:
                amounts[kind] = money(values["supply_amount"]) + money(values["tax_amount"])
            else:
                raise KeyError
            if (kind == DocumentKind.TAX_INVOICE
                    and {"supply_amount", "tax_amount"} <= values.keys()
                    and amounts[kind] != money(values["supply_amount"]) + money(values["tax_amount"])):
                issue("INVOICE_TOTAL_MISMATCH", "세금계산서의 공급가액·세액·총액을 확인해 주세요.")
        except (KeyError, InvalidOperation):
            issue("AMOUNT_UNREADABLE", "금액을 정확히 읽지 못한 서류가 있습니다.", by_kind[kind])
    if len(set(amounts.values())) > 1:
        issue("AMOUNT_MISMATCH", "공사내역서·세금계산서·이체확인증의 금액이 다릅니다.")
    for left, left_field, right, right_field in (
        (DocumentKind.CONSTRUCTION_STATEMENT, "supplier", DocumentKind.TAX_INVOICE, "supplier"),
        (DocumentKind.TAX_INVOICE, "supplier", DocumentKind.TRANSFER, "recipient"),
    ):
        if left not in fields or right not in fields:
            continue
        a, b = fields[left].get(left_field), fields[right].get(right_field)
        if not a or not b:
            issue("COUNTERPARTY_UNREADABLE", "거래처 이름을 확인할 수 없습니다.")
        elif normalized(a) != normalized(b):
            issue("COUNTERPARTY_MISMATCH", "서류의 거래처·수취인 이름이 다릅니다. 임의로 같은 사람으로 처리하지 않습니다.")
    for kind, field in ((DocumentKind.TRANSFER, "sender"), (DocumentKind.BANK_COPY, "account_holder")):
        if kind not in fields:
            continue
        value = fields[kind].get(field)
        if not case.applicant_name or not value:
            issue("APPLICANT_UNCONFIRMED", "신청인과 보낸 사람·예금주를 확인해 주세요.")
        elif identity(value) != identity(case.applicant_name):
            issue("APPLICANT_MISMATCH", "신청인과 보낸 사람 또는 예금주가 다릅니다.")
    buyers = {identity(value) for value in (case.business_name, case.applicant_name) if value}
    for kind in (DocumentKind.CONSTRUCTION_STATEMENT, DocumentKind.TAX_INVOICE):
        if kind not in fields:
            continue
        buyer = fields[kind].get("buyer")
        if not buyer:
            issue("BUYER_UNCONFIRMED", "서류의 공급받는 자를 확인해 주세요.", by_kind[kind])
        elif identity(buyer) not in buyers:
            if not case.business_name:
                issue("BUYER_UNCONFIRMED", "서류의 공급받는 자와 가게·신청인의 관계를 확인해 주세요.", by_kind[kind])
            else:
                issue("BUYER_MISMATCH", "서류의 공급받는 자와 확인한 가게·신청인 이름이 다릅니다.", by_kind[kind])
    certificate = fields.get(DocumentKind.CLOSURE_CERTIFICATE, {})
    actual_date = certificate.get("closure_date")
    if actual_date is None or case.closure_date is None:
        issue("CLOSURE_DATE_UNCONFIRMED", "폐업사실증명원과 실제 폐업일을 확인해 주세요.")
    else:
        try:
            if document_date(actual_date) != case.closure_date:
                issue("CLOSURE_DATE_MISMATCH", "폐업사실증명원의 폐업일과 확인한 폐업일이 다릅니다.")
        except ValueError:
            issue("CLOSURE_DATE_UNREADABLE", "폐업사실증명원의 날짜를 정확히 읽지 못했습니다.")
    for values in fields.values():
        if case.business_name and values.get("business_name") and identity(values["business_name"]) != identity(case.business_name):
            issue("BUSINESS_NAME_MISMATCH", "현재 가게와 상호가 다른 서류가 있습니다.")
    before = by_kind.get(DocumentKind.BEFORE_PHOTO, [])
    after = by_kind.get(DocumentKind.AFTER_PHOTO, [])
    if before and after and before[0].content_hash == after[0].content_hash:
        issue("SAME_BEFORE_AFTER_PHOTO", "철거 전·후에 같은 사진이 들어 있습니다.")
    stage(3, "NEEDS_CONFIRMATION" if issues else "DONE")
    stage(4, "RUNNING")
    for record in case.documents:
        service.artifact(case.case_id, record)
    stage(4, "DONE")
    stage(5, "NEEDS_CONFIRMATION" if issues else "DONE")
    return DocumentCheck(status="ISSUES" if issues else "COMPLETE", steps=steps,
                         issues=issues, document_digest=document_digest(case))


def summary_pdf(title: str, rows: list[tuple[str, str]]) -> bytes:
    document = pymupdf.open()
    try:
        page = document.new_page()
        text = title + "\n\n" + "\n\n".join(f"{key}: {value}" for key, value in rows)
        remaining = page.insert_textbox((40, 40, 555, 800), text, fontname="korea", fontsize=12)
        if remaining < 0:
            raise DocumentError("요약 내용이 한 쪽을 넘습니다. 입력 길이를 확인해 주세요.")
        return document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()


def settlement_zip(case: DocumentContext, service: DocumentService) -> bytes:
    checked = case.document_check
    if checked is None or checked.status != "COMPLETE" or checked.document_digest != document_digest(case):
        raise DocumentError("현재 서류의 점검을 마친 뒤 제출 파일을 만들 수 있습니다.")
    output = io.BytesIO()
    required = set.union(*SETTLEMENT_GROUPS)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for record in case.documents:
            if record.analysis.kind in required:
                archive.writestr(f"{record.analysis.kind}_{record.document_id}.pdf",
                                 service.artifact(case.case_id, record).read_bytes())
        archive.writestr("점검결과.json", checked.model_dump_json(indent=2).encode())
        archive.writestr("제출안내.pdf", summary_pdf("정산 서류 점검 결과", [
            ("점검 범위", "프로토타입 정산 서류 6종 목록. 공고별 최종 요건은 별도 확인"),
            ("제출", "소상공인24에서 신청인이 직접 제출"),
            ("지원 자격·금액", "이 점검은 자격·승인·지급을 확정하지 않습니다"),
        ]))
    return output.getvalue()
