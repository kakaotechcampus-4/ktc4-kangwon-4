"""State, existing procedure constraints and independent Review bound choices."""

import asyncio
import json
from uuid import UUID

import pytest
from pydantic import ValidationError
from test_action_codes import (
    NOW,
    REF,
    StubModel,
    evidence,
    source,
    supervisor_request,
    support_sources,
)

from app.agent.blocker_candidates import build_blocker_candidates, missing_info_fields
from app.agent.llm import LLMRequestError
from app.agent.review_tool import ReviewTool
from app.agent.schemas import (
    CaseFact,
    FactChangeCandidate,
    KnownProcedureStep,
    MissingField,
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


def missing_questions(request, *paths):
    info = request.source_results[1].output
    info.question_candidates = [
        QuestionCandidate(
            question_id=UUID(int=index),
            text="합성 누락 질문",
            resolves_field_paths=[path],
            reason_summary="합성 미확인 항목",
        )
        for index, path in enumerate(paths, 81)
    ]
    info.missing_fields = [
        MissingField(
            field_path=question.resolves_field_paths[0],
            reason_summary="현재 판단에 필요한 합성 항목",
            blocks=["SUPERVISOR_DECISION"],
            question_candidate_id=question.question_id,
        )
        for question in info.question_candidates
    ]
    request.source_results[1] = source(info)


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
    assert len(rows) == 2
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


def test_demolition_required_still_prioritizes_unresolved_landlord_scope():
    request = request_with_state(demolition_required="REQUIRED")
    request.source_results.extend(support_sources())
    rows = candidates(request)
    assert rows[0]["actions"][0]["action_code"] == "CONFIRM_RESTORATION_SCOPE"
    assert rows[0]["actions"][0]["questions_to_ask"] == [
        "원상복구해야 할 범위는 어디까지인가요?"
    ]
    assert all(row["candidate_id"].startswith("procedure:") for row in rows)
    assert (
        missing_info_fields(request.case_snapshot, request.source_results, mutations())
        is None
    )


def test_completed_restoration_continues_closure_without_support():
    request = request_with_state(restoration_status="COMPLETED")
    request.source_results.extend(support_sources())
    rows = candidates(request)
    assert [row["candidate_id"] for row in rows] == ["procedure:1"]


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
    assert [row["candidate_id"] for row in candidates(request)] == ["procedure:1"]


def test_support_program_count_does_not_change_closure_candidates():
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
    assert [row["candidate_id"] for row in candidates(request)] == [
        "procedure:4",
        "procedure:1",
    ]


class ChoiceModel(StubModel):
    def __init__(self, invalid=False, choice=0):
        super().__init__()
        self.invalid = invalid
        self.choice = choice

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
                    "blocker": {
                        "description": "판단에 필요한 정보를 확인해 주세요.",
                        "evidence_refs": [REF],
                    },
                    "next_action": None,
                    "questions_for_user": [],
                    "grounded_claims": [],
                }
            )
        row = rows[self.choice]
        action = row["actions"][0]
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


@pytest.mark.parametrize(
    "state",
    [
        {"restoration_scope": "PARTIAL", "restoration_status": "COMPLETED"},
        {"restoration_scope": "PARTIAL", "demolition_required": "NOT_REQUIRED"},
    ],
)
def test_ready_procedure_keeps_one_verified_confirmation_blocker(state):
    async def run():
        request = request_with_state(**state)
        rows = candidates(request)
        assert rows and all(row["blocker"] is not None for row in rows)
        assert all("확인할 필요" in row["blocker"]["description"] for row in rows)
        assert all(row["evidence_refs"] == [REF] for row in rows)

        # ChoiceModel invents a demolition blocker; only the verified candidate
        # supplies the MVP's one evidence-backed blocker in the reviewed output.
        draft = await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(
            request
        )
        assert draft.decision.decision_type == "ACTION"
        assert draft.decision.blocker.description == rows[0]["blocker"]["description"]
        assert "철거" not in draft.decision.blocker.description
        assert draft.decision.next_action is not None
        assert draft.decision.evidence_refs == [REF]
        assert draft.decision.next_action.evidence_refs == [REF]
        assert draft.decision.questions_for_user == []
        assert any("/blocker/" in claim.target_path for claim in draft.grounded_claims)
        assert request.case_snapshot.case_status == "IN_PROGRESS"
        result = await ReviewTool(
            ChoiceModel(), max_output_attempts=1, provider_max_retries=0
        ).review(subject(request, draft))
        assert result.verdict == "PASS"

    asyncio.run(run())


