import asyncio
import json
from copy import deepcopy

import pytest
from app.agent.info_agent.agent import InfoAnalysisAgent
from app.agent.review_tool import ReviewIntegrityError
from app.agent.schemas import ConflictOutcome, ReviewSubject
from app.common.agent_service import build_conflict_input
from pydantic import ValidationError
from test_action_codes import NOW
from test_info_replanning import Responses, finding, output
from test_procedure_only_graph import graph_run_inputs


def run_until_conflict(*, held=False):
    graph, request, _, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    lines = ["자가가 아니라 무상 임차예요.", "폐업 예정일은 2026-12-20입니다.",
             "사업자 폐업신고 서류를 제출했어요."]
    request.trigger.input.redacted_text = " ".join(lines)
    first = output([finding("FILE_TAX_BUSINESS_CLOSURE", "doc1")])
    first["facts"] = [{
        "operation": "SET", "field_path": field, "value_type": kind, "value": value,
        "source_text": text, "confidence_bps": 9500, "requires_confirmation": held and index == 1,
        "reason_summary": "합성 사용자 진술",
    } for index, (field, kind, value, text) in enumerate([
        ("lease_status", "ENUM", "LEASED_FREE", lines[0]),
        ("planned_closure_date", "DATE", "2026-12-20", lines[1]),
    ])]
    first["procedure_observations"] = [{
        "step_code": "FILE_TAX_BUSINESS_CLOSURE", "observed_status": "IN_PROGRESS",
        "source_text": lines[2], "requires_confirmation": False,
        "requirements_confirmed": False, "submitted": True, "reason_summary": "사용자의 제출 보고",
    }]
    client = Responses(first, output([finding("FILE_TAX_BUSINESS_CLOSURE", "doc1")]))
    graph._info_agent = InfoAnalysisAgent(client, clock=lambda: NOW, max_local_attempts=1)
    original = request.model_dump_json()
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "CONFLICT", outcome
    assert request.model_dump_json() == original
    restored = ConflictOutcome.model_validate_json(outcome.model_dump_json())
    assert restored.retained_info_result.output.procedure_findings == []
    assert restored.retained_info_result.output.conflicts == []
    return graph, restored, client


def confirm(outcome, accepted=True):
    return build_conflict_input(
        case_snapshot=outcome.conflict_snapshot.model_copy(deep=True),
        conflicts=outcome.conflicts, conflict_snapshot=outcome.conflict_snapshot,
        retained_info_result=outcome.retained_info_result,
        selections=[{"conflict_ref": c.conflict_ref, "accepted": accepted} for c in outcome.conflicts],
        input_event_id="owner-confirmation", confirmed_at=NOW,
    )


@pytest.mark.parametrize("accepted", [True, False])
def test_confirmed_or_rejected_conflict_keeps_other_facts_and_progress_after_json_storage(accepted):
    graph, saved, client = run_until_conflict()
    request = confirm(saved, accepted)
    before = request.model_dump_json()
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    changes = {c.field_path: c for c in outcome.review_subject.supervisor_draft.mutations.fact_changes}
    assert changes["planned_closure_date"].model_dump(mode="json")["proposed_value"] == "2026-12-20"
    assert ("lease_status" in changes) is accepted
    progress, = outcome.review_subject.supervisor_draft.mutations.procedure_progress_changes
    assert progress.proposed_status == "IN_PROGRESS" and progress.proposed_submitted
    assert request.model_dump_json() == before
    assert len(client.messages) == 2
    assert json.loads(client.messages[-1][1]["content"].removeprefix("INPUT_JSON="))["input"] is None


def test_uncertain_retained_fact_is_not_saved():
    graph, saved, _ = run_until_conflict(held=True)
    outcome = asyncio.run(graph.run(confirm(saved)))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    assert all(c.field_path != "planned_closure_date"
               for c in outcome.review_subject.supervisor_draft.mutations.fact_changes)


