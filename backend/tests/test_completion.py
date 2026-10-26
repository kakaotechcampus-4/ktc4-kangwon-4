"""Completion needs the full applicable cafe scope and grounded tax follow-ups."""

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
)

from app.agent.action_catalog import resolve_procedure_bindings
from app.agent.completion import (
    CAFE_TRACKED_CODES,
    completed_scope_refs,
    completion_fields,
)
from app.agent.procedure_tool.cafe import build_cafe_procedure_steps
from app.agent.procedure_tool.rules import procedure_applicability
from app.agent.prompts import info_messages
from app.agent.review_tool import ReviewTool
from app.agent.schemas import (
    CaseFact,
    CompletedDecisionDraft,
    FactCandidate,
    FactChangeCandidate,
    MutationSet,
    ProcedureProgress,
    ProcedureProgressChangeCandidate,
    ReviewSubject,
)
from app.agent.supervisor.agent import SupervisorAgent, SupervisorGuardrailError

TAX = "FILE_TAX_BUSINESS_CLOSURE"
EMPLOYMENT_FACTS = (
    "had_employees", "pension_enrolled", "health_insurance_enrolled",
    "employment_insurance_enrolled", "industrial_accident_insurance_enrolled",
)


def complete_request():
    request = supervisor_request().model_copy(deep=True)
    request.known_procedure_steps = sorted(build_cafe_procedure_steps({
        code: index for index, code in enumerate([TAX, *sorted(CAFE_TRACKED_CODES - {TAX})], start=1)
    }), key=lambda item: item.procedure_step.procedure_step_id)
    for fact in request.case_snapshot.facts:
        if fact.field_path == "lease_status":
            fact.value = "LEASED_PAID"
    request.case_snapshot.facts.extend([
        CaseFact(field_path=field, value_type="BOOLEAN", value=True, status="CONFIRMED",
                 evidence_refs=[REF], updated_at=NOW)
        for field in EMPLOYMENT_FACTS
    ])
    request.case_snapshot.facts.extend([
        CaseFact(field_path=field, value_type="ENUM", value=value, status="CONFIRMED",
                 evidence_refs=[REF], updated_at=NOW)
        for field, value in (
            ("restoration_scope", "NOT_REQUIRED"), ("demolition_required", "NOT_REQUIRED"),
        )
    ])
    request.case_snapshot.procedure_progress = [
        ProcedureProgress(procedure_step=step.procedure_step, status="COMPLETED",
                          evidence_refs=[REF], updated_at=NOW)
        for step in request.known_procedure_steps
    ]
    info = request.source_results[1].output.model_copy(deep=True)
    info.procedure_findings[0].current_status = "COMPLETED"
    info.procedure_findings[0].followup_guidance = [{
        "text": "합성 테스트 절차입니다.", "evidence_refs": [REF],
    }]
    request.source_results[1] = source(info)
    return request


def completion(request, changes=None):
    mutations = changes or MutationSet(
        fact_changes=[], procedure_progress_changes=[], support_match_updates=[],
    )
    return completion_fields(
        request, mutations,
        {item.evidence_id: item for item in request.case_snapshot.evidence_records},
        resolve_procedure_bindings(request.known_procedure_steps),
    )


@pytest.mark.parametrize("invalid_guidance", ["missing", "stale", "missing_parent"])
def test_complete_state_alone_cannot_approve_public_completion(invalid_guidance):
    request = complete_request()
    if invalid_guidance == "missing":
        request.source_results[1].output.procedure_findings[0].followup_guidance = []
    elif invalid_guidance == "stale":
        request.case_snapshot.evidence_records[0].freshness_status = "STALE"
    else:
        request.case_snapshot.evidence_records[0].parent_evidence_refs = ["absent-parent"]
    original = request.model_dump_json()
    assert completed_scope_refs(
        request.case_snapshot, request.known_procedure_steps,
        MutationSet(fact_changes=[], procedure_progress_changes=[], support_match_updates=[]),
        resolve_procedure_bindings(request.known_procedure_steps),
    ) == {REF}
    assert completion(request) is None
    assert request.model_dump_json() == original