@pytest.mark.parametrize("blocker_kind", ["restoration", "support"])
def test_mvp_schema_rejects_removing_a_verified_blocker(
    blocker_kind,
):
    async def run():
        request = request_with_state(
            **({"demolition_required": "REQUIRED"} if blocker_kind == "support" else {})
        )
        if blocker_kind == "support":
            request.source_results.append(
                source(support_sources()[0].output, "SUPPORT_AGENT", 6)
            )
        draft = await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(
            request
        )
        assert draft.decision.blocker is not None
        with pytest.raises(ValidationError):
            draft.decision.blocker = None

    asyncio.run(run())


@pytest.mark.parametrize("freshness", ["UNKNOWN", "STALE"])
@pytest.mark.parametrize("stale_parent", [False, True])
def test_unverified_procedure_source_keeps_source_confirmation_blocker(
    freshness, stale_parent
):
    request = request_with_state(restoration_status="COMPLETED")
    records = request.source_results[0].output.evidence_records
    if stale_parent:
        records[0].parent_evidence_refs = ["parent"]
        records.append(evidence(evidence_id="parent", freshness_status=freshness))
    else:
        records[0].freshness_status = freshness
    rows = candidates(request)
    assert rows and all(row["blocker"] is not None for row in rows)
    assert all("안내의 현재 적용 여부" in row["blocker"]["description"] for row in rows)
    assert all(
        action["action_code"] == "CONFIRM_TAX_CLOSURE_REQUIREMENTS"
        for row in rows
        for action in row["actions"]
    )


def test_uncertain_restoration_scope_still_allows_landlord_confirmation():
    async def run():
        request = request_with_state()
        info = request.source_results[1].output
        for finding in info.procedure_findings:
            finding.relevance = "POSSIBLY_RELEVANT"
        request.source_results[1] = source(info)

        draft = await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(
            request
        )
        assert draft.decision.decision_type == "ACTION"
        assert draft.decision.next_action.action_code == "CONFIRM_RESTORATION_SCOPE"
        assert draft.decision.next_action.questions_to_ask == [
            "원상복구해야 할 범위는 어디까지인가요?",
            "철거가 필요한가요?",
        ]
        assert draft.mutations.fact_changes == []
        result = await ReviewTool(
            ChoiceModel(), max_output_attempts=1, provider_max_retries=0
        ).review(subject(request, draft))
        assert result.verdict == "PASS"

    asyncio.run(run())


@pytest.mark.parametrize("lease_status", ["LEASED_PAID", "OWNED"])
def test_undetermined_procedure_relevance_keeps_candidates_empty(lease_status):
    request = request_with_state(lease_status=lease_status)
    for finding in request.source_results[1].output.procedure_findings:
        finding.relevance = "UNDETERMINED"
    assert candidates(request) == []


@pytest.mark.parametrize("stale_parent", [False, True])
def test_uncertain_restoration_requires_current_source_chain(stale_parent):
    request = request_with_state()
    request.source_results[1].output.procedure_findings[
        -1
    ].relevance = "POSSIBLY_RELEVANT"
    records = request.source_results[0].output.evidence_records
    if stale_parent:
        records[0].parent_evidence_refs = ["parent"]
        records.append(evidence(evidence_id="parent", freshness_status="STALE"))
    else:
        records[0].freshness_status = "STALE"
    assert [row["candidate_id"] for row in candidates(request)] == ["procedure:1"]


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
        for finding in request.source_results[1].output.procedure_findings:
            finding.relevance = "UNDETERMINED"
        missing_questions(request, "restoration_scope")
        draft = await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(
            request
        )
        assert draft.decision.decision_type == "NEEDS_MORE_INFO"
        assert draft.decision.next_action is None
        assert "정해지지" not in draft.decision.blocker.description
        assert draft.decision.selection_summary == "원상복구 범위 확인이 필요합니다."
        result = await ReviewTool(
            ChoiceModel(), max_output_attempts=1, provider_max_retries=0
        ).review(subject(request, draft))
        assert result.verdict == "PASS"

    asyncio.run(run())