@pytest.mark.parametrize("change", ["digest", "case", "conflicted_field", "missing_evidence", "stale"])
def test_retained_input_rejects_tampering_and_stale_state(change):
    graph, saved, _ = run_until_conflict()
    if change == "digest":
        data = saved.model_dump(mode="json")
        data["retained_info_result"]["output"]["fact_candidates"][0]["value"] = "2026-12-21"
        with pytest.raises(ValidationError):
            ConflictOutcome.model_validate(data)
        return
    if change == "case":
        saved.retained_info_result.meta.case_id = 999
        with pytest.raises(ValidationError):
            confirm(saved)
        return
    if change == "conflicted_field":
        with pytest.raises((ValidationError, ValueError)):
            saved.conflicts[0].field_path = "planned_closure_date"
        return
    request = confirm(saved)
    if change == "missing_evidence":
        ref = saved.retained_info_result.output.fact_candidates[0].source_evidence_refs[0]
        request.case_snapshot.evidence_records = [e for e in request.case_snapshot.evidence_records if e.evidence_id != ref]
    else:
        request.case_snapshot.active_blocker_candidate_ids = ["changed-after-conflict"]
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "SAFE_FAILURE"
    assert outcome.failure_code == "STALE_CONFLICT_CONFIRMATION"


@pytest.mark.parametrize("forgery", ["changed", "omitted", "fresh_progress"])
def test_review_rejects_a_model_pass_for_altered_retained_changes(forgery):
    graph, saved, _ = run_until_conflict()
    outcome = asyncio.run(graph.run(confirm(saved)))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    subject = outcome.review_subject
    draft = deepcopy(subject.supervisor_draft)
    retained = next(c for c in draft.mutations.fact_changes if c.field_path == "planned_closure_date")
    if forgery == "changed":
        retained.proposed_value = "2026-12-21"
    elif forgery == "omitted":
        draft.mutations.fact_changes.remove(retained)
    else:
        draft.mutations.procedure_progress_changes[0].proposed_submitted = False
    bad = ReviewSubject.create(**{
        **subject.model_dump(exclude={"subject_digest", "supervisor_draft"}), "supervisor_draft": draft,
    })
    with pytest.raises(ReviewIntegrityError):
        asyncio.run(graph._review_tool.review(bad))


def test_document_clause_that_differs_from_a_confirmed_fact_goes_to_conflict():
    # #137: 서류로 확인한 원상복구 조항이 이미 확정된 사실과 다르면 덮어쓰지 않고 사장님 확인(CONFLICT)으로 간다.
    from uuid import UUID

    from app.agent.document_tool.models import (
        DocumentAnalysis, DocumentContext, DocumentKind, DocumentRecord, ExtractedField, document_input_text,
    )

    graph, request, _, _, _ = graph_run_inputs("DOCUMENT_SUBMITTED")
    lease = next(fact for fact in request.case_snapshot.facts if fact.field_path == "lease_status")
    request.case_snapshot.facts.append(lease.model_copy(update={
        "field_path": "restoration_scope", "value": "FULL",
    }))
    clause = "원상복구 범위는 카운터·싱크대 부분이다."
    request.trigger.input.redacted_text = document_input_text(DocumentContext(documents=[DocumentRecord(
        document_id=UUID(int=137), filename="lease.pdf", content_hash="h", redaction_count=0,
        cache_key="c", artifact_hash="a", confirmed_fields={"restoration_clause": clause},
        analysis=DocumentAnalysis(kind=DocumentKind.LEASE, needs_confirmation=True, fields=[
            ExtractedField(name="restoration_clause", value=clause, page=1, quote=clause)]),
    )]))
    first = output([finding("FILE_TAX_BUSINESS_CLOSURE", "doc1")])
    first["facts"] = [{
        "operation": "SET", "field_path": "restoration_scope", "value_type": "ENUM", "value": "PARTIAL",
        "source_text": clause, "confidence_bps": 9500, "requires_confirmation": False,
        "reason_summary": "사장님이 확인한 서류 조항",
    }]
    graph._info_agent = InfoAnalysisAgent(
        Responses(first, output([finding("FILE_TAX_BUSINESS_CLOSURE", "doc1")])),
        clock=lambda: NOW, max_local_attempts=1,
    )
    original = request.model_dump_json()

    outcome = asyncio.run(graph.run(request))

    assert outcome.outcome_type == "CONFLICT", outcome
    assert [item.field_path for item in outcome.conflicts] == ["restoration_scope"]
    assert request.model_dump_json() == original  # 확정 사실을 바로 바꾸지 않는다
