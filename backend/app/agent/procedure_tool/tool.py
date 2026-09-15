"""Live Kakao web search and official-source retrieval for closure procedures.

Kakao search snippets are discovery hints only.  This tool emits evidence only
after it has fetched an allowlisted official HTTPS document itself, bounded its
size, accepted its content type, and extracted non-empty text.  It does not
interpret the documents, decide applicability, or select the next action.
"""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import html
import ipaddress
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Self
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from uuid import UUID, uuid4

import httpx
from app.agent.guardrails import GuardrailViolation, ensure_no_sensitive_text
from app.agent.schemas import (
    EvidenceRecord,
    ProcedureLookupInput,
    ProcedureLookupResult,
    ProcedureLookupWarning,
    ProcedureSearchSummary,
    ProcedureSourceDocument,
)

from .models import ProcedureSearchConfig, SearchHit

SleepCallable = Callable[[float], Awaitable[None]]
ClockCallable = Callable[[], datetime]
UuidFactory = Callable[[], UUID]

_TRANSIENT_STATUS_CODES = frozenset({408, 409, 425, 429})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_ACCEPTED_CONTENT_TYPES = frozenset(
    {"text/html", "application/xhtml+xml", "text/plain"}
)
_IGNORED_HTML_TAGS = frozenset(
    {
        "canvas",
        "iframe",
        "noscript",
        "object",
        "script",
        "style",
        "svg",
        "template",
    }
)
_BLOCK_HTML_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
_VOID_HTML_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_TRACKING_QUERY_KEYS = frozenset(
    {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid", "ref", "referrer"}
)
_SECRET_QUERY_KEY_PARTS = (
    "apikey",
    "api_key",
    "servicekey",
    "service_key",
    "access_token",
    "auth_token",
    "credential",
    "signature",
    "secret",
)
_MAX_URL_CHARS = 4_096
_MAX_TITLE_CHARS = 300
_MAX_EXCERPT_CHARS = 4_000
_MAX_FOCUS_OCCURRENCES_PER_TERM = 256
_PROCEDURE_FOCUS_TERMS = (
    "폐업",
    "휴업",
    "철거",
    "원상복구",
    "신고",
    "신청",
    "접수",
    "제출",
    "반납",
    "서류",
    "허가",
    "등록",
    "세무",
    "홈택스",
    "정부24",
)

_AUTHORITY_NAMES: tuple[tuple[str, str], ...] = (
    ("hometax.go.kr", "국세청 홈택스"),
    ("nts.go.kr", "국세청"),
    ("easylaw.go.kr", "찾기쉬운 생활법령정보"),
    ("law.go.kr", "국가법령정보센터"),
    ("gov.kr", "정부24"),
    ("4insure.or.kr", "4대사회보험 정보연계센터"),
    ("semas.or.kr", "소상공인시장진흥공단"),
    ("sbiz24.kr", "소상공인24"),
    ("bizinfo.go.kr", "기업마당"),
)


class ProcedureLookupError(RuntimeError):
    """Base exception that carries only safe operational metadata."""

    def __init__(self, message: str, *, code: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ProcedureLookupRequestError(ProcedureLookupError):
    """Raised when no Kakao search query can be completed."""


class ProcedureLookupInputError(ProcedureLookupError):
    """Raised for a cross-field request violation at the tool boundary."""


@dataclass(frozen=True, slots=True)
class _QueryOutcome:
    hits: tuple[SearchHit, ...]
    provider_result_count: int
    rejected_result_count: int


@dataclass(frozen=True, slots=True)
class _FetchedDocument:
    canonical_url: str
    source_domain: str
    title: str
    excerpt: str
    content_hash: str
    retrieved_at: datetime


class _UpstreamFailure(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class _DocumentFailure(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProcedureLookupTool:
    """Search the web and retrieve official business-closure source documents."""

    def __init__(
        self,
        config: ProcedureSearchConfig,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepCallable = asyncio.sleep,
        clock: ClockCallable = _utc_now,
        uuid_factory: UuidFactory = uuid4,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("Pass either an HTTP client or a transport, not both")
        self.config = config
        self._sleep = sleep
        self._clock = clock
        self._uuid = uuid_factory
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=config.timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    @classmethod
    def from_env(
        cls,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepCallable = asyncio.sleep,
        clock: ClockCallable = _utc_now,
        uuid_factory: UuidFactory = uuid4,
        **config_kwargs: Any,
    ) -> ProcedureLookupTool:
        """Construct a lookup tool from ``ProcedureSearchConfig.from_env``."""

        return cls(
            ProcedureSearchConfig.from_env(**config_kwargs),
            client=client,
            transport=transport,
            sleep=sleep,
            clock=clock,
            uuid_factory=uuid_factory,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close only the HTTP client created by this tool."""

        if self._owns_client:
            await self._client.aclose()

    async def lookup(self, request: ProcedureLookupInput) -> ProcedureLookupResult:
        """Run one bounded lookup or raise a typed, fail-closed timeout."""

        try:
            return await asyncio.wait_for(
                self._lookup(request),
                timeout=self.config.total_timeout_seconds,
            )
        except TimeoutError:
            raise ProcedureLookupRequestError(
                "procedure lookup exceeded its total time limit",
                code="LOOKUP_TIMEOUT",
                retryable=True,
            ) from None

    async def _lookup(self, request: ProcedureLookupInput) -> ProcedureLookupResult:
        """Return fetched official documents without interpreting their contents."""

        if request.lookup_goal != "BUSINESS_CLOSURE":
            raise ProcedureLookupInputError(
                "unsupported procedure lookup goal",
                code="INVALID_INPUT",
                retryable=False,
            )
        if request.source_policy != "OFFICIAL_ONLY":
            raise ProcedureLookupInputError(
                "unsupported procedure source policy",
                code="INVALID_INPUT",
                retryable=False,
            )
        queries = [str(query) for query in request.search_queries]
        if any(
            len(query) > 200 or any(ord(character) < 32 for character in query)
            for query in queries
        ):
            raise ProcedureLookupInputError(
                "procedure search query is invalid",
                code="INVALID_INPUT",
                retryable=False,
            )
        try:
            ensure_no_sensitive_text(queries)
        except GuardrailViolation:
            raise ProcedureLookupInputError(
                "procedure search query failed sensitive-data preflight",
                code="INVALID_INPUT",
                retryable=False,
            ) from None

        searched_at = self._aware_now()
        query_outcomes: list[_QueryOutcome] = []
        failed_queries = 0
        query_failures: list[_UpstreamFailure] = []
        for query in queries:
            try:
                query_outcomes.append(
                    await self._search_query(
                        query,
                        size=int(request.max_results_per_query),
                    )
                )
            except _UpstreamFailure as exc:
                failed_queries += 1
                query_failures.append(exc)

        if not query_outcomes:
            retryable = bool(query_failures) and all(
                failure.retryable for failure in query_failures
            )
            raise ProcedureLookupRequestError(
                "procedure search provider is unavailable",
                code="SEARCH_UNAVAILABLE",
                retryable=retryable,
            )

        provider_result_count = sum(
            item.provider_result_count for item in query_outcomes
        )
        rejected_result_count = sum(
            item.rejected_result_count for item in query_outcomes
        )
        candidates: list[SearchHit] = []
        seen_candidate_urls: set[str] = set()
        official_candidate_count = 0
        for outcome in query_outcomes:
            for hit in outcome.hits:
                try:
                    canonical_url, _ = self._canonical_official_url(hit.url)
                except ValueError:
                    rejected_result_count += 1
                    continue
                official_candidate_count += 1
                if canonical_url in seen_candidate_urls:
                    continue
                seen_candidate_urls.add(canonical_url)
                candidates.append(
                    SearchHit(title=hit.title, url=canonical_url, query=hit.query)
                )

        documents: list[ProcedureSourceDocument] = []
        evidence_records: list[EvidenceRecord] = []
        fetch_failure_count = 0
        seen_final_urls: set[str] = set()
        for hit in candidates:
            try:
                fetched = await self._fetch_document(hit)
            except _DocumentFailure:
                fetch_failure_count += 1
                continue
            if fetched.canonical_url in seen_final_urls:
                continue
            seen_final_urls.add(fetched.canonical_url)

            document_id = self._uuid()
            evidence_id = f"procedure:web:{document_id}"
            evidence = EvidenceRecord(
                evidence_id=evidence_id,
                source_type="OFFICIAL_DOCUMENT",
                source_ref=fetched.canonical_url,
                source_version=fetched.content_hash,
                locator=fetched.canonical_url,
                excerpt=fetched.excerpt,
                parent_evidence_refs=[],
                published_at=None,
                retrieved_at=fetched.retrieved_at,
                freshness_status="UNKNOWN",
                content_hash=fetched.content_hash,
            )
            document = ProcedureSourceDocument(
                document_id=document_id,
                title=fetched.title,
                authority_name=self._authority_name(fetched.source_domain),
                canonical_url=fetched.canonical_url,
                source_domain=fetched.source_domain,
                excerpt=fetched.excerpt,
                published_at=None,
                retrieved_at=fetched.retrieved_at,
                freshness_status="UNKNOWN",
                content_hash=fetched.content_hash,
                evidence_ref=evidence_id,
                search_query=hit.query,
            )
            evidence_records.append(evidence)
            documents.append(document)

        warnings = self._warnings(
            failed_queries=failed_queries,
            rejected_result_count=rejected_result_count,
            fetch_failure_count=fetch_failure_count,
            official_candidate_count=official_candidate_count,
            document_count=len(documents),
        )
        if documents and failed_queries == 0 and fetch_failure_count == 0:
            completion_status = "COMPLETE"
        elif not documents and failed_queries == 0 and official_candidate_count == 0:
            completion_status = "NO_RESULTS"
        else:
            completion_status = "PARTIAL"

        summary = ProcedureSearchSummary(
            provider="KAKAO_DAUM_WEB",
            requested_query_count=len(request.search_queries),
            successful_query_count=len(query_outcomes),
            failed_query_count=failed_queries,
            provider_result_count=provider_result_count,
            official_candidate_count=official_candidate_count,
            fetched_document_count=len(documents),
            rejected_result_count=rejected_result_count,
            fetch_failure_count=fetch_failure_count,
            searched_at=searched_at,
        )
        return ProcedureLookupResult(
            completion_status=completion_status,
            lookup_id=self._uuid(),
            documents=documents,
            search_summary=summary,
            warnings=warnings,
            evidence_records=evidence_records,
            based_on_snapshot_id=request.based_on_snapshot_id,
            as_of=request.as_of,
        )

    async def _search_query(self, query: str, *, size: int) -> _QueryOutcome:
        total_attempts = self.config.max_retries + 1
        last_failure = _UpstreamFailure("SEARCH_UNAVAILABLE", retryable=True)
        for attempt_index in range(total_attempts):
            response: httpx.Response | None = None
            try:
                request = self._isolated_get_request(
                    self.config.endpoint,
                    headers={
                        "Authorization": f"KakaoAK {self.config.api_key}",
                        "Accept": "application/json",
                    },
                    params={
                        "query": query,
                        "size": size,
                        "page": 1,
                        "sort": "accuracy",
                    },
                )
                response = await self._client.send(
                    request,
                    stream=True,
                    auth=None,
                    follow_redirects=False,
                )
                if response.status_code in _REDIRECT_STATUS_CODES:
                    raise _UpstreamFailure("SEARCH_REDIRECT_REJECTED", retryable=False)
                if not response.is_success:
                    raise _UpstreamFailure(
                        "SEARCH_HTTP_ERROR",
                        retryable=_is_transient_status(response.status_code),
                    )
                if _media_type(response.headers.get("content-type")) != (
                    "application/json"
                ):
                    raise _UpstreamFailure(
                        "SEARCH_CONTENT_TYPE_INVALID", retryable=False
                    )
                body = await self._read_search_body(response)
                return self._parse_search_response(
                    body,
                    query,
                    result_limit=size,
                )
            except _UpstreamFailure as exc:
                last_failure = exc
            except (httpx.TimeoutException, httpx.TransportError):
                last_failure = _UpstreamFailure(
                    "SEARCH_TRANSPORT_ERROR", retryable=True
                )
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
                last_failure = _UpstreamFailure(
                    "SEARCH_RESPONSE_INVALID", retryable=True
                )
            finally:
                if response is not None:
                    await response.aclose()

            if not last_failure.retryable or attempt_index + 1 >= total_attempts:
                raise last_failure
            await self._backoff(attempt_index)
        raise last_failure

    @staticmethod
    def _parse_search_response(
        body: bytes,
        query: str,
        *,
        result_limit: int,
    ) -> _QueryOutcome:
        payload = json.loads(body)
        if not isinstance(payload, Mapping):
            raise TypeError("Kakao search response must be an object")
        raw_documents = payload.get("documents")
        if not isinstance(raw_documents, list):
            raise TypeError("Kakao search response documents must be a list")
        hits: list[SearchHit] = []
        rejected = max(0, len(raw_documents) - result_limit)
        for item in raw_documents[:result_limit]:
            if not isinstance(item, Mapping):
                rejected += 1
                continue
            title = item.get("title")
            url = item.get("url")
            if not isinstance(title, str) or not isinstance(url, str):
                rejected += 1
                continue
            clean_title = _clean_title(title)
            if not clean_title or not url.strip():
                rejected += 1
                continue
            hits.append(SearchHit(title=clean_title, url=url.strip(), query=query))
        return _QueryOutcome(
            hits=tuple(hits),
            provider_result_count=len(raw_documents),
            rejected_result_count=rejected,
        )

    async def _read_search_body(self, response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                raise _UpstreamFailure(
                    "SEARCH_CONTENT_LENGTH_INVALID", retryable=False
                ) from None
            if declared_length > self.config.max_response_bytes:
                raise _UpstreamFailure("SEARCH_RESPONSE_TOO_LARGE", retryable=False)
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > self.config.max_response_bytes:
                raise _UpstreamFailure("SEARCH_RESPONSE_TOO_LARGE", retryable=False)
        return bytes(body)

    async def _fetch_document(self, hit: SearchHit) -> _FetchedDocument:
        total_attempts = self.config.max_retries + 1
        last_failure = _DocumentFailure("SOURCE_UNAVAILABLE", retryable=True)
        for attempt_index in range(total_attempts):
            try:
                (
                    final_url,
                    source_domain,
                    content_type,
                    body,
                ) = await self._fetch_with_redirects(hit.url)
                title, excerpt = _extract_document_text(
                    body,
                    content_type=content_type,
                    # Kakao title/snippet fields are discovery metadata only.
                    # A missing source-page title falls back to the verified host.
                    fallback_title="",
                    focus_query=hit.query,
                )
                if not excerpt:
                    raise _DocumentFailure("SOURCE_TEXT_EMPTY")
                return _FetchedDocument(
                    canonical_url=final_url,
                    source_domain=source_domain,
                    title=title or source_domain,
                    excerpt=excerpt,
                    content_hash="sha256:" + hashlib.sha256(body).hexdigest(),
                    retrieved_at=self._aware_now(),
                )
            except _DocumentFailure as exc:
                last_failure = exc
            except (httpx.TimeoutException, httpx.TransportError):
                last_failure = _DocumentFailure(
                    "SOURCE_TRANSPORT_ERROR", retryable=True
                )

            if not last_failure.retryable or attempt_index + 1 >= total_attempts:
                raise last_failure
            await self._backoff(attempt_index)
        raise last_failure

    async def _fetch_with_redirects(
        self,
        initial_url: str,
    ) -> tuple[str, str, str, bytes]:
        current_url, current_domain = self._canonical_official_url(initial_url)
        visited: set[str] = set()
        for redirect_count in range(self.config.max_redirects + 1):
            if current_url in visited:
                raise _DocumentFailure("SOURCE_REDIRECT_LOOP")
            visited.add(current_url)
            request = self._isolated_get_request(
                current_url,
                headers={
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
                    "User-Agent": "REBORN-ProcedureLookup/1.0",
                },
            )
            response = await self._client.send(
                request,
                stream=True,
                auth=None,
                follow_redirects=False,
            )
            try:
                if response.status_code in _REDIRECT_STATUS_CODES:
                    location = response.headers.get("location")
                    if not location:
                        raise _DocumentFailure("SOURCE_REDIRECT_INVALID")
                    if redirect_count >= self.config.max_redirects:
                        raise _DocumentFailure("SOURCE_REDIRECT_LIMIT")
                    next_url = urljoin(current_url, location)
                    try:
                        current_url, current_domain = self._canonical_official_url(
                            next_url
                        )
                    except ValueError as exc:
                        raise _DocumentFailure("SOURCE_REDIRECT_REJECTED") from exc
                    continue
                if not response.is_success:
                    raise _DocumentFailure(
                        "SOURCE_HTTP_ERROR",
                        retryable=_is_transient_status(response.status_code),
                    )
                content_type = _media_type(response.headers.get("content-type"))
                if content_type not in _ACCEPTED_CONTENT_TYPES:
                    raise _DocumentFailure("SOURCE_CONTENT_TYPE_REJECTED")
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except ValueError:
                        raise _DocumentFailure(
                            "SOURCE_CONTENT_LENGTH_INVALID"
                        ) from None
                    if declared_length > self.config.max_response_bytes:
                        raise _DocumentFailure("SOURCE_RESPONSE_TOO_LARGE")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self.config.max_response_bytes:
                        raise _DocumentFailure("SOURCE_RESPONSE_TOO_LARGE")
                return current_url, current_domain, content_type, bytes(body)
            finally:
                await response.aclose()
        raise _DocumentFailure("SOURCE_REDIRECT_LIMIT")

    def _canonical_official_url(self, value: str) -> tuple[str, str]:
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > _MAX_URL_CHARS
        ):
            raise ValueError("source URL is invalid")
        raw = value.strip()
        if any(ord(character) < 32 for character in raw):
            raise ValueError("source URL contains control characters")
        parsed = urlsplit(raw)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ValueError("source URL must use HTTPS")
        if parsed.username or parsed.password:
            raise ValueError("source URL must not contain credentials")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("source URL has an invalid port") from exc
        if port not in {None, 443}:
            raise ValueError("source URL must use the standard HTTPS port")
        try:
            host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError as exc:
            raise ValueError("source hostname is invalid") from exc
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("IP-literal source URLs are not allowed")
        if not any(
            host == domain or host.endswith("." + domain)
            for domain in self.config.allowed_domains
        ):
            raise ValueError("source hostname is outside the official allowlist")

        safe_query: list[tuple[str, str]] = []
        for key, item in parse_qsl(parsed.query, keep_blank_values=True):
            lowered = key.lower()
            if lowered.startswith("utm_") or lowered in _TRACKING_QUERY_KEYS:
                continue
            if any(part in lowered for part in _SECRET_QUERY_KEY_PARTS):
                raise ValueError("source URL query may contain a credential")
            safe_query.append((key, item))
        safe_query.sort()
        path = parsed.path or "/"
        # The only accepted explicit port is the default HTTPS port, so omit it
        # from canonical identity to deduplicate ``:443`` and implicit forms.
        netloc = host
        canonical = urlunsplit(
            ("https", netloc, path, urlencode(safe_query, doseq=True), "")
        )
        if len(canonical) > _MAX_URL_CHARS:
            raise ValueError("canonical source URL is too long")
        return canonical, host

    def _authority_name(self, domain: str) -> str:
        for suffix, name in _AUTHORITY_NAMES:
            if domain == suffix or domain.endswith("." + suffix):
                return name
        return domain

    @staticmethod
    def _warnings(
        *,
        failed_queries: int,
        rejected_result_count: int,
        fetch_failure_count: int,
        official_candidate_count: int,
        document_count: int,
    ) -> list[ProcedureLookupWarning]:
        warnings: list[ProcedureLookupWarning] = []
        if failed_queries:
            warnings.append(
                ProcedureLookupWarning(
                    code="SEARCH_QUERY_FAILED",
                    message="일부 폐업 절차 검색 요청을 완료하지 못했습니다.",
                )
            )
        if rejected_result_count:
            warnings.append(
                ProcedureLookupWarning(
                    code="RESULT_REJECTED",
                    message="공식 출처 정책을 통과하지 못한 검색 결과를 제외했습니다.",
                )
            )
        if fetch_failure_count:
            warnings.append(
                ProcedureLookupWarning(
                    code="SOURCE_FETCH_FAILED",
                    message="일부 공식 출처의 원문을 가져오지 못했습니다.",
                )
            )
        if official_candidate_count == 0:
            warnings.append(
                ProcedureLookupWarning(
                    code="NO_OFFICIAL_RESULTS",
                    message="검색 결과에서 검증 가능한 공식 출처를 찾지 못했습니다.",
                )
            )
        elif document_count == 0:
            warnings.append(
                ProcedureLookupWarning(
                    code="NO_FETCHED_DOCUMENTS",
                    message="분석에 사용할 수 있는 공식 원문이 없습니다.",
                )
            )
        return warnings

    async def _backoff(self, attempt_index: int) -> None:
        delay = self.config.retry_backoff_seconds * (2**attempt_index)
        if delay > 0:
            await self._sleep(delay)

    def _isolated_get_request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, Any] | None = None,
    ) -> httpx.Request:
        """Create a request without inheriting client headers, cookies, or auth."""

        return httpx.Request(
            "GET",
            url,
            headers=headers,
            params=params,
            extensions={
                "timeout": httpx.Timeout(self.config.timeout_seconds).as_dict()
            },
        )

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("procedure lookup clock must return an aware datetime")
        return value


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_stack: list[str] = []
        self._in_title = False
        self._primary_content_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.primary_text_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        normalized = tag.lower()
        if self._ignored_stack:
            if normalized not in _VOID_HTML_TAGS:
                self._ignored_stack.append(normalized)
            return
        if normalized in _IGNORED_HTML_TAGS:
            self._ignored_stack.append(normalized)
            return
        if normalized == "title":
            self._in_title = True
        if normalized in {"article", "main"}:
            self._primary_content_depth += 1
        if normalized in _BLOCK_HTML_TAGS:
            self.text_parts.append(" ")
            if self._primary_content_depth:
                self.primary_text_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if self._ignored_stack:
            if normalized in self._ignored_stack:
                matching_index = (
                    len(self._ignored_stack)
                    - 1
                    - self._ignored_stack[::-1].index(normalized)
                )
                del self._ignored_stack[matching_index:]
            return
        if normalized == "title":
            self._in_title = False
        if normalized in _BLOCK_HTML_TAGS:
            self.text_parts.append(" ")
            if self._primary_content_depth:
                self.primary_text_parts.append(" ")
        if normalized in {"article", "main"} and self._primary_content_depth:
            self._primary_content_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_stack:
            return
        if self._in_title:
            self.title_parts.append(data)
        else:
            self.text_parts.append(data)
            if self._primary_content_depth:
                self.primary_text_parts.append(data)


def _extract_document_text(
    body: bytes,
    *,
    content_type: str,
    fallback_title: str,
    focus_query: str,
) -> tuple[str, str]:
    text = _decode_body(body)
    title = _clean_title(fallback_title)
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = _VisibleTextParser()
        try:
            parser.feed(text)
            parser.close()
        except (AssertionError, ValueError):
            return "", ""
        parsed_title = _collapse_text(" ".join(parser.title_parts))
        if parsed_title:
            title = parsed_title[:_MAX_TITLE_CHARS]
        primary_text = _collapse_text(" ".join(parser.primary_text_parts))
        text = primary_text or " ".join(parser.text_parts)
    excerpt = _focused_excerpt(_collapse_text(text), focus_query=focus_query)
    return title[:_MAX_TITLE_CHARS], excerpt


def _focused_excerpt(text: str, *, focus_query: str) -> str:
    """Keep a bounded source substring around the densest relevant term window."""

    if len(text) <= _MAX_EXCERPT_CHARS:
        return text
    terms = list(
        dict.fromkeys(
            term.casefold()
            for term in re.findall(r"[0-9A-Za-z가-힣]+", focus_query)
            if len(term) >= 2
        )
    )
    normalized_text = text.casefold()
    candidate_positions = {0}
    for term in terms:
        position = normalized_text.find(term)
        occurrence_count = 0
        while position >= 0 and occurrence_count < _MAX_FOCUS_OCCURRENCES_PER_TERM:
            candidate_positions.add(position)
            occurrence_count += 1
            position = normalized_text.find(term, position + len(term))

        last_position = normalized_text.rfind(term)
        if last_position >= 0:
            candidate_positions.add(last_position)

    def score(position: int) -> tuple[int, int, int, int]:
        start = max(0, position - 400)
        window = normalized_text[start : start + _MAX_EXCERPT_CHARS]
        query_coverage = sum(term in window for term in terms)
        procedure_coverage = sum(term in window for term in _PROCEDURE_FOCUS_TERMS)
        specificity = sum(len(term) for term in terms if term in window)
        # A later equally relevant window is more likely to be article content
        # than a repeated site-wide navigation menu near the document start.
        return query_coverage, procedure_coverage, specificity, start

    focus_at = max(candidate_positions, key=score)
    excerpt_start = max(0, focus_at - 400)
    return text[excerpt_start : excerpt_start + _MAX_EXCERPT_CHARS].strip()


def _decode_body(body: bytes) -> str:
    # UTF-8 is by far the most common encoding for current official pages.  A
    # strict decode first avoids silently corrupting valid text, while the
    # Korean legacy fallback keeps EUC-KR pages readable without trusting an
    # unbounded or executable charset declaration.
    for encoding in ("utf-8", "euc-kr"):
        try:
            codecs.lookup(encoding)
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def _clean_title(value: str) -> str:
    without_tags = re.sub(r"<[^>]*>", " ", value)
    return _collapse_text(html.unescape(without_tags))[:_MAX_TITLE_CHARS]


def _collapse_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _media_type(value: str | None) -> str:
    if value is None:
        return ""
    return value.split(";", 1)[0].strip().lower()


def _is_transient_status(status_code: int) -> bool:
    return status_code in _TRANSIENT_STATUS_CODES or status_code >= 500


__all__ = [
    "ProcedureLookupError",
    "ProcedureLookupInputError",
    "ProcedureLookupRequestError",
    "ProcedureLookupTool",
]