def test_landlord_priority_passes_review_and_does_not_create_support_mutations():
    async def run():
        request = request_with_state(demolition_required="REQUIRED")
        request.source_results.append(
            source(support_sources()[0].output, "SUPPORT_AGENT", 6)
        )
        draft = await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(
            request
        )
        assert draft.decision.next_action.action_code == "CONFIRM_RESTORATION_SCOPE"
        assert draft.mutations.support_match_updates == []
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
    missing_questions(
        request, "restoration_scope_detail", "demolition_required", "employee_count"
    )
    result = missing_info_fields(request.case_snapshot, request.source_results, changes)
    assert result["questions_for_user"] == ["직원이 몇 명인가요?"]
    assert result["next_action"] is None


def test_missing_fallback_asks_one_condition_with_sources_already_available():
    request = request_with_state()
    missing_questions(request, "employee_count", "restoration_scope")
    assert request.source_results[0].output.completion_status == "COMPLETE"

    result = missing_info_fields(
        request.case_snapshot, request.source_results, mutations()
    )

    assert result["questions_for_user"] == ["직원이 몇 명인가요?"]
    assert result["blocker"]["description"] == "직원 수 확인이 필요합니다."
    assert result["selection_summary"] == result["blocker"]["description"]
    assert "안내" not in result["blocker"]["description"]


def test_missing_fallback_uses_stable_order_for_blocking_fields():
    request = request_with_state()
    missing_questions(
        request,
        "planned_closure_date",
        "employee_count",
        "restoration_scope",
        "demolition_required",
    )
    info = request.source_results[1].output
    info.missing_fields[1].blocks = ["SUPPORT_ANALYSIS"]
    info.missing_fields.reverse()
    info.question_candidates.reverse()

    result = missing_info_fields(
        request.case_snapshot, request.source_results, mutations()
    )

    assert result["questions_for_user"] == ["확인한 원상복구 범위가 있으면 알려주세요."]
    assert result["blocker"]["description"] == "원상복구 범위 확인이 필요합니다."


@pytest.mark.parametrize(
    "reason", ["no_questions", "optional_date", "not_blocking", "confirmed"]
)
def test_no_actual_missing_condition_does_not_request_generic_guidance(reason):
    request = request_with_state(restoration_scope="PARTIAL")
    if reason == "optional_date":
        missing_questions(request, "planned_closure_date")
    elif reason == "not_blocking":
        missing_questions(request, "employee_count")
        request.source_results[1].output.missing_fields[0].blocks = ["SUPPORT_ANALYSIS"]
    elif reason == "confirmed":
        missing_questions(request, "restoration_scope")

    assert (
        missing_info_fields(request.case_snapshot, request.source_results, mutations())
        is None
    )


def test_fallback_uses_confirmed_mutations_before_asking():
    request = request_with_state()
    missing_questions(request, "restoration_scope", "employee_count")
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

    result = missing_info_fields(
        request.case_snapshot, request.source_results, mutations(fact_changes=[change])
    )

    assert result["questions_for_user"] == ["직원이 몇 명인가요?"]
    assert result["blocker"]["description"] == "직원 수 확인이 필요합니다."


def test_single_missing_condition_passes_review_without_weakening_shared_guard():
    async def run():
        request = request_with_state()
        for finding in request.source_results[1].output.procedure_findings:
            finding.relevance = "UNDETERMINED"
        missing_questions(request, "employee_count", "restoration_scope")
        draft = await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(
            request
        )
        assert draft.decision.decision_type == "NEEDS_MORE_INFO"
        assert draft.decision.next_action is None
        assert draft.decision.questions_for_user == ["직원이 몇 명인가요?"]
        review = ReviewTool(
            ChoiceModel(), max_output_attempts=1, provider_max_retries=0
        )
        assert (await review.review(subject(request, draft))).verdict == "PASS"

        draft.decision.blocker.description = "폐업 예정일 확인이 필요합니다."
        result = await review.review(subject(request, draft))
        assert result.verdict == "REVISE"
        assert any(
            issue.target_path.endswith("/decision/blocker") for issue in result.issues
        )

    asyncio.run(run())