def test_confirmed_negative_histories_and_scope_facts_need_no_excluded_progress():
    request = complete_request()
    for fact in request.case_snapshot.facts:
        if fact.field_path in EMPLOYMENT_FACTS:
            fact.value = False
        elif fact.field_path == "employee_count":
            fact.value = 0
    request.case_snapshot.procedure_progress = [
        progress for progress in request.case_snapshot.procedure_progress
        if progress.procedure_step.step_code != "CONFIRM_RESTORATION_SCOPE"
        and procedure_applicability(next(
            step for step in request.known_procedure_steps
            if step.procedure_step == progress.procedure_step
        ), request.case_snapshot) is True
    ]
    assert completion(request)["decision_type"] == "COMPLETED"


@pytest.mark.parametrize("state", [
    "complete", "unknown_count", "zero_count", "negative_history", "held_history", "missing_insurance", "unfinished_staff",
])
def test_current_staff_establishes_history_but_not_settlement_or_insurance_completion(state):
    request = complete_request()
    request.case_snapshot.facts = [fact for fact in request.case_snapshot.facts
                                   if fact.field_path not in {"had_employees", "employee_count"}]
    if state != "unknown_count":
        request.case_snapshot.facts.append(CaseFact(
            field_path="employee_count", value_type="INTEGER", value=0 if state == "zero_count" else 2,
            status="CONFIRMED", evidence_refs=[REF], updated_at=NOW,
        ))
    if state == "negative_history":
        request.case_snapshot.facts.append(CaseFact(
            field_path="had_employees", value_type="BOOLEAN", value=False, status="CONFIRMED",
            evidence_refs=[REF], updated_at=NOW,
        ))
    elif state == "missing_insurance":
        request.case_snapshot.facts = [fact for fact in request.case_snapshot.facts if fact.field_path != "pension_enrolled"]
    elif state == "held_history":
        text = "고용한 적이 없습니다."
        request.trigger.input.redacted_text = text
        held_evidence = evidence(evidence_id="synthetic-held-history", source_type="USER_INPUT",
                                 source_ref=request.trigger.input.input_event_id, excerpt=text, content_hash=None)
        request.source_results[1].output.evidence_records.append(held_evidence)
        request.source_results[1].output.fact_candidates = [FactCandidate(
            candidate_id=UUID(int=940), operation="SET", field_path="had_employees",
            value_type="BOOLEAN", value=False, source_evidence_refs=[held_evidence.evidence_id],
            source_span={"input_event_id": request.trigger.input.input_event_id, "text": text,
                         "start_offset": 0, "end_offset": len(text)},
            confidence_bps=10000, requires_confirmation=True,
            reason_summary="현재 직원 수와 고용 이력 보고가 모순됩니다.",
        )]
    elif state == "unfinished_staff":
        next(progress for progress in request.case_snapshot.procedure_progress
             if progress.procedure_step.step_code == "SETTLE_EMPLOYEE_PAYMENTS").status = "NOT_STARTED"
    original = request.model_dump_json()
    changes = MutationSet(fact_changes=[], procedure_progress_changes=[], support_match_updates=[])
    assert (completion(request, changes) is not None) is (state == "complete")
    assert changes.fact_changes == []
    assert request.model_dump_json() == original


def test_existing_restoration_completion_finishes_scope_without_new_work_progress():
    request = complete_request()
    request.case_snapshot.evidence_records.append(evidence(evidence_id="legacy-restoration"))
    next(fact for fact in request.case_snapshot.facts if fact.field_path == "restoration_scope").value = "FULL"
    request.case_snapshot.facts.append(CaseFact(
        field_path="restoration_status", value_type="ENUM", value="COMPLETED",
        status="CONFIRMED", evidence_refs=["legacy-restoration"], updated_at=NOW,
    ))
    request.case_snapshot.procedure_progress = [item for item in request.case_snapshot.procedure_progress
                                              if item.procedure_step.step_code != "PERFORM_RESTORATION"]
    before = request.model_dump_json()
    fields = completion(request)
    assert fields["decision_type"] == "COMPLETED"
    assert "legacy-restoration" in fields["evidence_refs"]
    assert request.model_dump_json() == before


