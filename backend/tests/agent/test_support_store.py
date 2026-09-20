"""검수 전 지원사업이 실제 Case와 비교되지 않는지 확인.

기업마당 API가 주는 것은 "소상공인", "예산 소진시까지" 같은 문장이다. 코드가
그걸 자격 규칙으로 바꾸면 누가 대상인지 코드가 정하는 셈이 되고, 그건 이
프로젝트가 하지 않기로 한 일이다(`/CLAUDE.md`). 그래서 발견은 자동이지만
승격은 자동이 아니다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from app.agent.schemas import EvidenceRecord, KnownProcedureStep, ProcedureStepRef
from app.agent.support_agent import (
    DEFAULT_CATALOG_PATH,
    JsonFileSupportStore,
    ReviewedSupportEntry,
    ReviewedSupportSnapshot,
    SupportStoreError,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)
WIKI_ID = UUID("33333333-3333-4333-8333-333333333333")
STEP = KnownProcedureStep(
    procedure_step=ProcedureStepRef(
        procedure_step_id=2, step_code="CHECK_DEMOLITION_SUPPORT"
    ),
    step_name="철거 전 지원조건 확인",
    utterance_aliases=["철거 지원"],
)


def evidence(evidence_id: str = "support:bizinfo:1") -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_type="OFFICIAL_API",
        source_ref="https://www.bizinfo.go.kr/api",
        source_version="v1",
        locator="https://www.bizinfo.go.kr/sii/siia/x.do?pblancId=PBLN_1",
        excerpt="소상공인 대상 폐업 지원",
        parent_evidence_refs=[],
        published_at=None,
        retrieved_at=NOW,
        freshness_status="CURRENT",
        content_hash=None,
    )


def entry(**updates: Any) -> ReviewedSupportEntry:
    values: dict[str, Any] = {
        "support_program_id": 1,
        "wiki_uuid": WIKI_ID,
        "program_name": "2026년 희망리턴패키지 원스톱폐업지원 소상공인 모집 공고",
        "external_notice_id": "PBLN_000000000117676",
        "detail_url": "https://www.bizinfo.go.kr/sii/siia/x.do?pblancId=PBLN_1",
        "discovered_target": "소상공인",
        "discovered_period": "세부사업별 상이",
        "evidence": evidence(),
        "reviewed_by": None,
        "reviewed_at": None,
        "related_step_codes": [],
        "criteria": [],
        "required_documents": [],
        "application_channel": None,
        "application_url": None,
        "application_period": None,
    }
    values.update(updates)
    return ReviewedSupportEntry(**values)


def reviewed_entry(**updates: Any) -> ReviewedSupportEntry:
    return entry(
        reviewed_by="AI 리드",
        reviewed_at=NOW,
        related_step_codes=["CHECK_DEMOLITION_SUPPORT"],
        criteria=[
            {
                "criterion_code": "BUSINESS_TYPE",
                "field_path": "business_type",
                "operator": "EQ",
                "required_values": ["CAFE"],
                "evidence_refs": ["support:bizinfo:1"],
            }
        ],
        **updates,
    )


def snapshot(*entries: ReviewedSupportEntry) -> ReviewedSupportSnapshot:
    return ReviewedSupportSnapshot(
        catalog_version="reviewed-support/test",
        generated_at=NOW,
        entries=list(entries or (entry(),)),
    )


def test_a_discovered_notice_is_not_served_until_someone_reviews_it() -> None:
    catalog, pending = snapshot().build_catalog(known_steps=[STEP])

    assert catalog.programs == ()
    assert pending == 1


def test_a_reviewed_notice_becomes_a_comparable_programme() -> None:
    catalog, pending = snapshot(reviewed_entry()).build_catalog(known_steps=[STEP])

    assert pending == 0
    assert len(catalog.programs) == 1
    program = catalog.programs[0]
    assert program.program_name.startswith("2026년 희망리턴패키지")
    assert program.criteria[0].field_path.value == "business_type"
    assert program.related_steps[0].step_code == "CHECK_DEMOLITION_SUPPORT"
    assert catalog.evidence_records[0].evidence_id == "support:bizinfo:1"


def test_criteria_cannot_be_written_without_a_reviewer() -> None:
    # Rules with nobody's name on them are exactly what must not exist.
    with pytest.raises(ValidationError):
        entry(
            criteria=[
                {
                    "criterion_code": "BUSINESS_TYPE",
                    "field_path": "business_type",
                    "operator": "EQ",
                    "required_values": ["CAFE"],
                    "evidence_refs": ["support:bizinfo:1"],
                }
            ]
        )


def test_a_reviewer_without_rules_is_still_not_served() -> None:
    # Reading a notice and concluding nothing usable is a valid outcome, and it
    # must not put the programme in front of a user.
    read_but_empty = entry(reviewed_by="AI 리드", reviewed_at=NOW)
    catalog, pending = snapshot(read_but_empty).build_catalog(known_steps=[STEP])

    assert catalog.programs == ()
    assert pending == 1


def test_a_reviewer_and_a_review_time_go_together() -> None:
    with pytest.raises(ValidationError):
        entry(reviewed_by="AI 리드", reviewed_at=None)


def test_the_same_notice_cannot_appear_twice() -> None:
    with pytest.raises(ValidationError):
        snapshot(entry(), entry(support_program_id=2, wiki_uuid=UUID(int=9)))


def test_a_broken_catalog_file_is_refused(tmp_path: Path) -> None:
    broken = tmp_path / "catalog.json"
    broken.write_text(json.dumps({"entries": []}), encoding="utf-8")

    with pytest.raises(SupportStoreError):
        JsonFileSupportStore.from_path(broken)


def test_the_shipped_catalog_holds_real_notices_that_await_review() -> None:
    store = JsonFileSupportStore.from_path(DEFAULT_CATALOG_PATH)
    catalog, pending = store.snapshot().build_catalog(known_steps=[STEP])

    assert pending > 0
    # Nothing ships pre-approved: every entry came from the API, not a person.
    assert catalog.programs == ()
    for item in store.snapshot().entries:
        assert item.external_notice_id.startswith("PBLN_")
        assert item.evidence.source_type.value == "OFFICIAL_API"
