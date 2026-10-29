"""The closure MVP does not execute or request input for support programs."""

import asyncio
import json
from datetime import date, timedelta
from itertools import product
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import ValidationError
from test_action_codes import (
    NOW,
    StubModel,
    result_fixes_xfail,
    source,
    supervisor_request,
    support_sources,
)
from test_blocker_candidates import ChoiceModel

from app.agent.graph import AgentGraph
from app.agent.review_tool import ReviewIntegrityError, ReviewTool
from app.agent.schemas import (
    CASE_FIELD_SPECS,
    AgentGraphInput,
    CaseFact,
    CaseFieldKey,
    ConflictCandidate,
    ConflictConfirmedTrigger,
    InfoAnalysisResult,
    ProcedureProgress,
    ReviewResult,
    ReviewSubject,
    SafeFailureOutcome,
    canonical_digest,
)
from app.agent.supervisor.agent import SupervisorAgent


def graph_run_inputs(trigger_type, review_tool=None):
    template = supervisor_request()
    request = AgentGraphInput(
        trigger=template.trigger.model_dump() | {"trigger_type": trigger_type},
        case_snapshot=template.case_snapshot,
    )

    async def analyze_info(component_input):
        return InfoAnalysisResult.model_validate(
            template.source_results[1].output.model_dump()
            | {
                "based_on_procedure_lookup_call_id": component_input.procedure_lookup_call_id,
                "based_on_procedure_lookup_digest": canonical_digest(
                    component_input.procedure_lookup_result
                ),
            }
        )

    procedure = AsyncMock()
    procedure.lookup.return_value = template.source_results[0].output
    info = AsyncMock()
    info.analyze.side_effect = analyze_info
    support = AsyncMock()
    support.analyze.side_effect = AssertionError("Support is outside the closure MVP")
    graph = AgentGraph(
        procedure_tool=procedure,
        info_agent=info,
        support_agent=support,
        supervisor=SupervisorAgent(ChoiceModel(), clock=lambda: NOW, max_local_attempts=1),
        review_tool=review_tool or ReviewTool(StubModel()),
        known_procedure_steps=template.known_procedure_steps,
        clock=lambda: NOW,
    )
    return graph, request, procedure, info, support


@pytest.mark.parametrize("trigger_type", ["CASE_CREATED", "RESULT_SUBMITTED"])
def test_closure_judgment_passes_review_without_support(trigger_type):
    graph, request, procedure, info, support = graph_run_inputs(trigger_type)

    outcome = asyncio.run(graph.run(request))

    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    assert outcome.review_subject.supervisor_draft.next_action.target.target_kind == "PROCEDURE"
    assert [item.meta.component for item in outcome.review_subject.source_results] == [
        "PROCEDURE_TOOL", "INFO_AGENT",
    ]
    procedure.lookup.assert_awaited_once()
    info.analyze.assert_awaited_once()
    support.analyze.assert_not_awaited()


@pytest.mark.parametrize("targets", [["SUPPORT_AGENT"], ["INFO_AGENT", "SUPPORT_AGENT"]])
def test_support_rework_fails_without_calling_support_or_requesting_user_input(targets):
    async def review(subject):
        return ReviewResult(
            reviewed_subject_id=subject.review_subject_id,
            reviewed_subject_digest=subject.subject_digest,
            verdict="REVISE",
            issues=[],
            missing_evidence=[{
                "claim_path": "/supervisor_draft/decision/next_action",
                "required_source_types": ["OFFICIAL_DOCUMENT"],
                "reason_summary": "합성 지원 검토 요청",
            }],
            recommended_rework_targets=targets,
            resolution_reason="합성 재작업 요청",
        )

    reviewer = AsyncMock()
    reviewer.review.side_effect = review
    graph, request, procedure, info, support = graph_run_inputs("CASE_CREATED", reviewer)

    outcome = asyncio.run(graph.run(request))

    assert outcome.outcome_type == "SAFE_FAILURE", outcome
    assert outcome.failed_component == "REVIEW_TOOL"
    assert outcome.recovery_action_code == "CONTACT_SUPPORT"
    assert outcome.retryable is False
    assert outcome.requested_field_paths == []
    procedure.lookup.assert_awaited_once()
    info.analyze.assert_awaited_once()
    reviewer.review.assert_awaited_once()
    support.analyze.assert_not_awaited()


