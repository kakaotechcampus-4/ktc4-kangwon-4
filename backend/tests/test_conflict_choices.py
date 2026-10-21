"""Batch choices preserve rejected facts and replan once through real components."""

import asyncio
import hashlib
import json
from datetime import date, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError
from test_action_codes import NOW, REF, StubModel
from test_info_replanning import Responses, finding, output
from test_procedure_only_graph import graph_run_inputs

from app.agent import schemas as agent_schemas
from app.agent.enrichment import (
    StaleConfirmationError,
    build_conflict_overlays,
    confirmation_state,
    evidence_records_equal,
    same_fact_value,
)
from app.agent.info_agent.agent import (
    InfoAnalysisAgent,
    InfoAnalysisGuardrailError,
)
from app.agent.review_tool import ReviewIntegrityError, ReviewTool
from app.agent.schemas import (
    CASE_FIELD_SPECS,
    AgentGraphInput,
    CaseFact,
    CaseFieldKey,
    ConflictCandidate,
    ConflictConfirmedTrigger,
    ConflictOutcome,
    EvidenceRecord,
    InfoAnalysisInput,
    ProcedureDependency,
    ProcedureEligibility,
    ProcedureProgress,
    ReviewSubject,
    canonical_digest,
)

REJECTED_TEXT = "기존 기록과 다르게 보고했던 사용자 원문입니다."
REPORT_TYPE = getattr(agent_schemas, "ProcedureProgressReport", None)


def pending_confirmation(accepted=(True, False), *, held=False):
    """Real INPUT extraction and conflict storage; confirmation never replays INPUT."""
    graph, original, procedure, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    text = "가맹점입니다. 유상 임차 중입니다. 폐업 예정일은 2026-11-02입니다. 합성 절차의 신고서를 접수해 처리 진행 중입니다."
    original.trigger.input.redacted_text = text
    reply = output([finding("FILE_TAX_BUSINESS_CLOSURE", "doc1")])
    reply["facts"] = [
        {"operation": "SET", "field_path": field, "value_type": kind, "value": value,
         "source_text": sentence, "confidence_bps": 10000,
         "requires_confirmation": held if field == "planned_closure_date" else False,
         "reason_summary": "합성 사용자 보고"}
        for field, kind, value, sentence in [
            ("franchise_status", "BOOLEAN", True, "가맹점입니다."),
            ("lease_status", "ENUM", "LEASED_PAID", "유상 임차 중입니다."),
            ("planned_closure_date", "DATE", date(2026, 11, 2), "폐업 예정일은 2026-11-02입니다."),
        ]
    ]
    procedure_reply = output([finding("FILE_TAX_BUSINESS_CLOSURE", "doc1")])
    if REPORT_TYPE is None:
        info_client = Responses(reply, procedure_reply)
    else:
        original.trigger.input.procedure_reports = [REPORT_TYPE(
            procedure_step=graph._known_procedure_steps[0].procedure_step,
            status="IN_PROGRESS", requirements_confirmed=True, submitted=True,
        )]
        info_client = Responses(
            input_responses=[reply | {"procedure_findings": []}],
            procedure_responses={"FILE_TAX_BUSINESS_CLOSURE": [procedure_reply]},
        )
    graph._info_agent = InfoAnalysisAgent(info_client, clock=lambda: NOW, max_local_attempts=1)
    conflict = asyncio.run(graph.run(original))
    assert conflict.outcome_type == "CONFLICT", conflict
    restored = ConflictOutcome.model_validate_json(conflict.model_dump_json())
    trigger = ConflictConfirmedTrigger(
        trigger_type="CONFLICT_CONFIRMED", input_event_id="pending-confirmation",
        client_event_id=None, conflicts=restored.conflicts,
        selections=[{"conflict_ref": item.conflict_ref, "accepted": choice}
                    for item, choice in zip(restored.conflicts, accepted, strict=True)],
        conflict_snapshot=restored.conflict_snapshot, pending_input=restored.pending_input,
        confirmed_at=NOW,
    )
    request = AgentGraphInput(trigger=trigger, case_snapshot=restored.conflict_snapshot.model_copy(deep=True))
    return graph, request, restored, info_client, procedure


