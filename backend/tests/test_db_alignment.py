"""Agent values must fit the DB columns in docs/schema/schema_table.md.

The agent produces the strings that BE writes into MySQL, so every limit here
mirrors one column in backend/app/be/models/. Failing in the agent is the
point: a value that is too long must be rejected while it can still be retried,
not silently truncated at INSERT time. Synthetic data only.
"""

import asyncio
import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from app.agent.procedure_tool.rules import procedure_constraints
from app.agent.schemas import Blocker, CaseSnapshot, EvidenceRecord, KnownProcedureStep
from app.agent.support_agent.agent import SupportAgent
from app.agent.support_agent.models import ReviewedSupportCatalog
from pydantic import ValidationError

NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)
REF = "synthetic-document"
HASH = hashlib.sha256(b"synthetic").hexdigest()


def evidence(**changes):
    return EvidenceRecord.model_validate(
        {
            "evidence_id": REF,
            "source_type": "OFFICIAL_DOCUMENT",
            "source_ref": "https://example.org/synthetic",
            "source_version": None,
            "locator": None,
            "excerpt": "합성 테스트 자료입니다.",
            "parent_evidence_refs": [],
            "published_at": None,
            "retrieved_at": NOW,
            "freshness_status": "CURRENT",
            "content_hash": HASH,
        }
        | changes
    )


def snapshot(business_type="카페"):
    fields = [
        ("business_type", "STRING", business_type),
        ("franchise_status", "BOOLEAN", False),
        ("lease_status", "ENUM", "LEASED_PAID"),
    ]
    return CaseSnapshot.model_validate(
        {
            "snapshot_id": UUID(int=1),
            "case_id": 1,
            "case_status": "IN_PROGRESS",
            "facts": [
                {
                    "field_path": name,
                    "value_type": kind,
                    "value": value,
                    "status": "CONFIRMED",
                    "evidence_refs": [REF],
                    "updated_at": NOW,
                }
                for name, kind, value in fields
            ],
            "procedure_progress": [],
            "evidence_records": [evidence()],
            "captured_at": NOW,
        }
    )


def step(applicable_business_type):
    return KnownProcedureStep.model_validate(
        {
            "procedure_step": {
                "procedure_step_id": 1,
                "step_code": "FILE_FOOD_SERVICE_CLOSURE",
            },
            "step_name": "합성 절차",
            "utterance_aliases": [],
            "registry_version": "synthetic/1",
            "applicable_business_type": applicable_business_type,
            "deprecated_at": None,
            "dependencies": [],
            "eligibility_conditions": [],
        }
    )


BUSINESS_TYPE_REASON = "applicable_business_type is not confirmed for this Case"


# 1. EVIDENCE.content_hash is VARCHAR(64); a bare sha-256 hex digest is exactly 64.
def test_evidence_content_hash_fits_its_column():
    assert len(evidence().content_hash) <= 64
    with pytest.raises(ValidationError):
        evidence(content_hash="sha256:" + HASH)


# 2. SUPPORT_ITEM/SUPPORT_MATCH.catalog_version is VARCHAR(50).
def test_wiki_catalog_version_fits_its_column():
    source = ReviewedSupportCatalog.model_validate(
        {
            "catalog_version": "reviewed-support/2026-09-28 reviewed_by=Roka-jsj",
            "programs": [
                {
                    "support_program": {"support_program_id": 1, "wiki_uuid": UUID(int=2)},
                    "program_name": "합성 지원사업",
                    "related_steps": [],
                    "criteria": [
                        {
                            "criterion_code": "LEASE",
                            "field_path": "lease_status",
                            "operator": "EQ",
                            "required_values": ["LEASED_PAID"],
                            "evidence_refs": [REF],
                        }
                    ],
                    "required_documents": [],
                    "application_channel": None,
                    "application_url": None,
                    "application_period": None,
                    "source_version": None,
                    "freshness_status": "CURRENT",
                    "evidence_refs": [REF],
                }
            ],
            "evidence_records": [evidence()],
        }
    )

    class StubWiki:
        async def lookup(self, ref):
            return source

    agent = SupportAgent(None, source, wiki_store=StubWiki())
    merged, hit, missing = asyncio.run(agent._resolve_wiki(None, source))
    assert (hit, missing) == ("HIT", [])
    assert len(merged.catalog_version) <= 50

    with pytest.raises(ValidationError):
        source.model_copy(update={"catalog_version": "wiki:" + HASH}).model_validate(
            source.model_dump(mode="python") | {"catalog_version": "wiki:" + HASH}
        )


# 3. CASE.business_type holds what the user typed ("카페"); PROCEDURE_STEP
#    .applicable_business_type holds a code (ALL/CAFE). They must be compared
#    after converting, or every business-specific procedure is filtered out.
@pytest.mark.parametrize("business_type", ["카페", "휴게음식점", "CAFE"])
def test_korean_business_type_matches_the_procedure_business_code(business_type):
    reasons = procedure_constraints(step("CAFE"), snapshot(business_type))
    assert BUSINESS_TYPE_REASON not in reasons


@pytest.mark.parametrize("business_type", ["식당", "일반음식점"])
def test_other_business_type_still_filters_the_cafe_procedure(business_type):
    reasons = procedure_constraints(step("CAFE"), snapshot(business_type))
    assert BUSINESS_TYPE_REASON in reasons


def test_all_applies_to_every_business_type():
    assert procedure_constraints(step("ALL"), snapshot("카페")) == []


# 4. BLOCKER.description is VARCHAR(500).
def test_blocker_description_fits_its_column():
    assert Blocker(description="가" * 500, evidence_refs=[REF]).description
    with pytest.raises(ValidationError):
        Blocker(description="가" * 501, evidence_refs=[REF])


# 5. The remaining columns the agent writes into, same rule.
@pytest.mark.parametrize(
    "field,limit",
    [("evidence_id", 100), ("source_ref", 500), ("source_version", 100), ("locator", 255)],
)
def test_evidence_text_fits_its_column(field, limit):
    assert evidence(**{field: "a" * limit})
    with pytest.raises(ValidationError):
        evidence(**{field: "a" * (limit + 1)})
