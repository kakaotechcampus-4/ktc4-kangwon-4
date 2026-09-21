"""Read-only discovery of official support notices from Bizinfo.

The adapter makes one bounded GET to the fixed Bizinfo API endpoint and emits
unreviewed candidates plus deterministic official-API evidence.  It never
decides eligibility and it deliberately has no path into ``SupportAgent`` or
``ReviewedSupportCatalog``.
"""

from __future__ import annotations

import html
import ipaddress
import json
import logging
import math
import os
import re
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Annotated, Any, Self
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from app.agent.guardrails import GuardrailViolation, ensure_no_sensitive_text
from app.agent.schemas import EvidenceRecord, FreshnessStatus

from .discovery_models import (
    BIZINFO_SUPPORT_API_ENDPOINT,
    SupportNoticeCandidate,
    SupportNoticeDiscoveryInput,
    SupportNoticeDiscoveryResult,
    _candidate_content_digest,
    _candidate_evidence_excerpt,
    _has_sensitive_query_parameter,
    _is_sensitive_query_parameter_name,
)

_DEFAULT_TIMEOUT_SECONDS = 8.0
_DEFAULT_MAX_RESPONSE_BYTES = 1_000_000
_DEFAULT_MAX_RESULTS = 50
_MAX_RESULTS = 100
_MAX_RESPONSE_BYTES = 5_000_000
_MAX_API_KEY_CHARS = 2_048
_MAX_TEXT_CHARS = 20_000
_BIZINFO_HOST = "www.bizinfo.go.kr"
_BIZINFO_DETAIL_PATH = "/sii/siia/selectSIIA200Detail.do"
_SEOUL = ZoneInfo("Asia/Seoul")
_ACCEPTED_JSON_TYPES = frozenset({"application/json", "text/json"})
_IGNORED_HTML_TAGS = frozenset(
    {"canvas", "iframe", "noscript", "object", "script", "style", "svg", "template"}
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
_BUSINESS_REGISTRATION_NUMBER = re.compile(
    r"(?<!\d)\d{3}(?:(?:\s*-\s*)|\s+)?"
    r"\d{2}(?:(?:\s*-\s*)|\s+)?\d{5}(?!\d)"
)
_KOREAN_STREET_ADDRESS = re.compile(
    r"(?:[가-힣A-Za-z0-9·]+(?:대로|로|길))\s*\d+(?:\s*-\s*\d+)?"
)

ClockCallable = Callable[[], datetime]
NonNegativeStrictInt = Annotated[StrictInt, Field(ge=0)]


def _redacted_url_text(url: httpx.URL) -> str:
    parameters = [
        (
            name,
            "[REDACTED]" if _is_sensitive_query_parameter_name(name) else value,
        )
        for name, value in url.params.multi_items()
    ]
    return str(httpx.URL(url).copy_with(params=parameters))


class _LogSafeURL(httpx.URL):
    """Keep the wire query intact while making string representations safe."""

    def __str__(self) -> str:
        return _redacted_url_text(self)

    def __repr__(self) -> str:
        return f"URL({str(self)!r})"


class _HttpxQueryRedactionFilter(logging.Filter):
    """Remove sensitive query values before an HTTPX record reaches handlers."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _redacted_url_text(value) if isinstance(value, httpx.URL) else value
                for value in record.args
            )
        return True


_HTTPX_LOGGER = logging.getLogger("httpx")
_HTTPX_QUERY_FILTER = _HttpxQueryRedactionFilter()
_HTTPX_FILTER_LOCK = threading.Lock()
_httpx_filter_users = 0


@contextmanager
def _redact_httpx_query_logs() -> Iterator[None]:
    """Install one concurrency-safe process filter during HTTPX transmission."""

    global _httpx_filter_users
    with _HTTPX_FILTER_LOCK:
        if _httpx_filter_users == 0:
            _HTTPX_LOGGER.addFilter(_HTTPX_QUERY_FILTER)
        _httpx_filter_users += 1
    try:
        yield
    finally:
        with _HTTPX_FILTER_LOCK:
            _httpx_filter_users -= 1
            if _httpx_filter_users == 0:
                _HTTPX_LOGGER.removeFilter(_HTTPX_QUERY_FILTER)


class SupportNoticeDiscoveryConfigurationError(ValueError):
    """Raised when Bizinfo discovery cannot be configured safely."""


class SupportNoticeDiscoveryError(RuntimeError):
    """Safe operational failure that never includes credentials or response data."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


class SupportNoticeDiscoveryRequestError(SupportNoticeDiscoveryError):
    """Raised when the fixed official endpoint cannot complete a request."""


class SupportNoticeDiscoveryInputError(SupportNoticeDiscoveryError):
    """Raised before transmission when discovery keywords are not safe."""


class SupportNoticeDiscoveryResponseError(SupportNoticeDiscoveryError):
    """Raised when an upstream response violates the accepted contract."""


@dataclass(frozen=True, slots=True)
class BizInfoSupportDiscoveryConfig:
    """Secret and hard limits for a Bizinfo API read.

    The endpoint is intentionally not configurable.  Process-environment values
    take precedence over the repository-root ``.env``, matching the Procedure
    tool and the rest of the Agent runtime.
    """

    api_key: str = field(repr=False)
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES
    max_results: int = _DEFAULT_MAX_RESULTS

    def __post_init__(self) -> None:
        if type(self.api_key) is not str:
            raise SupportNoticeDiscoveryConfigurationError(
                "BIZINFO_API_KEY is missing or invalid"
            )
        api_key = self.api_key.strip()
        if (
            not api_key
            or len(api_key) > _MAX_API_KEY_CHARS
            or any(ord(char) < 32 or ord(char) == 127 for char in api_key)
        ):
            raise SupportNoticeDiscoveryConfigurationError(
                "BIZINFO_API_KEY is missing or invalid"
            )
        object.__setattr__(self, "api_key", api_key)

        if (
            type(self.timeout_seconds) not in {int, float}
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= 30
        ):
            raise SupportNoticeDiscoveryConfigurationError(
                "Bizinfo timeout must be finite and between 0 and 30 seconds"
            )
        if (
            type(self.max_response_bytes) is not int
            or not 1_024 <= self.max_response_bytes <= _MAX_RESPONSE_BYTES
        ):
            raise SupportNoticeDiscoveryConfigurationError(
                "Bizinfo response limit must be between 1024 and 5000000 bytes"
            )
        if (
            type(self.max_results) is not int
            or not 1 <= self.max_results <= _MAX_RESULTS
        ):
            raise SupportNoticeDiscoveryConfigurationError(
                "Bizinfo result limit must be between 1 and 100"
            )

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        max_results: int = _DEFAULT_MAX_RESULTS,
    ) -> BizInfoSupportDiscoveryConfig:
        environment = os.environ if environ is None else environ
        dotenv_path = Path(env_file) if env_file is not None else _repo_root() / ".env"
        file_values: Mapping[str, str | None]
        if dotenv_path.is_file():
            try:
                file_values = dotenv_values(dotenv_path)
            except (OSError, ValueError) as exc:
                raise SupportNoticeDiscoveryConfigurationError(
                    "Bizinfo environment file could not be read"
                ) from exc
        else:
            file_values = {}

        raw_key = environment.get("BIZINFO_API_KEY")
        if raw_key is None:
            raw_key = file_values.get("BIZINFO_API_KEY")
        api_key = "" if raw_key is None else str(raw_key)
        return cls(
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            max_results=max_results,
        )