@pytest.mark.parametrize("freshness", ["CURRENT", "STALE"])
def test_possible_procedure_applies_only_as_current_confirmation(freshness):
    request = request_with_state(lease_status="OWNED")
    info = request.source_results[1].output
    for finding in info.procedure_findings:
        finding.relevance = "POSSIBLY_RELEVANT"
    request.source_results[1] = source(info)
    request.source_results[0].output.evidence_records[0].freshness_status = freshness

    rows = candidates(request)

    if freshness != "CURRENT":
        assert rows == []
        return
    assert len(rows) == 1
    tax = rows[0]
    assert tax["blocker"]["description"] == (
        "사업자 폐업신고 대상 여부와 준비사항을 확인할 필요가 있습니다."
    )
    assert [action["action_code"] for action in tax["actions"]] == [
        "CONFIRM_TAX_CLOSURE_REQUIREMENTS"
    ]
    assert "대상 여부" in tax["actions"][0]["title"]
    assert "대상인지" in tax["actions"][0]["questions_to_ask"][0]


def request_with_all_closure_steps(**values):
    request = request_with_state(**values)
    lookup = request.source_results[0].output
    info = request.source_results[1].output
    for step_id, code, name in (
        (20, "FILE_FOOD_SERVICE_CLOSURE", "식품영업 폐업신고"),
        (10, "REPORT_WORKPLACE_INSURANCE_CLOSURE", "사업장 탈퇴 신고"),
    ):
        reference = ProcedureStepRef(procedure_step_id=step_id, step_code=code)
        lookup.documents[0].step_codes.append(code)
        info.procedure_findings.append(
            info.procedure_findings[0].model_copy(
                update={
                    "finding_id": UUID(int=100 + step_id),
                    "procedure_step": reference,
                    "step_name": name,
                },
                deep=True,
            )
        )
        request.known_procedure_steps.append(
            request.known_procedure_steps[0].model_copy(
                update={"procedure_step": reference, "step_name": name},
                deep=True,
            )
        )
    info.based_on_procedure_lookup_digest = canonical_digest(lookup)
    request.source_results = [source(lookup, "PROCEDURE_TOOL", 5), source(info)]
    return request


def test_all_closure_candidates_are_kept_with_stable_logical_order():
    request = request_with_all_closure_steps()
    expected = ["procedure:4", "procedure:20", "procedure:1", "procedure:10"]
    assert [row["candidate_id"] for row in candidates(request)] == expected
    request.known_procedure_steps.reverse()
    request.source_results[1].output.procedure_findings.reverse()
    request.source_results.reverse()
    assert [row["candidate_id"] for row in candidates(request)] == expected


@pytest.mark.parametrize("downstream_applicable", [True, False])
def test_applicable_prerequisite_precedes_in_progress_procedure(downstream_applicable):
    request = request_with_all_closure_steps(lease_status="OWNED")
    food = request.known_procedure_steps[2].procedure_step
    insurance = request.known_procedure_steps[3]
    insurance.dependencies = [
        ProcedureDependency(
            prerequisite_procedure_step_id=1, dependency_type="SEQUENTIAL"
        )
    ]
    if not downstream_applicable:
        insurance.eligibility_conditions = [
            {"condition_key": "has_employee", "condition_value": "true"}
        ]
    request.case_snapshot.procedure_progress = [
        ProcedureProgress(
            procedure_step=food,
            status="IN_PROGRESS",
            evidence_refs=[REF],
            updated_at=NOW,
        )
    ]
    rows = candidates(request)
    assert [row["candidate_id"] for row in rows] == (
        ["procedure:1", "procedure:20"]
        if downstream_applicable
        else ["procedure:20", "procedure:1"]
    )


