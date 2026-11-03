import asyncio
import io
from datetime import date
from zipfile import ZipFile

import pytest
from app.agent.document_tool.checks import check_settlement, settlement_zip
from app.agent.document_tool.documents import DocumentError, DocumentService
from app.agent.document_tool.models import DocumentContext, DocumentKind
from document_fixtures import DocumentClient, document_pdf


async def settlement_context(service, *, transfer=True, bank_copy=True):
    context = DocumentContext(applicant_name="김리본", business_name="봄날개인카페", closure_date=date(2026, 10, 31))
    documents = {
        DocumentKind.CONSTRUCTION_STATEMENT: {"amount": "3,300,000원", "supplier": "그린철거", "buyer": "봄날개인카페"},
        DocumentKind.TAX_INVOICE: {"supply_amount": "3,000,000원", "tax_amount": "300,000원", "supplier": "그린철거", "buyer": "봄날개인카페"},
        DocumentKind.BEFORE_PHOTO: {}, DocumentKind.AFTER_PHOTO: {},
        DocumentKind.CLOSURE_CERTIFICATE: {"closure_date": "2026년 10월 31일"},
    }
    if bank_copy:
        documents[DocumentKind.BANK_COPY] = {"account_holder": "김리본"}
    if transfer:
        documents[DocumentKind.TRANSFER] = {"amount": "3,300,000원", "sender": "김리본", "recipient": "그린철거"}
    for kind, fields in documents.items():
        record = await service.ingest(context.case_id, f"{kind}.pdf", document_pdf(kind, **fields))
        if kind in {DocumentKind.BEFORE_PHOTO, DocumentKind.AFTER_PHOTO}:
            record = service.confirm_kind(context.case_id, record, kind)
        context.documents.append(record)
    return context


def test_missing_transfer_then_new_document_only_recheck_and_eight_file_zip(tmp_path):
    async def run():
        client = DocumentClient()
        service = DocumentService(tmp_path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")
        context = await settlement_context(service, transfer=False)
        context.document_check = check_settlement(context, service)
        assert {issue.code for issue in context.document_check.issues} == {"MISSING_TRANSFER"}
        with pytest.raises(DocumentError):
            settlement_zip(context, service)
        calls = len(client.calls)
        transfer = await service.ingest(context.case_id, "transfer.pdf", document_pdf(
            DocumentKind.TRANSFER, amount="3,300,000원", sender="김리본", recipient="그린철거"))
        assert len(client.calls) == calls + 2
        context.documents.append(transfer)
        context.document_check = check_settlement(context, service)
        assert context.document_check.status == "COMPLETE"
        assert len(context.document_check.steps) == 6
        with ZipFile(io.BytesIO(settlement_zip(context, service))) as archive:
            assert archive.testzip() is None and len(archive.namelist()) == 8
    asyncio.run(run())


def test_uncertain_ocr_correction_is_explicit_and_does_not_replace_extraction(tmp_path):
    async def run():
        client = DocumentClient()
        service = DocumentService(tmp_path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")
        context = await settlement_context(service)
        index = next(i for i, r in enumerate(context.documents) if r.analysis.kind == DocumentKind.TRANSFER)
        client.needs_confirmation = True
        uncertain = await service.ingest(context.case_id, "scan.pdf", document_pdf(
            DocumentKind.TRANSFER, amount="3,300,0008", sender="김리본", recipient="그린철거"))
        context.documents[index] = uncertain
        checked = check_settlement(context, service)
        assert {"AMOUNT_MISMATCH", "DOCUMENT_KIND_UNCONFIRMED"} <= {x.code for x in checked.issues}
        context.documents[index] = service.confirm_analysis(context.case_id, uncertain, DocumentKind.TRANSFER,
            confirmed_fields={"amount": "3,300,000원", "sender": "김리본", "recipient": "그린철거"})
        context.document_check = check_settlement(context, service)
        assert context.document_check.status == "COMPLETE"
        assert uncertain.analysis.fields[0].value == "3,300,0008"
        assert settlement_zip(context, service)
    asyncio.run(run())


def test_checked_zip_is_blocked_after_processing_policy_changes(tmp_path):
    async def run():
        client = DocumentClient()
        service = DocumentService(tmp_path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")
        context = await settlement_context(service)
        context.document_check = check_settlement(context, service)
        assert context.document_check.status == "COMPLETE"
        client.config.reasoning_effort = "medium"
        with pytest.raises(DocumentError, match="설정"):
            settlement_zip(context, service)
    asyncio.run(run())


def test_bank_copy_is_not_a_required_settlement_document(tmp_path):
    # 2026 점포철거비 공고의 정산 서류 목록에 통장 사본이 없다.
    async def run():
        client = DocumentClient()
        service = DocumentService(tmp_path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")
        context = await settlement_context(service, bank_copy=False)
        context.document_check = check_settlement(context, service)
        assert context.document_check.status == "COMPLETE"
        assert context.document_check.issues == []
    asyncio.run(run())


@pytest.mark.parametrize("kind,changes,expected", [
    (DocumentKind.TRANSFER, {"amount": "4,000,000원"}, "AMOUNT_MISMATCH"),
    (DocumentKind.TAX_INVOICE, {"amount": "3,400,000원"}, "INVOICE_TOTAL_MISMATCH"),
    (DocumentKind.TRANSFER, {"recipient": "다른철거업체"}, "COUNTERPARTY_MISMATCH"),
    (DocumentKind.BANK_COPY, {"account_holder": "다른사람"}, "APPLICANT_MISMATCH"),
    (DocumentKind.CLOSURE_CERTIFICATE, {"closure_date": "2026-10-30"}, "CLOSURE_DATE_MISMATCH"),
    (DocumentKind.BANK_COPY, {"business_name": "다른가게"}, "BUSINESS_NAME_MISMATCH"),
    (DocumentKind.CONSTRUCTION_STATEMENT, {"buyer": None}, "BUYER_UNCONFIRMED"),
])
def test_mismatched_or_missing_required_field_blocks_package(tmp_path, kind, changes, expected):
    async def run():
        client = DocumentClient()
        service = DocumentService(tmp_path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")
        context = await settlement_context(service)
        record = next(item for item in context.documents if item.analysis.kind == kind)
        fields = {field.name: field.value for field in record.analysis.fields}
        if kind == DocumentKind.TAX_INVOICE:
            fields.setdefault("amount", "3,300,000원")
        fields.update(changes)
        fields = {key: value for key, value in fields.items() if value is not None}
        index = context.documents.index(record)
        context.documents[index] = service.confirm_analysis(context.case_id, record, kind, confirmed_fields=fields)
        context.document_check = check_settlement(context, service)
        assert expected in {issue.code for issue in context.document_check.issues}
        with pytest.raises(DocumentError):
            settlement_zip(context, service)
    asyncio.run(run())


def test_modifying_checked_context_or_masked_pdf_blocks_export(tmp_path):
    async def run():
        client = DocumentClient()
        service = DocumentService(tmp_path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")
        context = await settlement_context(service)
        context.document_check = check_settlement(context, service)
        altered = context.model_copy(deep=True)
        altered.applicant_name = "다른신청인"
        with pytest.raises(DocumentError):
            settlement_zip(altered, service)
        path = service.artifact(context.case_id, context.documents[0])
        path.write_bytes(path.read_bytes() + b"tampered")
        with pytest.raises(DocumentError, match="변경"):
            settlement_zip(context, service)
    asyncio.run(run())