@pytest.mark.parametrize("invalid_state", [
    "partial_registry", "temporary_registry", "deprecated", "not_cafe",
    "unknown_history", "unknown_eligibility", "wrong_progress_code", "wrong_binding_code",
])
def test_state_helper_rejects_incomplete_or_mismatched_scope(invalid_state):
    request = complete_request()
    bindings = dict(resolve_procedure_bindings(request.known_procedure_steps))
    if invalid_state == "partial_registry":
        request.known_procedure_steps = request.known_procedure_steps[:4]
    elif invalid_state == "temporary_registry":
        request.known_procedure_steps[0].registry_version = "temp"
    elif invalid_state == "deprecated":
        request.known_procedure_steps[0].deprecated_at = NOW
    elif invalid_state == "not_cafe":
        next(fact for fact in request.case_snapshot.facts
             if fact.field_path == "business_type").value = "일반음식점"
    elif invalid_state in {"unknown_history", "unknown_eligibility"}:
        field = "had_employees" if invalid_state == "unknown_history" else "demolition_required"
        request.case_snapshot.facts = [
            fact for fact in request.case_snapshot.facts if fact.field_path != field
        ]
    elif invalid_state == "wrong_progress_code":
        progress = request.case_snapshot.procedure_progress[0]
        progress.procedure_step = progress.procedure_step.model_copy(update={"step_code": "WRONG_CODE"})
    else:
        bindings[TAX] = bindings[TAX].model_copy(update={"step_code": "WRONG_CODE"})
    assert completed_scope_refs(
        request.case_snapshot, request.known_procedure_steps,
        MutationSet(fact_changes=[], procedure_progress_changes=[], support_match_updates=[]),
        bindings,
    ) is None


def test_cleared_pending_history_cannot_count_as_a_confirmed_scope_fact():
    request = complete_request()
    change = FactChangeCandidate(
        candidate_id=UUID(int=920), operation="CLEAR", source_fact_candidate_id=UUID(int=921),
        source_type="INFO_ANALYSIS", field_path="had_employees", value_type="BOOLEAN",
        before_status="CONFIRMED", before_value=True, proposed_status="UNKNOWN", proposed_value=None,
        candidate_status="READY_FOR_REVIEW", reason_summary="합성 고용 이력 미확정 변경",
        source_evidence_refs=[REF], source_call_id=UUID(int=3), confirmed_conflict_ref=None,
    )
    original = request.model_dump_json()
    assert completed_scope_refs(
        request.case_snapshot, request.known_procedure_steps,
        MutationSet(fact_changes=[change], procedure_progress_changes=[], support_match_updates=[]),
        resolve_procedure_bindings(request.known_procedure_steps),
    ) is None
    assert request.model_dump_json() == original


class CompletionModel:
    def __init__(self):
        self.calls = 0
        self.messages = []
        self.options = []

    async def generate(self, model, messages, **kwargs):
        self.calls += 1
        self.messages.append(messages)
        self.options.append(kwargs)
        return model.model_validate({
            "decision_type": "COMPLETED", "blocker_candidate_id": None,
            "action_code": None,
        })


def reviewed_subject(request, draft):
    return ReviewSubject.create(
        schema_version="agent-io/2.0", review_subject_id=UUID(int=901), review_attempt=1,
        run_id=UUID(int=2), case_id=1, trigger=request.trigger,
        snapshot=request.case_snapshot, known_procedure_steps=request.known_procedure_steps,
        source_results=request.source_results, supervisor_draft=draft,
    )


