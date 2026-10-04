"""Match Case DB evidence to approved procedure metadata without SQL or fetches."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from uuid import UUID, uuid4

from app.agent.guardrails import ensure_no_sensitive_text
from app.agent.procedure_tool.store import (
    ReviewedProcedureRecord,
    ReviewedProcedureStore,
)
from app.agent.schemas import (
    EvidenceRecord,
    FreshnessStatus,
    ProcedureLookupInput,
    ProcedureLookupResult,
    ProcedureLookupWarning,
    ProcedureSourceDocument,
)

__all__ = ["ProcedureLookupInputError", "StoredProcedureLookupTool"]

_MAX_QUERY_LENGTH = 200


class ProcedureLookupInputError(RuntimeError):
    """Invalid procedure input with safe operational metadata."""

    def __init__(self, message: str, *, code: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class StoredProcedureLookupTool:
    """Answer a procedure lookup from documents a person already approved."""

    def __init__(
        self,
        store: ReviewedProcedureStore,
        *,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._store = store
        self._uuid = uuid_factory

    async def aclose(self) -> None:
        """No resource to release; kept so the runtime can close every tool."""

    async def lookup(self, request: ProcedureLookupInput) -> ProcedureLookupResult:
        self._validate_request(request)

        # First query that matches a record owns it: the query is what binds a
        # document to a canonical step downstream, so it must stay stable.
        available: list[tuple[ReviewedProcedureRecord, EvidenceRecord]] = []
        for record in self._store.records():
            candidates = [
                item for item in request.evidence_records
                if item.source_type == "OFFICIAL_DOCUMENT"
                and item.source_ref == record.canonical_url
                and item.source_version == self._store.snapshot_version
            ]
            if not candidates:
                continue
            if len(candidates) != 1 or (
                candidates[0].excerpt != record.excerpt
                or candidates[0].content_hash
                != record.content_hash.removeprefix("sha256:")
            ):
                raise ProcedureLookupInputError(
                    "DB procedure source differs from the approved record",
                    code="PROCEDURE_SOURCE_MISMATCH", retryable=False,
                )
            evidence = candidates[0]
            freshness = record.freshness(request.as_of)
            if record.reviewed_by is None or (
                evidence.freshness_status == FreshnessStatus.CURRENT
                and freshness != FreshnessStatus.CURRENT
            ):
                raise ProcedureLookupInputError(
                    "DB procedure source needs a current human review",
                    code="PROCEDURE_REVIEW_REQUIRED", retryable=False,
                )
            available.append((record, evidence))

        selected: list[tuple[str, ReviewedProcedureRecord, EvidenceRecord]] = []
        seen_urls: set[str] = set()
        matched_queries: set[str] = set()
        for query in request.search_queries:
            matches = [item for item in available if item[0].matches(query)]
            if matches:
                matched_queries.add(query)
            for record, evidence in matches[: request.max_results_per_query]:
                if record.canonical_url in seen_urls:
                    continue
                seen_urls.add(record.canonical_url)
                selected.append((query, record, evidence))

        documents: list[ProcedureSourceDocument] = []
        evidence_records: list[EvidenceRecord] = []
        unreviewed = 0
        stale = 0
        for query, record, evidence in selected:
            freshness = evidence.freshness_status
            if freshness == FreshnessStatus.UNKNOWN:
                unreviewed += 1
            elif freshness == FreshnessStatus.STALE:
                stale += 1
            document_id = self._uuid()
            evidence_records.append(evidence.model_copy(deep=True))
            documents.append(
                ProcedureSourceDocument(
                    document_id=document_id,
                    title=record.title,
                    authority_name=record.authority_name,
                    canonical_url=evidence.source_ref,
                    source_domain=record.source_domain,
                    excerpt=evidence.excerpt,
                    published_at=evidence.published_at,
                    retrieved_at=evidence.retrieved_at,
                    freshness_status=freshness,
                    content_hash=evidence.content_hash,
                    evidence_ref=evidence.evidence_id,
                    search_query=query,
                    step_codes=list(record.step_codes),
                )
            )

        requested = len(request.search_queries)
        document_count = len(documents)
        return ProcedureLookupResult(
            completion_status="COMPLETE" if documents else "NO_RESULTS",
            lookup_id=self._uuid(),
            documents=documents,
            warnings=self._warnings(
                document_count=document_count,
                unmatched_query_count=requested - len(matched_queries),
                unreviewed_count=unreviewed,
                stale_count=stale,
            ),
            evidence_records=evidence_records,
            based_on_snapshot_id=request.based_on_snapshot_id,
            as_of=request.as_of,
        )

    @staticmethod
    def _warnings(
        *,
        document_count: int,
        unmatched_query_count: int,
        unreviewed_count: int,
        stale_count: int,
    ) -> list[ProcedureLookupWarning]:
        warnings: list[ProcedureLookupWarning] = []
        if unmatched_query_count:
            warnings.append(
                ProcedureLookupWarning(
                    code="NO_REVIEWED_SOURCE_MATCH",
                    message=(
                        "검수된 절차 자료에서 일부 조회어에 해당하는 문서를 "
                        "찾지 못했습니다."
                    ),
                )
            )
        if unreviewed_count:
            warnings.append(
                ProcedureLookupWarning(
                    code="UNREVIEWED_PROCEDURE_SOURCE",
                    message=(
                        "DB에서 최신성을 확인하지 못한 절차 자료가 포함되어 있어 "
                        "최신성을 확인할 수 없습니다."
                    ),
                )
            )
        if stale_count:
            warnings.append(
                ProcedureLookupWarning(
                    code="STALE_PROCEDURE_REVIEW",
                    message="검수 유효기간이 지난 절차 자료가 포함되어 있습니다.",
                )
            )
        if document_count == 0:
            warnings.append(
                ProcedureLookupWarning(
                    code="NO_OFFICIAL_RESULTS",
                    message="검증 가능한 공식 출처를 찾지 못했습니다.",
                )
            )
        return warnings

    @staticmethod
    def _validate_request(request: ProcedureLookupInput) -> None:
        queries: Sequence[str] = request.search_queries
        for query in queries:
            if len(query) > _MAX_QUERY_LENGTH:
                raise ProcedureLookupInputError(
                    "procedure search query is too long",
                    code="QUERY_TOO_LONG",
                    retryable=False,
                )
            if any(character.isspace() and character != " " for character in query):
                raise ProcedureLookupInputError(
                    "procedure search query contains control characters",
                    code="QUERY_NOT_SUPPORTED",
                    retryable=False,
                )
        ensure_no_sensitive_text(queries)
