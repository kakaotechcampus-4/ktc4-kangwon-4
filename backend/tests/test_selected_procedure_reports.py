"""Explicit user selections, never free-text interpretation, advance progress."""

import asyncio
from datetime import timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_action_codes import NOW, REF, StubModel, source
from test_info_batching import Replies
from test_info_batching import request as cafe_request
from test_info_replanning import Responses, finding, output, request_for_replanning
from test_procedure_only_graph import graph_run_inputs

from app.agent.action_catalog import resolve_procedure_bindings
from app.agent.blocker_candidates import build_blocker_candidates, missing_info_fields
from app.agent.enrichment import build_fact_overlays
from app.agent.info_agent.agent import InfoAnalysisAgent
from app.agent.review_tool import ReviewIntegrityError, ReviewTool
from app.agent.schemas import (
    CaseFact,
    FactCandidate,
    MutationSet,
    ProcedureProgress,
    ProcedureProgressReport,
    RedactedInput,
    ReviewSubject,
    canonical_digest,
)


def selected_plan(status="IN_PROGRESS"):
    graph, request, _, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    request.trigger.input.procedure_reports = [ProcedureProgressReport(
        procedure_step=graph._known_procedure_steps[0].procedure_step, status=status,
    )]
    request.trigger.input.redacted_text = ""
    graph._info_agent = InfoAnalysisAgent(
        Responses(output([finding("FILE_TAX_BUSINESS_CLOSURE", "doc1")])),
        clock=lambda: NOW, max_local_attempts=1,
    )
    before = request.model_dump_json()
    outcome = asyncio.run(graph.run(request))
    assert request.model_dump_json() == before
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    return request, outcome


def test_selection_only_submission_reaches_review_with_original_json_evidence():
    request, outcome = selected_plan()
    subject = outcome.review_subject
    info = next(source.output for source in subject.source_results if source.meta.component == "INFO_AGENT")
    observation, = info.procedure_progress_observations
    assert observation.source_span is None
    assert observation.structured_report == request.trigger.input.procedure_reports[0]
    evidence, = info.evidence_records
    assert evidence.locator == "procedure_reports:0"
    assert evidence.source_ref == request.trigger.input.input_event_id
    assert evidence.retrieved_at == request.trigger.input.submitted_at
    observation.assert_structured_report_integrity(request.trigger.input, {evidence.evidence_id: evidence})
    change, = subject.supervisor_draft.mutations.procedure_progress_changes
    assert change.before_status == "NOT_STARTED" and change.proposed_status == "IN_PROGRESS"


def test_not_started_selection_does_not_create_a_progress_mutation():
    _, outcome = selected_plan("NOT_STARTED")
    assert outcome.review_subject.supervisor_draft.mutations.procedure_progress_changes == []


@pytest.mark.parametrize("invalid", ["empty", "unknown_status", "strict_boolean", "not_started_flags", "duplicate"])
def test_invalid_selected_input_is_rejected_by_the_dto(invalid):
    request, _ = selected_plan()
    payload = request.trigger.input.model_dump(mode="json")
    if invalid == "empty":
        payload["procedure_reports"] = []
    elif invalid == "unknown_status":
        payload["procedure_reports"][0]["status"] = "FINISHED"
    elif invalid == "strict_boolean":
        payload["procedure_reports"][0]["submitted"] = 1
    elif invalid == "not_started_flags":
        payload["procedure_reports"][0].update(status="NOT_STARTED", requirements_confirmed=True)
    else:
        payload["procedure_reports"].append(payload["procedure_reports"][0])
    with pytest.raises(ValidationError):
        RedactedInput.model_validate(payload)