@pytest.mark.parametrize("has_info_question", [False, True])
def test_failure_does_not_request_fields_from_support_analysis(has_info_question):
    support = support_sources()[0]
    support.output.support_checks[0].unknown_field_paths = ["employee_count"]
    support.output_digest = canonical_digest(support.output)
    info = supervisor_request().source_results[1].output
    if has_info_question:
        info = InfoAnalysisResult.model_validate(info.model_dump() | {
            "question_candidates": [{
                "question_id": UUID(int=91),
                "text": "원상복구 범위를 확인하셨나요?",
                "resolves_field_paths": ["restoration_scope"],
                "reason_summary": "합성 확인 항목",
            }],
        })

    fields = AgentGraph._requested_field_paths({
        "source_results": [source(info), support],
    })

    assert fields == (["restoration_scope"] if has_info_question else [])


def test_info_question_keeps_closure_fields_but_omits_support_only_fields():
    question_id = UUID(int=92)
    info = supervisor_request().source_results[1].output
    info = InfoAnalysisResult.model_validate(info.model_dump() | {
        "missing_fields": [
            {
                "field_path": field,
                "reason_summary": "합성 미확인 항목",
                "blocks": blocks,
                "question_candidate_id": question_id,
            }
            for field, blocks in [
                ("employee_count", ["SUPPORT_ANALYSIS"]),
                ("restoration_scope", ["SUPPORT_ANALYSIS", "PROCEDURE_LOOKUP"]),
            ]
        ],
        "question_candidates": [{
            "question_id": question_id,
            "text": "직원 수와 원상복구 범위를 확인하셨나요?",
            "resolves_field_paths": ["employee_count", "restoration_scope"],
            "reason_summary": "합성 복합 질문",
        }],
    })

    failure = {"source_results": [source(info)]}
    requested = AgentGraph._requested_field_paths(failure)
    assert requested == ["restoration_scope"]
    if hasattr(AgentGraph, "_requested_field_guidance"):
        assert AgentGraph._requested_field_guidance(failure, requested) == {
            "restoration_scope": "확인한 원상복구 범위가 있으면 알려주세요.",
        }


@pytest.mark.parametrize("linked_id,expected", [
    (95, "임대인이 확인해 준 원상복구 범위가 무엇인가요?"),
    (96, "원상복구 범위를 확인하셨나요?"),
    (93, "원상복구 범위를 확인하셨나요?"),
])
@result_fixes_xfail(raises=AttributeError)
def test_requested_guidance_prefers_linked_question_then_resolving_question(linked_id, expected):
    info = supervisor_request().source_results[1].output
    info = InfoAnalysisResult.model_validate(info.model_dump() | {
        "missing_fields": [{
            "field_path": "restoration_scope", "blocks": ["SUPERVISOR_DECISION"],
            "reason_summary": "합성 미확인 항목", "question_candidate_id": UUID(int=linked_id),
        }],
        "question_candidates": [
            {
                "question_id": UUID(int=question_id), "text": text,
                "resolves_field_paths": [field], "reason_summary": "합성 확인 질문",
            }
            for question_id, field, text in [
                (93, "employee_count", "직원이 몇 명인가요?"),
                (94, "restoration_scope", "원상복구 범위를 확인하셨나요?"),
                (95, "restoration_scope", "임대인이 확인해 준 원상복구 범위가 무엇인가요?"),
            ]
        ],
    })
    failure = {"source_results": [source(info)]}

    assert AgentGraph._requested_field_guidance(failure, [CaseFieldKey.RESTORATION_SCOPE]) == {
        "restoration_scope": expected,
    }


@result_fixes_xfail(raises=AttributeError)
def test_requested_guidance_fallback_covers_every_case_field():
    guidance = AgentGraph._requested_field_guidance({}, list(CASE_FIELD_SPECS))

    assert list(guidance) == list(CASE_FIELD_SPECS)
    assert all(text.strip() for text in guidance.values())
    assert guidance[CaseFieldKey.PLANNED_CLOSURE_DATE] == "예정한 폐업일이 언제인지 알려주세요."


@pytest.mark.parametrize("recovery,retryable", [
    ("RETRY", True), ("CONTACT_SUPPORT", False), ("NONE", False),
])
@result_fixes_xfail(raises=AttributeError)
def test_non_input_recovery_has_no_field_guidance(recovery, retryable):
    _, request, _, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    info = supervisor_request().source_results[1].output
    info = InfoAnalysisResult.model_validate(info.model_dump() | {
        "question_candidates": [{
            "question_id": UUID(int=97), "text": "원상복구 범위를 알려주세요.",
            "resolves_field_paths": ["restoration_scope"], "reason_summary": "합성 확인 질문",
        }],
    })
    failure = {
        "source_results": [source(info)], "recovery_action_code": recovery, "retryable": retryable,
    }
    outcome = AgentGraph._build_safe_failure(request, run_id=UUID(int=2), trace_id=None, failure=failure)

    assert AgentGraph._requested_field_paths(failure) == ["restoration_scope"]
    assert AgentGraph._requested_field_guidance(failure, outcome.requested_field_paths) == {}


