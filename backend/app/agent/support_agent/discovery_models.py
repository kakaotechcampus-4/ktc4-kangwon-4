"""Strict contracts for read-only support-notice discovery.

These models describe unreviewed official notice candidates.  They are kept
separate from :class:`ReviewedSupportCatalog`: discovery proves what the
official API returned, but it does not establish program eligibility or make a
notice safe for support analysis.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Final, Literal
from urllib.parse import parse_qsl, urlsplit

from app.agent.schemas import (
    EvidenceRecord,
    FreshnessStatus,
    NonNegativeStrictInt,
)
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

_MAX_KEYWORDS = 8
_MAX_RESULTS = 100
BIZINFO_SUPPORT_API_ENDPOINT: Final[str] = (
    "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
)
_BIZINFO_HOST: Final[str] = "www.bizinfo.go.kr"
_BIZINFO_DETAIL_PATH: Final[str] = "/sii/siia/selectSIIA200Detail.do"
_BIZINFO_NOTICE_ID = re.compile(r"PBLN_[A-Za-z0-9_]+")
_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_SENSITIVE_QUERY_NAME_TOKENS = frozenset(
    {
        "auth",
        "authorization",
        "credential",
        "credentials",
        "jwt",
        "key",
        "passphrase",
        "passwd",
        "password",
        "secret",
        "session",
        "sig",
        "signature",
        "token",
    }
)
_SENSITIVE_COMPACT_QUERY_NAMES = frozenset(
    {
        "accesstoken",
        "apikey",
        "authtoken",
        "clientsecret",
        "crtfckey",
        "idtoken",
        "oauth",
        "privatekey",
        "refreshtoken",
        "servicekey",
        "sessionid",
    }
)
_CONTENT_HASH_EXCLUDED_FIELDS = frozenset(
    {"provider", "freshness_status", "evidence_ref", "view_count"}
)
_MAX_EXCERPT_CHARS = 4_000

DiscoveryKeyword = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
]
DiscoveryText = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1),
]
DiscoveryUrl = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4_096),
]


class SupportNoticeDiscoveryModel(BaseModel):
    """Reject unknown fields and prevent post-validation reassignment."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        validate_default=True,
    )


class SupportNoticeDiscoveryInput(SupportNoticeDiscoveryModel):
    """Bounded Bizinfo hashtag lookup requested by trusted Agent code."""

    keywords: Annotated[
        tuple[DiscoveryKeyword, ...],
        Field(min_length=1, max_length=_MAX_KEYWORDS),
    ]
    max_results: Annotated[StrictInt, Field(ge=1, le=_MAX_RESULTS)] = 20

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validated_keywords(values)


class SupportNoticeCandidate(SupportNoticeDiscoveryModel):
    """Normalized but unreviewed notice returned by the official Bizinfo API."""

    provider: Literal["BIZINFO"] = "BIZINFO"
    notice_id: DiscoveryText
    title: DiscoveryText
    detail_url: DiscoveryUrl
    summary: DiscoveryText | None
    target: DiscoveryText | None
    application_period: DiscoveryText | None
    application_method: DiscoveryText | None
    application_url: DiscoveryUrl | None
    jurisdiction_institution: DiscoveryText | None
    executing_institution: DiscoveryText | None
    support_area_major: DiscoveryText | None
    support_area_middle: DiscoveryText | None
    reference_contact: DiscoveryText | None
    hashtags: tuple[DiscoveryText, ...]
    attachment_name: DiscoveryText | None
    attachment_url: DiscoveryUrl | None
    print_attachment_name: DiscoveryText | None
    print_attachment_url: DiscoveryUrl | None
    provider_created_at: AwareDatetime | None
    provider_updated_at: AwareDatetime | None
    view_count: NonNegativeStrictInt
    freshness_status: FreshnessStatus
    evidence_ref: DiscoveryText

    @field_validator("notice_id")
    @classmethod
    def require_bizinfo_notice_id(cls, value: str) -> str:
        if _BIZINFO_NOTICE_ID.fullmatch(value) is None:
            raise ValueError("notice_id must use the Bizinfo PBLN identifier format")
        return value

    @field_validator("freshness_status")
    @classmethod
    def require_unknown_freshness(cls, value: FreshnessStatus) -> FreshnessStatus:
        if value != FreshnessStatus.UNKNOWN:
            raise ValueError("discovered support notice freshness must be UNKNOWN")
        return value

    @field_validator("hashtags")
    @classmethod
    def require_unique_hashtags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("candidate hashtags must be unique")
        return values

    @model_validator(mode="after")
    def validate_urls(self) -> SupportNoticeCandidate:
        detail = _validated_web_url(self.detail_url, https_only=True)
        parsed_detail = urlsplit(detail)
        if (
            parsed_detail.hostname != _BIZINFO_HOST
            or parsed_detail.path != _BIZINFO_DETAIL_PATH
            or parse_qsl(parsed_detail.query, keep_blank_values=True)
            != [("pblancId", self.notice_id)]
        ):
            raise ValueError("detail_url must identify this notice on Bizinfo")
        for value in (self.attachment_url, self.print_attachment_url):
            if value is not None:
                parsed = urlsplit(_validated_web_url(value, https_only=True))
                if parsed.hostname != _BIZINFO_HOST:
                    raise ValueError("attachment URLs must use the Bizinfo host")
        if self.application_url is not None:
            _validated_web_url(self.application_url, https_only=False)
        if (self.attachment_name is None) != (self.attachment_url is None):
            raise ValueError("attachment name and URL must be present together")
        if (self.print_attachment_name is None) != (self.print_attachment_url is None):
            raise ValueError("print attachment name and URL must be present together")
        return self


