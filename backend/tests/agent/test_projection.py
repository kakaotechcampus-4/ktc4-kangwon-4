from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app.agent.guardrails import GuardrailViolation
from app.agent.projection import (
    ensure_projection_has_no_obvious_sensitive_text,
    to_model_projection,
)
from app.agent.schemas import EvidenceRecord, RedactedInput, Redaction

NOW = datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc)


def test_evidence_projection_keeps_provenance_without_source_content() -> None:
    record = EvidenceRecord(
        evidence_id="ev-1",
        source_type="OFFICIAL_DOCUMENT",
        source_ref="https://example.invalid/private",
        source_version="2026-09",
        locator="section:secret",
        excerpt="검수 원문",
        parent_evidence_refs=["ev-parent"],
        published_at=NOW,
        retrieved_at=NOW,
        freshness_status="CURRENT",
        content_hash="sha256:" + "a" * 64,
    )

    assert to_model_projection(record) == {
        "evidence_id": "ev-1",
        "source_type": "OFFICIAL_DOCUMENT",
        "source_version": "2026-09",
        "parent_evidence_refs": ["ev-parent"],
        "freshness_status": "CURRENT",
    }


def test_redacted_input_projection_drops_text_and_redaction_details() -> None:
    redacted = RedactedInput(
        input_event_id="input-1",
        source_type="USER_INPUT",
        redacted_text="[REDACTED] 상점 정리",
        redactions=[
            Redaction(
                type="OTHER",
                placeholder="[REDACTED]",
                start_offset=0,
                end_offset=10,
            )
        ],
        submitted_at=NOW,
    )

    projection = to_model_projection(redacted)

    assert "redacted_text" not in projection
    assert "redactions" not in projection
    assert projection["input_event_id"] == "input-1"


def test_sensitive_value_in_projection_is_rejected() -> None:
    with pytest.raises(GuardrailViolation, match="sensitive output detected"):
        ensure_projection_has_no_obvious_sensitive_text(
            {"summary": "Authorization: Bearer abcdefghijklmnop"}
        )