@pytest.mark.parametrize("code,retryable,fields,stale", [
    pytest.param(
        code, retryable, fields, stale,
        marks=result_fixes_xfail(raises=pytest.fail.Exception)
        if retryable != (code == "RETRY") or (
            not fields and not stale if code == "RESUBMIT_INPUT" else bool(fields)
        ) else (),
    )
    for code, retryable, fields, stale in product(
        ["RETRY", "RESUBMIT_INPUT", "CONTACT_SUPPORT", "NONE"],
        [False, True], [[], ["restoration_scope"]], [False, True],
    )
])
def test_safe_failure_recovery_combinations(code, retryable, fields, stale):
    _, request, _, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    payload = {
        "outcome_type": "SAFE_FAILURE", "run_id": UUID(int=2), "case_id": 1,
        "trigger": request.trigger, "snapshot_id": request.case_snapshot.snapshot_id,
        "failure_code": "STALE_CONFLICT_CONFIRMATION" if stale else "COMPONENT_UNAVAILABLE",
        "message_code": "AGENT_COMPONENT_UNAVAILABLE", "recovery_action_code": code,
        "requested_field_paths": fields, "retryable": retryable, "failed_component": None,
        "trace_id": None,
    }
    valid = retryable == (code == "RETRY") and (
        bool(fields) or stale if code == "RESUBMIT_INPUT" else not fields
    )
    if valid:
        outcome = SafeFailureOutcome.model_validate(payload)
        assert SafeFailureOutcome.model_validate_json(outcome.model_dump_json()) == outcome
    else:
        with pytest.raises(ValidationError):
            SafeFailureOutcome.model_validate(payload)


@result_fixes_xfail(raises=pytest.fail.Exception)
def test_safe_failure_rejects_duplicate_requested_fields():
    _, request, _, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    outcome = AgentGraph._build_safe_failure(request, run_id=UUID(int=2), trace_id=None, failure={})

    with pytest.raises(ValidationError):
        SafeFailureOutcome.model_validate(outcome.model_dump() | {
            "recovery_action_code": "RESUBMIT_INPUT",
            "requested_field_paths": ["restoration_scope", "restoration_scope"],
        })


@pytest.mark.parametrize("error,expected", [
    pytest.param("timeout", "RUN_DEADLINE_EXCEEDED", marks=result_fixes_xfail()),
    pytest.param("component", "COMPONENT_UNAVAILABLE", marks=result_fixes_xfail()),
    ("invalid_output", "STRUCTURED_OUTPUT_FAILED"),
])
def test_graph_failure_with_missing_fields_keeps_recovery_combination(error, expected):
    from app.agent.llm import LLMRequestError
    from app.agent.run_scope import RunDeadlineExceededError

    graph, request, _, info, _ = graph_run_inputs("RESULT_SUBMITTED")
    original = info.analyze.side_effect

    async def analyze(component_input):
        result = await original(component_input)
        return InfoAnalysisResult.model_validate(result.model_dump() | {
            "question_candidates": [{
                "question_id": UUID(int=91), "text": "원상복구 범위를 알려주세요.",
                "resolves_field_paths": ["restoration_scope"],
                "reason_summary": "합성 누락 질문",
            }],
        })

    info.analyze.side_effect = analyze
    graph._supervisor = AsyncMock()
    graph._supervisor.draft.side_effect = (
        RunDeadlineExceededError() if error == "timeout"
        else LLMRequestError("synthetic unavailable", code="SYNTHETIC_COMPONENT_ERROR", retryable=True)
        if error == "component" else ValueError("synthetic invalid output")
    )
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "SAFE_FAILURE"
    assert outcome.failure_code == expected
    assert outcome.retryable is (error != "invalid_output")
    assert outcome.recovery_action_code == (
        "RESUBMIT_INPUT" if error == "invalid_output" else "RETRY"
    )
    assert outcome.requested_field_paths == (
        ["restoration_scope"] if error == "invalid_output" else []
    )
    SafeFailureOutcome.model_validate_json(outcome.model_dump_json())


