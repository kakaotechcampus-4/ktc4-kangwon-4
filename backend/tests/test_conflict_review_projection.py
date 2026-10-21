"""Conflict Review retains choices, stored reports and original evidence."""

import asyncio
import json
from datetime import date, timedelta
from uuid import UUID

import pytest
from test_action_codes import NOW, REF, StubModel, evidence
from test_conflict_choices import batch_request, pending_confirmation, reseal_pending

from app.agent.enrichment import build_conflict_overlays
from app.agent.review_tool import ReviewIntegrityError, ReviewTool
from app.agent.review_tool.tool import (
    _resolve_json_pointer,
    _review_prompt_projection,
    _validate_integrity,
)
from app.agent.schemas import (
    AgentGraphInput,
    CaseFact,
    ConflictCandidate,
    ConflictConfirmedTrigger,
    ProcedureProgressChangeCandidate,
    ProcedureProgressObservation,
    ReviewSubject,
    canonical_digest,
)


def confirmation_subject(accepted=(True, False), *, legacy=False, reverse=False):
    graph, request, _, _, _ = batch_request(accepted)
    if legacy:
        request.trigger = ConflictConfirmedTrigger(
            trigger_type="CONFLICT_CONFIRMED", input_event_id="legacy-confirmation",
            client_event_id=None, confirmed_conflict=request.trigger.conflicts[0],
            confirmed_at=NOW,
        )
    elif reverse:
        request.trigger.selections.reverse()
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    return outcome.review_subject


@pytest.mark.parametrize("accepted", [(True, False), (False, True), (False, False)])
@pytest.mark.parametrize("reverse", [False, True])
def test_batch_confirmation_preserves_canonical_choices_values_and_order(accepted, reverse):
    subject = confirmation_subject(accepted, reverse=reverse)
    original = subject.model_dump_json()
    payload = _review_prompt_projection(subject, _validate_integrity(subject))
    full = subject.model_dump(mode="json")
    trigger = payload["trigger"]
    assert set(trigger) == {"trigger_type", "conflicts", "selections"}
    assert trigger["selections"] == full["trigger"]["selections"]
    for index, conflict in enumerate(trigger["conflicts"]):
        assert set(conflict) == {
            "conflict_ref", "field_path", "committed_status", "committed_value",
            "proposed_operation", "proposed_status", "proposed_value", "source_evidence_refs",
        }
        for key, value in conflict.items():
            path = f"/trigger/conflicts/{index}/{key}"
            assert _resolve_json_pointer(payload, path) == _resolve_json_pointer(full, path) == value
    for index, selection in enumerate(trigger["selections"]):
        path = f"/trigger/selections/{index}/accepted"
        assert _resolve_json_pointer(payload, path) is _resolve_json_pointer(full, path)
    expected = {
        conflict.conflict_ref for conflict, chosen in subject.trigger.choices() if chosen
    }
    changes = payload["supervisor_draft"]["mutations"]["fact_changes"]
    assert {item["confirmed_conflict_ref"] for item in changes} == expected
    assert len(changes) == sum(accepted)
    assert "conflict_snapshot" not in trigger
    assert subject.model_dump_json() == original


def test_legacy_confirmation_keeps_its_original_path_and_explicit_review_instruction():
    subject = confirmation_subject(legacy=True)
    original = subject.model_dump_json()

    class Inspect(StubModel):
        async def generate(self, model, messages, **kwargs):
            system = messages[0]["content"]
            assert "confirmed_conflict는 사용자가 수락한 단건" in system
            assert "accepted=false는 기존 값을 유지" in system
            assert "배열 순서가 아니라 conflict_ref" in system
            assert "다른 안전 검수" in system
            assert "/trigger/ 경로를 재작업 대상으로 삼지 마세요" in system
            payload = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))
            trigger = payload["trigger"]
            assert set(trigger) == {"trigger_type", "confirmed_conflict"}
            assert trigger["confirmed_conflict"]["conflict_ref"] == (
                payload["supervisor_draft"]["mutations"]["fact_changes"][0]["confirmed_conflict_ref"]
            )
            path = "/trigger/confirmed_conflict/committed_value"
            assert _resolve_json_pointer(payload, path) is False
            assert _resolve_json_pointer(payload, "/trigger/confirmed_conflict/proposed_value") is True
            return await super().generate(model, messages, **kwargs)

    client = Inspect()
    result = asyncio.run(ReviewTool(client).review(subject))
    assert result.verdict == "PASS" and client.calls == 1
    assert subject.model_dump_json() == original


