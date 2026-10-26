"""The closure MVP does not execute or request input for support programs."""

import asyncio
from itertools import product
from pathlib import Path
from types import SimpleNamespace
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
from app.agent.procedure_tool.store import ReviewedProcedureSnapshot
from app.agent.procedure_tool.stored_tool import StoredProcedureLookupTool
from app.agent.review_tool import ReviewTool
from app.agent.schemas import (
    CASE_FIELD_SPECS,
    AgentGraphInput,
    CaseFact,
    CaseFieldKey,
    ConflictCandidate,
    EvidenceRecord,
    InfoAnalysisResult,
    ReviewResult,
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
        content_safety=AsyncMock(),
        procedure_tool=procedure,
        info_agent=info,
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
    lookup_request = procedure.lookup.await_args.args[0]
    assert lookup_request.procedure_step_codes == [
        item.procedure_step.step_code for item in graph._known_procedure_steps
    ]
    assert lookup_request.search_queries == ["등록 절차 코드 조회"]
    info.analyze.assert_awaited_once()
    support.analyze.assert_not_awaited()


def test_empty_registry_keeps_all_four_bundled_source_topics(monkeypatch):
    graph, request, procedure, _, _ = graph_run_inputs("CASE_CREATED")
    monkeypatch.setattr(graph, "_known_procedure_steps", [])
    snapshot = ReviewedProcedureSnapshot.model_validate_json(
        (Path(__file__).parents[1] / "app/common/reviewed-procedures.ko-KR.json").read_text()
    )
    request.case_snapshot.evidence_records.extend([
        EvidenceRecord(
            evidence_id=record.record_id, source_type="OFFICIAL_DOCUMENT",
            source_ref=record.canonical_url, source_version=snapshot.snapshot_version,
            locator=None, excerpt=record.excerpt, parent_evidence_refs=[],
            published_at=record.published_at, retrieved_at=record.retrieved_at,
            freshness_status="CURRENT", content_hash=record.content_hash,
        ) for record in snapshot.records
    ])
    store = SimpleNamespace(snapshot_version=snapshot.snapshot_version, records=lambda: snapshot.records)
    procedure.lookup.side_effect = StoredProcedureLookupTool(store).lookup

    state = asyncio.run(graph._procedure_node({"request": request, "run_id": UUID(int=91)}))

    lookup_request = procedure.lookup.await_args.args[0]
    assert lookup_request.procedure_step_codes == []
    result = state["source_results"][0].output
    assert {item.evidence_ref for item in result.documents} == {
        record.record_id for record in snapshot.records
    }
    assert result.warnings == []


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