@pytest.mark.parametrize("changed", ["snapshot", "value"])
def test_graph_stale_confirmation_requires_new_choice_without_requested_fields(changed):
    graph, request, procedure, info, _ = graph_run_inputs("RESULT_SUBMITTED")
    conflict = ConflictCandidate.create(
        conflict_ref="synthetic-conflict", candidate_id=UUID(int=60),
        snapshot_id=UUID(int=61) if changed == "snapshot" else request.case_snapshot.snapshot_id,
        field_path="lease_status", committed_status="CONFIRMED",
        committed_value="LEASED_PAID" if changed == "value" else "OWNED",
        proposed_operation="SET", proposed_status="CONFIRMED", proposed_value="LEASED_FREE",
        source_evidence_refs=["synthetic-document"], source_call_id=UUID(int=3),
    )
    request = AgentGraphInput(
        trigger={"trigger_type": "CONFLICT_CONFIRMED", "input_event_id": "synthetic-confirmation",
                     "client_event_id": None, "confirmed_conflict": conflict, "confirmed_at": NOW},
        case_snapshot=request.case_snapshot,
    )
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "SAFE_FAILURE", outcome
    assert outcome.failure_code == "STALE_CONFLICT_CONFIRMATION"
    assert outcome.recovery_action_code == "RESUBMIT_INPUT"
    assert outcome.retryable is False
    assert outcome.requested_field_paths == []
    procedure.lookup.assert_not_awaited()
    info.analyze.assert_not_awaited()


@result_fixes_xfail(raises=pytest.fail.Exception)
def test_failure_builder_rejects_explicit_conflicting_recovery_and_retryable():
    _, request, _, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    with pytest.raises(ValidationError):
        AgentGraph._build_safe_failure(
            request, run_id=UUID(int=2), trace_id=None,
            failure={"recovery_action_code": "CONTACT_SUPPORT", "retryable": True},
        )


@pytest.mark.parametrize("blocks,expected", [
    pytest.param(None, ["restoration_scope"], marks=result_fixes_xfail()),
    pytest.param(
        ["SUPPORT_ANALYSIS"], [], marks=result_fixes_xfail(raises=AttributeError),
    ),
    pytest.param(
        ["SUPPORT_ANALYSIS", "SUPERVISOR_DECISION"], ["restoration_scope"],
        marks=result_fixes_xfail(raises=AttributeError),
    ),
])
def test_failure_requests_held_facts_without_missing_questions(blocks, expected):
    from test_info_replanning import analyze_facts

    text = "원상복구 범위는 없다고 했는데 임대인은 전부 하라고 했어요."
    held = analyze_facts([("restoration_scope", "NOT_REQUIRED", text)], text, requires_confirmation=True)
    assert held.fact_candidates[0].requires_confirmation
    assert held.missing_fields == []
    assert held.question_candidates == []
    if blocks is not None:
        held = InfoAnalysisResult.model_validate(held.model_dump() | {
            "missing_fields": [{
                "field_path": "restoration_scope", "blocks": blocks,
                "reason_summary": "합성 확인 항목", "question_candidate_id": None,
            }],
        })

    failure = {"source_results": [source(held)]}
    requested = AgentGraph._requested_field_paths(failure)
    assert requested == expected
    assert AgentGraph._requested_field_guidance(failure, requested) == (
        {"restoration_scope": "확인한 원상복구 범위가 있으면 알려주세요."}
        if expected else {}
    )


@pytest.mark.parametrize("scope", [None, "NOT_REQUIRED", "PARTIAL", "FULL"])
@pytest.mark.parametrize("origin", ["held", "missing", "question"])
def test_failure_requests_restoration_progress_only_after_scope_confirmation(scope, origin):
    from test_info_replanning import analyze_facts

    _, request, _, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    request.case_snapshot.facts.append(CaseFact(
        field_path="restoration_scope", value_type="ENUM", value=scope,
        status="UNKNOWN" if scope is None else "CONFIRMED",
        evidence_refs=[] if scope is None else ["synthetic-document"],
        updated_at=None if scope is None else NOW,
    ))
    info = supervisor_request().source_results[1].output
    if origin == "held":
        text = "원상복구 범위는 전체이고 작업을 진행하고 있습니다."
        result = analyze_facts([("restoration_scope", "FULL", text), ("restoration_status", "IN_PROGRESS", text)],
                               text, requires_confirmation=True)
        result.fact_candidates[0].requires_confirmation = False  # 아직 검수를 통과한 Case 사실은 아니다.
        info.evidence_records.extend(result.evidence_records)
        info.fact_candidates = result.fact_candidates
    elif origin == "missing":
        info = InfoAnalysisResult.model_validate(info.model_dump() | {"missing_fields": [{
            "field_path": "restoration_status", "reason_summary": "합성 진행 확인",
            "blocks": ["SUPERVISOR_DECISION"], "question_candidate_id": None,
        }]})
    else:
        info = InfoAnalysisResult.model_validate(info.model_dump() | {"question_candidates": [{
            "question_id": UUID(int=92), "text": "원상복구 진행을 알려주세요.",
            "resolves_field_paths": ["restoration_status"], "reason_summary": "합성 진행 확인",
        }]})
    outcome = AgentGraph._build_safe_failure(
        request, run_id=UUID(int=2), trace_id=None,
        failure={"source_results": [source(info)]},
    )

    assert outcome.requested_field_paths == (["restoration_status"] if scope in {"PARTIAL", "FULL"} else [])