@pytest.mark.parametrize("tamper", ["choice", "event", "excerpt", "locator", "source_ref", "content_hash", "time"])
def test_review_rejects_resealed_choice_or_evidence_changes_before_its_model(tamper):
    _, outcome = selected_plan()
    subject = outcome.review_subject.model_copy(deep=True)
    source = next(source for source in subject.source_results if source.meta.component == "INFO_AGENT")
    if tamper == "choice":
        subject.trigger.input.procedure_reports[0].status = "COMPLETED"
    elif tamper == "event":
        changed = subject.trigger.input.model_copy(update={"input_event_id": "another-event"})
        subject = subject.model_copy(update={
            "trigger": subject.trigger.model_copy(update={"input_event_id": "another-event", "input": changed}),
        })
    else:
        evidence = source.output.evidence_records[0]
        changes = {
            "excerpt": (evidence.excerpt or "") + " ", "locator": "procedure_reports:1",
            "source_ref": "another-event", "content_hash": "1" * 64,
            "time": evidence.retrieved_at + timedelta(seconds=1),
        }
        source.output.evidence_records[0] = evidence.model_copy(update={
            "retrieved_at" if tamper == "time" else tamper: changes[tamper],
        })
    source.output_digest = canonical_digest(source.output)
    forged = ReviewSubject.create(**{
        key: getattr(subject, key) for key in type(subject).model_fields if key != "subject_digest"
    })
    client = StubModel()
    with pytest.raises(ReviewIntegrityError):
        asyncio.run(ReviewTool(client).review(forged))
    assert client.calls == 0


def test_structured_evidence_tolerates_db_second_precision_without_changing_content():
    request, outcome = selected_plan()
    info = next(source.output for source in outcome.review_subject.source_results if source.meta.component == "INFO_AGENT")
    observation, = info.procedure_progress_observations
    evidence, = info.evidence_records
    changed = evidence.model_copy(update={
        "retrieved_at": evidence.retrieved_at.astimezone(timezone(timedelta(hours=9))) + timedelta(microseconds=123456),
    })
    observation.assert_structured_report_integrity(request.trigger.input, {changed.evidence_id: changed})
    assert evidence.retrieved_at == request.trigger.input.submitted_at


def test_legacy_empty_report_serialization_preserves_existing_input_hashes():
    request, _ = selected_plan()
    data = request.trigger.input.model_dump(mode="json")
    data.pop("procedure_reports")
    data["redacted_text"] = "기존 입력"
    original = RedactedInput.model_validate(data)
    assert original.model_dump(mode="json") == data
    assert "procedure_reports" not in original.model_dump_json()


@pytest.mark.parametrize("invalid", ["unregistered_step", "rollback"])
def test_selected_progress_cannot_change_an_unknown_or_completed_step(invalid):
    graph, request, _, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    reference = graph._known_procedure_steps[0].procedure_step
    if invalid == "unregistered_step":
        reference = reference.model_copy(update={"procedure_step_id": 999})
    else:
        request.case_snapshot.procedure_progress = [ProcedureProgress(
            procedure_step=reference, status="COMPLETED",
            evidence_refs=[request.case_snapshot.evidence_records[0].evidence_id], updated_at=NOW,
        )]
    request.trigger.input.procedure_reports = [ProcedureProgressReport(
        procedure_step=reference, status="IN_PROGRESS",
    )]
    graph._info_agent = InfoAnalysisAgent(
        Responses(output([finding("FILE_TAX_BUSINESS_CLOSURE", "doc1")])),
        clock=lambda: NOW, max_local_attempts=1,
    )
    before = request.model_dump_json()
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "SAFE_FAILURE", outcome
    assert outcome.failed_component == "INFO_AGENT"
    assert graph._review_tool._client.calls == 0
    assert request.model_dump_json() == before


def restoration_fact(value="COMPLETED", operation="SET"):
    return {
        "operation": operation, "field_path": "restoration_status", "value_type": "ENUM", "value": value,
        "source_text": "원상복구 작업을 완료했습니다.", "confidence_bps": 10000,
        "requires_confirmation": False, "reason_summary": "합성 사용자 보고",
    }