def test_rejected_choice_retains_its_own_source_body_and_transitive_parent():
    graph, request, _, _, _ = batch_request()
    parent = evidence(evidence_id="rejected-parent", source_type="USER_INPUT",
                      source_ref="synthetic:private-parent", excerpt="합성 거절 근거의 부모 원문")
    record = evidence(evidence_id="rejected-only", source_type="USER_INPUT",
                      source_ref="synthetic:private-reference", excerpt="합성 거절 선택의 원문",
                      parent_evidence_refs=[parent.evidence_id])
    request.case_snapshot.evidence_records.extend([record, parent])
    conflict = request.trigger.conflicts[1]
    request.trigger.conflicts[1] = ConflictCandidate.create(**{
        **conflict.model_dump(exclude={"conflict_digest"}),
        "source_evidence_refs": [record.evidence_id],
    })
    request.trigger.conflict_snapshot = request.case_snapshot.model_copy(deep=True)
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    subject = outcome.review_subject
    payload = _review_prompt_projection(subject, _validate_integrity(subject))
    assert payload["trigger"]["selections"][1]["accepted"] is False
    assert payload["trigger"]["conflicts"][1]["source_evidence_refs"] == [record.evidence_id]
    records = [*payload["snapshot"]["evidence_records"], *(
        item for source_payload in payload["source_results"]
        for item in source_payload["output"]["evidence_records"]
    )]
    by_id = {item["evidence_id"]: item for item in records if item is not None}
    for original in (record, parent):
        assert by_id[original.evidence_id]["excerpt"] == original.excerpt
        assert "source_ref" not in by_id[original.evidence_id]
        assert original.source_ref not in json.dumps(payload, ensure_ascii=False)
    assert by_id[record.evidence_id]["parent_evidence_refs"] == [parent.evidence_id]


@pytest.mark.parametrize("operation", ["SET", "CLEAR"])
def test_confirmation_date_values_and_operation_survive_json_round_trip(operation):
    graph, request, _, _, _ = batch_request()
    request.case_snapshot.facts.append(CaseFact(
        field_path="planned_closure_date", value_type="DATE", value=date(2026, 10, 30),
        status="CONFIRMED", evidence_refs=[REF], updated_at=NOW,
    ))
    conflict = ConflictCandidate.create(
        conflict_ref="stored-date-choice", candidate_id=UUID(int=991),
        snapshot_id=request.case_snapshot.snapshot_id, field_path="planned_closure_date",
        committed_status="CONFIRMED", committed_value=date(2026, 10, 30),
        proposed_operation=operation, proposed_status="CONFIRMED" if operation == "SET" else "UNKNOWN",
        proposed_value=date(2026, 11, 2) if operation == "SET" else None,
        source_evidence_refs=["stored-conflicting-input"], source_call_id=UUID(int=992),
    )
    request.trigger = ConflictConfirmedTrigger(
        trigger_type="CONFLICT_CONFIRMED", input_event_id="date-confirmation", client_event_id=None,
        conflicts=[conflict], selections=[{"conflict_ref": conflict.conflict_ref, "accepted": True}],
        conflict_snapshot=request.case_snapshot.model_copy(deep=True), confirmed_at=NOW,
    )
    restored = AgentGraphInput.model_validate_json(request.model_dump_json())
    outcome = asyncio.run(graph.run(restored))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    subject = outcome.review_subject
    payload = _review_prompt_projection(subject, _validate_integrity(subject))
    projected = payload["trigger"]["conflicts"][0]
    assert projected["committed_value"] == "2026-10-30"
    assert projected["proposed_value"] == ("2026-11-02" if operation == "SET" else None)
    assert projected["proposed_operation"] == operation
    change = payload["supervisor_draft"]["mutations"]["fact_changes"][0]
    assert change["value_type"] == "DATE"
    assert change["operation"] == operation
    assert change["confirmed_conflict_ref"] == projected["conflict_ref"]


@pytest.mark.parametrize("forgery", ["rejected_change", "missing_accepted", "value", "evidence"])
def test_confirmation_projection_does_not_relax_mutation_provenance(forgery):
    subject = confirmation_subject()
    draft = subject.supervisor_draft.model_copy(deep=True)
    if forgery == "rejected_change":
        trigger = subject.trigger.model_copy(deep=True)
        trigger.selections[1].accepted = True
        draft.mutations.fact_changes = build_conflict_overlays(subject.snapshot, trigger)
    elif forgery == "missing_accepted":
        draft.mutations.fact_changes.clear()
    elif forgery == "value":
        draft.mutations.fact_changes[0].proposed_value = False
    else:
        draft.mutations.fact_changes[0].source_evidence_refs = [REF]
    forged = ReviewSubject.create(**{
        key: getattr(subject, key) for key in type(subject).model_fields
        if key not in {"subject_digest", "supervisor_draft"}
    }, supervisor_draft=draft)
    client = StubModel()
    with pytest.raises(ReviewIntegrityError):
        asyncio.run(ReviewTool(client).review(forged))
    assert client.calls == 0


