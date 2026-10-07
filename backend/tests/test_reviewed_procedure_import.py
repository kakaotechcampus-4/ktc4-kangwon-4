"""Validate the whole import before calling existing BE writes; no DB connection."""

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session

from app.agent.procedure_tool.store import ProcedureStoreError, ReviewedProcedureRecord
from app.agent.schemas import KnownProcedureStep, ProcedureStepRef
from app.be.crud import case as case_crud
from app.be.crud import evidence as evidence_crud
from app.be.models.evidence import Evidence
from app.be.services.reviewed_procedure import import_reviewed_procedures
from app.common.agent_data import (
    InMemoryReviewedProcedureStore,
    build_reviewed_procedure_store,
)

AS_OF = date(2026, 10, 4)
NOW = datetime(2026, 10, 4, 1, 2, 3, 654321, tzinfo=timezone.utc)


def record(**changes):
    return ReviewedProcedureRecord.model_validate({
        "record_id": "SYNTHETIC_CLOSURE",
        "title": "합성 절차",
        "authority_name": "합성 기관",
        "canonical_url": "https://example.go.kr/closure",
        "source_domain": "example.go.kr",
        "excerpt": "테스트 전용 발췌",
        "content_hash": "sha256:" + "a" * 64,
        "published_at": NOW,
        "retrieved_at": NOW,
        "reviewed_by": "synthetic-reviewer",
        "reviewed_at": NOW,
        "review_valid_days": 90,
        "step_codes": ["FILE_TAX_BUSINESS_CLOSURE"],
        "required_terms": ["폐업"],
        "any_terms": [],
        **changes,
    })


def store(*records, version="synthetic/1"):
    return InMemoryReviewedProcedureStore(version, records or (record(),))


@pytest.fixture
def writes(monkeypatch):
    rows = []
    monkeypatch.setattr(case_crud, "get_case_by_id", lambda *_: object())
    monkeypatch.setattr(
        evidence_crud, "get_evidence_by_case_id",
        lambda _, case_id: [row for row in rows if row.case_id == case_id],
    )
    writer = MagicMock(side_effect=lambda _, row: rows.append(row) or row)
    monkeypatch.setattr(evidence_crud, "create_evidence", writer)
    return rows, writer


def test_preserves_source_and_normalizes_time_without_committing(writes):
    session = MagicMock(spec=Session)
    row, = import_reviewed_procedures(session, 1, store(), as_of=AS_OF)
    assert row.source_ref == "https://example.go.kr/closure"
    assert row.locator == row.source_ref
    assert row.excerpt == "테스트 전용 발췌"
    assert row.source_version == "synthetic/1"
    assert row.source_type == "OFFICIAL_DOCUMENT"
    assert row.content_hash == "a" * 64
    assert row.freshness_status == "CURRENT"
    assert row.retrieved_at.isoformat() == "2026-10-04T10:02:03"
    assert row.published_at == row.retrieved_at
    assert len(row.evidence_id) <= Evidence.__table__.c.evidence_id.type.length
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


def test_same_case_repeat_skips_but_other_cases_and_versions_get_distinct_ids(writes):
    session = MagicMock(spec=Session)
    first, = import_reviewed_procedures(session, 1, store(), as_of=AS_OF)
    again, = import_reviewed_procedures(session, 1, store(), as_of=AS_OF)
    other_case, = import_reviewed_procedures(session, 2, store(), as_of=AS_OF)
    other_version, = import_reviewed_procedures(
        session, 1, store(version="synthetic/2"), as_of=AS_OF
    )
    assert again is first
    assert len({first.evidence_id, other_case.evidence_id, other_version.evidence_id}) == 3
    assert writes[1].call_count == 3


@pytest.mark.parametrize("changes", [
    {"reviewed_by": None, "reviewed_at": None},
    {"canonical_url": "https://example.go.kr/" + "a" * 255},
])
def test_invalid_second_record_does_not_partially_write(writes, changes):
    bad = record(record_id="SECOND", **changes)
    with pytest.raises(ProcedureStoreError):
        import_reviewed_procedures(
            MagicMock(spec=Session), 1, store(record(), bad), as_of=AS_OF
        )
    writes[1].assert_not_called()


def test_long_version_is_rejected_before_write(writes):
    with pytest.raises(ProcedureStoreError, match="source_version"):
        import_reviewed_procedures(
            MagicMock(spec=Session), 1, store(version="a" * 101), as_of=AS_OF
        )
    writes[1].assert_not_called()


def test_existing_id_conflict_is_checked_before_any_new_write(writes):
    session = MagicMock(spec=Session)
    import_reviewed_procedures(session, 1, store(), as_of=AS_OF)
    writes[1].reset_mock()
    with pytest.raises(ProcedureStoreError, match="다른 내용"):
        import_reviewed_procedures(
            session, 1,
            store(record(record_id="NEW"), record(excerpt="승인 원문 변경")),
            as_of=AS_OF,
        )
    writes[1].assert_not_called()


def test_missing_case_is_rejected(writes, monkeypatch):
    monkeypatch.setattr(case_crud, "get_case_by_id", lambda *_: None)
    with pytest.raises(ProcedureStoreError, match="Case"):
        import_reviewed_procedures(MagicMock(spec=Session), 1, store(), as_of=AS_OF)
    writes[1].assert_not_called()


