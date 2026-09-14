"""Deterministic validation helpers used around model calls."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class GuardrailViolation(ValueError):
    """Raised when a model result cannot safely cross a runtime boundary."""


_SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("NATIONAL_ID", re.compile(r"(?<!\d)\d{6}\s*[- ]\s*\d{7}(?!\d)")),
    ("BEARER_TOKEN", re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{12,}")),
    ("API_KEY", re.compile(r"(?i)\b(?:sk|pk)-[a-z0-9_-]{12,}")),
)


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, datetime):
        normalized = value.astimezone(timezone.utc)
        return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (UUID, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    return value


def canonical_json(value: Any) -> str:
    """Serialize a schema value deterministically for review/evidence digests."""

    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_digest(value: Any) -> str:
    payload = canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def exact_span(text: str, source_text: str) -> tuple[int, int]:
    """Return an exact Unicode-code-point span or reject ungrounded text."""

    if not source_text:
        raise GuardrailViolation("source_text must not be empty")
    start = text.find(source_text)
    if start < 0:
        raise GuardrailViolation("model source_text is not present in redacted input")
    return start, start + len(source_text)


def ensure_known_refs(refs: Iterable[str], known: Iterable[str], *, label: str) -> None:
    known_set = set(known)
    unknown = sorted(set(refs) - known_set)
    if unknown:
        raise GuardrailViolation(f"unknown {label} references: {', '.join(unknown)}")


def ensure_no_sensitive_text(values: Iterable[str]) -> None:
    """Reject obvious unredacted secrets/identifiers before returning free text."""

    for value in values:
        for label, pattern in _SENSITIVE_PATTERNS:
            if pattern.search(value):
                raise GuardrailViolation(f"sensitive output detected: {label}")