class SupportNoticeDiscoveryResult(SupportNoticeDiscoveryModel):
    """One completed provider read, including source evidence and truncation."""

    provider: Literal["BIZINFO"] = "BIZINFO"
    keywords: Annotated[
        tuple[DiscoveryKeyword, ...],
        Field(min_length=1, max_length=_MAX_KEYWORDS),
    ]
    applied_result_limit: Annotated[StrictInt, Field(ge=1, le=_MAX_RESULTS)]
    provider_total_count: NonNegativeStrictInt | None
    provider_returned_count: NonNegativeStrictInt
    duplicate_count: NonNegativeStrictInt
    result_count: NonNegativeStrictInt
    truncated: StrictBool
    retrieved_at: AwareDatetime
    candidates: Annotated[
        tuple[SupportNoticeCandidate, ...],
        Field(max_length=_MAX_RESULTS),
    ]
    evidence_records: Annotated[
        tuple[EvidenceRecord, ...],
        Field(max_length=_MAX_RESULTS),
    ]

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validated_keywords(values)

    @model_validator(mode="after")
    def validate_result_integrity(self) -> SupportNoticeDiscoveryResult:
        if self.result_count != len(self.candidates):
            raise ValueError("result_count must equal the candidate count")
        if self.result_count > self.applied_result_limit:
            raise ValueError("result_count exceeds the applied result limit")
        if len(self.evidence_records) != len(self.candidates):
            raise ValueError("each candidate must have exactly one evidence record")
        if self.duplicate_count > self.provider_returned_count:
            raise ValueError("duplicate_count exceeds the provider response count")
        if self.result_count + self.duplicate_count > self.provider_returned_count:
            raise ValueError("normalized results exceed the provider response count")
        unique_returned_count = self.provider_returned_count - self.duplicate_count
        expected_result_count = min(unique_returned_count, self.applied_result_limit)
        if self.result_count != expected_result_count:
            raise ValueError("result_count does not match the bounded unique count")
        if (self.provider_returned_count == 0) != (self.provider_total_count is None):
            raise ValueError(
                "provider total count presence does not match the response"
            )
        if (
            self.provider_total_count is not None
            and self.provider_total_count < self.provider_returned_count
        ):
            raise ValueError("provider total count is smaller than the returned count")

        notice_ids = [candidate.notice_id for candidate in self.candidates]
        if len(set(notice_ids)) != len(notice_ids):
            raise ValueError("notice_id must be unique")

        evidence_by_id = {
            evidence.evidence_id: evidence for evidence in self.evidence_records
        }
        if len(evidence_by_id) != len(self.evidence_records):
            raise ValueError("evidence_id must be unique")
        candidate_evidence_refs = [
            candidate.evidence_ref for candidate in self.candidates
        ]
        if len(set(candidate_evidence_refs)) != len(candidate_evidence_refs):
            raise ValueError("candidate evidence_ref must be unique")
        if set(candidate_evidence_refs) != set(evidence_by_id):
            raise ValueError("candidate and evidence identifiers must be bijective")
        for candidate in self.candidates:
            evidence = evidence_by_id.get(candidate.evidence_ref)
            if evidence is None:
                raise ValueError("candidate references unknown evidence")
            if evidence.source_type.value != "OFFICIAL_API":
                raise ValueError("discovery evidence must be OFFICIAL_API")
            if evidence.freshness_status != FreshnessStatus.UNKNOWN:
                raise ValueError("discovery evidence freshness must be UNKNOWN")
            if evidence.retrieved_at != self.retrieved_at:
                raise ValueError("evidence retrieval time must match the result")
            if evidence.source_ref != BIZINFO_SUPPORT_API_ENDPOINT:
                raise ValueError("discovery evidence must identify the Bizinfo API")
            if evidence.locator != candidate.detail_url:
                raise ValueError("evidence locator must match the candidate detail URL")
            candidate_values = candidate.model_dump(mode="python")
            expected_hash = _candidate_content_digest(candidate_values)
            if (
                evidence.content_hash is None
                or evidence.content_hash != expected_hash
                or evidence.source_version != evidence.content_hash
            ):
                raise ValueError("evidence hash must match the normalized candidate")
            expected_evidence_id = (
                f"support:bizinfo:{candidate.notice_id}:"
                f"{expected_hash.removeprefix('sha256:')}"
            )
            if evidence.evidence_id != expected_evidence_id:
                raise ValueError("evidence_id must be derived from notice_id and hash")
            if evidence.excerpt != _candidate_evidence_excerpt(candidate_values):
                raise ValueError("evidence excerpt must match the normalized candidate")
            if evidence.parent_evidence_refs:
                raise ValueError(
                    "direct Bizinfo evidence must not have parent evidence"
                )
            if evidence.published_at is not None:
                raise ValueError("unverified notice publication time must remain null")

        expected_truncated = (
            self.provider_total_count is not None
            and self.provider_total_count > self.result_count
        ) or self.provider_returned_count - self.duplicate_count > self.result_count
        if self.truncated != expected_truncated:
            raise ValueError("truncated does not match provider counts")
        return self


