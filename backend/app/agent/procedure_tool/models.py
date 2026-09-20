"""Configuration and provider-neutral internals for live procedure lookup.

The public request/result contracts live in :mod:`app.agent.schemas`. This
module deliberately contains no procedure master or rule-evaluation model:
``ProcedureLookupTool`` discovers official source documents on the internet and
leaves their interpretation to the information-analysis Agent.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values

DEFAULT_GOOGLE_SEARCH_ENDPOINT: Final[str] = "https://discoveryengine.googleapis.com"
DEFAULT_KAKAO_SEARCH_ENDPOINT: Final[str] = "https://dapi.kakao.com/v2/search/web"
# Backwards-compatible import alias. New code should use the provider-specific name.
DEFAULT_SEARCH_ENDPOINT: Final[str] = DEFAULT_KAKAO_SEARCH_ENDPOINT
# Environment configuration may only narrow these code-reviewed trust roots to
# an exact root or one of its child hosts. Adding another trust root requires a
# code/security review; an environment value must never broaden network egress.
CODE_REVIEWED_OFFICIAL_DOMAINS: Final[tuple[str, ...]] = (
    "law.go.kr",
    "easylaw.go.kr",
    "nps.or.kr",
)
DEFAULT_OFFICIAL_DOMAINS: Final[tuple[str, ...]] = CODE_REVIEWED_OFFICIAL_DOMAINS

_DEFAULT_TIMEOUT_SECONDS = 8.0
_DEFAULT_TOTAL_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_RETRIES = 1
_DEFAULT_RETRY_BACKOFF_SECONDS = 0.25
_DEFAULT_MAX_RESPONSE_BYTES = 1_000_000
_DEFAULT_MAX_REDIRECTS = 3
_MAX_ALLOWED_RETRIES = 4
_BROAD_PUBLIC_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        "ac.kr",
        "co.kr",
        "ne.kr",
        "or.kr",
        "pe.kr",
        "re.kr",
    }
)


class ProcedureSearchConfigurationError(ValueError):
    """Raised when procedure-search configuration is absent or unsafe."""


@dataclass(frozen=True, slots=True)
class ProcedureSearchConfig:
    """Validated official-first discovery and document-fetch configuration.

    Provider keys are excluded from ``repr`` so diagnostics cannot accidentally
    disclose them. A code-reviewed official-source registry needs no credential.
    Kakao and Google are optional URL-discovery fallbacks for queries that the
    registry cannot cover. Process-environment values take precedence over the
    repository ``.env`` file, matching the rest of the Agent runtime.
    """

    official_source_registry_enabled: bool = True
    google_api_key: str | None = field(default=None, repr=False)
    google_project_id: str | None = None
    google_engine_id: str | None = None
    google_location: str = "global"
    kakao_api_key: str | None = field(default=None, repr=False)
    kakao_endpoint: str = DEFAULT_KAKAO_SEARCH_ENDPOINT
    allowed_domains: tuple[str, ...] = DEFAULT_OFFICIAL_DOMAINS
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    total_timeout_seconds: float = _DEFAULT_TOTAL_TIMEOUT_SECONDS
    max_retries: int = _DEFAULT_MAX_RETRIES
    retry_backoff_seconds: float = _DEFAULT_RETRY_BACKOFF_SECONDS
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES
    max_redirects: int = _DEFAULT_MAX_REDIRECTS

    def __post_init__(self) -> None:
        google_api_key = _normalize_optional(self.google_api_key)
        google_project_id = _normalize_optional(self.google_project_id)
        google_engine_id = _normalize_optional(self.google_engine_id)
        google_fields = (google_api_key, google_project_id, google_engine_id)
        if any(google_fields) and not all(google_fields):
            raise ProcedureSearchConfigurationError(
                "Google procedure search requires API_KEY, PROJECT_ID, and ENGINE_ID"
            )
        if google_project_id is not None:
            google_project_id = _validate_project_id(google_project_id)
        if google_engine_id is not None:
            google_engine_id = _validate_engine_id(google_engine_id)
        location = self.google_location.strip().lower()
        if location not in {"global", "us", "eu"}:
            raise ProcedureSearchConfigurationError(
                "PROCEDURE_GOOGLE_LOCATION must be global, us, or eu"
            )
        kakao_api_key = _normalize_optional(self.kakao_api_key)
        if (
            not self.official_source_registry_enabled
            and google_api_key is None
            and kakao_api_key is None
        ):
            raise ProcedureSearchConfigurationError(
                "at least one procedure source provider must be configured"
            )
        object.__setattr__(self, "google_api_key", google_api_key)
        object.__setattr__(self, "google_project_id", google_project_id)
        object.__setattr__(self, "google_engine_id", google_engine_id)
        object.__setattr__(self, "google_location", location)
        object.__setattr__(self, "kakao_api_key", kakao_api_key)
        object.__setattr__(
            self, "kakao_endpoint", _validate_kakao_endpoint(self.kakao_endpoint)
        )
        normalized_domains = tuple(
            dict.fromkeys(_normalize_domain(item) for item in self.allowed_domains)
        )
        if not normalized_domains:
            raise ProcedureSearchConfigurationError(
                "at least one official procedure source domain is required"
            )
        object.__setattr__(self, "allowed_domains", normalized_domains)
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ProcedureSearchConfigurationError(
                "PROCEDURE_SEARCH_TIMEOUT_SECONDS must be finite and positive"
            )
        if (
            not math.isfinite(self.total_timeout_seconds)
            or self.total_timeout_seconds <= 0
        ):
            raise ProcedureSearchConfigurationError(
                "PROCEDURE_SEARCH_TOTAL_TIMEOUT_SECONDS must be finite and positive"
            )
        if not 0 <= self.max_retries <= _MAX_ALLOWED_RETRIES:
            raise ProcedureSearchConfigurationError(
                f"PROCEDURE_SEARCH_MAX_RETRIES must be between 0 and "
                f"{_MAX_ALLOWED_RETRIES}"
            )
        if (
            not math.isfinite(self.retry_backoff_seconds)
            or self.retry_backoff_seconds < 0
        ):
            raise ProcedureSearchConfigurationError(
                "PROCEDURE_SEARCH_RETRY_BACKOFF_SECONDS must be finite and not negative"
            )
        if not 1_024 <= self.max_response_bytes <= 10_000_000:
            raise ProcedureSearchConfigurationError(
                "PROCEDURE_SEARCH_MAX_RESPONSE_BYTES must be between 1024 and 10000000"
            )
        if not 0 <= self.max_redirects <= 10:
            raise ProcedureSearchConfigurationError(
                "PROCEDURE_SEARCH_MAX_REDIRECTS must be between 0 and 10"
            )

    @property
    def google_enabled(self) -> bool:
        return self.google_api_key is not None

    @property
    def kakao_enabled(self) -> bool:
        return self.kakao_api_key is not None

    @property
    def google_search_url(self) -> str:
        if not self.google_enabled:
            raise ProcedureSearchConfigurationError(
                "Google procedure search is not configured"
            )
        host = (
            "discoveryengine.googleapis.com"
            if self.google_location == "global"
            else f"{self.google_location}-discoveryengine.googleapis.com"
        )
        return (
            f"https://{host}/v1/projects/{self.google_project_id}"
            f"/locations/{self.google_location}/collections/default_collection"
            f"/engines/{self.google_engine_id}/servingConfigs/default_search:searchLite"
        )

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> ProcedureSearchConfig:
        environment = os.environ if environ is None else environ
        dotenv_path = Path(env_file) if env_file is not None else _repo_root() / ".env"
        file_values: Mapping[str, str | None]
        if dotenv_path.is_file():
            try:
                file_values = dotenv_values(dotenv_path)
            except (OSError, ValueError) as exc:
                raise ProcedureSearchConfigurationError(
                    "procedure-search environment file could not be read"
                ) from exc
        else:
            file_values = {}

        def value(key: str) -> str | None:
            raw = environment.get(key)
            if raw is None:
                raw = file_values.get(key)
            if raw is None:
                return None
            normalized = str(raw).strip()
            return normalized or None

        google_api_key = value("PROCEDURE_GOOGLE_API_KEY")
        google_project_id = value("PROCEDURE_GOOGLE_PROJECT_ID")
        google_engine_id = value("PROCEDURE_GOOGLE_ENGINE_ID")
        kakao_api_key = (
            value("PROCEDURE_KAKAO_REST_API_KEY")
            or value("PROCEDURE_SEARCH_API_KEY")
            or value("KAKAO_CLIENT_ID")
        )

        allowed_domains_raw = value("PROCEDURE_SEARCH_ALLOWED_DOMAINS")
        allowed_domains = (
            tuple(
                item.strip() for item in allowed_domains_raw.split(",") if item.strip()
            )
            if allowed_domains_raw is not None
            else DEFAULT_OFFICIAL_DOMAINS
        )
        return cls(
            official_source_registry_enabled=_parse_bool(
                value("PROCEDURE_OFFICIAL_REGISTRY_ENABLED"),
                default=True,
                name="PROCEDURE_OFFICIAL_REGISTRY_ENABLED",
            ),
            google_api_key=google_api_key,
            google_project_id=google_project_id,
            google_engine_id=google_engine_id,
            google_location=value("PROCEDURE_GOOGLE_LOCATION") or "global",
            kakao_api_key=kakao_api_key,
            kakao_endpoint=(
                value("PROCEDURE_KAKAO_SEARCH_ENDPOINT")
                or value("PROCEDURE_SEARCH_ENDPOINT")
                or DEFAULT_KAKAO_SEARCH_ENDPOINT
            ),
            allowed_domains=allowed_domains,
            timeout_seconds=_parse_float(
                value("PROCEDURE_SEARCH_TIMEOUT_SECONDS"),
                default=_DEFAULT_TIMEOUT_SECONDS,
                name="PROCEDURE_SEARCH_TIMEOUT_SECONDS",
            ),
            total_timeout_seconds=_parse_float(
                value("PROCEDURE_SEARCH_TOTAL_TIMEOUT_SECONDS"),
                default=_DEFAULT_TOTAL_TIMEOUT_SECONDS,
                name="PROCEDURE_SEARCH_TOTAL_TIMEOUT_SECONDS",
            ),
            max_retries=_parse_int(
                value("PROCEDURE_SEARCH_MAX_RETRIES"),
                default=_DEFAULT_MAX_RETRIES,
                name="PROCEDURE_SEARCH_MAX_RETRIES",
            ),
            retry_backoff_seconds=_parse_float(
                value("PROCEDURE_SEARCH_RETRY_BACKOFF_SECONDS"),
                default=_DEFAULT_RETRY_BACKOFF_SECONDS,
                name="PROCEDURE_SEARCH_RETRY_BACKOFF_SECONDS",
            ),
            max_response_bytes=_parse_int(
                value("PROCEDURE_SEARCH_MAX_RESPONSE_BYTES"),
                default=_DEFAULT_MAX_RESPONSE_BYTES,
                name="PROCEDURE_SEARCH_MAX_RESPONSE_BYTES",
            ),
            max_redirects=_parse_int(
                value("PROCEDURE_SEARCH_MAX_REDIRECTS"),
                default=_DEFAULT_MAX_REDIRECTS,
                name="PROCEDURE_SEARCH_MAX_REDIRECTS",
            ),
        )


@dataclass(frozen=True, slots=True)
class SearchHit:
    """Untrusted discovery result returned by a configured search provider."""

    title: str
    url: str
    query: str
    provider: Literal[
        "OFFICIAL_SOURCE_REGISTRY",
        "GOOGLE_AGENT_SEARCH",
        "KAKAO_DAUM_WEB",
    ]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _normalize_domain(value: str) -> str:
    candidate = value.strip().lower().rstrip(".")
    if (
        not candidate
        or candidate.startswith("*.")
        or ":" in candidate
        or "/" in candidate
    ):
        raise ProcedureSearchConfigurationError(
            "official source domains must be bare host suffixes"
        )
    try:
        normalized = candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ProcedureSearchConfigurationError(
            "official source domain is invalid"
        ) from exc
    labels = normalized.split(".")
    if not all(
        part
        and len(part) <= 63
        and not part.startswith("-")
        and not part.endswith("-")
        and part.replace("-", "a").isalnum()
        for part in labels
    ):
        raise ProcedureSearchConfigurationError("official source domain is invalid")
    if "." not in normalized or normalized in _BROAD_PUBLIC_SUFFIXES:
        raise ProcedureSearchConfigurationError(
            "official source domains must not be a top-level or broad public suffix"
        )
    if not any(
        normalized == approved or normalized.endswith(f".{approved}")
        for approved in CODE_REVIEWED_OFFICIAL_DOMAINS
    ):
        raise ProcedureSearchConfigurationError(
            "official source domains must be within the code-reviewed registry"
        )
    return normalized


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _validate_project_id(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", value):
        raise ProcedureSearchConfigurationError(
            "PROCEDURE_GOOGLE_PROJECT_ID is invalid"
        )
    return value


def _validate_engine_id(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", value):
        raise ProcedureSearchConfigurationError("PROCEDURE_GOOGLE_ENGINE_ID is invalid")
    return value


def _validate_kakao_endpoint(value: str) -> str:
    raw = value.strip()
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ProcedureSearchConfigurationError(
            "Kakao search endpoint must be an absolute HTTPS URL"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProcedureSearchConfigurationError(
            "Kakao search endpoint must not contain credentials, query, or fragment"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise ProcedureSearchConfigurationError(
            "Kakao search endpoint has an invalid port"
        ) from exc
    if port not in {None, 443}:
        raise ProcedureSearchConfigurationError(
            "Kakao search endpoint must use the standard HTTPS port"
        )
    hostname = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    if hostname != "dapi.kakao.com" or parsed.path.rstrip("/") != "/v2/search/web":
        raise ProcedureSearchConfigurationError(
            "Kakao search endpoint must be the Daum web-search endpoint"
        )
    netloc = hostname
    return urlunsplit(("https", netloc, parsed.path or "/", "", ""))


def _parse_int(raw: str | None, *, default: int, name: str) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ProcedureSearchConfigurationError(f"{name} must be an integer") from exc


def _parse_bool(raw: str | None, *, default: bool, name: str) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ProcedureSearchConfigurationError(f"{name} must be true or false")


def _parse_float(raw: str | None, *, default: float, name: str) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ProcedureSearchConfigurationError(f"{name} must be numeric") from exc


__all__ = [
    "DEFAULT_GOOGLE_SEARCH_ENDPOINT",
    "DEFAULT_KAKAO_SEARCH_ENDPOINT",
    "DEFAULT_OFFICIAL_DOMAINS",
    "DEFAULT_SEARCH_ENDPOINT",
    "ProcedureSearchConfig",
    "ProcedureSearchConfigurationError",
    "SearchHit",
]
