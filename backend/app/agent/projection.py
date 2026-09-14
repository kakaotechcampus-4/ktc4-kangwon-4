"""Minimum-data projection for payloads sent to external language models."""

from __future__ import annotations

from typing import Any

from app.agent.guardrails import ensure_no_sensitive_text
from pydantic import BaseModel


def to_model_projection(value: BaseModel | dict[str, Any] | list[Any]) -> Any:
    """Remove runtime, source-location and evidence-content fields recursively.

    Evidence IDs, source classes, freshness and lineage remain available for
    provenance reasoning.  The source reference, locator, excerpt and hashes do
    not leave the runtime.  User text is supplied only to the Info Agent through
    its explicit ``RedactedInput`` boundary.
    """

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, list):
        return [to_model_projection(item) for item in value]
    if not isinstance(value, dict):
        return value

    keys = set(value)
    if {"evidence_id", "source_type", "freshness_status"}.issubset(keys):
        return {
            "evidence_id": value["evidence_id"],
            "source_type": value["source_type"],
            "source_version": value.get("source_version"),
            "parent_evidence_refs": to_model_projection(
                value.get("parent_evidence_refs", [])
            ),
            "freshness_status": value["freshness_status"],
        }
    if {"input_event_id", "text", "start_offset", "end_offset"}.issubset(keys):
        return {
            "input_event_id": value["input_event_id"],
            "start_offset": value["start_offset"],
            "end_offset": value["end_offset"],
        }
    if "redacted_text" in value:
        return {
            key: to_model_projection(item)
            for key, item in value.items()
            if key not in {"redacted_text", "redactions"}
        }
    return {
        key: to_model_projection(item)
        for key, item in value.items()
        if key
        not in {
            "trace_id",
            "content_hash",
            "locator",
            "source_ref",
        }
    }


def ensure_projection_has_no_obvious_sensitive_text(value: Any) -> None:
    strings: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, dict):
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    ensure_no_sensitive_text(strings)


__all__ = ["ensure_projection_has_no_obvious_sensitive_text", "to_model_projection"]