def test_completed_supervisor_decision_passes_independent_review_without_a_fake_action():
    async def run():
        request = complete_request()
        client = CompletionModel()
        draft = await SupervisorAgent(client, clock=lambda: NOW).draft(request)
        assert draft.decision.decision_type == "COMPLETED"
        assert draft.decision.blocker is None
        assert draft.decision.blockers == []
        assert draft.decision.next_action is None
        assert draft.decision.questions_for_user == []
        assert draft.decision.followup_guidance
        assert len(draft.grounded_claims) == len(draft.decision.followup_guidance) + 1
        assert draft.grounded_claims[0].claim_type == "TAX"
        result = await ReviewTool(StubModel()).review(reviewed_subject(request, draft))
        assert result.verdict == "PASS", result
        assert client.calls == 1
        payload = json.loads(client.messages[0][1]["content"].removeprefix("INPUT_JSON="))
        contract = payload["contract"]
        assert contract["completion_candidate"]["decision_type"] == "COMPLETED"
        assert contract["allowed_decision_types"] == ["COMPLETED"]
        assert client.options[0]["enum_constraints"]["decision_type"] == ["COMPLETED"]
        assert contract["action_count"]["COMPLETED"] == 0
        assert contract["blocker_count"]["COMPLETED"] == {"exactly": 0}
        assert contract["primary_blocker_count"]["COMPLETED"] == 0
        assert contract["action_count"]["ACTION"] == 1
        assert contract["action_count"]["NEEDS_MORE_INFO"] == 0
        system = client.messages[0][0]["content"]
        assert "completion_candidate가 있으면 COMPLETED" in system
        for empty in ("blocker_candidate_id=null", "action_code=null"):
            assert empty in system

    asyncio.run(run())


def test_completion_runtime_binds_every_tax_guidance_to_its_exact_path_and_refs():
    async def run():
        request = complete_request()
        info = request.source_results[1].output.model_copy(deep=True)
        guidance = [
            {"text": "합성 신고 일정은 기준일 다음 달까지입니다.", "evidence_refs": ["tax-schedule"]},
            {"text": "합성 문의처는 관할 기관입니다.", "evidence_refs": ["tax-contact"]},
        ]
        finding = info.procedure_findings[0]
        info.procedure_findings[0] = type(finding).model_validate({
            **finding.model_dump(), "followup_guidance": guidance,
            "evidence_refs": [REF, "tax-schedule", "tax-contact"],
        })
        records = [
            evidence(evidence_id=item["evidence_refs"][0], excerpt=item["text"],
                     source_ref="https://example.org/" + item["evidence_refs"][0])
            for item in guidance
        ]
        lookup = request.source_results[0].output.model_copy(deep=True)
        lookup.evidence_records.extend(records)
        lookup.documents.extend(
            lookup.documents[0].model_copy(update={
                "document_id": UUID(int=910 + index), "excerpt": record.excerpt,
                "evidence_ref": record.evidence_id, "canonical_url": record.source_ref,
            }) for index, record in enumerate(records)
        )
        request.source_results[0] = source(lookup, "PROCEDURE_TOOL", 5)
        info.based_on_procedure_lookup_digest = request.source_results[0].output_digest
        request.source_results[1] = source(info)
        request.case_snapshot.evidence_records.extend(records)
        draft = await SupervisorAgent(CompletionModel(), clock=lambda: NOW).draft(request)
        assert [(claim.claim_type, claim.target_path, claim.text, claim.assertion_level,
                 claim.evidence_refs) for claim in draft.grounded_claims if "/followup_guidance/" in claim.target_path] == [
            ("TAX", f"/supervisor_draft/decision/followup_guidance/{index}/text",
             item["text"], "NEEDS_CONFIRMATION", item["evidence_refs"])
            for index, item in enumerate(guidance)
        ]
        result = await ReviewTool(StubModel()).review(reviewed_subject(request, draft))
        assert result.verdict == "PASS", result

    asyncio.run(run())


