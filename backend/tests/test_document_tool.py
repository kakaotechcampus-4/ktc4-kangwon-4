import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.agent.document_tool.documents import DocumentError, DocumentService
from app.agent.document_tool.models import DocumentContext, DocumentKind
from app.agent.document_tool.tool import (
    DocumentBatchError,
    DocumentTool,
    build_document_tool,
)
from app.agent.llm import current_call_budget
from app.agent.run_scope import current_deadline
from document_fixtures import DocumentClient, document_pdf


def make_agent(path):
    client = DocumentClient()
    return DocumentTool(DocumentService(path, client, reviewer=client, submission_policy="RRN_BACK_ONLY")), client


def test_reanalysis_replaces_same_document_and_invalidates_check_without_mutating_caller(tmp_path):
    async def run():
        agent, client = make_agent(tmp_path)
        content = document_pdf(DocumentKind.TRANSFER, amount="3,300,000원")
        original = DocumentContext()
        first = await agent.add_document(original, "first.pdf", content)
        unchanged = await agent.add_document(first, "renamed.pdf", content)
        calls = len(client.calls)
        assert first.model_dump_json() == unchanged.model_dump_json()
        client.config.reasoning_effort = "medium"
        updated = await agent.add_documents(first, [("same.pdf", content, None)])
        assert len(updated.documents) == 1 and not original.documents
        assert updated.documents[0].document_id == first.documents[0].document_id
        assert updated.documents[0].cache_key != first.documents[0].cache_key
        assert len(client.calls) == calls + 2
        assert updated.document_check is None
        assert first.documents[0].cache_key != updated.documents[0].cache_key
    asyncio.run(run())


def test_batch_preserves_partial_progress_and_one_budget_deadline(tmp_path, monkeypatch):
    async def run():
        agent, client = make_agent(tmp_path)
        files = [("one.pdf", document_pdf(DocumentKind.LEASE), None),
                 ("two.pdf", document_pdf(DocumentKind.TRANSFER), None)]
        snapshots = []
        ingest = agent.documents.ingest

        async def fail_second(case_id, filename, data, **kwargs):
            snapshots.append((current_call_budget(), current_deadline()))
            if filename == "two.pdf":
                raise ValueError("synthetic interruption")
            return await ingest(case_id, filename, data, **kwargs)

        monkeypatch.setattr(agent.documents, "ingest", fail_second)
        with pytest.raises(DocumentBatchError) as caught:
            await agent.add_documents(DocumentContext(), files)
        partial = caught.value.partial_case
        assert len(partial.documents) == 1 and caught.value.failed_file_index == 1
        assert snapshots[0][0] is snapshots[1][0] and snapshots[0][1] is snapshots[1][1]
        calls = len(client.calls)
        monkeypatch.setattr(agent.documents, "ingest", ingest)
        resumed = await agent.add_documents(partial, files)
        assert len(resumed.documents) == 2 and len(client.calls) == calls + 2
    asyncio.run(run())


def test_confirmation_is_bound_to_current_case_and_explicit_owner_values(tmp_path):
    async def run():
        agent, client = make_agent(tmp_path)
        client.needs_confirmation = True
        first = await agent.add_document(DocumentContext(), "scan.pdf", document_pdf(
            DocumentKind.TRANSFER, amount="3,300,0008"))
        record = first.documents[0]
        with pytest.raises(DocumentError):
            agent.confirm_document(DocumentContext(), record.document_id, DocumentKind.TRANSFER,
                                   confirmed_fields={"amount": "3,300,000원"})
        confirmed = agent.confirm_document(first, record.document_id, DocumentKind.TRANSFER,
                                           confirmed_fields={"amount": "3,300,000원"})
        assert confirmed.documents[0].confirmed_fields == {"amount": "3,300,000원"}
        assert first.documents[0].confirmed_fields is None
        restored = DocumentContext.model_validate_json(confirmed.model_dump_json())
        assert restored == confirmed
        removed = agent.remove_document(restored, record.document_id)
        assert not removed.documents and len(restored.documents) == 1
        with pytest.raises(DocumentError):
            agent.remove_document(removed, uuid4())
    asyncio.run(run())


def test_factory_uses_document_role_and_shared_review_without_mobile_models(tmp_path, monkeypatch):
    from app.agent.document_tool import tool as module

    env = tmp_path / "settings.env"
    env.write_text("CHAT_PROXY_URL=https://example.invalid/v1\nPROXY_TOKEN=test-only\n"
                   "OPENAI_MODEL=strong-review\nOPENAI_REASONING_EFFORT=xhigh\n"
                   "AGENT_DOCUMENT_MODEL_PREFIX=LUNA6_\nAGENT_DOCUMENT_REASONING_EFFORT=medium\n"
                   "LUNA6_CHAT_PROXY_URL=https://example.invalid/v1\nLUNA6_PROXY_TOKEN=test-only\n"
                   "LUNA6_MODEL=small-document\nLUNA6_REASONING_EFFORT=high\n")
    clients = []

    def client(config, **_):
        value = type("Client", (), {"config": config, "aclose": AsyncMock()})()
        clients.append(value)
        return value

    monkeypatch.setattr(module, "StructuredLLMClient", client)
    monkeypatch.setattr(module.LangfuseTraceSink, "from_env", lambda **_: None)

    async def run():
        agent = await build_document_tool(tmp_path / "vault", submission_policy="RRN_BACK_ONLY", env_file=env)
        assert agent.documents.llm.config.model == "small-document"
        assert agent.documents.llm.config.reasoning_effort == "medium"
        assert agent.documents.reviewer.config.model == "strong-review"
        assert agent.documents.reviewer.config.reasoning_effort == "xhigh"
        await agent.aclose()
        assert all(item.aclose.await_count == 1 for item in clients)
    asyncio.run(run())
