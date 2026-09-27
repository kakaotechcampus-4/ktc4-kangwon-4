"""State, existing procedure constraints and independent Review bound choices."""

import asyncio
import json
from uuid import UUID

import pytest
from app.agent.blocker_candidates import build_blocker_candidates, missing_info_fields
from app.agent.review_tool import ReviewTool
from app.agent.schemas import (
    CaseFact,
    FactChangeCandidate,
    KnownProcedureStep,
    MutationSet,
    ProcedureDependency,
    ProcedureProgress,
    ProcedureProgressChangeCandidate,
    ProcedureStepRef,
    QuestionCandidate,
    ReviewSubject,
    canonical_digest,
)
from app.agent.supervisor.agent import SupervisorAgent, SupervisorGuardrailError
from test_action_codes import (
    NOW,
    REF,
    StubModel,
    source,
    supervisor_request,
    support_sources,
)

RESTORATION = ProcedureStepRef(
    procedure_step_id=4, step_code="CONFIRM_RESTORATION_SCOPE"
)


def request_with_state(**values):
    request = supervisor_request().model_copy(deep=True)
    for fact in request.case_snapshot.facts:
        if fact.field_path == "lease_status":
            fact.value = values.pop("lease_status", "LEASED_PAID")
    for key in ("restoration_scope", "demolition_required", "restoration_status"):
        value = values.get(key)
        request.case_snapshot.facts.append(
            CaseFact(
                field_path=key,
                value_type="ENUM",
                value=value,
                status="CONFIRMED" if value is not None else "UNKNOWN",
                evidence_refs=[REF] if value is not None else [],
                updated_at=NOW if value is not None else None,
            )
        )
    lookup = request.source_results[0].output
    lookup.documents[0].step_codes.append(RESTORATION.step_code)
    info = request.source_results[1].output
    info.procedure_findings.append(
        info.procedure_findings[0].model_copy(
            update={
                "finding_id": UUID(int=50),
                "procedure_step": RESTORATION,
                "step_name": "원상복구 범위 확인",
                "required_actions": [],
            }
        )
    )
    info.based_on_procedure_lookup_digest = canonical_digest(lookup)
    request.source_results = [source(lookup, "PROCEDURE_TOOL", 5), source(info)]
    request.known_procedure_steps.append(
        KnownProcedureStep(
            procedure_step=RESTORATION,
            step_name="원상복구 범위 확인",
            utterance_aliases=[],
            registry_version="synthetic/1",
            applicable_business_type="ALL",
            deprecated_at=None,
            dependencies=[],
            eligibility_conditions=[],
        )
    )
    return request


def mutations(**changes):
    return MutationSet(
        **{
            "fact_changes": [],
            "procedure_progress_changes": [],
            "support_match_updates": [],
        }
        | changes
    )


def candidates(request, changes=None):
    evidence = SupervisorAgent._evidence(request.source_results, request)
    return build_blocker_candidates(
        request.case_snapshot,
        request.known_procedure_steps,
        request.source_results,
        changes or mutations(),
        evidence,
    )


@pytest.mark.parametrize(
    "confirmed,expected",
    [
        ({}, ["원상복구해야 할 범위는 어디까지인가요?", "철거가 필요한가요?"]),
        ({"restoration_scope": "PARTIAL"}, ["철거가 필요한가요?"]),
        (
            {"demolition_required": "NOT_REQUIRED"},
            ["원상복구해야 할 범위는 어디까지인가요?"],
        ),
    ],
)
def test_only_unknown_restoration_fields_are_asked(confirmed, expected):
    rows = candidates(request_with_state(**confirmed))
    assert len(rows) == 1
    assert rows[0]["candidate_id"] == "procedure:4"
    assert rows[0]["actions"][0]["questions_to_ask"] == expected
    assert "확인되지 않았습니다" in rows[0]["blocker"]["description"]


def test_overlay_is_used_before_selecting_confirmation_questions():
    change = FactChangeCandidate(
        candidate_id=UUID(int=51),
        operation="SET",
        source_fact_candidate_id=UUID(int=52),
        source_type="INFO_ANALYSIS",
        field_path="restoration_scope",
        value_type="ENUM",
        before_status="UNKNOWN",
        before_value=None,
        proposed_status="CONFIRMED",
        proposed_value="FULL",
        candidate_status="READY_FOR_REVIEW",
        reason_summary="합성 확인 결과",
        source_evidence_refs=[REF],
        source_call_id=UUID(int=3),
        confirmed_conflict_ref=None,
    )
    rows = candidates(request_with_state(), mutations(fact_changes=[change]))
    assert rows[0]["actions"][0]["questions_to_ask"] == ["철거가 필요한가요?"]


