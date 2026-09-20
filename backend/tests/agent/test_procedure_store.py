from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from app.agent.guardrails import GuardrailViolation
from app.agent.procedure_tool import (
    DEFAULT_SNAPSHOT_PATH,
    JsonFileProcedureStore,
    ProcedureLookupInputError,
    ProcedureStoreError,
    ReviewedProcedureRecord,
    ReviewedProcedureSnapshot,
    StoredProcedureLookupTool,
)
from app.agent.schemas import ProcedureLookupInput
from pydantic import ValidationError

NOW = datetime(2026, 9, 19, 3, 30, tzinfo=timezone.utc)
AS_OF = date(2026, 9, 19)
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000801")
HASH = "sha256:" + "a" * 64
OTHER_HASH = "sha256:" + "b" * 64


def uuids(count: int = 12):
    values = iter(
        UUID(f"00000000-0000-4000-8000-0000000009{index:02d}") for index in range(count)
    )
    return lambda: next(values)


def record(**updates: Any) -> ReviewedProcedureRecord:
    values: dict[str, Any] = {
        "record_id": "TAX_BUSINESS_CLOSURE",
        "title": "휴업·폐업신고 안내",
        "authority_name": "찾기쉬운 생활법령정보",
        "canonical_url": "https://www.easylaw.go.kr/CSP/CnpClsMain.laf?csmSeq=25",
        "source_domain": "www.easylaw.go.kr",
        "excerpt": "폐업신고서를 관할 세무서장에게 제출해야 합니다.",
        "content_hash": HASH,
        "published_at": None,
        "retrieved_at": NOW,
        "reviewed_by": None,
        "reviewed_at": None,
        "review_valid_days": 90,
        "step_codes": ["FILE_TAX_BUSINESS_CLOSURE"],
        "required_terms": ["폐업"],
        "any_terms": ["사업자", "국세청"],
    }
    values.update(updates)
    return ReviewedProcedureRecord(**values)


def snapshot(*records: ReviewedProcedureRecord) -> ReviewedProcedureSnapshot:
    return ReviewedProcedureSnapshot(
        snapshot_version="reviewed-procedures/test",
        generated_at=NOW,
        locale="ko-KR",
        records=list(records or (record(),)),
    )


def lookup_request(
    *,
    queries: list[str] | None = None,
    max_results: int = 5,
) -> ProcedureLookupInput:
    return ProcedureLookupInput(
        lookup_goal="BUSINESS_CLOSURE",
        search_queries=queries or ["사업자 폐업 신고 절차 국세청"],
        as_of=AS_OF,
        locale="ko-KR",
        source_policy="OFFICIAL_ONLY",
        max_results_per_query=max_results,
        based_on_snapshot_id=SNAPSHOT_ID,
        review_feedback=[],
    )


def tool(store_snapshot: ReviewedProcedureSnapshot | None = None):
    return StoredProcedureLookupTool(
        JsonFileProcedureStore(store_snapshot or snapshot()),
        clock=lambda: NOW,
        uuid_factory=uuids(),
    )


def test_reviewed_record_reads_unknown_until_a_person_approves_it() -> None:
    assert record().freshness(AS_OF).value == "UNKNOWN"


def test_reviewed_record_reads_current_inside_its_review_window() -> None:
    approved = record(reviewed_by="AI 리드", reviewed_at=NOW, review_valid_days=30)

    assert approved.freshness(AS_OF).value == "CURRENT"
    assert approved.freshness(AS_OF + timedelta(days=31)).value == "STALE"


def test_reviewed_record_requires_reviewer_and_review_time_together() -> None:
    with pytest.raises(ValidationError):
        record(reviewed_by="AI 리드", reviewed_at=None)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.easylaw.go.kr/CSP/x.laf",
        "https://www.easylaw.go.kr:8443/CSP/x.laf",
        "https://203.0.113.10/CSP/x.laf",
        "https://user:pw@www.easylaw.go.kr/CSP/x.laf",
        "https://www.easylaw.go.kr/CSP/x.laf#frag",
    ],
)
def test_reviewed_record_rejects_unsafe_source_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        record(canonical_url=url)


def test_snapshot_rejects_two_records_for_one_url() -> None:
    with pytest.raises(ValidationError):
        snapshot(record(), record(record_id="DUPLICATE"))


def test_store_rejects_a_snapshot_that_fails_its_contract(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"records": []}), encoding="utf-8")

    with pytest.raises(ProcedureStoreError):
        JsonFileProcedureStore.from_path(broken)


def test_store_reports_a_missing_snapshot_instead_of_serving_nothing(
    tmp_path: Path,
) -> None:
    with pytest.raises(ProcedureStoreError):
        JsonFileProcedureStore.from_path(tmp_path / "absent.json")


