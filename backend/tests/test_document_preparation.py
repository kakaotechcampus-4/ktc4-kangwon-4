import asyncio
import os
import time
from uuid import uuid4

import pymupdf
import pytest
from app.agent.document_tool import preparation
from app.agent.document_tool.documents import DocumentError, DocumentService
from app.agent.document_tool.models import DocumentContext, DocumentKind
from app.agent.document_tool.tool import DocumentTool
from document_fixtures import DocumentClient, document_pdf


def test_pdf_preparation_runs_in_a_child_process_without_blocking_the_event_loop(tmp_path, monkeypatch):
    async def run():
        calls = []
        original = preparation.run_pdf

        async def observed(function, *args):
            calls.append(function.__name__)
            return await original(function, *args)

        monkeypatch.setattr(preparation, "run_pdf", observed)
        client = DocumentClient()
        service = DocumentService(tmp_path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")
        await service.ingest(uuid4(), "synthetic.pdf", document_pdf(DocumentKind.TRANSFER, amount="100원"))
        assert "prepare_document" in calls
        assert await original(os.getpid) != os.getpid()
        ticks = 0
        task = asyncio.create_task(original(time.sleep, 0.2))
        while not task.done():
            await asyncio.sleep(0.01)
            ticks += 1
        await task
        assert ticks >= 3
    asyncio.run(run())


@pytest.mark.parametrize("method", ["get_pixmap", "apply_redactions"])
def test_rendering_and_redaction_failures_have_safe_document_errors(tmp_path, monkeypatch, method):
    service = DocumentService(tmp_path, DocumentClient(), submission_policy="RRN_BACK_ONLY")
    content = document_pdf(DocumentKind.TRANSFER, private="900101-1234567")
    monkeypatch.setattr(pymupdf.Page, method, lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("private-error")))
    with pytest.raises(DocumentError, match="문서를 처리") as caught:
        service._prepare(content, ".pdf")
    assert "private-error" not in str(caught.value)


def test_corrupt_pdf_fails_safely_in_the_real_worker_before_model_calls(tmp_path):
    async def run():
        client = DocumentClient()
        tool = DocumentTool(DocumentService(tmp_path, client, submission_policy="RRN_BACK_ONLY"))
        with pytest.raises(DocumentError, match="파일"):
            await tool.add_document(DocumentContext(), "corrupt.pdf", b"%PDF-1.4 deliberately corrupted")
        assert not client.calls and not list(tmp_path.rglob("*.json"))
    asyncio.run(run())