def test_inappropriate_copied_tax_guidance_can_rework_its_info_source():
    class ReworkGuidance:
        async def generate(self, model, messages, **kwargs):
            assert "고정 복사된 Supervisor 경로 대신 원본" in messages[0]["content"]
            assert "meta.call_id" in messages[0]["content"]
            return model.model_validate({
                "verdict": "REVISE", "issues": [{
                    "issue_code": "CONTRACT_VIOLATION", "category": "CONTRACT",
                    "severity": "BLOCKING", "target_component": "INFO_AGENT",
                    "target_call_id": str(UUID(int=3)),
                    "target_path": "/source_results/1/output/procedure_findings/0/followup_guidance/0/text",
                    "reason_summary": "합성 후속 안내에 일정·문의처 밖의 납부 방법이 있습니다.",
                    "evidence_refs": [REF],
                }], "missing_evidence": [], "recommended_rework_targets": ["INFO_AGENT"],
                "resolution_reason": "원본 Info 발췌를 고쳐야 합니다.",
            })

    async def run():
        request = complete_request()
        info = request.source_results[1].output.model_copy(deep=True)
        info.procedure_findings[0].followup_guidance = [{
            "text": "합성 납부 방법을 안내합니다.", "evidence_refs": [REF],
        }]
        request.source_results[1] = source(info)
        draft = await SupervisorAgent(CompletionModel(), clock=lambda: NOW).draft(request)
        result = await ReviewTool(ReworkGuidance()).review(reviewed_subject(request, draft))
        assert result.verdict == "REVISE"
        assert result.recommended_rework_targets == ["INFO_AGENT"]
        issue = next(item for item in result.issues if item.target_component == "INFO_AGENT")
        assert issue.target_call_id == request.source_results[1].meta.call_id
        assert issue.target_path.endswith("/followup_guidance/0/text")
        # Replacing Info changes the runtime-owned completion guidance on the next draft.
        info.procedure_findings[0].followup_guidance = [{
            "text": "합성 테스트 절차입니다.", "evidence_refs": [REF],
        }]
        request.source_results[1] = source(info)
        revised = await SupervisorAgent(CompletionModel(), clock=lambda: NOW).draft(request)
        assert revised.decision.followup_guidance[0].text == "합성 테스트 절차입니다."
        system = info_messages({})[0]["content"]
        assert "일정·문의처만 담으세요" in system
        assert "납부 실행 방법·장소" in system

    asyncio.run(run())


@pytest.mark.parametrize("invalid", [
    {"decision_type": "NEEDS_MORE_INFO"},
    {"blocker_candidate_id": "procedure:1"},
    {"action_code": "FILE_TAX_BUSINESS_CLOSURE"},
])
def test_invalid_completion_choices_are_retried_without_automatic_replacement(invalid):
    class RetryCompletion(CompletionModel):
        async def generate(self, model, messages, **kwargs):
            valid = await super().generate(model, messages, **kwargs)
            return model.model_validate(valid.model_dump() | invalid) if self.calls == 1 else valid

    client = RetryCompletion()
    draft = asyncio.run(SupervisorAgent(client, clock=lambda: NOW, max_local_attempts=2).draft(complete_request()))
    assert draft.decision.decision_type == "COMPLETED"
    assert client.calls == 2
    retry = client.messages[1][-1]["content"]
    assert "contract.completion_candidate" in retry and "COMPLETED" in retry
    assert "blocker_candidate_id=null" in retry and "action_code=null" in retry


def test_completion_without_a_candidate_fails_instead_of_becoming_an_action():
    client = CompletionModel()
    with pytest.raises(SupervisorGuardrailError):
        asyncio.run(SupervisorAgent(client, max_local_attempts=2).draft(supervisor_request()))
    assert client.calls == 2
    payload = json.loads(client.messages[0][1]["content"].removeprefix("INPUT_JSON="))
    assert payload["contract"]["completion_candidate"] is None
    assert payload["contract"]["allowed_decision_types"] == ["ACTION", "NEEDS_MORE_INFO"]
    assert client.options[0]["enum_constraints"]["decision_type"] == ["ACTION", "NEEDS_MORE_INFO"]