@pytest.mark.parametrize("failure", [
    pytest.param("supervisor", marks=result_fixes_xfail()),
    "timeout",
    pytest.param("review_exhausted", marks=result_fixes_xfail()),
    "support_rework",
])
def test_graph_failure_keeps_held_fact_recovery(failure):
    from test_info_replanning import analyze_facts

    from app.agent.run_scope import RunDeadlineExceededError

    async def review(subject):
        return ReviewResult(
            reviewed_subject_id=subject.review_subject_id,
            reviewed_subject_digest=subject.subject_digest,
            verdict="REVISE", issues=[],
            missing_evidence=[{
                "claim_path": "/supervisor_draft/decision/blocker",
                "required_source_types": ["USER_INPUT"],
                "reason_summary": "합성 보류 사실 확인 요청",
            }],
            recommended_rework_targets=[
                "SUPPORT_AGENT" if failure == "support_rework" else "SUPERVISOR"
            ],
            resolution_reason="합성 재작업 요청",
        )

    reviewer = AsyncMock()
    reviewer.review.side_effect = review
    graph, request, _, info, support = graph_run_inputs("RESULT_SUBMITTED", reviewer)
    text = "원상복구 범위는 없다고 했는데 임대인은 전부 하라고 했어요."
    request.trigger.input.redacted_text = text
    held = analyze_facts([("restoration_scope", "NOT_REQUIRED", text)], text, requires_confirmation=True)
    original = info.analyze.side_effect

    async def analyze(component_input):
        result = await original(component_input)
        return InfoAnalysisResult.model_validate(result.model_dump() | {
            "fact_candidates": held.fact_candidates,
            "evidence_records": [*result.evidence_records, *held.evidence_records],
        })

    info.analyze.side_effect = analyze
    if failure in {"supervisor", "timeout"}:
        graph._supervisor = AsyncMock()
        graph._supervisor.draft.side_effect = (
            RunDeadlineExceededError() if failure == "timeout"
            else ValueError("synthetic invalid output")
        )

    outcome = asyncio.run(graph.run(request))

    assert outcome.outcome_type == "SAFE_FAILURE", outcome
    assert outcome.recovery_action_code == (
        "RETRY" if failure == "timeout"
        else "CONTACT_SUPPORT" if failure == "support_rework"
        else "RESUBMIT_INPUT"
    )
    assert outcome.retryable is (failure == "timeout")
    assert outcome.requested_field_paths == (
        [] if failure in {"timeout", "support_rework"} else ["restoration_scope"]
    )
    if failure == "review_exhausted":
        assert outcome.failure_code == "REVIEW_RETRY_EXHAUSTED"
        assert reviewer.review.await_count == 3
    support.analyze.assert_not_awaited()
    SafeFailureOutcome.model_validate_json(outcome.model_dump_json())