@pytest.mark.parametrize(
    "state",
    [
        {"restoration_status": "COMPLETED"},
        {"restoration_scope": "PARTIAL", "demolition_required": "NOT_REQUIRED"},
        {"lease_status": "OWNED"},
    ],
)
def test_resolved_or_inapplicable_restoration_is_not_repeated(state):
    rows = candidates(request_with_state(**state))
    assert rows and all(row["candidate_id"] != "procedure:4" for row in rows)


def test_confirmed_demolition_uses_support_and_does_not_reask_scope():
    request = request_with_state(demolition_required="REQUIRED")
    assert candidates(request) == []
    fallback = missing_info_fields(
        request.case_snapshot, request.source_results, mutations()
    )
    assert "지원 안내" in fallback["blocker"]["description"]
    assert not any("원상복구" in text for text in fallback["questions_for_user"])
    request.source_results.extend(support_sources())
    rows = candidates(request)
    assert len(rows) == 1
    assert (
        rows[0]["actions"][0]["action_code"] == "CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS"
    )


def test_completed_restoration_does_not_ban_unrelated_support():
    request = request_with_state(restoration_status="COMPLETED")
    request.source_results.extend(support_sources())
    assert any(row["candidate_id"] == "support:1" for row in candidates(request))


@pytest.mark.parametrize("blocked_by", ["dependency", "completed", "missing_registry"])
def test_existing_procedure_constraints_filter_candidates(blocked_by):
    request = request_with_state()
    if blocked_by == "dependency":
        request.known_procedure_steps[-1].dependencies = [
            ProcedureDependency(
                prerequisite_procedure_step_id=1, dependency_type="SEQUENTIAL"
            )
        ]
    elif blocked_by == "completed":
        request.case_snapshot.procedure_progress = [
            ProcedureProgress(
                procedure_step=RESTORATION,
                status="COMPLETED",
                evidence_refs=[REF],
                updated_at=NOW,
            )
        ]
    else:
        request.known_procedure_steps.pop()
    assert candidates(request) == []


def test_candidate_count_is_bounded_with_multiple_support_programs():
    request = request_with_state(demolition_required="REQUIRED")
    support = support_sources()[0]
    check = support.output.support_checks[0]
    support.output.support_checks = [
        check.model_copy(
            update={
                "support_program": check.support_program.model_copy(
                    update={"support_program_id": index, "wiki_uuid": UUID(int=index)}
                ),
            }
        )
        for index in range(1, 6)
    ]
    request.source_results.append(support)
    assert len(candidates(request)) == 3


class ChoiceModel(StubModel):
    def __init__(self, invalid=False):
        super().__init__()
        self.invalid = invalid

    async def generate(self, model, messages, **kwargs):
        if kwargs["schema_name"] == "reborn_review_output":
            return await super().generate(model, messages, **kwargs)
        self.calls += 1
        payload = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))
        rows = payload["contract"]["blocker_candidates"]
        if not rows:
            return model.model_validate(
                {
                    "decision_type": "NEEDS_MORE_INFO",
                    "blocker_candidate_id": None,
                    "selection_summary": "이미 정해지지 않았습니다.",
                    "requires_human": True,
                    "evidence_refs": [REF],
                    "blocker": None,
                    "next_action": None,
                    "questions_for_user": [],
                    "grounded_claims": [],
                }
            )
        row, action = rows[0], rows[0]["actions"][0]
        return model.model_validate(
            {
                "decision_type": "ACTION",
                "blocker_candidate_id": "invented"
                if self.invalid
                else row["candidate_id"],
                "selection_summary": "현재 아무것도 정해지지 않았습니다.",
                "requires_human": True,
                "evidence_refs": [REF],
                "blocker": {
                    "description": "철거가 필요합니다.",
                    "evidence_refs": [REF],
                },
                "next_action": {
                    **action,
                    "reason": "원상복구 범위가 정해지지 않았습니다.",
                },
                "questions_for_user": [],
                "grounded_claims": [],
            }
        )


def subject(request, draft):
    return ReviewSubject.create(
        schema_version="agent-io/2.0",
        review_subject_id=UUID(int=90),
        review_attempt=1,
        run_id=UUID(int=2),
        case_id=1,
        trigger=request.trigger,
        snapshot=request.case_snapshot,
        known_procedure_steps=request.known_procedure_steps,
        source_results=request.source_results,
        supervisor_draft=draft,
    )


def test_model_state_invention_is_replaced_and_review_cannot_override_guard():
    async def run():
        request = request_with_state(restoration_scope="PARTIAL")
        draft = await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(
            request
        )
        assert (
            draft.decision.blocker.description
            == "철거 필요 여부가 아직 확인되지 않았습니다."
        )
        assert draft.decision.next_action.questions_to_ask == ["철거가 필요한가요?"]
        review = ReviewTool(
            ChoiceModel(), max_output_attempts=1, provider_max_retries=0
        )
        assert (await review.review(subject(request, draft))).verdict == "PASS"
        draft.decision.next_action.reason = "철거 여부가 정해지지 않았습니다."
        # Keep claim binding valid: the shared candidate guard must still block it.
        for claim in draft.grounded_claims:
            if claim.target_path.endswith("/next_action/reason"):
                claim.text = draft.decision.next_action.reason
        result = await review.review(subject(request, draft))
        assert result.verdict == "REVISE"
        assert any(
            issue.target_path.endswith("/next_action") for issue in result.issues
        )

    asyncio.run(run())


