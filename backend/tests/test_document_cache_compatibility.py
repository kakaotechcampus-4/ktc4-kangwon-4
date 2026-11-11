import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from document_fixtures import DocumentClient

from app.agent.document_tool import documents
from app.agent.document_tool.cache_compatibility import COMPATIBLE_SOURCE_DIGESTS
from app.agent.document_tool.documents import DocumentError, DocumentService
from app.agent.document_tool.models import DocumentKind
from app.agent.document_tool.safety import ContentSafetyGuard


@pytest.fixture
def legacy_document(tmp_path, monkeypatch):
    current = documents._source_digests()
    assert current in COMPATIBLE_SOURCE_DIGESTS, "Register the final reviewed source pair before deployment."
    monkeypatch.setattr(documents, "_source_digests", lambda: COMPATIBLE_SOURCE_DIGESTS[current])
    client, reviewer, checker = DocumentClient(), DocumentClient(), DocumentClient()
    client.needs_confirmation = True
    service = DocumentService(tmp_path, client, reviewer=reviewer, safety=ContentSafetyGuard(checker),
                              tessdata=tmp_path / "tessdata", submission_policy="RRN_BACK_ONLY")
    service.tessdata.mkdir()
    (service.tessdata / "manifest.json").write_text('{"version":1}')
    service._prepare_async = AsyncMock(return_value=(
        ["kind=TRANSFER\namount=3,300,0008"], b"synthetic-masked-pdf", 0, False,
    ))
    case_id, content = uuid4(), b"synthetic-source-pdf"
    record = asyncio.run(service.ingest(case_id, "file.pdf", content))
    record = service.confirm_analysis(case_id, record, DocumentKind.TRANSFER,
                                      confirmed_fields={"amount": "3,300,000원"})
    monkeypatch.setattr(documents, "_source_digests", lambda: current)
    return service, case_id, content, record, current


def test_completed_legacy_cache_preserves_owner_values_without_model_or_preparation_calls(legacy_document):
    service, case_id, content, record, _ = legacy_document
    clients = [service.llm, service.reviewer, service.safety.client]
    calls = [len(client.calls) for client in clients]
    preparation_calls = service._prepare_async.await_count
    assert service.artifact(case_id, record).is_file()
    cached = asyncio.run(service.ingest(case_id, "again.pdf", content))
    assert cached == record and cached.confirmed_fields == {"amount": "3,300,000원"}
    assert [len(client.calls) for client in clients] == calls
    assert service._prepare_async.await_count == preparation_calls


@pytest.mark.parametrize(("target", "attribute", "value"), [
    ("llm.config", "model", "changed"),
    ("llm.config", "reasoning_effort", "medium"),
    ("reviewer.config", "model", "changed"),
    ("reviewer.config", "reasoning_effort", "medium"),
    ("", "submission_policy", "ALL_IDENTIFIERS"),
    ("", "private_values", ("private-name",)),
    ("safety.client.config", "model", "changed"),
    ("safety.client.config", "reasoning_effort", "medium"),
    ("", "safety", None),
    ("", "manifest", '{"version":2}'),
])
def test_legacy_artifact_rejects_changed_model_privacy_safety_or_ocr_settings(
    legacy_document, target, attribute, value,
):
    service, case_id, _, record, _ = legacy_document
    subject = service
    for name in filter(None, target.split(".")):
        subject = getattr(subject, name)
    if attribute == "manifest":
        (service.tessdata / "manifest.json").write_text(value)
    else:
        setattr(subject, attribute, value)
    with pytest.raises(DocumentError, match="설정"):
        service.artifact(case_id, record)


@pytest.mark.parametrize("index", [0, 1], ids=["documents", "preparation"])
def test_unreviewed_future_source_change_rejects_legacy_artifact(legacy_document, monkeypatch, index):
    service, case_id, _, record, current = legacy_document
    future = list(current)
    future[index] = "f" * 64
    monkeypatch.setattr(documents, "_source_digests", lambda: tuple(future))
    with pytest.raises(DocumentError, match="설정"):
        service.artifact(case_id, record)


@pytest.mark.parametrize("tamper", ["pdf", "record"])
def test_legacy_compatibility_does_not_bypass_pdf_or_record_integrity(legacy_document, tamper):
    service, case_id, _, record, _ = legacy_document
    if tamper == "pdf":
        service.artifact(case_id, record).write_bytes(b"changed-pdf")
    else:
        record = record.model_copy(update={"filename": "changed.pdf"})
    with pytest.raises(DocumentError):
        service.artifact(case_id, record)


def test_incomplete_legacy_preparation_is_not_migrated(legacy_document):
    service, case_id, content, record, _ = legacy_document
    directory = service._case_directory(case_id)
    prepared = directory / f"{record.cache_key}.prepared.json"
    original = prepared.read_bytes()
    (directory / f"{record.cache_key}.json").unlink()
    service._prepare_async = AsyncMock(side_effect=DocumentError("new preparation"))
    with pytest.raises(DocumentError, match="new preparation"):
        asyncio.run(service.ingest(case_id, "again.pdf", content))
    service._prepare_async.assert_awaited_once()
    assert prepared.read_bytes() == original