@result_fixes_xfail()
@pytest.mark.parametrize("choose_question", [False, True])
def test_graph_preserves_held_fact_with_a_model_selected_question_or_action(choose_question):
    from test_info_replanning import analyze_facts

    text = "원상복구 범위는 없다고 했는데 임대인은 전부 하라고 했어요."
    held = analyze_facts([("restoration_scope", "NOT_REQUIRED", text)], text, requires_confirmation=True)
    graph, request, _, info, _ = graph_run_inputs("RESULT_SUBMITTED")
    graph._supervisor._llm = ChoiceModel(information=choose_question)
    request.trigger.input.redacted_text = text
    original = info.analyze.side_effect

    async def analyze(component_input):
        result = await original(component_input)
        return InfoAnalysisResult.model_validate(result.model_dump() | {
            "fact_candidates": held.fact_candidates,
            "evidence_records": [*result.evidence_records, *held.evidence_records],
        })

    info.analyze.side_effect = analyze
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    draft = outcome.review_subject.supervisor_draft
    if choose_question:
        assert draft.decision.decision_type == "NEEDS_MORE_INFO"
        assert draft.decision.next_action is None
        assert draft.decision.questions_for_user == ["확인한 원상복구 범위가 있으면 알려주세요."]
    else:
        assert draft.decision.decision_type == "ACTION"
        assert draft.decision.next_action.action_code == "CONFIRM_TAX_CLOSURE_REQUIREMENTS"
    held_blocker = next(item for item in draft.decision.blockers
                        if item.candidate_id == "missing:restoration_scope")
    assert held.fact_candidates[0].source_evidence_refs[0] in held_blocker.evidence_refs
    assert draft.mutations.fact_changes == []
    assert draft.mutations.procedure_progress_changes == []


def batch_conflict_graph(accepted=(True, False)):
    from test_info_replanning import Responses, finding, output

    from app.agent.info_agent.agent import InfoAnalysisAgent

    graph, original, procedure, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    snapshot = original.case_snapshot.model_copy(deep=True)
    conflicts = [
        ConflictCandidate.create(
            conflict_ref=f"stored-conflict-{index}", candidate_id=UUID(int=100 + index),
            snapshot_id=snapshot.snapshot_id, field_path=field,
            committed_status="CONFIRMED", committed_value=before,
            proposed_operation="SET", proposed_status="CONFIRMED", proposed_value=after,
            source_evidence_refs=["synthetic-document"], source_call_id=UUID(int=110),
        )
        for index, (field, before, after) in enumerate([
            ("franchise_status", False, True), ("lease_status", "OWNED", "LEASED_FREE"),
        ])
    ]
    request = AgentGraphInput(
        trigger=ConflictConfirmedTrigger(
            trigger_type="CONFLICT_CONFIRMED", input_event_id="batch-choice", client_event_id=None,
            conflicts=conflicts, selections=[
                {"conflict_ref": item.conflict_ref, "accepted": chosen}
                for item, chosen in zip(conflicts, accepted, strict=True)
            ], conflict_snapshot=snapshot.model_copy(deep=True), confirmed_at=NOW,
        ), case_snapshot=snapshot,
    )
    client = Responses(output([finding("FILE_TAX_BUSINESS_CLOSURE", "doc1")]))
    graph._info_agent = InfoAnalysisAgent(client, clock=lambda: NOW, max_local_attempts=1)
    return graph, request, client, procedure


@pytest.mark.parametrize("accepted", [(True, False), (False, True), (False, False), (True, True)])
def test_batch_conflicts_replan_once_with_only_the_selected_values(accepted):
    graph, request, client, procedure = batch_conflict_graph(accepted)
    before = request.model_dump_json()
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    changes = outcome.review_subject.supervisor_draft.mutations.fact_changes
    assert {(item.confirmed_conflict_ref, item.proposed_value) for item in changes} == {
        (item.conflict_ref, item.proposed_value)
        for item, chosen in request.trigger.choices() if chosen
    }
    assert request.model_dump_json() == before
    assert len(client.messages) == 1
    assert json.loads(client.messages[0][1]["content"].removeprefix("INPUT_JSON="))["input"] is None
    procedure.lookup.assert_awaited_once()
    assert graph._review_tool._client.calls == 1


@pytest.mark.parametrize("forgery", ["rejected_change", "missing_accepted", "different_value"])
def test_batch_review_rejects_changes_that_differ_from_user_choices_before_model_pass(forgery):
    from app.agent.enrichment import build_conflict_overlays

    graph, request, _, _ = batch_conflict_graph()
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    original = outcome.review_subject
    draft = original.supervisor_draft.model_copy(deep=True)
    if forgery == "rejected_change":
        altered = request.trigger.model_copy(deep=True)
        altered.selections[1].accepted = True
        draft.mutations.fact_changes = build_conflict_overlays(request.case_snapshot, altered)
    elif forgery == "missing_accepted":
        draft.mutations.fact_changes = []
    else:
        draft.mutations.fact_changes[0].proposed_value = False
    subject = ReviewSubject.create(**{
        key: getattr(original, key) for key in type(original).model_fields
        if key not in {"subject_digest", "supervisor_draft"}
    }, supervisor_draft=draft)
    client = StubModel()
    with pytest.raises(ReviewIntegrityError):
        asyncio.run(ReviewTool(client).review(subject))
    assert client.calls == 0