@pytest.mark.parametrize("accepted", [(True, False), (False, True), (False, False), (True, True)])
def test_pending_reports_survive_all_choices_once_with_fresh_info_and_original_evidence(accepted):
    graph, request, conflict, client, _ = pending_confirmation(accepted)
    before = canonical_digest(request)
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    subject = outcome.review_subject
    fresh = next(item for item in subject.source_results if item.meta.component == "INFO_AGENT")
    packet = conflict.pending_input
    assert fresh.meta.call_id != packet.source_info_call_id
    assert fresh.meta.run_id != conflict.run_id
    assert fresh.output.fact_candidates == packet.fact_candidates
    assert fresh.output.procedure_progress_observations == packet.procedure_progress_observations
    if REPORT_TYPE is not None:
        observation, = fresh.output.procedure_progress_observations
        assert observation.source_span is None
        assert observation.structured_report == packet.original_input.procedure_reports[0]
        assert [json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))["analysis_stage"]
                for messages in client.messages] == ["INPUT", "PROCEDURE"]
    assert fresh.output.based_on_procedure_lookup_call_id == subject.source_results[0].meta.call_id
    assert fresh.output.based_on_procedure_lookup_digest == canonical_digest(subject.source_results[0].output)
    original_evidence = {item.evidence_id: item for item in conflict.evidence_records}
    for item in fresh.output.evidence_records:
        assert item == original_evidence[item.evidence_id]
        assert item.retrieved_at == NOW
    mutations = subject.supervisor_draft.mutations
    assert len(mutations.fact_changes) == sum(accepted) + 1
    pending_change = next(item for item in mutations.fact_changes if item.field_path == "planned_closure_date")
    assert pending_change.source_call_id == fresh.meta.call_id
    assert pending_change.source_fact_candidate_id == packet.fact_candidates[0].candidate_id
    progress, = mutations.procedure_progress_changes
    assert progress.procedure_analysis_call_id == fresh.meta.call_id
    assert progress.before_status == "NOT_STARTED" and progress.proposed_status == "IN_PROGRESS"
    assert getattr(progress, "proposed_submitted", False) is (REPORT_TYPE is not None)
    assert getattr(progress, "proposed_requirements_confirmed", False) is (REPORT_TYPE is not None)
    assert len(client.messages) == 2
    fresh_payload = json.loads(client.messages[1][1]["content"].removeprefix("INPUT_JSON="))
    assert fresh_payload["input"] is None
    assert packet.original_input.redacted_text not in json.dumps(fresh_payload, ensure_ascii=False)
    assert any(item["field_path"] == "planned_closure_date" and item["proposed_value"] == "2026-11-02"
               for item in fresh_payload["fact_overlays"])
    assert graph._review_tool._client.calls == 1
    assert canonical_digest(request) == before


def test_pending_reports_requiring_confirmation_remain_held_after_other_choices():
    graph, request, _, _, _ = pending_confirmation(held=True)
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    mutations = outcome.review_subject.supervisor_draft.mutations
    assert len(mutations.fact_changes) == 1
    assert mutations.fact_changes[0].source_type == "CONFIRMED_CONFLICT"
    info = outcome.review_subject.source_results[1].output
    assert info.fact_candidates[0].requires_confirmation
    if REPORT_TYPE is None:
        assert mutations.procedure_progress_changes == []
        assert info.procedure_progress_observations[0].requires_confirmation
    else:
        progress, = mutations.procedure_progress_changes
        assert progress.proposed_status == "IN_PROGRESS"
        assert progress.proposed_requirements_confirmed and progress.proposed_submitted
        assert not info.procedure_progress_observations[0].requires_confirmation


@pytest.mark.parametrize("tamper", [
    "omit_packet", "omit_conflict", "omit_fact", "omit_progress", "span", "source_call",
    "baseline", "evidence", "remove_marker",
])
def test_pending_digest_rejects_omission_and_changed_parent_or_source_context(tamper):
    _, request, _, _, _ = pending_confirmation()
    data = request.trigger.model_dump(mode="json")
    if tamper == "omit_packet":
        data.pop("pending_input")
    elif tamper == "omit_conflict":
        data["conflicts"].pop()
        data["selections"].pop()
    elif tamper == "omit_fact":
        data["pending_input"]["fact_candidates"] = []
    elif tamper == "omit_progress":
        data["pending_input"]["procedure_progress_observations"] = []
    elif tamper == "span":
        data["pending_input"]["fact_candidates"][0]["source_span"]["text"] = "원문을 고친 다른 보고입니다."
    elif tamper == "source_call":
        data["pending_input"]["source_info_call_id"] = str(UUID(int=999))
    elif tamper == "baseline":
        data["conflict_snapshot"]["case_id"] = 2
    elif tamper == "evidence":
        data["conflict_snapshot"]["evidence_records"][-1]["retrieved_at"] = (NOW + timedelta(seconds=1)).isoformat()
    else:
        data["conflicts"][0].pop("pending_input_digest")
    with pytest.raises(ValidationError):
        ConflictConfirmedTrigger.model_validate(data)