def test_sensitive_confirmation_ref_is_rejected_before_the_model():
    subject = confirmation_subject(legacy=True)
    sensitive_ref = "010-1234-5678"
    conflict = ConflictCandidate.create(**{
        **subject.trigger.confirmed_conflict.model_dump(exclude={"conflict_digest"}),
        "conflict_ref": sensitive_ref,
    })
    trigger = subject.trigger.model_copy(update={"confirmed_conflict": conflict}, deep=True)
    draft = subject.supervisor_draft.model_copy(deep=True)
    draft.mutations.fact_changes[0].confirmed_conflict_ref = sensitive_ref
    values = {key: getattr(subject, key) for key in type(subject).model_fields
              if key not in {"subject_digest", "supervisor_draft", "trigger"}}
    sensitive_subject = ReviewSubject.create(**values, trigger=trigger, supervisor_draft=draft)
    client = StubModel()
    with pytest.raises(ReviewIntegrityError, match="sensitive-data preflight"):
        asyncio.run(ReviewTool(client).review(sensitive_subject))
    assert client.calls == 0


def pending_confirmation_subject(accepted=True):
    graph, request, _, _, _ = pending_confirmation((accepted, False))
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    return outcome.review_subject


@pytest.mark.parametrize("accepted", [False, True])
def test_pending_confirmation_reviews_carried_facts_progress_and_full_context(accepted):
    subject = pending_confirmation_subject(accepted)
    original = subject.model_dump_json()
    changes = subject.supervisor_draft.mutations
    assert len(changes.fact_changes) == 1 + int(accepted)
    assert len(changes.procedure_progress_changes) == 1

    class Inspect(StubModel):
        async def generate(self, model, messages, **kwargs):
            assert "나머지 비충돌 후보의 뜻이나 진행 완료까지 승인한 것은 아닙니다" in messages[0]["content"]
            payload = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))
            pending = payload["trigger"]["pending_input"]
            assert pending["original_input"]["redacted_text"] == subject.trigger.pending_input.original_input.redacted_text
            assert "가맹점입니다." in pending["original_input"]["redacted_text"]
            assert _resolve_json_pointer(payload, "/trigger/pending_input/fact_candidates/0/value") == "2026-11-02"
            retained = subject.trigger.pending_input.procedure_progress_observations[0]
            projected = pending["procedure_progress_observations"][0]
            if "submitted" in type(retained).model_fields:
                assert _resolve_json_pointer(payload, "/trigger/pending_input/procedure_progress_observations/0/submitted") is True
            else:
                assert "submitted" not in projected
            if retained.source_span is None:
                assert projected["source_span"] is None
                assert projected["structured_report"] == retained.structured_report.model_dump(mode="json")
            else:
                assert projected["source_span"]["text"] == retained.source_span.text
            records = [*payload["snapshot"]["evidence_records"], *(
                record for source_payload in payload["source_results"]
                for record in source_payload["output"]["evidence_records"]
            )]
            by_id = {record["evidence_id"]: record for record in records if record is not None}
            for retained in subject.trigger.pending_input.fact_candidates:
                record = by_id[retained.source_evidence_refs[0]]
                assert record["excerpt"] == retained.source_span.text
                for parent_ref in record["parent_evidence_refs"]:
                    assert by_id[parent_ref]["excerpt"]
            return await super().generate(model, messages, **kwargs)

    client = Inspect()
    reviewed = asyncio.run(ReviewTool(client).review(subject))
    assert reviewed.verdict == "PASS" and client.calls == 1
    assert subject.model_dump_json() == original