class _BizInfoApiModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        strict=True,
    )


class _BizInfoNotice(_BizInfoApiModel):
    """The observed 2026-09-15 Bizinfo ``jsonArray`` item contract."""

    bsnsSumryCn: StrictStr
    creatPnttm: StrictStr
    excInsttNm: StrictStr
    fileNm: StrictStr | None = None
    flpthNm: StrictStr | None = None
    hashtags: StrictStr
    inqireCo: NonNegativeStrictInt
    jrsdInsttNm: StrictStr
    pblancId: StrictStr
    pblancNm: StrictStr
    pblancUrl: StrictStr
    pldirSportRealmLclasCodeNm: StrictStr
    pldirSportRealmMlsfcCodeNm: StrictStr
    printFileNm: StrictStr
    printFlpthNm: StrictStr
    rceptEngnHmpgUrl: StrictStr | None = None
    refrncNm: StrictStr
    reqstBeginEndDe: StrictStr
    reqstMthPapersCn: StrictStr
    totCnt: NonNegativeStrictInt
    trgetNm: StrictStr
    updtPnttm: StrictStr


class _BizInfoEnvelope(_BizInfoApiModel):
    json_array: Annotated[
        list[_BizInfoNotice],
        Field(alias="jsonArray", max_length=_MAX_RESULTS),
    ]


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        lowered = tag.lower()
        if self.ignored_depth:
            if lowered in _IGNORED_HTML_TAGS:
                self.ignored_depth += 1
            return
        if lowered in _IGNORED_HTML_TAGS:
            self.ignored_depth = 1
        elif lowered in _BLOCK_HTML_TAGS:
            self.parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if not self.ignored_depth and tag.lower() in _BLOCK_HTML_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if self.ignored_depth:
            if lowered in _IGNORED_HTML_TAGS:
                self.ignored_depth -= 1
            return
        if lowered in _BLOCK_HTML_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BizInfoSupportDiscoveryTool:
    """Fetch and normalize official support-notice discovery candidates."""

    def __init__(
        self,
        config: BizInfoSupportDiscoveryConfig,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: ClockCallable = _utc_now,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("Pass either an HTTP client or a transport, not both")
        self.config = config
        self._clock = clock
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=config.timeout_seconds,
            follow_redirects=False,
            transport=transport,
            trust_env=False,
        )

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: ClockCallable = _utc_now,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        max_results: int = _DEFAULT_MAX_RESULTS,
    ) -> BizInfoSupportDiscoveryTool:
        config = BizInfoSupportDiscoveryConfig.from_env(
            env_file=env_file,
            environ=environ,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            max_results=max_results,
        )
        return cls(config, client=client, transport=transport, clock=clock)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close only a client created by this adapter."""

        if self._owns_client:
            await self._client.aclose()

    async def discover(
        self, request: SupportNoticeDiscoveryInput
    ) -> SupportNoticeDiscoveryResult:
        """Return unreviewed notices and one evidence record per unique notice."""

        if not isinstance(request, SupportNoticeDiscoveryInput):
            raise TypeError("request must be SupportNoticeDiscoveryInput")
        sensitive_keyword = False
        try:
            ensure_no_sensitive_text(request.keywords)
            _ensure_no_support_search_identifiers(request.keywords)
        except GuardrailViolation:
            sensitive_keyword = True
        if sensitive_keyword:
            raise SupportNoticeDiscoveryInputError(
                "Support discovery keywords contain sensitive data",
                code="BIZINFO_SENSITIVE_KEYWORD",
                retryable=False,
            )
        result_limit = min(request.max_results, self.config.max_results)
        envelope = await self._request(request.keywords, result_limit)
        retrieved_at = self._retrieved_at()

        totals = {notice.totCnt for notice in envelope.json_array}
        if len(totals) > 1:
            raise _response_error("BIZINFO_TOTAL_COUNT_INCONSISTENT")
        provider_total_count = next(iter(totals), None)

        candidates: list[SupportNoticeCandidate] = []
        evidence_records: list[EvidenceRecord] = []
        seen_notice_ids: set[str] = set()
        duplicate_count = 0
        for notice in envelope.json_array:
            notice_id = _required_plain_text(notice.pblancId, "pblancId", 128)
            if notice_id in seen_notice_ids:
                duplicate_count += 1
                continue
            seen_notice_ids.add(notice_id)
            if len(candidates) >= result_limit:
                continue
            normalized_notice: tuple[SupportNoticeCandidate, EvidenceRecord] | None = (
                None
            )
            try:
                normalized_notice = _normalize_notice(notice, retrieved_at=retrieved_at)
            except ValidationError:
                pass
            if normalized_notice is None:
                raise _response_error("BIZINFO_NOTICE_NORMALIZATION_INVALID")
            candidate, evidence = normalized_notice
            candidates.append(candidate)
            evidence_records.append(evidence)

        result_count = len(candidates)
        provider_returned_count = len(envelope.json_array)
        truncated = (
            provider_total_count is not None and provider_total_count > result_count
        ) or provider_returned_count - duplicate_count > result_count
        return SupportNoticeDiscoveryResult(
            keywords=request.keywords,
            applied_result_limit=result_limit,
            provider_total_count=provider_total_count,
            provider_returned_count=provider_returned_count,
            duplicate_count=duplicate_count,
            result_count=result_count,
            truncated=truncated,
            retrieved_at=retrieved_at,
            candidates=tuple(candidates),
            evidence_records=tuple(evidence_records),
        )

    async def _request(
        self, keywords: tuple[str, ...], result_limit: int
    ) -> _BizInfoEnvelope:
        transport_failed = False
        try:
            request = httpx.Request(
                "GET",
                BIZINFO_SUPPORT_API_ENDPOINT,
                params={
                    "crtfcKey": self.config.api_key,
                    "dataType": "json",
                    "hashtags": ",".join(keywords),
                    "pageUnit": result_limit,
                    "pageIndex": 1,
                },
                headers={
                    "Accept": "application/json",
                    "User-Agent": "RE-BORN-support-discovery/1.0",
                },
                extensions={
                    "timeout": httpx.Timeout(self.config.timeout_seconds).as_dict()
                },
            )
            # HTTPX logs ``request.url`` at INFO after the transport returns.
            # This subtype retains the real raw query for the wire while both
            # its string forms and the temporary logger filter are redacted.
            request.url = _LogSafeURL(request.url)
            with _redact_httpx_query_logs():
                response = await self._client.send(
                    request,
                    stream=True,
                    auth=None,
                    follow_redirects=False,
                )
            try:
                if 300 <= response.status_code < 400:
                    raise SupportNoticeDiscoveryRequestError(
                        "Bizinfo support discovery refused an upstream redirect",
                        code="BIZINFO_REDIRECT_REFUSED",
                        retryable=False,
                        status_code=response.status_code,
                    )
                if response.status_code != 200:
                    raise SupportNoticeDiscoveryRequestError(
                        "Bizinfo support discovery request failed",
                        code="BIZINFO_HTTP_ERROR",
                        retryable=(
                            response.status_code in {408, 425, 429}
                            or response.status_code >= 500
                        ),
                        status_code=response.status_code,
                    )
                content_type = response.headers.get("content-type", "")
                media_type = content_type.split(";", 1)[0].strip().lower()
                if not (
                    media_type in _ACCEPTED_JSON_TYPES or media_type.endswith("+json")
                ):
                    raise _response_error("BIZINFO_CONTENT_TYPE_INVALID")
                body = await self._read_bounded_body(response)
            finally:
                await response.aclose()
        except SupportNoticeDiscoveryError:
            raise
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPError):
            transport_failed = True
        if transport_failed:
            raise SupportNoticeDiscoveryRequestError(
                "Bizinfo support discovery transport failed",
                code="BIZINFO_TRANSPORT_ERROR",
                retryable=True,
            )

        invalid_response = False
        try:
            payload = _strict_json_loads(body)
            envelope = _BizInfoEnvelope.model_validate(payload, strict=True)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
            invalid_response = True
        if invalid_response:
            raise _response_error("BIZINFO_RESPONSE_SCHEMA_INVALID")
        return envelope

    async def _read_bounded_body(self, response: httpx.Response) -> bytes:
        declared = response.headers.get("content-length")
        if declared is not None:
            try:
                declared_length = int(declared)
            except ValueError:
                raise _response_error("BIZINFO_CONTENT_LENGTH_INVALID") from None
            if declared_length < 0:
                raise _response_error("BIZINFO_CONTENT_LENGTH_INVALID")
            if declared_length > self.config.max_response_bytes:
                raise _response_error("BIZINFO_RESPONSE_TOO_LARGE")

        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > self.config.max_response_bytes:
                raise _response_error("BIZINFO_RESPONSE_TOO_LARGE")
        return bytes(body)

    def _retrieved_at(self) -> datetime:
        retrieved_at = self._clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("discovery clock must return a timezone-aware datetime")
        return retrieved_at.astimezone(timezone.utc)


def _normalize_notice(
    notice: _BizInfoNotice,
    *,
    retrieved_at: datetime,
) -> tuple[SupportNoticeCandidate, EvidenceRecord]:
    notice_id = _required_plain_text(notice.pblancId, "pblancId", 128)
    if not re.fullmatch(r"PBLN_[A-Za-z0-9_]+", notice_id):
        raise _response_error("BIZINFO_NOTICE_ID_INVALID")
    title = _required_plain_text(notice.pblancNm, "pblancNm", 500)
    detail_url = _bizinfo_url(notice.pblancUrl, notice_id=notice_id, detail=True)

    normalized: dict[str, Any] = {
        "notice_id": notice_id,
        "title": title,
        "detail_url": detail_url,
        "summary": _optional_plain_text(notice.bsnsSumryCn, 20_000),
        "target": _optional_plain_text(notice.trgetNm, 4_000),
        "application_period": _optional_plain_text(notice.reqstBeginEndDe, 2_000),
        "application_method": _optional_plain_text(notice.reqstMthPapersCn, 8_000),
        "application_url": _external_metadata_url(notice.rceptEngnHmpgUrl),
        "jurisdiction_institution": _optional_plain_text(notice.jrsdInsttNm, 500),
        "executing_institution": _optional_plain_text(notice.excInsttNm, 500),
        "support_area_major": _optional_plain_text(
            notice.pldirSportRealmLclasCodeNm, 500
        ),
        "support_area_middle": _optional_plain_text(
            notice.pldirSportRealmMlsfcCodeNm, 500
        ),
        "reference_contact": _optional_plain_text(notice.refrncNm, 2_000),
        "hashtags": _hashtags(notice.hashtags),
        "attachment_name": _optional_plain_text(notice.fileNm, 1_000),
        "attachment_url": _optional_bizinfo_url(notice.flpthNm),
        "print_attachment_name": _optional_plain_text(notice.printFileNm, 1_000),
        "print_attachment_url": _optional_bizinfo_url(notice.printFlpthNm),
        "provider_created_at": _provider_datetime(notice.creatPnttm),
        "provider_updated_at": _provider_datetime(notice.updtPnttm),
        "view_count": notice.inqireCo,
    }
    digest = _candidate_content_digest(normalized)
    evidence_id = f"support:bizinfo:{notice_id}:{digest.removeprefix('sha256:')}"
    excerpt = _candidate_evidence_excerpt(normalized)
    evidence = EvidenceRecord(
        evidence_id=evidence_id,
        source_type="OFFICIAL_API",
        source_ref=BIZINFO_SUPPORT_API_ENDPOINT,
        source_version=digest,
        locator=detail_url,
        excerpt=excerpt,
        parent_evidence_refs=[],
        published_at=None,
        retrieved_at=retrieved_at,
        freshness_status="UNKNOWN",
        content_hash=digest,
    )
    candidate = SupportNoticeCandidate(
        **normalized,
        freshness_status=FreshnessStatus.UNKNOWN,
        evidence_ref=evidence_id,
    )
    return candidate, evidence


def _plain_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    decoded = html.unescape("".join(parser.parts))
    without_controls = "".join(
        " " if ord(char) < 32 or ord(char) == 127 else char for char in decoded
    )
    return " ".join(without_controls.split())


def _required_plain_text(value: str, field_name: str, max_chars: int) -> str:
    normalized = _plain_text(value)
    if not normalized or len(normalized) > max_chars:
        raise _response_error(f"BIZINFO_{field_name.upper()}_INVALID")
    return normalized


def _optional_plain_text(value: str | None, max_chars: int) -> str | None:
    if value is None:
        return None
    normalized = _plain_text(value)
    if not normalized:
        return None
    if len(normalized) > min(max_chars, _MAX_TEXT_CHARS):
        raise _response_error("BIZINFO_TEXT_FIELD_TOO_LARGE")
    return normalized


def _hashtags(value: str) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in value.split(","):
        hashtag = _optional_plain_text(raw, 100)
        if hashtag is None:
            continue
        key = hashtag.casefold()
        if key not in seen:
            seen.add(key)
            result.append(hashtag)
        if len(result) > 100:
            raise _response_error("BIZINFO_HASHTAG_COUNT_INVALID")
    return tuple(result)


def _bizinfo_url(value: str, *, notice_id: str, detail: bool) -> str:
    normalized = _absolute_web_url(value, https_only=True)
    parsed = urlsplit(normalized)
    if parsed.hostname != _BIZINFO_HOST:
        raise _response_error("BIZINFO_OFFICIAL_URL_INVALID")
    if detail:
        params = parse_qsl(parsed.query, keep_blank_values=True)
        if parsed.path != _BIZINFO_DETAIL_PATH or params != [("pblancId", notice_id)]:
            raise _response_error("BIZINFO_DETAIL_URL_INVALID")
    return normalized


def _optional_bizinfo_url(value: str | None) -> str | None:
    plain = _optional_plain_text(value, 4_096)
    if plain is None:
        return None
    return _bizinfo_url(plain, notice_id="", detail=False)


def _external_metadata_url(value: str | None) -> str | None:
    """Normalize a third-party application page, fragment and all.

    Unlike the Bizinfo URLs above, this one points at whatever site the issuing
    agency runs, and several of them are single-page apps whose route lives in
    the fragment -- 소상공인24 publishes ``https://www.sbiz24.kr/#/pbanc/591``.
    Dropping the fragment would not make that safer: it would send the user to
    the site's front page instead of the notice they were promised. Nothing
    here is ever fetched; it is shown to a person to click.
    """

    plain = _optional_plain_text(value, 4_096)
    if plain is None:
        return None
    return _absolute_web_url(plain, https_only=False, allow_fragment=True)


def _absolute_web_url(
    value: str, *, https_only: bool, allow_fragment: bool = False
) -> str:
    if len(value) > 4_096 or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise _response_error("BIZINFO_URL_INVALID")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise _response_error("BIZINFO_URL_INVALID") from None
    schemes = {"https"} if https_only else {"http", "https"}
    if (
        parsed.scheme.lower() not in schemes
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (parsed.fragment and not allow_fragment)
        or port not in {None, 80, 443}
    ):
        raise _response_error("BIZINFO_URL_INVALID")
    if _has_sensitive_query_parameter(parsed.query):
        raise _response_error("BIZINFO_URL_SENSITIVE_QUERY")
    try:
        hostname = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        raise _response_error("BIZINFO_URL_INVALID") from None
    if not hostname or "." not in hostname:
        raise _response_error("BIZINFO_URL_INVALID")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise _response_error("BIZINFO_URL_INVALID")
    scheme = parsed.scheme.lower()
    if https_only and port not in {None, 443}:
        raise _response_error("BIZINFO_URL_INVALID")
    if not https_only and (
        (scheme == "https" and port not in {None, 443})
        or (scheme == "http" and port not in {None, 80})
    ):
        raise _response_error("BIZINFO_URL_INVALID")
    netloc = hostname if port is None else f"{hostname}:{port}"
    fragment = parsed.fragment if allow_fragment else ""
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, fragment))


def _provider_datetime(value: str) -> datetime | None:
    normalized = _plain_text(value)
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_SEOUL)
    except ValueError:
        raise _response_error("BIZINFO_TIMESTAMP_INVALID") from None


class _DuplicateJsonKey(ValueError):
    pass


def _strict_json_loads(body: bytes) -> Any:
    def reject_constant(_: str) -> None:
        raise ValueError("non-finite JSON number")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJsonKey(key)
            result[key] = value
        return result

    return json.loads(
        body.decode("utf-8"),
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates,
    )


def _ensure_no_support_search_identifiers(keywords: tuple[str, ...]) -> None:
    for keyword in keywords:
        if _BUSINESS_REGISTRATION_NUMBER.search(keyword):
            raise GuardrailViolation("business registration number in search input")
        if _KOREAN_STREET_ADDRESS.search(keyword):
            raise GuardrailViolation("street address in search input")


def _response_error(code: str) -> SupportNoticeDiscoveryResponseError:
    return SupportNoticeDiscoveryResponseError(
        "Bizinfo support discovery returned an invalid response",
        code=code,
        retryable=False,
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


__all__ = [
    "BIZINFO_SUPPORT_API_ENDPOINT",
    "BizInfoSupportDiscoveryConfig",
    "BizInfoSupportDiscoveryTool",
    "SupportNoticeDiscoveryConfigurationError",
    "SupportNoticeDiscoveryError",
    "SupportNoticeDiscoveryInputError",
    "SupportNoticeDiscoveryRequestError",
    "SupportNoticeDiscoveryResponseError",
]