def test_legacy_conflict_digest_is_unchanged_when_new_marker_is_absent():
    _, request, _, _, _ = batch_request()
    candidate = request.trigger.conflicts[0]
    data = candidate.model_dump(mode="json", exclude={"conflict_ref", "conflict_digest", "pending_input_digest"})
    expected = "sha256:" + hashlib.sha256(json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    assert candidate.conflict_digest == expected


def reseal_pending(trigger):
    """Simulate trusted storage bugs; a matching digest never replaces semantic checks."""
    trigger.pending_input.pending_digest = trigger.pending_input.calculate_digest(
        trigger.conflict_snapshot, trigger.conflicts,
    )
    trigger.conflicts = [ConflictCandidate.create(
        **item.model_dump(exclude={"conflict_digest", "pending_input_digest"}),
        pending_input_digest=trigger.pending_input.pending_digest,
    ) for item in trigger.conflicts]
    return ConflictConfirmedTrigger.model_validate(trigger.model_dump(mode="json"))


@pytest.mark.parametrize("invalid", ["duplicate_fact", "duplicate_observation", "conflict_field", "source_call"])
def test_matching_pending_digest_does_not_bypass_structural_source_checks(invalid):
    _, request, _, _, _ = pending_confirmation()
    trigger = request.trigger.model_copy(deep=True)
    if invalid == "duplicate_fact":
        trigger.pending_input.fact_candidates.append(trigger.pending_input.fact_candidates[0].model_copy(deep=True))
    elif invalid == "duplicate_observation":
        trigger.pending_input.procedure_progress_observations.append(
            trigger.pending_input.procedure_progress_observations[0].model_copy(deep=True))
    elif invalid == "conflict_field":
        candidate = trigger.pending_input.fact_candidates[0]
        trigger.pending_input.fact_candidates[0] = type(candidate).model_validate(candidate.model_dump() | {
            "field_path": "franchise_status", "value_type": "BOOLEAN", "value": True,
        })
    else:
        trigger.pending_input.source_info_call_id = UUID(int=999)
    with pytest.raises((ValueError, ValidationError)):
        reseal_pending(trigger)


def test_retained_progress_with_same_id_but_another_code_fails_before_review():
    graph, request, _, client, _ = pending_confirmation()
    trigger = request.trigger.model_copy(deep=True)
    observation = trigger.pending_input.procedure_progress_observations[0]
    trigger.pending_input.procedure_progress_observations[0] = observation.model_copy(update={
        "procedure_step": observation.procedure_step.model_copy(update={"step_code": "UNREGISTERED"}),
    })
    if REPORT_TYPE is not None:
        # A selected report must retain the exact step ID and code even before Info.
        with pytest.raises(ValidationError, match="explicit progress selection"):
            reseal_pending(trigger)
        assert len(client.messages) == 1
    else:
        request.trigger = reseal_pending(trigger)
        outcome = asyncio.run(graph.run(request))
        assert outcome.outcome_type == "SAFE_FAILURE", outcome
        assert outcome.failed_component == "INFO_AGENT"
        assert len(client.messages) == 2
    assert graph._review_tool._client.calls == 0


@pytest.mark.parametrize("field,value", [
    ("excerpt", "원래 선택과 다른 진행 보고"),
    ("locator", "procedure_reports:999"),
    ("content_hash", "1" * 64),
])
def test_resealed_pending_progress_evidence_cannot_change_the_original_report(field, value):
    _, request, _, client, _ = pending_confirmation()
    trigger = request.trigger.model_copy(deep=True)
    ref = trigger.pending_input.procedure_progress_observations[0].source_evidence_refs[0]
    index = next(index for index, item in enumerate(trigger.conflict_snapshot.evidence_records)
                 if item.evidence_id == ref)
    evidence = trigger.conflict_snapshot.evidence_records[index]
    trigger.conflict_snapshot.evidence_records[index] = evidence.model_copy(update={field: value})
    with pytest.raises(ValueError):
        reseal_pending(trigger)
    assert len(client.messages) == 1


def test_resealed_conflict_evidence_rejects_out_of_bounds_locator_even_if_slice_matches():
    _, request, _, _, _ = pending_confirmation()
    trigger = request.trigger.model_copy(deep=True)
    text = trigger.pending_input.original_input.redacted_text
    fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
    old_ref = trigger.conflicts[0].source_evidence_refs[0]
    new_ref = f"input:{trigger.pending_input.original_input.input_event_id}:0:9999:{fingerprint[:12]}"
    index = next(index for index, item in enumerate(trigger.conflict_snapshot.evidence_records) if item.evidence_id == old_ref)
    evidence = trigger.conflict_snapshot.evidence_records[index]
    trigger.conflict_snapshot.evidence_records[index] = evidence.model_copy(update={
        "evidence_id": new_ref, "locator": "text:0-9999", "excerpt": text, "content_hash": fingerprint,
    })
    trigger.conflicts[0] = ConflictCandidate.create(
        **trigger.conflicts[0].model_dump(exclude={"conflict_digest", "source_evidence_refs"}),
        source_evidence_refs=[new_ref],
    )
    with pytest.raises(ValueError, match="outside the original input"):
        reseal_pending(trigger)


def test_retained_evidence_db_timestamp_precision_survives_full_confirmation_unchanged():
    graph, request, _, client, _ = pending_confirmation()
    trigger = request.trigger.model_copy(deep=True)
    ref = trigger.pending_input.fact_candidates[0].source_evidence_refs[0]
    stored = next(item for item in trigger.conflict_snapshot.evidence_records if item.evidence_id == ref)
    stored.retrieved_at = NOW + timedelta(microseconds=123456)
    request.trigger = reseal_pending(trigger)
    assert confirmation_state(request.case_snapshot) == confirmation_state(trigger.conflict_snapshot)
    before = request.model_dump_json()
    stored_before = request.trigger.pending_input.model_dump_json()
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    info = next(source.output for source in outcome.review_subject.source_results if source.meta.component == "INFO_AGENT")
    original = next(item for item in info.evidence_records if item.evidence_id == ref)
    assert original == stored
    assert original.retrieved_at.microsecond == 123456
    assert next(item for item in request.case_snapshot.evidence_records if item.evidence_id == ref).retrieved_at.microsecond == 0
    assert request.model_dump_json() == before
    assert request.trigger.pending_input.model_dump_json() == stored_before
    assert len(client.messages) == 2


@pytest.mark.parametrize("field,value", [
    ("source_ref", "another-event"), ("locator", "text:1-2"),
    ("excerpt", "2026-10-18T01:02:03.000001+00:00"), ("content_hash", "1" * 64),
    ("parent_evidence_refs", ["another-parent"]), ("freshness_status", "STALE"),
])
def test_db_time_equivalence_keeps_evidence_content_and_lineage_exact(field, value):
    _, request, _, _, _ = pending_confirmation()
    original = request.case_snapshot.evidence_records[-1].model_copy(update={
        "retrieved_at": NOW + timedelta(microseconds=123456), "published_at": NOW,
    })
    restored = original.model_copy(update={
        "retrieved_at": NOW.astimezone(timezone(timedelta(hours=9))),
        "published_at": NOW.astimezone(timezone(timedelta(hours=9))),
    })
    before = original.model_dump_json()
    assert evidence_records_equal(original, restored)
    changed = EvidenceRecord.model_validate(restored.model_dump() | {field: value})
    assert not evidence_records_equal(original, changed)
    assert original.model_dump_json() == before


@pytest.mark.parametrize("unmet", ["eligibility", "dependency"])
def test_retained_progress_cannot_bypass_the_existing_procedure_preconditions(unmet):
    graph, request, _, _, _ = pending_confirmation()
    step = graph._known_procedure_steps[0]
    if unmet == "eligibility":
        # The accepted franchise report makes this synthetic condition false.
        step.eligibility_conditions = [ProcedureEligibility(
            condition_key="franchise_status", condition_value="false",
        )]
    else:
        prerequisite = step.model_copy(update={
            "procedure_step": step.procedure_step.model_copy(update={
                "procedure_step_id": 2, "step_code": "FILE_FOOD_SERVICE_CLOSURE",
            }),
            "step_name": "합성 선행 절차",
        }, deep=True)
        graph._known_procedure_steps.append(prerequisite)
        step.dependencies = [ProcedureDependency(
            prerequisite_procedure_step_id=2, dependency_type="SEQUENTIAL",
        )]
    before = request.model_dump_json()
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "SAFE_FAILURE", outcome
    # Staged Info rejects a known-inapplicable report before Supervisor sees it.
    expected_component = "INFO_AGENT" if REPORT_TYPE is not None and unmet == "eligibility" else "SUPERVISOR"
    assert outcome.failed_component == expected_component
    assert graph._review_tool._client.calls == 0
    assert request.model_dump_json() == before


@pytest.mark.parametrize("invalid", ["fresh_call", "allowlist", "known_step", "no_advance", "new_model_fact"])
def test_retained_input_helper_rechecks_call_scope_and_progress_without_reextracting(invalid):
    graph, request, _, _, procedure = pending_confirmation()
    if invalid == "no_advance":
        previous = ProcedureProgress(
            procedure_step=request.trigger.pending_input.procedure_progress_observations[0].procedure_step,
            status="IN_PROGRESS", evidence_refs=[REF], updated_at=NOW,
            **({"requirements_confirmed": True, "submitted": True} if REPORT_TYPE is not None else {}),
        )
        request.trigger.conflict_snapshot.procedure_progress = [previous.model_copy(deep=True)]
        request.case_snapshot.procedure_progress = [previous.model_copy(deep=True)]
        request.trigger = reseal_pending(request.trigger)
    component = InfoAnalysisInput(
        input=None, case_snapshot=request.case_snapshot, conflict_confirmation=request.trigger,
        fact_overlays=build_conflict_overlays(request.case_snapshot, request.trigger),
        allowed_field_paths=list(CASE_FIELD_SPECS), known_procedure_steps=graph._known_procedure_steps,
        source_call_id=UUID(int=909), procedure_lookup_call_id=UUID(int=910),
        procedure_lookup_result=procedure.lookup.return_value, review_feedback=[],
    )
    if invalid == "fresh_call":
        component.source_call_id = request.trigger.pending_input.source_info_call_id
    elif invalid == "allowlist":
        component.allowed_field_paths.remove(CaseFieldKey.PLANNED_CLOSURE_DATE)
    elif invalid == "known_step":
        component.known_procedure_steps[0].procedure_step = component.known_procedure_steps[0].procedure_step.model_copy(
            update={"step_code": "UNREGISTERED"},
        )
    draft = output([finding("FILE_TAX_BUSINESS_CLOSURE", "doc1")])
    if invalid == "new_model_fact":
        draft["facts"] = [{
            "operation": "SET", "field_path": "employee_count", "value_type": "INTEGER", "value": 7,
            "source_text": "확인 뒤 임의로 만든 새 보고", "confidence_bps": 10000,
            "requires_confirmation": False, "reason_summary": "허용하지 않는 새 추출",
        }]
    with pytest.raises(InfoAnalysisGuardrailError):
        graph._info_agent._input_analysis(component, graph._info_agent._validated_draft(draft))


def batch_request(accepted=(True, False)):
    graph, original, procedure, _, support = graph_run_inputs("RESULT_SUBMITTED")
    snapshot = original.case_snapshot.model_copy(deep=True)
    snapshot.evidence_records.append(EvidenceRecord.model_validate(snapshot.evidence_records[0].model_dump() | {
        "evidence_id": "stored-conflicting-input", "source_type": "USER_INPUT",
        "source_ref": "synthetic:stored-input", "excerpt": REJECTED_TEXT,
    }))
    candidates = [
        ConflictCandidate.create(
            conflict_ref=f"stored-conflict-{index}", candidate_id=UUID(int=100 + index),
            snapshot_id=snapshot.snapshot_id, field_path=field,
            committed_status="CONFIRMED", committed_value=before,
            proposed_operation="SET", proposed_status="CONFIRMED", proposed_value=after,
            source_evidence_refs=["stored-conflicting-input"], source_call_id=UUID(int=110),
        )
        for index, (field, before, after) in enumerate([
            ("franchise_status", False, True), ("lease_status", "OWNED", "LEASED_FREE"),
        ])
    ]
    trigger = ConflictConfirmedTrigger(
        trigger_type="CONFLICT_CONFIRMED", input_event_id="stored-confirmation",
        client_event_id=None, conflicts=candidates,
        selections=[
            {"conflict_ref": item.conflict_ref, "accepted": choice}
            for item, choice in zip(candidates, accepted, strict=True)
        ],
        conflict_snapshot=snapshot.model_copy(deep=True), confirmed_at=NOW,
    )
    request = AgentGraphInput(trigger=trigger, case_snapshot=snapshot)
    client = Responses(output([finding("FILE_TAX_BUSINESS_CLOSURE", "doc1")]))
    graph._info_agent = InfoAnalysisAgent(client, clock=lambda: NOW, max_local_attempts=1)
    return graph, request, client, procedure, support


@pytest.mark.parametrize("accepted", [(True, False), (False, True), (False, False), (True, True)])
def test_batch_replans_once_reviews_only_accepted_facts_and_does_not_replay_text(accepted):
    graph, request, info_client, procedure, support = batch_request(accepted)
    before = request.model_dump_json()

    outcome = asyncio.run(graph.run(request))

    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    changes = outcome.review_subject.supervisor_draft.mutations.fact_changes
    assert {item.confirmed_conflict_ref for item in changes} == {
        conflict.conflict_ref for conflict, chosen in request.trigger.choices() if chosen
    }
    assert len(changes) == sum(accepted)
    assert request.model_dump_json() == before
    assert len(info_client.messages) == 1
    info_payload = json.loads(info_client.messages[0][1]["content"].removeprefix("INPUT_JSON="))
    assert info_payload["input"] is None
    assert "합성 테스트 입력" not in json.dumps(info_payload, ensure_ascii=False)
    assert REJECTED_TEXT not in json.dumps(info_payload, ensure_ascii=False)
    procedure.lookup.assert_awaited_once()
    support.analyze.assert_not_awaited()
    assert graph._supervisor._llm.calls == graph._review_tool._client.calls == 1


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "different_ref", "non_boolean"])
def test_choice_shape_rejects_missing_duplicate_unknown_and_non_boolean_answers(invalid):
    _, request, _, _, _ = batch_request()
    payload = request.trigger.model_dump(mode="json")
    if invalid == "missing":
        payload["selections"].pop()
    elif invalid == "duplicate":
        payload["selections"][1] = payload["selections"][0]
    elif invalid == "different_ref":
        payload["selections"][1]["conflict_ref"] = "client-invented"
    else:
        payload["selections"][0]["accepted"] = 1
    with pytest.raises(ValidationError):
        ConflictConfirmedTrigger.model_validate(payload)