def test_lookup_serves_the_reviewed_document_without_any_search_provider() -> None:
    result = asyncio.run(tool().lookup(lookup_request()))

    assert result.completion_status.value == "COMPLETE"
    assert len(result.documents) == 1
    document = result.documents[0]
    assert document.discovery_provider.value == "REVIEWED_PROCEDURE_STORE"
    assert document.canonical_url.startswith("https://www.easylaw.go.kr/")
    assert result.search_summary.provider_order == [
        document.discovery_provider,
    ]
    assert result.search_summary.fallback_query_count == 0


def test_lookup_keeps_the_query_that_found_the_document() -> None:
    # Info binds a document to a canonical step through search_query, so the
    # query that matched has to survive into the result.
    query = "4대보험 탈퇴 사업장 폐업 신고 절차"
    insurance = record(
        record_id="WORKPLACE_INSURANCE_CLOSURE",
        canonical_url="https://www.nps.or.kr/pnsinfo/x.do?menuId=MN24001107",
        source_domain="www.nps.or.kr",
        content_hash=OTHER_HASH,
        step_codes=["REPORT_WORKPLACE_INSURANCE_CLOSURE"],
        any_terms=["4대보험", "사업장"],
    )
    result = asyncio.run(
        tool(snapshot(record(), insurance)).lookup(
            lookup_request(queries=["사업자 폐업 신고 절차 국세청", query]),
        )
    )

    by_domain = {item.source_domain: item.search_query for item in result.documents}
    assert by_domain["www.nps.or.kr"] == query
    assert by_domain["www.easylaw.go.kr"] == "사업자 폐업 신고 절차 국세청"


def test_lookup_carries_the_records_review_state_into_evidence() -> None:
    approved = record(reviewed_by="AI 리드", reviewed_at=NOW, review_valid_days=30)
    result = asyncio.run(tool(snapshot(approved)).lookup(lookup_request()))

    assert result.documents[0].freshness_status.value == "CURRENT"
    assert result.evidence_records[0].freshness_status.value == "CURRENT"
    assert result.evidence_records[0].source_type.value == "OFFICIAL_DOCUMENT"
    assert result.evidence_records[0].source_ref == result.documents[0].canonical_url


def test_lookup_warns_that_an_unreviewed_document_was_served() -> None:
    result = asyncio.run(tool().lookup(lookup_request()))

    assert "UNREVIEWED_PROCEDURE_SOURCE" in {item.code for item in result.warnings}


def test_lookup_warns_when_a_review_has_expired() -> None:
    expired = record(
        reviewed_by="AI 리드",
        reviewed_at=NOW - timedelta(days=400),
        review_valid_days=30,
    )
    result = asyncio.run(tool(snapshot(expired)).lookup(lookup_request()))

    assert result.documents[0].freshness_status.value == "STALE"
    assert "STALE_PROCEDURE_REVIEW" in {item.code for item in result.warnings}


def test_lookup_returns_no_results_rather_than_inventing_a_document() -> None:
    result = asyncio.run(
        tool().lookup(lookup_request(queries=["전혀 관련 없는 조회어"]))
    )

    assert result.completion_status.value == "NO_RESULTS"
    assert result.documents == []
    assert result.evidence_records == []
    assert "NO_OFFICIAL_RESULTS" in {item.code for item in result.warnings}


def test_lookup_serves_one_document_per_url_when_two_queries_match_it() -> None:
    result = asyncio.run(
        tool().lookup(
            lookup_request(
                queries=["사업자 폐업 신고 절차 국세청", "개인사업자 폐업 국세청 절차"],
            )
        )
    )

    assert len(result.documents) == 1


def test_lookup_honours_the_per_query_result_limit() -> None:
    second = record(
        record_id="SECOND_SOURCE",
        canonical_url="https://www.easylaw.go.kr/CSP/other.laf?csmSeq=706",
        content_hash=OTHER_HASH,
        step_codes=["FILE_FOOD_SERVICE_CLOSURE"],
    )
    result = asyncio.run(
        tool(snapshot(record(), second)).lookup(lookup_request(max_results=1))
    )

    assert len(result.documents) == 1


def test_lookup_refuses_a_query_carrying_personal_identifiers() -> None:
    # Same refusal the live tool gives, from the same shared guardrail: the two
    # sources must not differ in what a caller is allowed to ask for.
    with pytest.raises(GuardrailViolation):
        asyncio.run(
            tool().lookup(lookup_request(queries=["폐업 국세청 880101-1234567"]))
        )


def test_lookup_refuses_an_over_long_query() -> None:
    with pytest.raises(ProcedureLookupInputError):
        asyncio.run(
            tool().lookup(lookup_request(queries=["폐업 국세청 " + "가" * 300]))
        )


def test_shipped_snapshot_loads_and_is_not_yet_approved() -> None:
    # The snapshot that ships with the package is a fetch nobody has read yet.
    # It must stay UNKNOWN, which is what keeps Review from letting a claim
    # built on it go out as settled fact.
    store = JsonFileProcedureStore.from_path(DEFAULT_SNAPSHOT_PATH)

    assert store.records()
    for item in store.records():
        assert item.freshness(AS_OF).value == "UNKNOWN", item.record_id