def test_public_cafe_builder_covers_all_eight_procedures_with_real_conditions():
    request = complete_request()
    by_code = {item.procedure_step.step_code: item for item in request.known_procedure_steps}
    assert set(by_code) == CAFE_TRACKED_CODES
    assert by_code["RETURN_PREMISES"].dependencies
    assert by_code["REPORT_EMPLOYEE_INSURANCE_LOSS"].eligibility_conditions
    ids = {item.procedure_step.step_code: item.procedure_step.procedure_step_id
           for item in request.known_procedure_steps}
    ids.pop(TAX)
    with pytest.raises(ValueError):
        build_cafe_procedure_steps(ids)


@pytest.mark.parametrize("incomplete", [
    "partial_registry", "temporary_registry", "not_started", "in_progress",
    "missing_tax_guidance", "stale_tax_evidence", "user_tax_evidence", "unknown_scope",
])
def test_incomplete_or_untrusted_inputs_cannot_end_tracking(incomplete):
    request = complete_request()
    if incomplete == "partial_registry":
        request.known_procedure_steps.pop()
    elif incomplete == "temporary_registry":
        request.known_procedure_steps[0].registry_version = "temp"
    elif incomplete in {"not_started", "in_progress"}:
        request.case_snapshot.procedure_progress[0].status = incomplete.upper()
    elif incomplete == "missing_tax_guidance":
        request.source_results[1].output.procedure_findings[0].followup_guidance = []
    elif incomplete == "stale_tax_evidence":
        request.case_snapshot.evidence_records[0].freshness_status = "STALE"
    elif incomplete == "user_tax_evidence":
        request.case_snapshot.evidence_records[0].source_type = "USER_INPUT"
    else:
        request.case_snapshot.facts = [
            item for item in request.case_snapshot.facts if item.field_path != "restoration_scope"
        ]
    assert completion(request) is None


@pytest.mark.parametrize("field", EMPLOYMENT_FACTS)
def test_unknown_employment_or_insurance_history_without_staff_evidence_blocks_completion(field):
    request = complete_request()
    request.case_snapshot.facts = [item for item in request.case_snapshot.facts if item.field_path != field]
    assert completion(request) is None


def test_conflicting_current_staff_and_history_require_confirmation_before_completion():
    from test_blocker_candidates import ChoiceModel

    async def run():
        request = complete_request()
        request.case_snapshot.facts = [
            fact for fact in request.case_snapshot.facts if fact.field_path != "employee_count"
        ]
        request.case_snapshot.facts.append(CaseFact(
            field_path="employee_count", value_type="INTEGER", value=3,
            status="CONFIRMED", evidence_refs=[REF], updated_at=NOW,
        ))
        for fact in request.case_snapshot.facts:
            if fact.field_path in EMPLOYMENT_FACTS:
                fact.value = False
        staff_step = next(step for step in request.known_procedure_steps
                          if step.procedure_step.step_code == "SETTLE_EMPLOYEE_PAYMENTS")
        request.case_snapshot.procedure_progress = [
            progress for progress in request.case_snapshot.procedure_progress
            if progress.procedure_step.step_code not in {
                "SETTLE_EMPLOYEE_PAYMENTS", "REPORT_EMPLOYEE_INSURANCE_LOSS",
                "REPORT_WORKPLACE_INSURANCE_CLOSURE",
            }
        ]
        request.case_snapshot.active_blocker_candidate_ids = [
            "missing:had_employees", f"procedure:{staff_step.procedure_step.procedure_step_id}",
        ]
        original = request.model_dump_json()
        assert completion(request) is None
        assert procedure_applicability(staff_step, request.case_snapshot) is None

        draft = await SupervisorAgent(ChoiceModel(information=True), clock=lambda: NOW).draft(request)
        assert draft.decision.decision_type == "NEEDS_MORE_INFO"
        assert draft.decision.blocker.candidate_id == "missing:had_employees"
        assert draft.decision.questions_for_user == ["직원을 고용한 적이 있나요?"]
        assert draft.decision.next_action is None
        assert draft.resolved_blocker_candidate_ids == []
        assert draft.mutations.fact_changes == []
        assert request.model_dump_json() == original
        assert (await ReviewTool(StubModel()).review(reviewed_subject(request, draft))).verdict == "PASS"

    asyncio.run(run())


