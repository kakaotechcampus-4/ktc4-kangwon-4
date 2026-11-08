import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pymupdf
import pytest
from document_fixtures import DocumentClient, document_pdf

from app.agent.document_tool.documents import DocumentError, DocumentService
from app.agent.document_tool.models import (
    DocumentAnalysis,
    DocumentKind,
    ExtractedField,
    OCRTranscript,
    ReviewDecision,
)
from app.agent.document_tool.safety import (
    ContentSafetyGuard,
    SafetyBlockedError,
    SafetyCheckUnavailableError,
    SafetyDecision,
)
from app.agent.llm import LLMRequestError, LLMResponseError


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
        monkeypatch.setattr(service, "_prepare_async", AsyncMock(return_value=([""], b"synthetic-artifact", 0, True)))
        record = await service.ingest(uuid4(), "photo.png", b"synthetic-image", kind_hint=DocumentKind.BEFORE_PHOTO)
        assert record.analysis.kind == DocumentKind.BEFORE_PHOTO
        assert record.analysis.needs_confirmation and not client.calls
    asyncio.run(run())


def test_ocr_values_require_owner_confirmation_even_when_model_is_confident(tmp_path, monkeypatch):
    async def run():
        client = DocumentClient()
        service = DocumentService(tmp_path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")
        monkeypatch.setattr(service, "_prepare_async", AsyncMock(return_value=(
            ["kind=TRANSFER\namount=3,300,000원"], document_pdf(DocumentKind.TRANSFER, amount="3,300,000원"), 0, True,
        )))
        monkeypatch.setattr(service, "_read_image_text", AsyncMock(return_value=["kind=TRANSFER\namount=3,300,000원"]))
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


@pytest.mark.parametrize(("reply", "error_type", "code", "retryable"), [
    (SafetyDecision(decision="REFUSE"), SafetyBlockedError, "AGENT_SAFETY_REFUSE", False),
    (SafetyDecision(decision="CRISIS_SUPPORT"), SafetyBlockedError, "AGENT_SAFETY_CRISIS_SUPPORT", False),
    (LLMResponseError("synthetic refusal", code="PROVIDER_REFUSAL", retryable=False),
     SafetyBlockedError, "AGENT_SAFETY_REFUSE", False),
    (LLMRequestError("synthetic failure", code="UPSTREAM_HTTP_ERROR", retryable=True),
     SafetyCheckUnavailableError, "AGENT_SAFETY_CHECK_UNAVAILABLE", True),
    (LLMResponseError("synthetic invalid response", code="INVALID_JSON", retryable=False),
     SafetyCheckUnavailableError, "AGENT_SAFETY_CHECK_UNAVAILABLE", True),
    ({"decision": "UNKNOWN"}, SafetyCheckUnavailableError, "AGENT_SAFETY_CHECK_UNAVAILABLE", True),
], ids=["refuse", "crisis", "provider-refusal", "request-failed", "invalid-response", "invalid-decision"])
def test_safety_failure_stops_extraction_review_and_record_save(tmp_path, reply, error_type, code, retryable):
    async def run():
        client, checker, reviewer = DocumentClient(), DocumentClient(), DocumentClient()
        checker.generate = AsyncMock(side_effect=[reply])
        service = DocumentService(tmp_path, client, safety=ContentSafetyGuard(checker), reviewer=reviewer,
                                  submission_policy="RRN_BACK_ONLY")
        with pytest.raises(error_type) as raised:
            await service.ingest(uuid4(), "document.pdf", document_pdf(DocumentKind.TRANSFER))
        assert raised.value.code == code and raised.value.retryable is retryable
        assert not client.calls and not reviewer.calls and checker.generate.await_count == 1
        assert not [path for path in tmp_path.rglob("*.json") if not path.name.endswith(".prepared.json")]
    asyncio.run(run())


def test_model_image_masks_full_identifier_while_submission_policy_retains_birth_part(tmp_path):
    client = DocumentClient()
    service = DocumentService(tmp_path, client, submission_policy="RRN_BACK_ONLY")
    content = document_pdf(DocumentKind.TRANSFER, amount="3,300,000원", private="900101-1234567")
    with pymupdf.open(stream=content, filetype="pdf") as source:
        birth = source[0].search_for("900101")[0]
        back = source[0].search_for("1234567")[0]
    _, model, _, _ = service._prepare(content, ".pdf", for_model=True)
    _, submission, _, _ = service._prepare(content, ".pdf")
    with pymupdf.open(stream=model, filetype="pdf") as masked:
        for rectangle in [birth, back]:
            assert max(masked[0].get_pixmap(clip=rectangle, colorspace=pymupdf.csGRAY).samples) == 0
    with pymupdf.open(stream=submission, filetype="pdf") as masked:
        assert max(masked[0].get_pixmap(clip=birth, colorspace=pymupdf.csGRAY).samples) > 0


def test_scan_uses_vision_transcript_image_review_and_cached_reupload(tmp_path):
    async def run():
        client = DocumentClient()
        client.vision_text = "kind=TRANSFER\namount=3,300,000원"
        service = DocumentService(tmp_path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")
        original = client.generate
        image_roles = []

        async def inspect(model, messages, **kwargs):
            if model in {OCRTranscript, ReviewDecision}:
                parts = messages[-1]["content"]
                assert isinstance(parts, list) and any(p["type"] == "image_url" for p in parts)
                image_roles.append(model.__name__)
            return await original(model, messages, **kwargs)

        client.generate = inspect
        with pymupdf.open(stream=document_pdf(DocumentKind.TRANSFER, amount="3,300,000원"), filetype="pdf") as source:
            content = source[0].get_pixmap().tobytes("png")
        case_id = uuid4()
        record = await service.ingest(case_id, "scan.png", content)
        assert record.ocr_used and record.analysis.needs_confirmation
        assert record.analysis.fields[0].value == "3,300,000원"
        assert image_roles == ["OCRTranscript", "ReviewDecision"]
        calls = len(client.calls)
        assert await service.ingest(case_id, "again.png", content) == record
        assert len(client.calls) == calls
    asyncio.run(run())


def test_failed_vision_read_cannot_fall_back_to_incomplete_local_ocr(tmp_path, monkeypatch):
    async def run():
        client = DocumentClient()
        service = DocumentService(tmp_path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")
        with pymupdf.open(stream=document_pdf(DocumentKind.TRANSFER), filetype="pdf") as source:
            content = source[0].get_pixmap().tobytes("png")
        monkeypatch.setattr(service, "_read_image_text", AsyncMock(side_effect=DocumentError("판독 실패")))
        with pytest.raises(DocumentError, match="판독 실패"):
            await service.ingest(uuid4(), "scan.png", content)
        assert not client.calls and not list(tmp_path.rglob("*.json"))
    asyncio.run(run())