@pytest.mark.parametrize("changed", ["fact", "progress", "evidence", "snapshot_id"])
def test_any_baseline_change_invalidates_even_an_all_rejected_batch(changed):
    graph, request, _, procedure, _ = batch_request((False, False))
    current = request.case_snapshot
    if changed == "fact":
        current.facts[0].value = "다른 업종"
    elif changed == "progress":
        current.procedure_progress.append(ProcedureProgress(
            procedure_step={"procedure_step_id": 1, "step_code": "FILE_TAX_BUSINESS_CLOSURE"},
            status="IN_PROGRESS", evidence_refs=[REF], updated_at=NOW,
        ))
    elif changed == "evidence":
        current.evidence_records[0].excerpt = "바뀐 공식 원문"
    else:
        current.snapshot_id = UUID(int=999)
    with pytest.raises(StaleConfirmationError):
        build_conflict_overlays(current, request.trigger)
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "SAFE_FAILURE"
    assert outcome.failure_code == "STALE_CONFLICT_CONFIRMATION"
    procedure.lookup.assert_not_awaited()


def test_same_state_tolerates_list_order_read_time_and_equivalent_timezones():
    _, request, _, _, _ = batch_request()
    baseline = request.trigger.conflict_snapshot
    current = request.case_snapshot.model_copy(deep=True)
    current.facts.reverse()
    current.captured_at = NOW + timedelta(hours=1)
    current.facts[0].updated_at = NOW.astimezone(timezone(timedelta(hours=9)))
    assert confirmation_state(baseline) == confirmation_state(current)
    assert len(build_conflict_overlays(current, request.trigger)) == 1