@pytest.mark.parametrize("changed", [
    "fact_missing", "fact_id", "fact_value", "fact_span", "fact_evidence",
    "fact_reason", "fact_confirmation", "fact_confidence", "observation_missing",
    "observation_status", "observation_flags", "observation_reason", "observation_confirmation",
])
def test_fresh_info_must_preserve_every_retained_typed_candidate(changed):
    if changed == "observation_flags" and "submitted" not in ProcedureProgressObservation.model_fields:
        pytest.skip("submission flag preservation requires the procedure progress feature")
    subject = pending_confirmation_subject()
    info_source = subject.source_results[1]
    info = info_source.output.model_copy(deep=True)
    if changed == "fact_missing":
        info.fact_candidates.clear()
    elif changed.startswith("fact_"):
        fact = info.fact_candidates[0]
        if changed == "fact_id":
            fact.candidate_id = UUID(int=890)
        elif changed == "fact_value":
            fact.value = date(2026, 11, 1)
        elif changed == "fact_span":
            fact.source_span = fact.source_span.model_copy(update={"input_event_id": "different-event"})
        elif changed == "fact_evidence":
            fact.source_evidence_refs = list(info.procedure_progress_observations[0].source_evidence_refs)
        elif changed == "fact_reason":
            fact.reason_summary = "다르게 바뀐 합성 이유"
        elif changed == "fact_confirmation":
            fact.requires_confirmation = True
        else:
            fact.confidence_bps = 9000
    elif changed == "observation_missing":
        info.procedure_progress_observations.clear()
    else:
        observation = info.procedure_progress_observations[0]
        if changed == "observation_status":
            update = {"observed_status": "COMPLETED"}
        elif changed == "observation_flags":
            update = {"submitted": False}
        elif changed == "observation_reason":
            update = {"reason_summary": "다르게 바뀐 합성 관찰 이유"}
        else:
            update = {"requires_confirmation": True}
        # Simulate a forged stored/model object, bypassing assignment validation.
        info.procedure_progress_observations[0] = observation.model_copy(update=update)
    sources = [*subject.source_results]
    sources[1] = info_source.model_copy(update={"output": info, "output_digest": canonical_digest(info)})
    forged = ReviewSubject.create(**{
        **subject.model_dump(exclude={"subject_digest", "source_results"}), "source_results": sources,
    })
    client = StubModel()
    with pytest.raises(ReviewIntegrityError, match="pending candidate"):
        asyncio.run(ReviewTool(client).review(forged))
    assert client.calls == 0


def test_pending_confirmation_rejects_reused_original_info_call():
    subject = pending_confirmation_subject()
    old_id = subject.trigger.pending_input.source_info_call_id
    sources = [*subject.source_results]
    sources[1] = sources[1].model_copy(update={"meta": sources[1].meta.model_copy(update={"call_id": old_id})})
    draft = subject.supervisor_draft.model_copy(deep=True)
    call_ids = [item.meta.call_id for item in sources]
    draft = draft.model_copy(update={
        "source_call_ids": call_ids,
        "decision": draft.decision.model_copy(update={"based_on_call_ids": call_ids}),
    })
    for change in draft.mutations.fact_changes:
        if change.source_type == "INFO_ANALYSIS":
            change.source_call_id = old_id
    for change in draft.mutations.procedure_progress_changes:
        change.procedure_analysis_call_id = old_id
    forged = ReviewSubject.create(**{
        **subject.model_dump(exclude={"subject_digest", "source_results", "supervisor_draft"}),
        "source_results": sources, "supervisor_draft": draft,
    })
    client = StubModel()
    with pytest.raises(ReviewIntegrityError, match="fresh Info source"):
        asyncio.run(ReviewTool(client).review(forged))
    assert client.calls == 0


@pytest.mark.parametrize("changed", ["fact_value", "progress_flags", "missing_accepted", "rejected_change"])
def test_pending_packet_does_not_relax_each_mutation_or_choice_check(changed):
    if changed == "progress_flags" and "proposed_submitted" not in ProcedureProgressChangeCandidate.model_fields:
        pytest.skip("submission mutation flags require the procedure progress feature")
    subject = pending_confirmation_subject(changed != "rejected_change")
    draft = subject.supervisor_draft.model_copy(deep=True)
    if changed == "fact_value":
        change = next(item for item in draft.mutations.fact_changes if item.source_type == "INFO_ANALYSIS")
        change.proposed_value = date(2026, 11, 3)
    elif changed == "progress_flags":
        draft.mutations.procedure_progress_changes[0].proposed_submitted = False
    elif changed == "missing_accepted":
        draft.mutations.fact_changes = [
            item for item in draft.mutations.fact_changes if item.source_type == "INFO_ANALYSIS"
        ]
    else:
        accepted = subject.trigger.model_copy(deep=True)
        accepted.selections[0].accepted = True
        draft.mutations.fact_changes.extend(build_conflict_overlays(subject.snapshot, accepted))
    forged = ReviewSubject.create(**{
        **subject.model_dump(exclude={"subject_digest", "supervisor_draft"}),
        "supervisor_draft": draft,
    })
    client = StubModel()
    with pytest.raises(ReviewIntegrityError):
        asyncio.run(ReviewTool(client).review(forged))
    assert client.calls == 0


