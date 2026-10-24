"""Deterministic validation helpers used around model calls."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


class GuardrailViolation(ValueError):
    """Raised when a model result cannot safely cross a runtime boundary."""


# These run over official excerpts and evidence as well as over model output,
# so a pattern here has to be narrow enough not to reject real source material.
_SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("NATIONAL_ID", re.compile(r"(?<!\d)\d{6}\s*[- ]\s*\d{7}(?!\d)")),
    # Hyphens only.  The search-input check in ``support_agent.discovery_tool``
    # deliberately also accepts spaces, because a person types a query freely
    # and nothing official flows through it.  Widening this one the same way
    # matches runs inside SHA-256 evidence digests and official document IDs,
    # which would fail a run on its own grounding.
    ("BUSINESS_REGISTRATION_NUMBER", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{5}(?!\d)")),
    # Hyphens are required here for the same reason as above: a digit-only form
    # matches runs inside SHA-256 evidence digests.  A Case freely names other
    # people ("the landlord said ..."), so their number can arrive unredacted.
    ("PHONE_NUMBER", re.compile(r"(?<!\d)01[016789]-\d{3,4}-\d{4}(?!\d)")),
    ("BEARER_TOKEN", re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{12,}")),
    ("API_KEY", re.compile(r"(?i)\b(?:sk|pk)-[a-z0-9_-]{12,}")),
)


def exact_span(text: str, source_text: str) -> tuple[int, int]:
    """Return an exact Unicode-code-point span or reject ungrounded text."""

    if not source_text:
        raise GuardrailViolation("source_text must not be empty")
    start = text.find(source_text)
    if start < 0:
        raise GuardrailViolation("model source_text is not present in redacted input")
    return start, start + len(source_text)


def resolve_evidence_aliases(
    value: Any,
    evidence_by_alias: Mapping[str, str],
) -> Any:
    """Turn short evidence handles in a model answer back into real IDs.

    A component that must name its evidence is otherwise copying a stored
    identifier exactly, and measured runs showed both the Info Agent and the
    Supervisor getting a character wrong or reaching for a nearby string that
    was not evidence at all. Offering short handles removes that failure, and
    this puts the real IDs back before anything else looks at the answer, so
    every later check sees exactly what it saw before handles existed.

    Only values inside an ``evidence_refs`` list are translated; free text is
    left alone. An unknown handle passes through unchanged and fails the same
    grounding check it would have failed anyway.
    """

    def walk(node: Any, *, inside_refs: bool) -> Any:
        if isinstance(node, str):
            return evidence_by_alias.get(node, node) if inside_refs else node
        if isinstance(node, list):
            return [walk(item, inside_refs=inside_refs) for item in node]
        if isinstance(node, dict):
            return {
                key: walk(item, inside_refs=key == "evidence_refs")
                for key, item in node.items()
            }
        return node

    if not evidence_by_alias:
        return value
    return walk(value, inside_refs=False)


def ensure_known_refs(refs: Iterable[str], known: Iterable[str], *, label: str) -> None:
    known_set = set(known)
    unknown = sorted(set(refs) - known_set)
    if unknown:
        raise GuardrailViolation(f"unknown {label} references: {', '.join(unknown)}")


def ensure_no_sensitive_text(values: Iterable[str]) -> None:
    """Reject obvious unredacted secrets/identifiers before returning free text."""

    for value in values:
        for label, pattern in _SENSITIVE_PATTERNS:
            # Runtime UUIDs can contain phone-shaped digits; prose still gets checked.
            if label == "PHONE_NUMBER" and re.fullmatch(
                r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", value,
            ):
                continue
            if pattern.search(value):
                raise GuardrailViolation(f"sensitive output detected: {label}")
