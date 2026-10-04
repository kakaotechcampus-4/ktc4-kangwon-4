"""Agent values must match the DB columns in backend/app/be/models/.

The agent produces the strings that BE writes into MySQL, so every limit here
mirrors one column in backend/app/be/models/. Failing in the agent is the
point: a value that is too long must be rejected while it can still be retried,
not silently truncated at INSERT time. Synthetic data only.
"""

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import Text
from test_action_codes import StubModel, action_payload, supervisor_request

from app.agent.procedure_tool.rules import procedure_constraints
from app.agent.schemas import (
    Blocker,
    CaseSnapshot,
    EvidenceRecord,
    KnownProcedureStep,
    NextAction,
    ProcedureLookupResult,
    ProcedureSourceDocument,
)
from app.agent.supervisor.agent import SupervisorAgent
from app.agent.support_agent.agent import SupportAgent
from app.agent.support_agent.models import ReviewedSupportCatalog
from app.be.models.blocker import Blocker as BlockerRow
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import Evidence as EvidenceRow
from scripts.evaluate_planning import CASES, build_case_snapshot

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


@pytest.mark.parametrize("content_hash", [HASH, "sha256:" + HASH])
def test_be_evidence_hash_is_normalized_for_db_and_json(content_hash):
    record = evidence(content_hash=content_hash)
    assert record.content_hash == HASH
    assert record.model_dump(mode="json")["content_hash"] == HASH
    assert EvidenceRecord.model_validate_json(record.model_dump_json()).content_hash == HASH


def test_be_case_snapshot_accepts_prefixed_evidence_hash():
    payload = snapshot().model_dump(mode="json")
    payload["evidence_records"][0]["content_hash"] = "sha256:" + HASH
    case_snapshot = CaseSnapshot.model_validate(payload)
    assert case_snapshot.evidence_records[0].content_hash == HASH
    assert case_snapshot.model_dump(mode="json")["evidence_records"][0]["content_hash"] == HASH


@pytest.mark.parametrize("content_hash", [
    "sha256:" + HASH[:-1],
    "sha256:" + HASH + "0",
    "sha256:sha256:" + HASH,
    "sha256:" + "g" * 64,
    "sha256:" + HASH.upper(),
    123,
])
def test_invalid_prefixed_evidence_hash_is_rejected(content_hash):
    with pytest.raises(ValidationError):
        evidence(content_hash=content_hash)


def test_procedure_document_hash_matches_normalized_evidence_hash():
    record = evidence(content_hash=HASH)
    document = ProcedureSourceDocument.model_validate({
        "document_id": UUID(int=3),
        "authority_name": "합성 공식 기관",
        "canonical_url": record.source_ref,
        "source_domain": "example.org",
        "title": "합성 절차",
        "excerpt": record.excerpt,
        "published_at": None,
        "retrieved_at": NOW,
        "freshness_status": "CURRENT",
        "content_hash": "sha256:" + HASH,
        "evidence_ref": REF,
        "search_query": "합성 절차",
        "step_codes": ["FILE_FOOD_SERVICE_CLOSURE"],
    })
    lookup = ProcedureLookupResult(
        completion_status="COMPLETE",
        lookup_id=UUID(int=4),
        documents=[document],
        warnings=[],
        evidence_records=[record],
        based_on_snapshot_id=UUID(int=1),
        as_of=NOW.date(),
    )
    assert lookup.documents[0].content_hash == lookup.evidence_records[0].content_hash == HASH


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


# 4. BE stores judgment text in TEXT columns, without a 500-character limit.
@pytest.mark.parametrize("model,field,column,values", [
    (Blocker, "description", BlockerRow.__table__.c.description, {"evidence_refs": [REF]}),
    (NextAction, "title", CaseHistory.__table__.c.next_action, action_payload() | {"sequence": 1}),
])
def test_judgment_text_matches_be_text_columns(model, field, column, values):
    assert isinstance(column.type, Text)
    for length in (501, 2000):
        text = "가" * length
        result = model.model_validate(values | {field: text})
        restored = model.model_validate_json(result.model_dump_json())
        assert getattr(restored, field) == text
    assert "maxLength" not in model.model_json_schema()["properties"][field]
    for invalid in ("", None, 123):
        with pytest.raises(ValidationError):
            model.model_validate(values | {field: invalid})


def test_supervisor_does_not_request_obsolete_text_limits():
    class Model(StubModel):
        async def generate(self, model, messages, **kwargs):
            contract = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))["contract"]
            assert "blocker_description_max_characters" not in contract
            assert "next_action_title_max_characters" not in contract
            return await super().generate(model, messages, **kwargs)

    asyncio.run(SupervisorAgent(Model(), max_local_attempts=1).draft(supervisor_request()))


# 5. The remaining columns the agent writes into, same rule, same source.
@pytest.mark.parametrize(
    "field", ["evidence_id", "source_ref", "source_version", "locator"]
)
def test_evidence_text_fits_its_column(field):
    limit = EvidenceRow.__table__.c[field].type.length
    assert evidence(**{field: "a" * limit})
    with pytest.raises(ValidationError):
        evidence(**{field: "a" * (limit + 1)})


def test_intake_snapshot_uses_a_db_compatible_evidence_hash():
    snapshot, text = build_case_snapshot(CASES["benchmark_case1"])

    assert snapshot.evidence_records[0].content_hash == hashlib.sha256(text.encode()).hexdigest()
