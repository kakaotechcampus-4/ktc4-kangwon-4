"""The closure MVP does not execute or request input for support programs."""

import asyncio
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from test_action_codes import (
    NOW,
    StubModel,
    source,
    supervisor_request,
    support_sources,
)
from test_blocker_candidates import ChoiceModel

from app.agent.graph import AgentGraph
from app.agent.review_tool import ReviewTool
from app.agent.schemas import (
    AgentGraphInput,
    InfoAnalysisResult,
    ReviewResult,
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

    assert AgentGraph._requested_field_paths({
        "source_results": [source(info)],
    }) == ["restoration_scope"]