def test_datetime_shaped_evidence_text_remains_significant_for_staleness():
    _, request, _, _, _ = batch_request()
    baseline = request.trigger.conflict_snapshot
    baseline.evidence_records[0].excerpt = "2026-10-18T01:02:03.000001+00:00"
    request.case_snapshot.evidence_records[0].excerpt = "2026-10-18T01:02:03.000002+00:00"
    with pytest.raises(StaleConfirmationError):
        build_conflict_overlays(request.case_snapshot, request.trigger)


def test_date_candidates_survive_json_round_trip_without_equating_bool_and_int():
    _, request, _, _, _ = batch_request()
    snapshot = request.case_snapshot
    original_date = date(2026, 10, 30)
    snapshot.facts.append(CaseFact(
        field_path="planned_closure_date", value_type="DATE", value=original_date,
        status="CONFIRMED", evidence_refs=[REF], updated_at=NOW,
    ))
    candidate = ConflictCandidate.create(
        conflict_ref="stored-date-conflict", candidate_id=UUID(int=120),
        snapshot_id=snapshot.snapshot_id, field_path="planned_closure_date",
        committed_status="CONFIRMED", committed_value=original_date,
        proposed_operation="SET", proposed_status="CONFIRMED", proposed_value=date(2026, 11, 2),
        source_evidence_refs=[REF], source_call_id=UUID(int=121),
    )
    trigger = ConflictConfirmedTrigger(
        trigger_type="CONFLICT_CONFIRMED", input_event_id="date-confirmation", client_event_id=None,
        conflicts=[candidate], selections=[{"conflict_ref": candidate.conflict_ref, "accepted": True}],
        conflict_snapshot=snapshot.model_copy(deep=True), confirmed_at=NOW,
    )
    restored = ConflictConfirmedTrigger.model_validate_json(trigger.model_dump_json())
    overlays = build_conflict_overlays(snapshot, restored)
    assert str(overlays[0].proposed_value) == "2026-11-02"
    assert not same_fact_value(CaseFieldKey.EMPLOYEE_COUNT, True, 1)
    assert not same_fact_value(CaseFieldKey.FRANCHISE_STATUS, 0, False)


