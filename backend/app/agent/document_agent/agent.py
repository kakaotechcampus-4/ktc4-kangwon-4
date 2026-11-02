"""Document Agent entry points; callers own persistence, authentication and uploads."""

import asyncio
import os
from collections.abc import Callable, Mapping
from contextlib import contextmanager, suppress
from dataclasses import replace
from pathlib import Path
from typing import TypeVar
from uuid import UUID

from dotenv import dotenv_values

from app.agent.document_agent.checks import check_settlement, settlement_zip
from app.agent.document_agent.documents import DocumentError, DocumentService
from app.agent.document_agent.models import (
    DocumentContext,
    DocumentFieldName,
    DocumentKind,
    DocumentRecord,
)
from app.agent.document_agent.safety import ContentSafetyGuard
from app.agent.llm import (
    LLMCallBudget,
    LLMConfig,
    ScopedCallBudget,
    StructuredLLMClient,
    call_budget_scope,
    current_call_budget,
    resolve_max_calls_per_run,
)
from app.agent.run_scope import RunDeadline, current_deadline, run_deadline_scope
from app.agent.runtime import resolve_run_deadline_seconds
from app.agent.tracing import LangfuseTraceSink, observation_scope

Context = TypeVar("Context", bound=DocumentContext)


class DocumentBatchError(DocumentError):
    def __init__(self, partial_case: DocumentContext, failed_file_index: int):
        super().__init__("문서 처리가 중단됐습니다. 완료한 파일을 유지하고 실패한 파일부터 다시 확인해 주세요.")
        self.partial_case = partial_case
        self.failed_file_index = failed_file_index


class DocumentAgent:
    def __init__(self, documents: DocumentService, *, trace_sink=None):
        self.documents = documents
        self._trace_sink = trace_sink

    @contextmanager
    def operation(self, name: str, case_id: UUID):
        with (
            call_budget_scope(current_call_budget() or LLMCallBudget(resolve_max_calls_per_run())),
            run_deadline_scope(current_deadline() or RunDeadline.after(resolve_run_deadline_seconds())),
            observation_scope(name, sink=self._trace_sink, as_type="span", metadata={"case_id": str(case_id)}),
        ):
            yield

    @staticmethod
    def _store(context: Context, record: DocumentRecord) -> None:
        old = next((item for item in context.documents if item.document_id == record.document_id), None)
        if old == record:
            return
        if old is None:
            context.documents.append(record)
        else:
            context.documents = [record if item.document_id == record.document_id else item for item in context.documents]
        context.document_check = None

    async def add_document(
        self, context: Context, filename: str, content: bytes, *, kind_hint: DocumentKind | None = None,
    ) -> Context:
        result = context.model_copy(deep=True)
        with self.operation("DOCUMENT_AGENT", result.case_id):
            record = await self.documents.ingest(result.case_id, filename, content, kind_hint=kind_hint)
        self._store(result, record)
        return result

    async def add_documents(
        self, context: Context, files: list[tuple[str, bytes, DocumentKind | None]], *,
        progress: Callable[[int, int, UUID], None] | None = None,
    ) -> Context:
        if not files or len(files) > 20 or sum(len(data) for _, data, _ in files) > 50_000_000:
            raise DocumentError("한 번에 20개·총 50MB 이하의 문서를 올려주세요.")
        result = context.model_copy(deep=True)
        with self.operation("DOCUMENT_BATCH", result.case_id):
            for index, (filename, content, hint) in enumerate(files):
                try:
                    record = await self.documents.ingest(result.case_id, filename, content, kind_hint=hint)
                except Exception:  # noqa: BLE001 - keep completed records and hide provider bodies
                    raise DocumentBatchError(result, index) from None
                self._store(result, record)
                if progress is not None:
                    with suppress(Exception):
                        progress(index + 1, len(files), record.document_id)
        return result

    def confirm_document(
        self, context: Context, document_id: UUID, kind: DocumentKind, *,
        confirmed_fields: Mapping[DocumentFieldName, str],
    ) -> Context:
        result = context.model_copy(deep=True)
        record = next((item for item in result.documents if item.document_id == document_id), None)
        if record is None:
            raise DocumentError("현재 Case의 문서가 아닙니다.")
        with self.operation("DOCUMENT_CONFIRMATION", result.case_id):
            confirmed = self.documents.confirm_analysis(
                result.case_id, record, kind, confirmed_fields=dict(confirmed_fields),
            )
        self._store(result, confirmed)
        return result

    def remove_document(self, context: Context, document_id: UUID) -> Context:
        result = context.model_copy(deep=True)
        if not any(item.document_id == document_id for item in result.documents):
            raise DocumentError("현재 Case의 문서가 아닙니다.")
        result.documents = [item for item in result.documents if item.document_id != document_id]
        result.document_check = None
        return result

    def check_documents(self, context: Context, *, progress=None) -> Context:
        result = context.model_copy(deep=True)
        with self.operation("DOCUMENT_CHECK", result.case_id):
            result.document_check = check_settlement(result, self.documents, progress=progress)
        return result

    def prepare_settlement(self, context: DocumentContext) -> bytes:
        with self.operation("DOCUMENT_PACKAGE", context.case_id):
            return settlement_zip(context, self.documents)

    async def aclose(self) -> None:
        clients = {self.documents.llm, self.documents.reviewer}
        if self.documents.safety is not None:
            clients.add(self.documents.safety.client)
        await asyncio.gather(*(client.aclose() for client in clients if client is not None), return_exceptions=True)
        if self._trace_sink is not None:
            self._trace_sink.flush()


async def build_document_agent(
    directory: Path, *, submission_policy: str, private_values: tuple[str, ...] = (),
    env_file: Path | None = None,
) -> DocumentAgent:
    path = env_file or Path(__file__).resolve().parents[4] / ".env"
    values = {**dotenv_values(path), **os.environ}
    prefix = values.get("AGENT_DOCUMENT_MODEL_PREFIX") or "INFO_"
    if prefix not in {"INFO_", "LUNA_", "LUNA6_", "HAIKU_", "GEMINI_"}:
        raise DocumentError("지원하는 문서 모델 설정을 선택해 주세요.")
    config = LLMConfig.from_env(env_file=path, env_prefix=prefix, inherit_shared=prefix == "INFO_")
    effort = (values.get("AGENT_DOCUMENT_REASONING_EFFORT") or "").strip()
    if effort:
        if effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
            raise DocumentError("문서 모델의 effort 설정을 확인해 주세요.")
        config = replace(config, reasoning_effort=effort)
    budget = ScopedCallBudget()
    clients = []
    try:
        extractor = StructuredLLMClient(config, call_budget=budget)
        clients.append(extractor)
        reviewer = StructuredLLMClient(LLMConfig.from_env(env_file=path), call_budget=budget)
        clients.append(reviewer)
        directory_value = values.get("AGENT_OCR_TESSDATA_DIR")
        service = DocumentService(
            directory, extractor, submission_policy=submission_policy, private_values=private_values,
            tessdata=Path(directory_value) if directory_value else None,
            safety=ContentSafetyGuard(reviewer), reviewer=reviewer,
        )
        return DocumentAgent(service, trace_sink=LangfuseTraceSink.from_env(env_file=path))
    except Exception:
        await asyncio.gather(*(client.aclose() for client in clients), return_exceptions=True)
        raise