@pytest.mark.parametrize("count,had_employees", [(0, True), (3, True), (0, False), (None, False)])
def test_consistent_or_unknown_staff_count_does_not_reopen_confirmed_history(count, had_employees):
    from app.agent.blocker_candidates import missing_info_fields

    request = complete_request()
    request.case_snapshot.facts = [
        fact for fact in request.case_snapshot.facts if fact.field_path != "employee_count"
    ]
    if count is not None:
        request.case_snapshot.facts.append(CaseFact(
            field_path="employee_count", value_type="INTEGER", value=count,
            status="CONFIRMED", evidence_refs=[REF], updated_at=NOW,
        ))
    next(fact for fact in request.case_snapshot.facts
         if fact.field_path == "had_employees").value = had_employees
    assert completion(request)["decision_type"] == "COMPLETED"
    assert missing_info_fields(
        request.case_snapshot, request.source_results,
        MutationSet(fact_changes=[], procedure_progress_changes=[], support_match_updates=[]),
        known_procedure_steps=request.known_procedure_steps,
    ) is None


def test_last_reviewable_progress_change_counts_without_mutating_the_snapshot():
    request = complete_request()
    progress = request.case_snapshot.procedure_progress[0]
    progress.status = "IN_PROGRESS"
    request.case_snapshot.evidence_records.append(evidence(evidence_id="pending-completion"))
    assert completion(request) is None
    changes = MutationSet(
        fact_changes=[], support_match_updates=[], procedure_progress_changes=[
            ProcedureProgressChangeCandidate(
                candidate_id=UUID(int=902), procedure_step=progress.procedure_step,
                before_status="IN_PROGRESS", proposed_status="COMPLETED",
                reason_summary="합성 처리 완료 확인", execution_evidence_refs=["pending-completion"],
                procedure_analysis_call_id=UUID(int=3),
            ),
        ],
    )
    assert completed_scope_refs(
        request.case_snapshot, request.known_procedure_steps, changes,
        resolve_procedure_bindings(request.known_procedure_steps),
    ) == {REF, "pending-completion"}
    assert completion(request, changes)["decision_type"] == "COMPLETED"
    assert progress.status == "IN_PROGRESS"


def test_completed_schema_requires_guidance_and_forbids_blockers_actions_and_questions():
    fields = completion(complete_request())
    payload = {
        **fields, "draft_id": UUID(int=903), "draft_version": 1,
        "based_on_call_ids": [UUID(int=3)], "created_at": NOW,
    }
    assert CompletedDecisionDraft.model_validate(payload).next_action is None
    for patch in (
        {"followup_guidance": []}, {"questions_for_user": ["추가 질문"]},
        {"blockers": [{"candidate_id": "missing:had_employees", "description": "가짜", "evidence_refs": [REF]}]},
        {"blocker": {"description": "가짜", "evidence_refs": [REF]}},
        {"next_action": {"action_code": "FILE_TAX_BUSINESS_CLOSURE"}},
    ):
        with pytest.raises(ValidationError):
            CompletedDecisionDraft.model_validate(payload | patch)


def test_review_overrides_a_model_pass_if_one_applicable_procedure_is_unfinished():
    async def run():
        request = complete_request()
        draft = await SupervisorAgent(CompletionModel(), clock=lambda: NOW).draft(request)
        request.case_snapshot.procedure_progress[-1].status = "IN_PROGRESS"
        subject = reviewed_subject(request, draft)
        result = await ReviewTool(StubModel()).review(subject)
        assert result.verdict == "REVISE"
        assert any(issue.issue_code == "CONTRACT_VIOLATION" for issue in result.issues)

    asyncio.run(run())