def test_pending_full_context_is_checked_for_sensitive_text_before_model():
    subject = pending_confirmation_subject()
    trigger = subject.trigger.model_copy(deep=True)
    pending = trigger.pending_input
    pending.original_input.redacted_text += " 연락처는 010-1234-5678입니다."
    pending.pending_digest = pending.calculate_digest(trigger.conflict_snapshot, trigger.conflicts)
    conflicts = [ConflictCandidate.create(**{
        **conflict.model_dump(exclude={"conflict_digest"}),
        "pending_input_digest": pending.pending_digest,
    }) for conflict in trigger.conflicts]
    trigger = trigger.model_copy(update={"conflicts": conflicts})
    trigger.assert_pending_input_integrity()
    forged = ReviewSubject.create(**{
        **subject.model_dump(exclude={"subject_digest", "trigger"}), "trigger": trigger,
    })
    client = StubModel()
    with pytest.raises(ReviewIntegrityError, match="sensitive-data preflight"):
        asyncio.run(ReviewTool(client).review(forged))
    assert client.calls == 0


def timestamp_roundtrip_subject():
    subject = pending_confirmation_subject()
    trigger = subject.trigger.model_copy(deep=True)
    ref = trigger.pending_input.fact_candidates[0].source_evidence_refs[0]
    original = next(item for item in trigger.conflict_snapshot.evidence_records if item.evidence_id == ref)
    original.retrieved_at += timedelta(microseconds=123456)
    trigger = reseal_pending(trigger)
    sources = [item.model_copy(deep=True) for item in subject.source_results]
    info = next(item for item in sources if item.meta.component == "INFO_AGENT")
    index = next(index for index, item in enumerate(info.output.evidence_records) if item.evidence_id == ref)
    info.output.evidence_records[index] = original.model_copy(deep=True)
    info.output_digest = canonical_digest(info.output)
    return ReviewSubject.create(**{
        **subject.model_dump(exclude={"subject_digest", "trigger", "source_results"}),
        "trigger": trigger, "source_results": sources,
    }), ref


def test_review_accepts_db_timestamp_precision_without_rewriting_original_evidence():
    subject, ref = timestamp_roundtrip_subject()
    before = subject.model_dump_json()
    stored = next(item for item in subject.trigger.conflict_snapshot.evidence_records if item.evidence_id == ref)
    current = next(item for item in subject.snapshot.evidence_records if item.evidence_id == ref)
    assert stored.retrieved_at.microsecond == 123456 and current.retrieved_at.microsecond == 0
    client = StubModel()
    result = asyncio.run(ReviewTool(client).review(subject))
    assert result.verdict == "PASS" and client.calls == 1
    assert subject.model_dump_json() == before
    assert stored.retrieved_at.microsecond == 123456 and current.retrieved_at.microsecond == 0


@pytest.mark.parametrize("changed", [
    "excerpt", "content_hash", "source_ref", "locator", "parent_evidence_refs",
    "freshness_status", "source_type", "retrieved_at", "published_at",
])
def test_timestamp_tolerance_does_not_allow_changed_evidence_content_or_provenance(changed):
    subject, ref = timestamp_roundtrip_subject()
    snapshot = subject.snapshot.model_copy(deep=True)
    index = next(index for index, item in enumerate(snapshot.evidence_records) if item.evidence_id == ref)
    evidence = snapshot.evidence_records[index]
    value = {
        "excerpt": "다른 합성 원문", "content_hash": "1" * 64,
        "source_ref": "different-event", "locator": "text:0-1",
        "parent_evidence_refs": [REF],
        "freshness_status": type(evidence.freshness_status)("UNKNOWN"),
        "source_type": type(evidence.source_type)("EXPERT_CONFIRMATION"),
        "retrieved_at": evidence.retrieved_at + timedelta(seconds=1),
        "published_at": NOW,
    }[changed]
    snapshot.evidence_records[index] = evidence.model_copy(update={changed: value})
    forged = ReviewSubject.create(**{
        **subject.model_dump(exclude={"subject_digest", "snapshot"}), "snapshot": snapshot,
    })
    client = StubModel()
    with pytest.raises(ReviewIntegrityError, match="same evidence ID has conflicting content"):
        asyncio.run(ReviewTool(client).review(forged))
    assert client.calls == 0
