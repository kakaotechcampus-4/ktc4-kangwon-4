"""DB evidence is required, preserved and checked against reviewed metadata."""

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent.procedure_tool.store import ReviewedProcedureRecord
from app.agent.procedure_tool.stored_tool import (
    ProcedureLookupInputError,
    StoredProcedureLookupTool,
)
from app.agent.schemas import EvidenceRecord, ProcedureLookupInput

NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


def lookup(*, evidence_changes=None, record_changes=None, missing=False, as_of=None):
    record = ReviewedProcedureRecord(
        record_id="TAX", title="합성 절차", authority_name="합성 기관",
        canonical_url="https://example.org/tax", source_domain="example.org",
        excerpt="합성 공식 자료", content_hash="sha256:" + "a" * 64,
        published_at=None, retrieved_at=NOW, reviewed_by="synthetic-reviewer",
        reviewed_at=NOW, review_valid_days=90,
        step_codes=["FILE_TAX_BUSINESS_CLOSURE"], required_terms=["폐업"], any_terms=[],
    )
    if record_changes:
        record = ReviewedProcedureRecord.model_validate(
            {**record.model_dump(), **record_changes}
        )
    evidence = EvidenceRecord(
        evidence_id="persisted-db-evidence", source_type="OFFICIAL_DOCUMENT",
        source_ref=record.canonical_url, source_version="synthetic/1", locator=None,
        excerpt=record.excerpt, content_hash=record.content_hash,
        published_at=None, retrieved_at=NOW, freshness_status="CURRENT",
        parent_evidence_refs=[],
    )
    if evidence_changes:
        evidence = EvidenceRecord.model_validate(
            {**evidence.model_dump(), **evidence_changes}
        )
    store = SimpleNamespace(snapshot_version="synthetic/1", records=lambda: [record])
    request = ProcedureLookupInput(
        lookup_goal="BUSINESS_CLOSURE", evidence_records=[] if missing else [evidence],
        search_queries=["폐업", "사업자 폐업"], as_of=as_of or NOW.date(),
        locale="ko-KR", source_policy="OFFICIAL_ONLY", max_results_per_query=5,
        based_on_snapshot_id=uuid4(), review_feedback=[],
    )
    return asyncio.run(StoredProcedureLookupTool(store).lookup(request)), evidence


def test_returns_the_db_evidence_unchanged_and_deduplicates_queries():
    result, evidence = lookup()
    assert result.evidence_records == [evidence]
    assert result.evidence_records[0] is not evidence
    assert result.documents[0].evidence_ref == evidence.evidence_id
    assert len(result.documents) == 1
    assert result.warnings == []


@pytest.mark.parametrize("changes", [{}, {"source_version": "old"}, {"source_ref": "https://example.org/other"}])
def test_missing_or_unapproved_source_never_uses_json_text(changes):
    result, _ = lookup(evidence_changes=changes, missing=not changes)
    assert result.completion_status == "NO_RESULTS"
    assert result.evidence_records == []


@pytest.mark.parametrize("changes", [{"excerpt": "변조된 자료"}, {"content_hash": "b" * 64}, {"content_hash": None}])
def test_changed_source_is_rejected(changes):
    with pytest.raises(ProcedureLookupInputError) as error:
        lookup(evidence_changes=changes)
    assert error.value.code == "PROCEDURE_SOURCE_MISMATCH"


def test_expired_approval_cannot_keep_db_current():
    with pytest.raises(ProcedureLookupInputError) as error:
        lookup(as_of=date(2027, 2, 1))
    assert error.value.code == "PROCEDURE_REVIEW_REQUIRED"


def test_unreviewed_metadata_is_rejected():
    with pytest.raises(ProcedureLookupInputError) as error:
        lookup(record_changes={"reviewed_by": None, "reviewed_at": None})
    assert error.value.code == "PROCEDURE_REVIEW_REQUIRED"


@pytest.mark.parametrize("status", ["UNKNOWN", "STALE"])
def test_db_freshness_is_never_upgraded(status):
    result, evidence = lookup(evidence_changes={"freshness_status": status})
    assert result.evidence_records == [evidence]
    assert result.documents[0].freshness_status == status
    assert result.warnings