def test_completed_progress_with_a_different_step_code_cannot_end_tracking():
    async def run():
        request = complete_request()
        draft = await SupervisorAgent(CompletionModel(), clock=lambda: NOW).draft(request)
        progress = next(item for item in request.case_snapshot.procedure_progress
                        if item.procedure_step.step_code == "FILE_FOOD_SERVICE_CLOSURE")
        # Preserve the registered definition; only the caller's progress reference is wrong.
        progress.procedure_step = progress.procedure_step.model_copy(update={"step_code": "WRONG_CODE"})
        assert completion(request) is None
        reviewed = await ReviewTool(StubModel()).review(reviewed_subject(request, draft))
        assert reviewed.verdict == "REVISE"
        assert any(item.issue_code == "CONTRACT_VIOLATION" for item in reviewed.issues)
    asyncio.run(run())


@pytest.mark.parametrize("parent_status", ["STALE", "UNKNOWN", None])
def test_current_tax_guidance_cannot_hide_an_untrusted_or_missing_parent(parent_status):
    request = complete_request()
    request.case_snapshot.evidence_records[0].parent_evidence_refs = ["tax-parent"]
    if parent_status is not None:
        request.case_snapshot.evidence_records.append(evidence(
            evidence_id="tax-parent", freshness_status=parent_status,
        ))
    assert completion(request) is None


def test_review_projection_preserves_each_used_body_once_without_changing_the_subject():
    from app.agent.review_tool.tool import (
        _review_prompt_projection,
        _validate_integrity,
    )

    request = complete_request()
    draft = asyncio.run(SupervisorAgent(CompletionModel(), clock=lambda: NOW).draft(request))
    subject = reviewed_subject(request, draft)
    original = subject.model_dump_json()
    context = _validate_integrity(subject)
    payload = _review_prompt_projection(subject, context)
    records = [record for record in payload["snapshot"]["evidence_records"] if record]
    for source_payload in payload["source_results"]:
        records.extend(record for record in source_payload["output"]["evidence_records"] if record)
    assert {record["evidence_id"] for record in records} == set(context.evidence_by_id)
    assert len(records) == len({record["evidence_id"] for record in records})
    assert all(record["excerpt"] == context.evidence_by_id[record["evidence_id"]].excerpt for record in records)
    document = payload["source_results"][0]["output"]["documents"][0]
    assert document["evidence_ref"] in {record["evidence_id"] for record in records}
    assert "excerpt" not in document
    assert subject.model_dump_json() == original



@pytest.mark.parametrize("derive_history", [False, True])
def test_completed_scope_resolves_proven_stored_blockers_and_review_checks_the_same_set(derive_history):
    async def run():
        request = complete_request()
        if derive_history:
            request.case_snapshot.facts = [fact for fact in request.case_snapshot.facts
                                           if fact.field_path not in {"had_employees", "employee_count"}]
            request.case_snapshot.facts.append(CaseFact(
                field_path="employee_count", value_type="INTEGER", value=2,
                status="CONFIRMED", evidence_refs=[REF], updated_at=NOW,
            ))
        request.case_snapshot.active_blocker_candidate_ids = [
            "missing:had_employees", "missing:pension_enrolled", "procedure:1", "procedure:999",
        ]
        original = request.model_dump_json()
        draft = await SupervisorAgent(CompletionModel(), clock=lambda: NOW).draft(request)
        assert draft.decision.blocker is None and draft.decision.blockers == []
        assert draft.resolved_blocker_candidate_ids == [
            "missing:had_employees", "missing:pension_enrolled", "procedure:1",
        ]
        assert draft.mutations.fact_changes == []
        assert request.model_dump_json() == original
        assert (await ReviewTool(StubModel()).review(reviewed_subject(request, draft))).verdict == "PASS"
        draft.resolved_blocker_candidate_ids = ["procedure:999"]
        result = await ReviewTool(StubModel()).review(reviewed_subject(request, draft))
        assert result.verdict == "REVISE"
        assert any(issue.target_path == "/supervisor_draft/resolved_blocker_candidate_ids" for issue in result.issues)

    asyncio.run(run())