@pytest.mark.parametrize("forgery", ["rejected_change", "missing_accepted", "different_value"])
def test_review_rejects_forged_mutations_before_calling_its_model(forgery):
    graph, request, _, _, _ = batch_request()
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    original = outcome.review_subject
    draft = original.supervisor_draft.model_copy(deep=True)
    if forgery == "rejected_change":
        all_accepted = request.trigger.model_copy(deep=True)
        all_accepted.selections[1].accepted = True
        draft.mutations.fact_changes = build_conflict_overlays(request.case_snapshot, all_accepted)
    elif forgery == "missing_accepted":
        draft.mutations.fact_changes = []
    else:
        draft.mutations.fact_changes[0].proposed_value = False
    values = {
        key: getattr(original, key) for key in type(original).model_fields
        if key not in {"subject_digest", "supervisor_draft"}
    }
    forged = ReviewSubject.create(**values, supervisor_draft=draft)
    model = StubModel()
    with pytest.raises(ReviewIntegrityError):
        asyncio.run(ReviewTool(model).review(forged))
    assert model.calls == 0


def test_same_date_report_does_not_create_a_conflict_after_json_restore():
    from test_info_replanning import request_for_replanning

    from app.agent.info_agent.agent import InfoAnalysisDraft

    request = request_for_replanning()
    request.case_snapshot.facts.append(CaseFact(
        field_path="planned_closure_date", value_type="DATE", value=date(2026, 11, 2),
        status="CONFIRMED", evidence_refs=[REF], updated_at=NOW,
    ))
    request.input.redacted_text = "폐업 예정일은 2026-11-02입니다."
    reply = output([])
    reply["facts"] = [{
        "operation": "SET", "field_path": "planned_closure_date", "value_type": "DATE",
        "value": "2026-11-02", "source_text": request.input.redacted_text,
        "confidence_bps": 10000, "requires_confirmation": False,
        "reason_summary": "기존과 같은 날짜 보고",
    }]
    parsed = InfoAnalysisAgent(Responses(reply), clock=lambda: NOW)._input_analysis(
        request, InfoAnalysisDraft.model_validate(reply),
    )
    assert parsed.conflicts == []
    assert parsed.facts == []
