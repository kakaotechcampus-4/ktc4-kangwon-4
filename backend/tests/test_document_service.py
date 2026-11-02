import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.agent.document_tool.documents import DocumentError, DocumentService
from app.agent.document_tool.models import (
    DocumentAnalysis,
    DocumentKind,
    ExtractedField,
    ReviewDecision,
)
from app.agent.document_tool.safety import (
    ContentSafetyGuard,
    SafetyBlockedError,
    SafetyDecision,
)
from document_fixtures import DocumentClient, document_pdf


@pytest.mark.parametrize("setting", ["model", "effort", "safety", "redaction"])
def test_settings_change_blocks_old_artifact_and_keeps_document_id_stable(tmp_path, setting):
    async def run():
        client, reviewer = DocumentClient(), DocumentClient()
        service = DocumentService(tmp_path, client, reviewer=reviewer,
                                  safety=ContentSafetyGuard(reviewer), submission_policy="RRN_BACK_ONLY")
        case_id, content = uuid4(), document_pdf(DocumentKind.TRANSFER, amount="3,300,000원")
        first = await service.ingest(case_id, "file.pdf", content)
        calls = len(client.calls)
        assert await service.ingest(case_id, "again.pdf", content) == first
        assert len(client.calls) == calls
        if setting == "model":
            client.config.model = "changed"
        elif setting == "effort":
            client.config.reasoning_effort = "medium"
        elif setting == "safety":
            reviewer.config.model = "changed"
        else:
            service.submission_policy = "ALL_IDENTIFIERS"
        with pytest.raises(DocumentError, match="설정"):
            service.artifact(case_id, first)
        refreshed = await service.ingest(case_id, "again.pdf", content)
        assert refreshed.document_id == first.document_id
        assert refreshed.cache_key != first.cache_key
        assert service.artifact(case_id, refreshed).is_file()
    asyncio.run(run())