def test_natural_language_completion_retries_and_keeps_scope_and_demolition_confirmation():
    request = cafe_request()
    request.case_snapshot.facts = [item for item in request.case_snapshot.facts
                                   if item.field_path not in {"restoration_scope", "restoration_status", "demolition_required"}]
    request.case_snapshot.facts.append(CaseFact(
        field_path="restoration_scope", value_type="ENUM", value="FULL", status="CONFIRMED",
        evidence_refs=[REF], updated_at=NOW,
    ))
    request.input.redacted_text = "원상복구 작업을 완료했습니다. 폐업 예정일은 2026-11-02입니다."
    before = request.model_dump_json()

    def respond(attempt, reply, payload):
        if payload["analysis_stage"] == "INPUT":
            reply["facts"] = [{
                "operation": "SET", "field_path": "planned_closure_date", "value_type": "DATE", "value": "2026-11-02",
                "source_text": "폐업 예정일은 2026-11-02입니다.", "confidence_bps": 10000,
                "requires_confirmation": False, "reason_summary": "합성 폐업일 보고",
            }]
            if attempt == 1:
                reply["facts"].append(restoration_fact())
        elif payload["procedure_analysis_step_codes"] == ["CONFIRM_RESTORATION_SCOPE"]:
            reply["missing_fields"] = [{
                "field_path": "demolition_required", "reason_summary": "철거 여부 미확인",
                "blocks": ["SUPERVISOR_DECISION"], "question": "철거가 필요한가요?",
            }]

    client = Replies(respond)
    result = asyncio.run(InfoAnalysisAgent(client, max_local_attempts=2).analyze(request))
    assert client.positions["INPUT", None] == 2
    assert {item.field_path for item in result.fact_candidates} == {"planned_closure_date"}
    assert result.procedure_progress_observations == []
    mutations = MutationSet(
        fact_changes=build_fact_overlays(request.case_snapshot, result, request.source_call_id),
        procedure_progress_changes=[], support_match_updates=[],
    )
    sources = [source(result)]
    evidence = {item.evidence_id: item for item in [*request.case_snapshot.evidence_records,
                *request.procedure_lookup_result.evidence_records, *result.evidence_records]}
    candidates = build_blocker_candidates(
        request.case_snapshot, request.known_procedure_steps, sources, mutations, evidence,
        resolve_procedure_bindings(request.known_procedure_steps),
    )
    assert "CONFIRM_RESTORATION_SCOPE" in {action["action_code"] for candidate in candidates for action in candidate["actions"]}
    missing = missing_info_fields(request.case_snapshot, sources, mutations)
    assert "missing:demolition_required" in {item["candidate_id"] for item in missing["blockers"]}
    assert request.model_dump_json() == before


@pytest.mark.parametrize("value,operation", [("COMPLETED", "SET"), ("NOT_REQUIRED", "SET"), (None, "CLEAR")])
def test_legacy_form_completion_noop_and_other_restoration_operations_stay_supported(value, operation):
    request = request_for_replanning(status="COMPLETED", scope="FULL")
    fact = restoration_fact(value, operation)
    fact["source_text"] = {"COMPLETED": "원상복구 작업을 완료했습니다.",
                           "NOT_REQUIRED": "원상복구 작업이 필요하지 않습니다.",
                           None: "원상복구 상태를 미확정으로 정정합니다."}[value]
    request.input.redacted_text = fact["source_text"]
    before = request.model_dump_json()
    agent = InfoAnalysisAgent(Responses())
    draft = output([])
    draft["facts"] = [fact]
    parsed = agent._input_analysis(request, agent._validated_draft(draft))
    assert parsed.facts == []
    assert len(parsed.conflicts) == (0 if value == "COMPLETED" else 1)
    assert request.model_dump_json() == before


def test_review_rejects_a_resealed_info_fact_mutation_claiming_restoration_completion():
    _, outcome = selected_plan()
    subject = outcome.review_subject.model_copy(deep=True)
    subject.trigger.input.redacted_text = "원상복구 작업을 완료했습니다."
    subject.snapshot.facts.append(CaseFact(
        field_path="restoration_scope", value_type="ENUM", value="FULL", status="CONFIRMED",
        evidence_refs=[REF], updated_at=NOW,
    ))
    component = request_for_replanning()
    component.input = subject.trigger.input
    span, evidence = InfoAnalysisAgent(Responses(), clock=lambda: NOW)._ground_text(
        component, subject.trigger.input.redacted_text,
    )
    info = next(item for item in subject.source_results if item.meta.component == "INFO_AGENT")
    info.output.fact_candidates.append(FactCandidate(
        candidate_id=uuid4(), **{key: value for key, value in restoration_fact().items() if key != "source_text"},
        source_span=span, source_evidence_refs=[evidence.evidence_id],
    ))
    info.output.evidence_records.append(evidence)
    info.output_digest = canonical_digest(info.output)
    subject.supervisor_draft.mutations.fact_changes = build_fact_overlays(subject.snapshot, info.output, info.meta.call_id)
    forged = ReviewSubject.create(**{
        key: getattr(subject, key) for key in type(subject).model_fields if key != "subject_digest"
    })
    client = StubModel()
    with pytest.raises(ReviewIntegrityError, match="Info fact mutation cannot establish restoration completion"):
        asyncio.run(ReviewTool(client).review(forged))
    assert client.calls == 0
