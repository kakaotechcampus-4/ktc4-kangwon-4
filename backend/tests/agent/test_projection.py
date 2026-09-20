from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from app.agent.guardrails import GuardrailViolation
from app.agent.projection import (
    ensure_projection_has_no_obvious_sensitive_text,
    to_model_projection,
)
from app.agent.schemas import (
    EvidenceRecord,
    ProcedureSourceDocument,
    RedactedInput,
    Redaction,
)

pytestmark = pytest.mark.real_data

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


def test_procedure_document_projection_drops_untrusted_web_excerpt() -> None:
    document = ProcedureSourceDocument(
        document_id=UUID("00000000-0000-4000-8000-000000000901"),
        title="공식 폐업 안내",
        authority_name="정부24",
        canonical_url="https://www.gov.kr/closure",
        source_domain="www.gov.kr",
        excerpt="외부 웹 원문은 Supervisor prompt로 다시 보내지 않습니다.",
        published_at=None,
        retrieved_at=NOW,
        freshness_status="UNKNOWN",
        content_hash="sha256:" + "a" * 64,
        evidence_ref="procedure:web:1",
        search_query="사업자 폐업 신고 절차",
        discovery_provider="KAKAO_DAUM_WEB",
    )

    projection = to_model_projection(document)

    assert "excerpt" not in projection
    assert projection["evidence_ref"] == "procedure:web:1"


def test_sensitive_value_in_projection_is_rejected() -> None:
    with pytest.raises(GuardrailViolation, match="sensitive output detected"):
        ensure_projection_has_no_obvious_sensitive_text(
            {"summary": "Authorization: Bearer abcdefghijklmnop"}
        )