def test_kind_confirmation_cannot_silently_approve_uncertain_values(tmp_path):
    async def run():
        client = DocumentClient()
        client.needs_confirmation = True
        service = DocumentService(tmp_path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")
        case_id = uuid4()
        record = await service.ingest(case_id, "scan.pdf", document_pdf(DocumentKind.TRANSFER, amount="3,300,0008"))
        with pytest.raises(DocumentError, match="값"):
            service.confirm_kind(case_id, record, DocumentKind.TRANSFER)
        confirmed = service.confirm_analysis(case_id, record, DocumentKind.TRANSFER,
                                             confirmed_fields={"amount": "3,300,000원"})
        assert confirmed.analysis.fields[0].value == "3,300,0008"
        assert confirmed.confirmed_fields == {"amount": "3,300,000원"}
        assert not confirmed.analysis.needs_confirmation
        assert record.analysis.needs_confirmation and record.confirmed_fields is None
        assert service.artifact(case_id, confirmed).is_file()
    asyncio.run(run())


@pytest.mark.parametrize("fields", [{"unknown": "value"}, {"amount": ""}])
def test_owner_confirmation_rejects_unknown_or_empty_fields(tmp_path, fields):
    async def run():
        client = DocumentClient()
        service = DocumentService(tmp_path, client, submission_policy="RRN_BACK_ONLY")
        case_id = uuid4()
        record = await service.ingest(case_id, "doc.pdf", document_pdf(DocumentKind.TRANSFER))
        with pytest.raises(DocumentError, match="항목"):
            service.confirm_analysis(case_id, record, DocumentKind.TRANSFER, confirmed_fields=fields)
        assert record.confirmed_fields is None
    asyncio.run(run())


def test_unreadable_photo_hint_still_requires_owner_confirmation(tmp_path, monkeypatch):
    async def run():
        client = DocumentClient()
        service = DocumentService(tmp_path, client, submission_policy="RRN_BACK_ONLY")
        monkeypatch.setattr(service, "_prepare", lambda *_: ([""], b"synthetic-artifact", 0, True))
        record = await service.ingest(uuid4(), "photo.png", b"synthetic-image", kind_hint=DocumentKind.BEFORE_PHOTO)
        assert record.analysis.kind == DocumentKind.BEFORE_PHOTO
        assert record.analysis.needs_confirmation and not client.calls
    asyncio.run(run())


def test_ocr_values_require_owner_confirmation_even_when_model_is_confident(tmp_path, monkeypatch):
    async def run():
        client = DocumentClient()
        service = DocumentService(tmp_path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")
        monkeypatch.setattr(service, "_prepare", lambda *_: (
            ["kind=TRANSFER\namount=3,300,000원"], b"synthetic-artifact", 0, True,
        ))
        case_id = uuid4()
        record = await service.ingest(case_id, "scan.png", b"synthetic-image")
        assert record.ocr_used and record.analysis.needs_confirmation
        confirmed = service.confirm_analysis(case_id, record, DocumentKind.TRANSFER,
                                             confirmed_fields={"amount": "3,300,000원"})
        assert not confirmed.analysis.needs_confirmation and confirmed.ocr_used
    asyncio.run(run())


@pytest.mark.parametrize("recover", [False, True])
def test_independent_review_rework_is_bounded_and_only_passed_extraction_is_saved(tmp_path, recover):
    async def run():
        client, reviewer = DocumentClient(), DocumentClient()
        reviewer.generate = AsyncMock(side_effect=[
            ReviewDecision(verdict="REVISE", issues=["원문과 대조해 주세요."]),
            ReviewDecision(verdict="PASS" if recover else "REVISE", issues=[]),
            ReviewDecision(verdict="REVISE", issues=["다시 확인해 주세요."]),
        ])
        service = DocumentService(tmp_path, client, reviewer=reviewer, submission_policy="RRN_BACK_ONLY")
        operation = service.ingest(uuid4(), "document.pdf", document_pdf(DocumentKind.TRANSFER, amount="3,300,000원"))
        if recover:
            assert (await operation).analysis.kind == DocumentKind.TRANSFER
            assert reviewer.generate.await_count == len(client.calls) == 2
        else:
            with pytest.raises(DocumentError, match="한도"):
                await operation
            assert reviewer.generate.await_count == len(client.calls) == 3
            assert not [p for p in tmp_path.rglob("*.json") if not p.name.endswith(".prepared.json")]
    asyncio.run(run())


def test_unsupported_quote_never_reaches_review_or_persistence(tmp_path):
    async def run():
        client, reviewer = DocumentClient(), DocumentClient()
        client.generate = AsyncMock(return_value=DocumentAnalysis(kind=DocumentKind.TRANSFER, fields=[
            ExtractedField(name="amount", value="9원", quote="없는 원문 9원", page=1),
        ]))
        reviewer.generate = AsyncMock()
        service = DocumentService(tmp_path, client, reviewer=reviewer, submission_policy="RRN_BACK_ONLY")
        with pytest.raises(DocumentError, match="한도"):
            await service.ingest(uuid4(), "document.pdf", document_pdf(DocumentKind.TRANSFER, amount="3,300,000원"))
        assert client.generate.await_count == 3 and reviewer.generate.await_count == 0
    asyncio.run(run())


def test_safety_refusal_stops_extraction(tmp_path):
    async def run():
        client, checker = DocumentClient(), DocumentClient()
        checker.generate = AsyncMock(return_value=SafetyDecision(decision="REFUSE"))
        service = DocumentService(tmp_path, client, safety=ContentSafetyGuard(checker), submission_policy="RRN_BACK_ONLY")
        with pytest.raises(SafetyBlockedError):
            await service.ingest(uuid4(), "document.pdf", document_pdf(DocumentKind.TRANSFER))
        assert not client.calls and checker.generate.await_count == 1
    asyncio.run(run())