def test_batch_review_failure_returns_no_changes_and_preserves_the_original_input():
    graph, request, _, _ = batch_conflict_graph()
    before = request.model_dump_json()

    async def reject(subject):
        return ReviewResult(
            reviewed_subject_id=subject.review_subject_id,
            reviewed_subject_digest=subject.subject_digest, verdict="REVISE", issues=[],
            missing_evidence=[{
                "claim_path": "/supervisor_draft/decision/blocker", "required_source_types": ["USER_INPUT"],
                "reason_summary": "합성 검수 반려",
            }], recommended_rework_targets=["SUPERVISOR"], resolution_reason="합성 검수 반려",
        )

    graph._max_review_revisions = 0
    graph._review_tool = AsyncMock()
    graph._review_tool.review.side_effect = reject
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "SAFE_FAILURE"
    assert outcome.failure_code == "REVIEW_RETRY_EXHAUSTED"
    assert outcome.failed_component == "REVIEW_TOOL"
    assert not hasattr(outcome, "review_subject")
    assert request.model_dump_json() == before


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "unknown_ref", "numeric_boolean"])
def test_batch_conflicts_require_one_strict_choice_per_original_candidate(invalid):
    _, request, _, _ = batch_conflict_graph()
    data = request.trigger.model_dump(mode="json")
    if invalid == "missing":
        data["selections"].pop()
    elif invalid == "duplicate":
        data["selections"][1] = data["selections"][0]
    elif invalid == "unknown_ref":
        data["selections"][1]["conflict_ref"] = "not-an-original-candidate"
    else:
        data["selections"][0]["accepted"] = 1
    with pytest.raises(ValidationError):
        ConflictConfirmedTrigger.model_validate(data)


@pytest.mark.parametrize("changed", ["snapshot_id", "case_id", "case_status", "fact", "progress", "evidence"])
def test_even_rejecting_all_conflicts_requires_the_unchanged_original_state(changed):
    graph, request, client, procedure = batch_conflict_graph((False, False))
    current = request.case_snapshot
    if changed == "snapshot_id":
        current.snapshot_id = UUID(int=999)
    elif changed == "case_id":
        current.case_id = 2
    elif changed == "case_status":
        before = request.model_dump_json()
        with pytest.raises(ValidationError):
            current.case_status = type(current.case_status).COMPLETED
        assert request.model_dump_json() == before
        assert client.messages == []
        procedure.lookup.assert_not_awaited()
        return
    elif changed == "fact":
        current.facts[0].value = "다른 업종"
    elif changed == "progress":
        current.procedure_progress.append(ProcedureProgress.model_validate({
            "procedure_step": graph._known_procedure_steps[0].procedure_step.model_dump(),
            "status": "IN_PROGRESS", "evidence_refs": ["synthetic-document"], "updated_at": NOW,
        }))
    else:
        current.evidence_records[0].excerpt = "달라진 공식 자료"
    before = request.model_dump_json()
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "SAFE_FAILURE", outcome
    assert outcome.failure_code == "STALE_CONFLICT_CONFIRMATION"
    assert request.model_dump_json() == before
    assert client.messages == []
    procedure.lookup.assert_not_awaited()


@pytest.mark.parametrize("operation", ["SET", "CLEAR"])
def test_batch_date_choice_survives_stored_json_and_read_time_changes(operation):
    from app.agent.enrichment import build_conflict_overlays

    _, request, _, _ = batch_conflict_graph()
    snapshot = request.case_snapshot
    snapshot.facts.append(CaseFact(
        field_path="planned_closure_date", value_type="DATE", value=date(2026, 10, 30),
        status="CONFIRMED", evidence_refs=["synthetic-document"], updated_at=NOW,
    ))
    candidate = ConflictCandidate.create(
        conflict_ref="date-choice", candidate_id=UUID(int=120), snapshot_id=snapshot.snapshot_id,
        field_path="planned_closure_date", committed_status="CONFIRMED", committed_value=date(2026, 10, 30),
        proposed_operation=operation, proposed_status="CONFIRMED" if operation == "SET" else "UNKNOWN",
        proposed_value=date(2026, 11, 2) if operation == "SET" else None,
        source_evidence_refs=["synthetic-document"], source_call_id=UUID(int=110),
    )
    trigger = ConflictConfirmedTrigger(
        trigger_type="CONFLICT_CONFIRMED", input_event_id="date-choice", client_event_id=None,
        conflicts=[candidate], selections=[{"conflict_ref": candidate.conflict_ref, "accepted": True}],
        conflict_snapshot=snapshot.model_copy(deep=True), confirmed_at=NOW,
    )
    restored = ConflictConfirmedTrigger.model_validate_json(trigger.model_dump_json())
    snapshot.facts.reverse()
    snapshot.captured_at += timedelta(hours=1)
    change, = build_conflict_overlays(snapshot, restored)
    assert change.operation == operation
    assert str(change.proposed_value) == ("2026-11-02" if operation == "SET" else "None")