def _validated_keywords(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        keyword = value.strip()
        if (
            not keyword
            or "," in keyword
            or any(ord(char) < 32 or ord(char) == 127 for char in keyword)
        ):
            raise ValueError("keywords must be non-empty single Bizinfo hashtag terms")
        dedupe_key = keyword.casefold()
        if dedupe_key in seen:
            raise ValueError("keywords must be unique")
        seen.add(dedupe_key)
        normalized.append(keyword)
    return tuple(normalized)


def _validated_web_url(value: str, *, https_only: bool) -> str:
    if any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError("support discovery URL is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("support discovery URL is invalid") from exc
    schemes = {"https"} if https_only else {"http", "https"}
    if (
        parsed.scheme not in schemes
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port not in {None, 80, 443}
    ):
        raise ValueError("support discovery URL is invalid")
    if _has_sensitive_query_parameter(parsed.query):
        raise ValueError("support discovery URL has a sensitive query parameter")
    if parsed.scheme == "https" and port not in {None, 443}:
        raise ValueError("support discovery URL is invalid")
    if parsed.scheme == "http" and port not in {None, 80}:
        raise ValueError("support discovery URL is invalid")
    try:
        hostname = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as exc:
        raise ValueError("support discovery URL is invalid") from exc
    if not hostname or "." not in hostname:
        raise ValueError("support discovery URL is invalid")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("support discovery URL must not use an IP literal")
    return value


def _has_sensitive_query_parameter(query: str) -> bool:
    if not query:
        return False
    if _INVALID_PERCENT_ESCAPE.search(query):
        return True
    try:
        parameters = parse_qsl(
            query.replace(";", "&"),
            keep_blank_values=True,
            max_num_fields=100,
        )
    except ValueError:
        return True
    return any(_is_sensitive_query_parameter_name(name) for name, _ in parameters)


def _is_sensitive_query_parameter_name(name: str) -> bool:
    camel_separated = _CAMEL_CASE_BOUNDARY.sub("_", name)
    tokens = {
        token.casefold()
        for token in re.split(r"[^A-Za-z0-9]+", camel_separated)
        if token
    }
    if tokens.intersection(_SENSITIVE_QUERY_NAME_TOKENS):
        return True
    compact = "".join(char for char in name.casefold() if char.isalnum())
    return compact in _SENSITIVE_COMPACT_QUERY_NAMES


def _candidate_content_digest(values: Mapping[str, Any]) -> str:
    serializable = {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in values.items()
        if key not in _CONTENT_HASH_EXCLUDED_FIELDS
    }
    canonical = json.dumps(
        serializable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _candidate_evidence_excerpt(values: Mapping[str, Any]) -> str:
    excerpt_values = [
        values.get("title"),
        values.get("summary"),
        values.get("target"),
        values.get("application_period"),
        values.get("application_method"),
    ]
    excerpt = " | ".join(value for value in excerpt_values if isinstance(value, str))
    return excerpt[:_MAX_EXCERPT_CHARS].rstrip()


__all__ = [
    "BIZINFO_SUPPORT_API_ENDPOINT",
    "SupportNoticeCandidate",
    "SupportNoticeDiscoveryInput",
    "SupportNoticeDiscoveryResult",
]