def test_invented_candidate_is_rejected_without_replacing_available_action():
    with pytest.raises(SupervisorGuardrailError):
        asyncio.run(
            SupervisorAgent(ChoiceModel(invalid=True), max_local_attempts=1).draft(
                request_with_state()
            )
        )


def test_no_grounded_action_keeps_safe_question_branch():
    async def run():
        request = request_with_state(demolition_required="REQUIRED")
        draft = await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(
            request
        )
        assert draft.decision.decision_type == "NEEDS_MORE_INFO"
        assert draft.decision.next_action is None
        assert "정해지지" not in draft.decision.blocker.description
        assert "지원 안내" in draft.decision.selection_summary
        result = await ReviewTool(
            ChoiceModel(), max_output_attempts=1, provider_max_retries=0
        ).review(subject(request, draft))
        assert result.verdict == "PASS"

    asyncio.run(run())


def test_support_priority_is_reviewable_with_official_evidence():
    async def run():
        request = request_with_state(demolition_required="REQUIRED")
        request.source_results.append(
            source(support_sources()[0].output, "SUPPORT_AGENT", 6)
        )
        draft = await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(
            request
        )
        assert (
            draft.decision.next_action.action_code
            == "CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS"
        )
        assert not any(
            "철거가 필요한가요" in text
            for text in draft.decision.next_action.questions_to_ask
        )
        result = await ReviewTool(
            ChoiceModel(), max_output_attempts=1, provider_max_retries=0
        ).review(subject(request, draft))
        assert result.verdict == "PASS"

    asyncio.run(run())


def test_registered_filing_keeps_execution_and_confirmation_distinct():
    rows = candidates(request_with_state(lease_status="OWNED"))
    tax = next(row for row in rows if row["candidate_id"] == "procedure:1")
    by_code = {action["action_code"]: action for action in tax["actions"]}
    assert "준비사항을 확인" in by_code["CONFIRM_TAX_CLOSURE_REQUIREMENTS"]["title"]
    filing = by_code["FILE_TAX_BUSINESS_CLOSURE"]
    assert "제출하세요" in filing["title"]
    assert (
        filing["reason"]
        == request_with_state()
        .source_results[1]
        .output.procedure_findings[0]
        .required_actions[0]
        .text
    )
    assert "접수" in filing["questions_to_ask"][0]


@pytest.mark.parametrize(
    "resolution",
    [
        "scope_not_required",
        "status_not_required",
        "status_completed",
        "step_completed",
        "step_completed_overlay",
    ],
)
def test_fallback_does_not_reask_unnecessary_restoration_details(resolution):
    values = {
        "scope_not_required": {"restoration_scope": "NOT_REQUIRED"},
        "status_not_required": {"restoration_status": "NOT_REQUIRED"},
        "status_completed": {"restoration_status": "COMPLETED"},
    }.get(resolution, {})
    request = request_with_state(**values)
    changes = mutations()
    if resolution == "step_completed":
        request.case_snapshot.procedure_progress.append(
            ProcedureProgress(
                procedure_step=RESTORATION,
                status="COMPLETED",
                evidence_refs=[REF],
                updated_at=NOW,
            )
        )
    elif resolution == "step_completed_overlay":
        changes.procedure_progress_changes.append(
            ProcedureProgressChangeCandidate(
                candidate_id=UUID(int=80),
                procedure_step=RESTORATION,
                before_status="NOT_STARTED",
                proposed_status="COMPLETED",
                reason_summary="확인 완료",
                execution_evidence_refs=[REF],
                procedure_analysis_call_id=UUID(int=3),
            )
        )
    request.source_results[1].output.question_candidates = [
        QuestionCandidate(
            question_id=UUID(int=index),
            text="합성 누락 질문",
            resolves_field_paths=[path],
            reason_summary="합성 미확인 항목",
        )
        for index, path in enumerate(
            ("restoration_scope_detail", "demolition_required", "employee_count"), 81
        )
    ]
    result = missing_info_fields(request.case_snapshot, request.source_results, changes)
    if resolution in {"scope_not_required", "status_not_required"}:
        # No inference from restoration to the independent demolition fact.
        assert result["questions_for_user"] == [
            "철거가 필요한지 확인한 내용이 있으면 알려주세요.",
            "직원이 몇 명인가요?",
        ]
    else:
        assert result["questions_for_user"] == ["직원이 몇 명인가요?"]
    assert result["next_action"] is None