@pytest.mark.parametrize("rebuilt", [
    "same_state", "new_snapshot_id", "no_conflict_evidence", "active_blocker", "progress_flag",
])
def test_real_conflict_snapshot_matches_what_be_rebuilds_after_storing_it(rebuilt):
    """BE stores the outcome as JSON, then rebuilds the Case from its DB: second-precision times,
    another row order and captured_at, the conflict evidence it inserted, the stored snapshot ID."""
    from test_info_replanning import Responses, finding, output

    from app.agent.enrichment import StaleConfirmationError, build_conflict_overlays
    from app.agent.info_agent.agent import InfoAnalysisAgent
    from app.agent.schemas import CaseSnapshot, ConflictSelection
    from app.common.agent_service import build_conflict_input

    graph, request, _, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    snapshot = request.case_snapshot.model_copy(deep=True)
    snapshot.procedure_progress.append(ProcedureProgress.model_validate({
        "procedure_step": graph._known_procedure_steps[0].procedure_step.model_dump(),
        "status": "IN_PROGRESS", "requirements_confirmed": True,
        "evidence_refs": ["synthetic-document"], "updated_at": NOW,
    }))
    text = "임대 계약은 자가인 줄 알았는데 무상 임차라고 하셨습니다."
    request = AgentGraphInput(trigger=request.trigger.model_dump() | {
        "input": request.trigger.input.model_dump() | {"redacted_text": text},
    }, case_snapshot=snapshot)
    answer = output([finding("FILE_TAX_BUSINESS_CLOSURE", "doc1")])
    answer["facts"] = [{
        "operation": "SET", "field_path": "lease_status", "value_type": "ENUM", "value": "LEASED_FREE",
        "source_text": "무상 임차라고 하셨습니다", "confidence_bps": 9500,
        "requires_confirmation": False, "reason_summary": "합성 임대차 정정",
    }]
    graph._info_agent = InfoAnalysisAgent(
        Responses(answer), clock=lambda: NOW + timedelta(microseconds=700000), max_local_attempts=1,
    )
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "CONFLICT", outcome

    stored = json.loads(json.dumps({
        "conflicts": [item.model_dump(mode="json") for item in outcome.conflicts],
        "conflict_snapshot": outcome.conflict_snapshot.model_dump(mode="json"),
    }))
    rows = [] if rebuilt == "no_conflict_evidence" else [
        item.model_copy(update={"retrieved_at": item.retrieved_at.replace(microsecond=0)})
        for item in outcome.evidence_records
    ]
    live = snapshot.model_copy(update={
        "snapshot_id": UUID(int=999) if rebuilt == "new_snapshot_id" else outcome.snapshot_id,
        "captured_at": snapshot.captured_at + timedelta(minutes=5),
        "evidence_records": [*snapshot.evidence_records, *rows][::-1],
        "facts": snapshot.facts[::-1],
    }, deep=True)
    if rebuilt == "active_blocker":
        live.active_blocker_candidate_ids = ["held:other"]
    if rebuilt == "progress_flag":
        live.procedure_progress[-1].submitted = True

    conflicts = [ConflictCandidate.model_validate(item) for item in stored["conflicts"]]
    confirmation = build_conflict_input(
        case_snapshot=live, conflicts=conflicts, input_event_id="be-confirm", confirmed_at=NOW,
        conflict_snapshot=CaseSnapshot.model_validate(stored["conflict_snapshot"]),
        selections=[ConflictSelection(conflict_ref=item.conflict_ref, accepted=True) for item in conflicts],
    )
    if rebuilt == "same_state":
        change, = build_conflict_overlays(confirmation.case_snapshot, confirmation.trigger)
        assert change.proposed_value == "LEASED_FREE"
    else:
        with pytest.raises(StaleConfirmationError):
            build_conflict_overlays(confirmation.case_snapshot, confirmation.trigger)