def test_expired_approval_remains_stale(writes):
    row, = import_reviewed_procedures(
        MagicMock(spec=Session), 1, store(), as_of=date(2027, 2, 1)
    )
    assert row.freshness_status == "STALE"


def test_duplicate_record_id_is_rejected_before_write(writes):
    with pytest.raises(ProcedureStoreError, match="중복"):
        import_reviewed_procedures(
            MagicMock(spec=Session), 1, store(record(), record()), as_of=AS_OF
        )
    writes[1].assert_not_called()


@pytest.fixture
def db_sources():
    snapshots, known, bindings = {}, [], {}
    for index, logical in enumerate(
        ("FILE_TAX_BUSINESS_CLOSURE", "CONFIRM_RESTORATION_SCOPE"), start=11,
    ):
        ref = ProcedureStepRef(procedure_step_id=index, step_code=f"BE_STEP_{index}")
        known.append(KnownProcedureStep(
            procedure_step=ref, step_name="합성 절차", utterance_aliases=[],
            registry_version="synthetic/1", applicable_business_type="CAFE",
            deprecated_at=None, dependencies=[], eligibility_conditions=[],
        ))
        bindings[logical] = ref
        snapshots[ref.step_code] = {
            "snapshot_version": "synthetic/1", "generated_at": NOW.isoformat(),
            "locale": "ko-KR", "records": [record(
                record_id=f"SOURCE_{index}", step_codes=[logical],
                canonical_url=f"https://example.go.kr/source-{index}",
            ).model_dump(mode="json")],
        }
    return snapshots, {"known_procedure_steps": known, "procedure_bindings": bindings}


def test_db_values_preserve_records_and_use_explicit_bindings_without_io(
    db_sources, monkeypatch,
):
    snapshots, kwargs = db_sources
    forbidden = MagicMock(side_effect=AssertionError("Adapter must not perform IO"))
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Session, "exec", forbidden)
    result = build_reviewed_procedure_store(snapshots, **kwargs)
    assert result.snapshot_version == "synthetic/1"
    assert [item.model_dump(mode="json") for item in result.records()] == [
        payload["records"][0] for payload in snapshots.values()
    ]
    assert all(item.matches("폐업 절차") for item in result.records())
    forbidden.assert_not_called()


def test_db_values_reject_binding_id_absent_from_registry(db_sources):
    snapshots, kwargs = db_sources
    kwargs["procedure_bindings"]["FILE_TAX_BUSINESS_CLOSURE"] = ProcedureStepRef(
        procedure_step_id=999, step_code="BE_STEP_11",
    )
    with pytest.raises(ValueError, match="unknown id\\+code"):
        build_reviewed_procedure_store(snapshots, **kwargs)


def test_db_values_reject_document_stored_under_unrelated_step(db_sources):
    snapshots, kwargs = db_sources
    snapshots["BE_STEP_12"] = snapshots.pop("BE_STEP_11")
    with pytest.raises(ProcedureStoreError, match="절차 대응"):
        build_reviewed_procedure_store(snapshots, **kwargs)


@pytest.mark.parametrize("bindings", [None, {}])
def test_db_values_require_binding_when_be_codes_differ(db_sources, bindings):
    snapshots, kwargs = db_sources
    kwargs["procedure_bindings"] = bindings
    with pytest.raises(ProcedureStoreError, match="대응값"):
        build_reviewed_procedure_store(snapshots, **kwargs)


@pytest.mark.parametrize("empty_records", [False, True])
def test_db_values_reject_missing_data(db_sources, empty_records):
    snapshots, kwargs = db_sources
    if empty_records:
        snapshots["BE_STEP_11"]["records"] = []
    else:
        snapshots = {}
    with pytest.raises(ProcedureStoreError):
        build_reviewed_procedure_store(snapshots, **kwargs)


@pytest.mark.parametrize("field,value", [
    ("snapshot_version", "synthetic/2"),
    ("generated_at", "2026-10-05T00:00:00Z"),
    ("locale", "en-US"),
])
def test_db_values_reject_mixed_snapshot_metadata(db_sources, field, value):
    snapshots, kwargs = db_sources
    snapshots["BE_STEP_12"][field] = value
    with pytest.raises(ProcedureStoreError, match="버전·생성 시각·언어"):
        build_reviewed_procedure_store(snapshots, **kwargs)


@pytest.mark.parametrize("field", ["record_id", "canonical_url"])
def test_db_values_reject_duplicate_documents_across_rows(db_sources, field):
    snapshots, kwargs = db_sources
    snapshots["BE_STEP_12"]["records"][0][field] = (
        snapshots["BE_STEP_11"]["records"][0][field]
    )
    with pytest.raises(ProcedureStoreError):
        build_reviewed_procedure_store(snapshots, **kwargs)


def test_db_values_require_approval_but_preserve_expired_records(db_sources):
    snapshots, kwargs = db_sources
    result = build_reviewed_procedure_store(snapshots, **kwargs)
    assert all(item.freshness(date(2027, 2, 1)) == "STALE" for item in result.records())
    snapshots["BE_STEP_11"]["records"][0].update(reviewed_by=None, reviewed_at=None)
    with pytest.raises(ProcedureStoreError, match="검수·승인"):
        build_reviewed_procedure_store(snapshots, **kwargs)
