"""DB evidence is required, preserved and checked against reviewed metadata."""

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.agent.info_agent.agent import InfoAnalysisAgent
from app.agent.procedure_tool.store import ReviewedProcedureRecord
from app.agent.procedure_tool.stored_tool import (
    ProcedureLookupInputError,
    StoredProcedureLookupTool,
)
from app.agent.review_tool import ReviewTool
from app.agent.schemas import (
    CaseFieldKey,
    EvidenceRecord,
    InfoAnalysisInput,
    ProcedureLookupInput,
    ProcedureStepRef,
    ReviewSubject,
)
from app.agent.supervisor import SupervisorAgent
from test_action_codes import StubModel, source, supervisor_request
from test_info_replanning import Responses, finding, output

NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


def lookup(*, evidence_changes=None, record_changes=None, missing=False, as_of=None,
           procedure_bindings=None, after_init=None):
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
    original = record.model_dump()
    tool = StoredProcedureLookupTool(store, procedure_bindings=procedure_bindings)
    if after_init:
        after_init()
    result = asyncio.run(tool.lookup(request))
    assert record.model_dump() == original
    return result, evidence


def test_returns_the_db_evidence_unchanged_and_deduplicates_queries():
    result, evidence = lookup()
    assert result.evidence_records == [evidence]
    assert result.evidence_records[0] is not evidence
    assert result.documents[0].evidence_ref == evidence.evidence_id
    assert len(result.documents) == 1
    assert result.warnings == []


@pytest.mark.parametrize("bindings,expected", [
    (None, ["FILE_TAX_BUSINESS_CLOSURE", "FILE_FOOD_SERVICE_CLOSURE"]),
    ({}, []),
    ({"FILE_TAX_BUSINESS_CLOSURE": "SYNTHETIC_BE_TAX"}, ["SYNTHETIC_BE_TAX"]),
    # The unmapped logical FOOD code must not survive as a second physical code.
    ({"FILE_TAX_BUSINESS_CLOSURE": "FILE_FOOD_SERVICE_CLOSURE"},
     ["FILE_FOOD_SERVICE_CLOSURE"]),
])
def test_only_explicit_bindings_translate_document_codes(bindings, expected):
    refs = None if bindings is None else {
        logical: ProcedureStepRef(procedure_step_id=1, step_code=physical)
        for logical, physical in bindings.items()
    }
    result, evidence = lookup(
        procedure_bindings=refs,
        record_changes={"step_codes": [
            "FILE_TAX_BUSINESS_CLOSURE", "FILE_FOOD_SERVICE_CLOSURE",
        ]},
    )
    assert result.documents[0].step_codes == expected
    assert result.evidence_records == [evidence]
    assert result.documents[0].evidence_ref == evidence.evidence_id


def test_unmapped_document_cannot_match_another_bindings_physical_code():
    result, _ = lookup(
        procedure_bindings={"FILE_TAX_BUSINESS_CLOSURE": ProcedureStepRef(
            procedure_step_id=1, step_code="FILE_FOOD_SERVICE_CLOSURE",
        )},
        record_changes={"step_codes": ["FILE_FOOD_SERVICE_CLOSURE"]},
    )
    assert result.documents[0].step_codes == []


def test_caller_cannot_change_bindings_after_tool_creation():
    ref = ProcedureStepRef(procedure_step_id=1, step_code="SYNTHETIC_BE_TAX")
    bindings = {"FILE_TAX_BUSINESS_CLOSURE": ref}

    def change_binding():
        ref.step_code = "SYNTHETIC_CHANGED"
        bindings.clear()

    result, _ = lookup(procedure_bindings=bindings, after_init=change_binding)
    assert result.documents[0].step_codes == ["SYNTHETIC_BE_TAX"]


def test_mapped_db_evidence_reaches_info_supervisor_and_review():
    request = supervisor_request()
    ref = ProcedureStepRef(procedure_step_id=1, step_code="SYNTHETIC_BE_TAX")
    bindings = {"FILE_TAX_BUSINESS_CLOSURE": ref}
    request.known_procedure_steps[0].procedure_step = ref
    result, evidence = lookup(procedure_bindings=bindings)
    result.based_on_snapshot_id = request.case_snapshot.snapshot_id
    snapshot = request.case_snapshot.model_dump()
    snapshot["evidence_records"] = [evidence]
    for fact in snapshot["facts"]:
        fact["evidence_refs"] = [evidence.evidence_id]
    request.case_snapshot = type(request.case_snapshot).model_validate(snapshot)
    info_request = InfoAnalysisInput(
        input=request.trigger.input, case_snapshot=request.case_snapshot,
        allowed_field_paths=list(CaseFieldKey),
        known_procedure_steps=request.known_procedure_steps,
        source_call_id=UUID(int=3), procedure_lookup_call_id=UUID(int=5),
        procedure_lookup_result=result, review_feedback=[],
    )
    projected = InfoAnalysisAgent._prompt_input(info_request, bindings)
    assert projected["procedure_analysis_step_codes"] == [ref.step_code]
    assert projected["procedure_evidence_by_step"] == {ref.step_code: ["doc1"]}
    item = finding(ref.step_code, "doc1")
    item["summary"]["text"] = evidence.excerpt

    class BoundSupervisorModel(StubModel):
        async def generate(self, model, messages, **kwargs):
            response = await super().generate(model, messages, **kwargs)
            response.next_action.target.procedure_step = ref
            return response

    async def run():
        info = await InfoAnalysisAgent(
            Responses(output([item])), procedure_bindings=bindings,
        ).analyze(info_request)
        assert info.procedure_findings[0].procedure_step == ref
        assert info.procedure_findings[0].evidence_refs == [evidence.evidence_id]
        request.source_results = [source(result, "PROCEDURE_TOOL", 5), source(info)]
        draft = await SupervisorAgent(
            BoundSupervisorModel(), procedure_bindings=bindings, max_local_attempts=1,
        ).draft(request)
        assert draft.decision.next_action.target.procedure_step == ref
        assert draft.decision.next_action.evidence_refs == [evidence.evidence_id]
        subject = ReviewSubject.create(
            schema_version="agent-io/2.0", review_subject_id=UUID(int=9),
            review_attempt=1, run_id=UUID(int=2), case_id=1,
            trigger=request.trigger, snapshot=request.case_snapshot,
            known_procedure_steps=request.known_procedure_steps,
            source_results=request.source_results, supervisor_draft=draft,
        )
        reviewed = await ReviewTool(
            StubModel(), procedure_bindings=bindings,
        ).review(subject)
        assert reviewed.verdict == "PASS", reviewed.issues
        assert result.evidence_records == [evidence]

    asyncio.run(run())


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