def test_in_progress_step_precedes_tie_order_until_completed_overlay():
    request = request_with_all_closure_steps(lease_status="OWNED")
    tax = request.known_procedure_steps[0].procedure_step
    request.case_snapshot.procedure_progress = [
        ProcedureProgress(
            procedure_step=tax,
            status="IN_PROGRESS",
            evidence_refs=[REF],
            updated_at=NOW,
        )
    ]
    assert candidates(request)[0]["candidate_id"] == "procedure:1"
    change = ProcedureProgressChangeCandidate(
        candidate_id=UUID(int=80),
        procedure_step=tax,
        before_status="IN_PROGRESS",
        proposed_status="COMPLETED",
        reason_summary="접수 확인",
        execution_evidence_refs=[REF],
        procedure_analysis_call_id=UUID(int=3),
    )
    rows = candidates(request, mutations(procedure_progress_changes=[change]))
    assert [row["candidate_id"] for row in rows] == ["procedure:20", "procedure:10"]


def test_confirmation_precedes_filing_in_current_schema():
    request = request_with_state(lease_status="OWNED")
    assert (
        candidates(request)[0]["actions"][0]["action_code"]
        == "CONFIRM_TAX_CLOSURE_REQUIREMENTS"
    )
    assert (
        candidates(request)[0]["actions"][1]["action_code"]
        == "FILE_TAX_BUSINESS_CLOSURE"
    )


def test_different_valid_model_choices_produce_same_ranked_action():
    async def run():
        request = request_with_all_closure_steps(demolition_required="REQUIRED")
        decisions = []
        for index in range(4):
            draft = await SupervisorAgent(
                ChoiceModel(choice=index), max_local_attempts=1
            ).draft(request)
            decisions.append((draft.decision.blocker, draft.decision.next_action))
            review = await ReviewTool(ChoiceModel(), max_output_attempts=1).review(
                subject(request, draft)
            )
            assert review.verdict == "PASS"
        assert all(decision == decisions[0] for decision in decisions)
        assert decisions[0][1].action_code == "CONFIRM_RESTORATION_SCOPE"

    asyncio.run(run())


def test_review_rejects_lower_priority_action_despite_model_pass():
    async def run():
        # A tax action is valid by itself, but no longer first when landlord
        # confirmation is still unresolved in the Case being reviewed.
        completed = request_with_state(restoration_status="COMPLETED")
        draft = await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(
            completed
        )
        unresolved = request_with_state()
        review = await ReviewTool(ChoiceModel(), max_output_attempts=1).review(
            subject(unresolved, draft)
        )
        assert review.verdict == "REVISE"
        assert any(
            issue.issue_code == "CONTRACT_VIOLATION"
            and issue.target_path == "/supervisor_draft/decision/next_action"
            for issue in review.issues
        )

    asyncio.run(run())


class UnreachableModel(StubModel):
    """Supervisor 호출만 공급자 장애로 실패시키고 독립 Review는 정상 응답한다."""

    async def generate(self, model, messages, **kwargs):
        if kwargs["schema_name"] == "reborn_review_output":
            return await super().generate(model, messages, **kwargs)
        self.calls += 1
        raise LLMRequestError(
            "LLM provider returned HTTP 503 after 3 attempt(s)",
            code="UPSTREAM_HTTP_ERROR",
            retryable=True,
            attempts=3,
        )


# 할 일 순서는 코드가 정하고 모델은 그 1순위밖에 고를 수 없다. 그래서 모델에 닿지
# 못해도 답은 이미 손에 있다. 판단 전체를 실패로 끝내면 사장님은 빈손이 된다.
def test_unreachable_model_answers_the_same_as_a_working_one():
    async def run():
        request = request_with_all_closure_steps(demolition_required="REQUIRED")
        working = await SupervisorAgent(ChoiceModel(), max_local_attempts=3).draft(
            request
        )
        model = UnreachableModel()
        offline = await SupervisorAgent(model, max_local_attempts=3).draft(request)
        assert offline.decision.decision_type == "ACTION"
        assert offline.decision.blocker == working.decision.blocker
        assert offline.decision.next_action == working.decision.next_action
        # 한 번이 최대 180초인 호출을 더 기다리지 않는다
        assert model.calls == 1
        review = await ReviewTool(ChoiceModel(), max_output_attempts=1).review(
            subject(request, offline)
        )
        assert review.verdict == "PASS"

    asyncio.run(run())
