"""개인 카페 한 Case를 실제 DB에 계속 저장하며 검증한다. 모델 응답만 가짜다."""

import asyncio
import json
from uuid import uuid4

import pytest
from case_world import case_engine  # noqa: F401 — 격리 MySQL 픽스처
from fastapi import HTTPException
from sqlmodel import Session, select

from app.agent import runtime
from app.agent.action_catalog import resolve_procedure_bindings
from app.agent.blocker_candidates import completed_procedure_decision_fields
from app.agent.review_tool import ReviewIntegrityError, ReviewTool
from app.agent.schemas import (
    InfoAnalysisResult,
    ProcedureDependency,
    ProcedureLookupResult,
    ReviewSubject,
)
from app.be.crud import conflict_reference, member
from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import DecisionRecord
from app.be.schemas.case import (
    CaseConflictsDecisionRequest,
    CaseCreateRequest,
    CaseResultsSubmitRequest,
)
from app.be.services import case as case_service
from app.be.services import conflict_decision, judgment
from app.be.services import roadmap as roadmap_service

LANDLORD = "카운터랑 싱크대는 빼고, 간판도 떼야 한대요. 바닥 타일은 그대로 둬도 된대요."
NOT_STARTED = "원상복구와 철거 작업은 아직 시작하지 않았습니다."
RESTORED = "확인한 원상복구와 철거 작업을 모두 완료했습니다."
FOOD_SUBMITTED = "식품영업 폐업신고 했어요."


class ScenarioModel:
    """입력 추출은 합성 응답, 순서는 그 판단의 실제 허용 후보 중 첫 항목을 고른다."""

    def __init__(self, *, report_progress=False):
        self.contracts = []
        self.report_progress = report_progress
        self.review_calls = 0

    async def aclose(self):
        pass

    async def generate(self, response_model, messages, **kwargs):
        name = kwargs["schema_name"]
        data = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))
        if name == "reborn_supervisor_draft":
            contract = data["contract"]
            self.contracts.append(contract)
            rows = contract["blocker_candidates"]
            if rows:
                row = rows[0]
                return response_model.model_validate({"decision_type": "ACTION",
                    "blocker_candidate_id": row["candidate_id"], "action_code": row["actions"][0]["action_code"]})
            return response_model.model_validate({"decision_type": "NEEDS_MORE_INFO",
                "blocker_candidate_id": contract["information_blockers"][0]["candidate_id"], "action_code": None})
        if name == "reborn_review_output":
            self.review_calls += 1
            # 운영 자유글 실패처럼 목록 계약 반려를 내도 코드가 확인한 목록은 통과해야 한다.
            return response_model.model_validate({"verdict": "REVISE", "issues": [{
                "issue_code": "CONTRACT_VIOLATION", "category": "CONTRACT", "severity": "BLOCKING",
                "target_component": "SUPERVISOR", "target_call_id": None,
                "target_path": "/supervisor_draft/decision/blockers", "reason_summary": "합성 목록 계약 반려",
                "evidence_refs": [],
            }], "missing_evidence": [], "recommended_rework_targets": ["SUPERVISOR"],
                "resolution_reason": "합성 목록 계약 반려"})
        assert name == "reborn_info_analysis", name
        text = data["input"]["redacted_text"]
        fact = {"operation": "SET", "value_type": "ENUM", "source_text": text,
                "confidence_bps": 9500, "requires_confirmation": False, "reason_summary": "합성 사용자 보고"}
        facts, observations = [], []
        if text == LANDLORD:
            facts = [fact | {"field_path": "restoration_scope", "value": "PARTIAL"},
                     fact | {"field_path": "demolition_required", "value": "REQUIRED"},
                     fact | {"field_path": "restoration_scope_detail", "value_type": "STRING", "value": LANDLORD}]
        elif text == RESTORED:
            facts = [fact | {"field_path": "restoration_status", "value": "COMPLETED"}]
            if self.report_progress:
                observations = [{"step_code": "PERFORM_RESTORATION", "observed_status": "COMPLETED",
                    "source_text": text, "requires_confirmation": False, "requirements_confirmed": True,
                    "submitted": False, "reason_summary": "합성 작업 완료 보고"}]
        elif text == NOT_STARTED:
            facts = [fact | {"field_path": "restoration_status", "value": "NOT_STARTED"}]
        else:
            assert text == FOOD_SUBMITTED, text
            observations = [{"step_code": "FILE_FOOD_SERVICE_CLOSURE", "observed_status": "IN_PROGRESS",
                "source_text": text, "requires_confirmation": False, "requirements_confirmed": True,
                "submitted": True, "reason_summary": "합성 신고 제출 보고"}]
        return response_model.model_validate({"completion_status": "COMPLETE", "facts": facts,
            "procedure_observations": observations, "missing_fields": [], "uncertainties": []})


class CafeFlow:
    def __init__(self, engine):
        self.engine, self.turns = engine, []
        with Session(engine) as session:
            owner = member.create_member(session, oauth_id=str(uuid4()), nickname="합성 개인카페 사장님")
            case, self.history_id = case_service.create_case(session, owner.id, CaseCreateRequest(
                business_type="CAFE", franchise_status=False, employee_count=2, lease_status="LEASED_PAID",
                has_business_loan=True, has_service_contracts=True, restoration_clause="EXISTS",
                planned_closure_month="2026-11", had_employees=True, pension_enrolled=True,
                health_insurance_enrolled=True, employment_insurance_enrolled=True,
                industrial_accident_insurance_enrolled=True,
            ))
            self.member_id, self.case_id = owner.id, case.id

    def plan(self, *, choices=None):
        service = judgment if choices is None else conflict_decision
        with Session(self.engine) as session:
            request, registry = (service._read_judgment_input(session, self.history_id) if choices is None
                                 else service._read_decision_input(session, self.history_id, choices))
        before = request.model_dump_json()
        outcome = asyncio.run(service._ask_agent(request, registry))
        assert request.model_dump_json() == before
        with Session(self.engine) as session:
            if choices is None:
                service._save_judgment_outcome(session, self.history_id, outcome)
            else:
                service._save_decision_outcome(session, self.history_id, outcome, choices)
        with Session(self.engine) as session:
            history = session.get(CaseHistory, self.history_id)
            self.turns.append((self.history_id, history.judgment_status, history.next_action_code))
            assert outcome.outcome_type != "SAFE_FAILURE", json.dumps({
                "turns": self.turns, "failure": outcome.model_dump(mode="json"),
                "progress_before": {row.procedure_step.step_code: row.status
                                    for row in request.case_snapshot.procedure_progress},
            }, ensure_ascii=False)
            if outcome.outcome_type == "REVIEWED_PLAN":
                outcome.assert_integrity()
                assert history.judgment_status in {"DONE", "NEEDS_MORE_INFO"}
        return outcome

    def submit(self, **answer):
        with Session(self.engine) as session:
            response = case_service.submit_case_results(session, self.member_id,
                CaseResultsSubmitRequest(case_history_id=self.history_id, **answer))
            self.history_id = response.case_history_id
        return self.plan()

    def entry(self):
        with Session(self.engine) as session:
            entry = case_service.get_case_results_entry(session, self.member_id)
            history = session.get(CaseHistory, self.history_id)
            return entry, history.next_action_code

    def progress(self):
        with Session(self.engine) as session:
            case = session.get(Case, self.case_id)
            assert (case.business_type, case.franchise_status, case.employee_count) == ("CAFE", False, 2)
            return {row.procedure_step.step_code: (row.status, row.requirements_confirmed, row.submitted)
                    for row in case.case_procedure_steps}

    def work_status(self):
        with Session(self.engine) as session:
            roadmap = roadmap_service.get_case_roadmap(session, self.member_id)
            return next(task.status for stage in roadmap.stages for task in stage.tasks
                        if task.task_id == "restoration_work")

    def confirm_restored(self):
        assert self.submit(raw_input=RESTORED).outcome_type == "CONFLICT"
        with Session(self.engine) as session:
            case = session.get(Case, self.case_id)
            assert (case.restoration_status, case.demolition_required) == ("NOT_STARTED", "REQUIRED")
            pending = conflict_reference.get_pending_conflicts_by_case_id(session, self.case_id)
            assert {row.canonical_field for row in pending} == {"restoration_status"}
            choices = {row.id: "PROPOSED" for row in pending}
            accepted = case_service.submit_case_conflicts_decision(session, self.member_id,
                CaseConflictsDecisionRequest(decisions=[{"conflict_reference_id": key, "side": value}
                                                       for key, value in choices.items()]))
            self.history_id = accepted.case_history_id
        outcome = self.plan(choices=choices)
        with Session(self.engine) as session:
            case = session.get(Case, self.case_id)
            assert (case.restoration_status, case.demolition_required) == ("COMPLETED", "REQUIRED")
            restoration = next(row for row in case.case_procedure_steps
                               if row.procedure_step.step_code == "PERFORM_RESTORATION")
            assert restoration.status == "COMPLETED"
        return outcome


def assert_completion_proof_cannot_be_reused(outcome, fake):
    for tamper in ("target", "evidence", "selection"):
        subject = outcome.review_subject.model_copy(deep=True)
        change = next(item for item in subject.supervisor_draft.mutations.procedure_progress_changes
                      if item.procedure_step.step_code == "PERFORM_RESTORATION")
        if tamper == "target":
            change.procedure_step = next(item.procedure_step for item in subject.known_procedure_steps
                                         if item.procedure_step.step_code == "RETURN_PREMISES")
        elif tamper == "evidence":
            change.execution_evidence_refs = [next(item.evidence_id for item in subject.snapshot.evidence_records
                                                  if item.evidence_id not in change.execution_evidence_refs)]
        elif subject.trigger.trigger_type == "CONFLICT_CONFIRMED":
            subject.trigger.selections[0].accepted = False
        else:
            subject.trigger.restoration_status_answer = None
        subject = ReviewSubject.create(**{key: getattr(subject, key) for key in type(subject).model_fields
                                          if key != "subject_digest"})
        before = fake.review_calls
        with pytest.raises(ReviewIntegrityError):
            asyncio.run(ReviewTool(fake, max_output_attempts=1).review(subject))
        assert fake.review_calls == before


@pytest.mark.parametrize("free_text_filing,report_progress", [(False, False), (True, True)])
def test_personal_cafe_submission_and_restoration_continue_in_the_same_case(
    case_engine, monkeypatch, free_text_filing, report_progress,
):
    fake = ScenarioModel(report_progress=report_progress)
    monkeypatch.setattr(runtime.StructuredLLMClient, "from_env", classmethod(lambda cls, *a, **k: fake))
    monkeypatch.setattr(runtime.LangfuseTraceSink, "from_env", classmethod(lambda cls, *a, **k: None))
    flow = CafeFlow(case_engine)
    flow.plan()
    entry, action = flow.entry()
    assert entry.result_input_kind == "RESTORATION_ANSWER" and action == "CONFIRM_RESTORATION_SCOPE"
    flow.submit(restoration_answer={"restoration_scope": "PARTIAL", "demolition_required": "REQUIRED"})
    assert flow.entry()[0].judgment_status == "NEEDS_MORE_INFO"
    flow.submit(raw_input=LANDLORD)
    flow.submit(raw_input=NOT_STARTED)
    used_text = False
    visited = set()
    for _ in range(20):
        entry, action = flow.entry()
        assert entry.result_input_kind == "ACTION_DONE", flow.turns
        target = (action, tuple(sorted(flow.progress().items())))
        # A repeated preparation/execution action means the preceding answer was not saved.
        assert target not in visited, flow.turns
        visited.add(target)
        if free_text_filing and action == "FILE_FOOD_SERVICE_CLOSURE" and not used_text:
            flow.submit(raw_input=FOOD_SUBMITTED)
            used_text = True
            assert flow.progress()[action] == ("IN_PROGRESS", True, True)
        else:
            flow.submit(action_done=True)
        progress = flow.progress()
        if action == "CONFIRM_FOOD_SERVICE_CLOSURE_REQUIREMENTS":
            assert progress["FILE_FOOD_SERVICE_CLOSURE"] == ("IN_PROGRESS", True, False)
        elif action == "FILE_FOOD_SERVICE_CLOSURE":
            assert progress[action] == ("IN_PROGRESS", True, True)
        if progress["FILE_FOOD_SERVICE_CLOSURE"][0] == "COMPLETED":
            break
    assert progress["FILE_FOOD_SERVICE_CLOSURE"] == ("COMPLETED", True, True), flow.turns
    assert used_text == free_text_filing
    with Session(case_engine) as session:
        food = next(row for row in session.get(Case, flow.case_id).case_procedure_steps
                    if row.procedure_step.step_code == "FILE_FOOD_SERVICE_CLOSURE")
        history = session.get(CaseHistory, flow.history_id)
        assert history.priority_blocker.candidate_id != f"procedure:{food.procedure_step_id}"
    assert progress["PERFORM_RESTORATION"] == ("IN_PROGRESS", True, False)
    # 작업 완료 글은 이전 NOT_STARTED와 충돌한다. 기존 확인 화면에서 새 값을 골라야 반영한다.
    outcome = flow.confirm_restored()
    assert_completion_proof_cannot_be_reused(outcome, fake)
    allowed = {action["action_code"] for row in fake.contracts[-1]["blocker_candidates"] for action in row["actions"]}
    assert "CONFIRM_PREMISES_RETURN_REQUIREMENTS" in allowed, (flow.turns, allowed)
    assert "PERFORM_RESTORATION" not in allowed
    with Session(case_engine) as session:
        restoration = next(row for row in session.get(Case, flow.case_id).case_procedure_steps
                           if row.procedure_step.step_code == "PERFORM_RESTORATION")
        assert all(row["candidate_id"] != f"procedure:{restoration.procedure_step_id}"
                   for row in fake.contracts[-1]["information_blockers"]), fake.contracts[-1]["information_blockers"]
    flow.submit(action_done=True)
    assert flow.progress()["PERFORM_RESTORATION"][0] == "COMPLETED"
    assert flow.work_status() == "COMPLETED"
    allowed = {action["action_code"] for row in fake.contracts[-1]["blocker_candidates"] for action in row["actions"]}
    assert "CONFIRM_PREMISES_RETURN_REQUIREMENTS" in allowed


def test_new_model_completion_fact_does_not_bypass_pending_owner_confirmation(case_engine, monkeypatch):
    fake = ScenarioModel(report_progress=True)
    monkeypatch.setattr(runtime.StructuredLLMClient, "from_env", classmethod(lambda cls, *a, **k: fake))
    monkeypatch.setattr(runtime.LangfuseTraceSink, "from_env", classmethod(lambda cls, *a, **k: None))
    flow = CafeFlow(case_engine)
    flow.plan()
    flow.submit(restoration_answer={"restoration_scope": "PARTIAL", "demolition_required": "REQUIRED"})
    flow.submit(raw_input=LANDLORD)
    assert flow.entry()[1] == "CONFIRM_RESTORATION_REQUIREMENTS"
    flow.submit(action_done=True)
    with Session(case_engine) as session:
        assert session.get(Case, flow.case_id).restoration_status == "UNKNOWN"
    # 아직 저장된 완료나 충돌 선택이 없다. 모델은 완료 사실과 보류해야 할 완료 관찰을 함께 낸다.
    outcome = flow.submit(raw_input=RESTORED)
    assert outcome.outcome_type == "REVIEWED_PLAN"
    mutations = outcome.review_subject.supervisor_draft.mutations
    assert all(change.procedure_step.step_code != "PERFORM_RESTORATION"
               for change in mutations.procedure_progress_changes)
    allowed = {action["action_code"] for row in fake.contracts[-1]["blocker_candidates"] for action in row["actions"]}
    assert "CONFIRM_PREMISES_RETURN_REQUIREMENTS" not in allowed
    with Session(case_engine) as session:
        restoration = next(row for row in session.get(Case, flow.case_id).case_procedure_steps
                           if row.procedure_step.step_code == "PERFORM_RESTORATION")
        assert restoration.status == "IN_PROGRESS"
        assert any(row["candidate_id"] == f"procedure:{restoration.procedure_step_id}"
                   for row in fake.contracts[-1]["information_blockers"])
    assert flow.work_status() == "IN_PROGRESS"
    # 실제 저장 뒤 다른 준비 버튼을 눌러도 저장된 모델 해석이 사용자 완료 확인으로 변하면 안 된다.
    flow.submit(action_done=True)
    allowed = {action["action_code"] for row in fake.contracts[-1]["blocker_candidates"] for action in row["actions"]}
    assert "CONFIRM_PREMISES_RETURN_REQUIREMENTS" not in allowed
    assert flow.work_status() == "IN_PROGRESS"


def ready_for_final_cafe_action(case_engine, monkeypatch):
    fake = ScenarioModel(report_progress=True)
    monkeypatch.setattr(runtime.StructuredLLMClient, "from_env", classmethod(lambda cls, *a, **k: fake))
    monkeypatch.setattr(runtime.LangfuseTraceSink, "from_env", classmethod(lambda cls, *a, **k: None))
    flow = CafeFlow(case_engine)
    flow.plan()
    flow.submit(restoration_answer={"restoration_scope": "PARTIAL", "demolition_required": "REQUIRED"})
    flow.submit(raw_input=LANDLORD)
    flow.submit(raw_input=NOT_STARTED)
    flow.submit(action_done=True)
    flow.confirm_restored()
    for _ in range(20):
        entry, action = flow.entry()
        assert entry.result_input_kind == "ACTION_DONE", flow.turns
        if action == "SETTLE_EMPLOYEE_PAYMENTS":
            return flow
        flow.submit(action_done=True)
    pytest.fail(f"마지막 직원 정산에 도달하지 못함: {flow.turns}")


def assert_completion_requires_supported_complete_sources(subject):
    for missing in ("unfinished", "business", "registry", "official_source", "info", "prerequisite"):
        changed = subject.model_copy(deep=True)
        sources = changed.source_results
        if missing == "unfinished":
            next(item for item in changed.snapshot.procedure_progress
                 if item.procedure_step.step_code == "FILE_FOOD_SERVICE_CLOSURE").status = "IN_PROGRESS"
        elif missing == "business":
            next(fact for fact in changed.snapshot.facts if fact.field_path == "business_type").value = "RESTAURANT"
        elif missing == "registry":
            changed.known_procedure_steps.pop()
        elif missing == "official_source":
            sources = [item for item in sources if not isinstance(item.output, ProcedureLookupResult)]
        elif missing == "info":
            next(item.output for item in sources if isinstance(item.output, InfoAnalysisResult)).completion_status = "PARTIAL"
        else:
            changed.known_procedure_steps[0].dependencies.append(
                ProcedureDependency(prerequisite_procedure_step_id=999999, dependency_type="SEQUENTIAL"))
        assert completed_procedure_decision_fields(
            changed.snapshot, changed.known_procedure_steps, sources,
            changed.supervisor_draft.mutations, resolve_procedure_bindings(changed.known_procedure_steps),
        ) is None, missing


def test_final_cafe_completion_is_reviewed_saved_and_returns_to_the_roadmap(case_engine, monkeypatch):
    flow = ready_for_final_cafe_action(case_engine, monkeypatch)
    outcome = flow.submit(action_done=True)
    assert outcome.outcome_type == "REVIEWED_PLAN"
    outcome.assert_integrity()
    decision = outcome.review_subject.supervisor_draft.decision
    assert decision.decision_type == "PROCEDURES_COMPLETED"
    assert (decision.blocker, decision.blockers, decision.next_action, decision.questions_for_user) == (
        None, [], None, [],
    )
    assert outcome.review_proof.verdict == "PASS"
    assert flow.progress()["SETTLE_EMPLOYEE_PAYMENTS"] == ("COMPLETED", True, False)
    assert_completion_requires_supported_complete_sources(outcome.review_subject)
    # 후보가 사라졌다는 말만으로 종료를 통과시키지 않는다. 이전 절차가 남으면 독립 검수가 거부한다.
    subject = outcome.review_subject.model_copy(deep=True)
    unfinished = next(item for item in subject.snapshot.procedure_progress
                      if item.procedure_step.step_code == "FILE_TAX_BUSINESS_CLOSURE")
    unfinished.status = "IN_PROGRESS"
    subject = ReviewSubject.create(**{key: getattr(subject, key) for key in type(subject).model_fields
                                      if key != "subject_digest"})
    review = asyncio.run(ReviewTool(ScenarioModel()).review_code_only(subject))
    assert review.verdict == "REVISE"

    class PassingReview:
        async def generate(self, response_model, *args, **kwargs):
            return response_model.model_validate({"verdict": "PASS", "issues": [], "missing_evidence": [],
                "recommended_rework_targets": [], "resolution_reason": "합성 모델 통과"})

    assert asyncio.run(ReviewTool(PassingReview()).review(subject)).verdict == "REVISE"
    with Session(case_engine) as session:
        case = session.get(Case, flow.case_id)
        history = session.get(CaseHistory, flow.history_id)
        record = session.exec(select(DecisionRecord).where(DecisionRecord.case_history_id == history.id)).one()
        assert (case.case_status, case.completed_at) == ("IN_PROGRESS", None)
        assert (history.judgment_status, record.decision_type, record.verdict) == (
            "DONE", "PROCEDURES_COMPLETED", "PASS",
        )
        assert (history.next_action, history.priority_blocker_id) == (None, None)
        home = case_service.get_case(session, flow.member_id)
        entry = case_service.get_case_results_entry(session, flow.member_id)
        status = case_service.get_case_results_submit_status(session, flow.member_id, history.id)
        assert (home.judgment_status, entry.judgment_status, status.result) == ("PROCEDURES_COMPLETED",) * 3
        assert (home.blocker, home.next_action, entry.next_action, status.blocker, status.next_action) == (None,) * 5
        roadmap = roadmap_service.get_case_roadmap(session, flow.member_id)
        tasks = {task.task_id: task for stage in roadmap.stages for task in stage.tasks}
        assert tasks["employee_payments"].status == "COMPLETED"
        assert tasks["vat_submission"].status == "NOT_STARTED"
        assert roadmap.current_stage is not None
        # 절차 안내 종료와 폐업 정리 완료는 다르다. 기존 부가세 체크만 Case를 완료시킨다.
        case_service.update_case_checklist(session, flow.member_id, "vat_submission", True)
    with Session(case_engine) as session:
        assert session.get(Case, flow.case_id).case_status == "COMPLETED"
        assert case_service.get_case(session, flow.member_id).case.case_status == "COMPLETED"
        assert roadmap_service.get_case_roadmap(session, flow.member_id).current_stage is None
        with pytest.raises(HTTPException) as error:
            case_service.submit_case_results(session, flow.member_id,
                CaseResultsSubmitRequest(case_history_id=flow.history_id, raw_input="추가 상황"))
        assert error.value.status_code == 409


def test_final_cafe_completion_is_not_saved_when_review_fails(case_engine, monkeypatch):
    flow = ready_for_final_cafe_action(case_engine, monkeypatch)
    reviewed_types = []

    async def reject_final_review(self, subject):
        reviewed_types.append(subject.supervisor_draft.decision.decision_type)
        raise ReviewIntegrityError("합성 마지막 완료 검수 거부")

    monkeypatch.setattr(ReviewTool, "review", reject_final_review)
    monkeypatch.setattr(ReviewTool, "review_code_only", reject_final_review)
    with Session(case_engine) as session:
        accepted = case_service.submit_case_results(session, flow.member_id,
            CaseResultsSubmitRequest(case_history_id=flow.history_id, action_done=True))
        history_id = accepted.case_history_id
        request, registry = judgment._read_judgment_input(session, history_id)
    outcome = asyncio.run(judgment._ask_agent(request, registry))
    assert outcome.outcome_type == "SAFE_FAILURE"
    assert reviewed_types == ["PROCEDURES_COMPLETED"]
    with Session(case_engine) as session:
        judgment._save_judgment_outcome(session, history_id, outcome)
    with Session(case_engine) as session:
        assert session.get(CaseHistory, history_id).judgment_status == "FAILED"
        assert session.get(Case, flow.case_id).case_status == "IN_PROGRESS"
        assert session.exec(select(DecisionRecord).where(DecisionRecord.case_history_id == history_id)).first() is None
    assert flow.progress()["SETTLE_EMPLOYEE_PAYMENTS"] == ("IN_PROGRESS", True, False)


def test_insurance_completion_waits_for_restoration_report_then_continues_to_return(case_engine, monkeypatch):
    class SettlementFirstModel(ScenarioModel):
        prioritize_settlement = False

        async def generate(self, response_model, messages, **kwargs):
            if self.prioritize_settlement and kwargs["schema_name"] == "reborn_supervisor_draft":
                contract = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))["contract"]
                preferred = next((row for row in contract["blocker_candidates"]
                                  if row["actions"][0]["action_code"] in {
                                      "CONFIRM_EMPLOYEE_SETTLEMENT_REQUIREMENTS", "SETTLE_EMPLOYEE_PAYMENTS",
                                  }), None)
                if preferred is not None:
                    self.contracts.append(contract)
                    return response_model.model_validate({"decision_type": "ACTION",
                        "blocker_candidate_id": preferred["candidate_id"],
                        "action_code": preferred["actions"][0]["action_code"]})
            return await super().generate(response_model, messages, **kwargs)

    fake = SettlementFirstModel(report_progress=True)
    monkeypatch.setattr(runtime.StructuredLLMClient, "from_env", classmethod(lambda cls, *a, **k: fake))
    monkeypatch.setattr(runtime.LangfuseTraceSink, "from_env", classmethod(lambda cls, *a, **k: None))
    flow = CafeFlow(case_engine)
    flow.plan()
    flow.submit(restoration_answer={"restoration_scope": "PARTIAL", "demolition_required": "REQUIRED"})
    flow.submit(raw_input=LANDLORD)
    flow.submit(raw_input=NOT_STARTED)
    flow.submit(action_done=True)
    fake.prioritize_settlement = True
    for _ in range(25):
        entry, action = flow.entry()
        if entry.judgment_status == "NEEDS_MORE_INFO":
            break
        assert entry.result_input_kind == "ACTION_DONE", flow.turns
        assert action not in {"PERFORM_RESTORATION", "CONFIRM_RESTORATION_REQUIREMENTS",
                              "CONFIRM_PREMISES_RETURN_REQUIREMENTS", "RETURN_PREMISES"}, flow.turns
        outcome = flow.submit(action_done=True)
    else:
        pytest.fail(f"원상복구 진행 보고 대기에 도달하지 못함: {flow.turns}")
    assert outcome.outcome_type == "REVIEWED_PLAN"
    decision = outcome.review_subject.supervisor_draft.decision
    assert decision.decision_type == "NEEDS_MORE_INFO" and decision.next_action is None
    question = " ".join(decision.questions_for_user)
    assert all(word in question for word in ("아직", "시작", "진행", "알려")), question
    assert "진행하세요" not in question
    assert outcome.review_proof.verdict == "PASS"
    progress = flow.progress()
    assert all(progress[code][0] == "COMPLETED" for code in (
        "FILE_FOOD_SERVICE_CLOSURE", "FILE_TAX_BUSINESS_CLOSURE", "SETTLE_EMPLOYEE_PAYMENTS",
        "REPORT_EMPLOYEE_INSURANCE_LOSS", "REPORT_WORKPLACE_INSURANCE_CLOSURE",
    ))
    assert progress["PERFORM_RESTORATION"] == ("IN_PROGRESS", True, False)
    assert progress["RETURN_PREMISES"] == ("NOT_STARTED", False, False)
    with Session(case_engine) as session:
        case = session.get(Case, flow.case_id)
        assert (case.restoration_status, case.case_status) == ("NOT_STARTED", "IN_PROGRESS")
        home = case_service.get_case(session, flow.member_id)
        assert home.judgment_status == "NEEDS_MORE_INFO" and home.next_action is None
        assert home.questions_for_user == decision.questions_for_user
    flow.confirm_restored()
    assert flow.entry()[1] == "CONFIRM_PREMISES_RETURN_REQUIREMENTS"
    flow.submit(action_done=True)
    assert flow.entry()[1] == "RETURN_PREMISES"
    terminal = flow.submit(action_done=True)
    assert terminal.review_subject.supervisor_draft.decision.decision_type == "PROCEDURES_COMPLETED"
    assert flow.progress()["RETURN_PREMISES"][0] == "COMPLETED"
    with Session(case_engine) as session:
        case = session.get(Case, flow.case_id)
        assert (case.restoration_status, case.case_status) == ("COMPLETED", "IN_PROGRESS")


def test_prepared_restoration_without_reported_status_asks_status_instead_of_failing(case_engine, monkeypatch):
    # 운영 11/09: 진행 상태를 말한 적 없이 철거 준비만 확인하고 다른 절차를 다 끝내면
    # 할 일·질문·완료가 모두 없어 Supervisor가 멈췄다(STRUCTURED_OUTPUT_FAILED)
    fake = ScenarioModel(report_progress=True)
    monkeypatch.setattr(runtime.StructuredLLMClient, "from_env", classmethod(lambda cls, *a, **k: fake))
    monkeypatch.setattr(runtime.LangfuseTraceSink, "from_env", classmethod(lambda cls, *a, **k: None))
    flow = CafeFlow(case_engine)
    flow.plan()
    flow.submit(raw_input=LANDLORD)
    for _ in range(25):
        entry, action = flow.entry()
        if entry.judgment_status == "NEEDS_MORE_INFO":
            break
        assert entry.result_input_kind == "ACTION_DONE", flow.turns
        assert action not in {"PERFORM_RESTORATION", "RETURN_PREMISES"}, flow.turns
        outcome = flow.submit(action_done=True)
    else:
        pytest.fail(f"진행 상태 질문에 도달하지 못함: {flow.turns}")
    assert outcome.review_proof.verdict == "PASS"
    assert outcome.review_subject.supervisor_draft.decision.questions_for_user == [
        "원상복구 작업이 어디까지 진행됐는지 알려주세요."
    ]
    with Session(case_engine) as session:
        assert session.get(Case, flow.case_id).restoration_status == "UNKNOWN"
    answered = flow.submit(raw_input=NOT_STARTED)
    decision = answered.review_subject.supervisor_draft.decision
    assert decision.decision_type == "NEEDS_MORE_INFO" and decision.next_action is None
    assert "아직 시작 전" in " ".join(decision.questions_for_user)


@pytest.mark.parametrize("waiting_status", [None, "NOT_STARTED", "IN_PROGRESS"],
                         ids=["direct-completion", "not-started", "in-progress"])
def test_restoration_status_question_is_answered_with_buttons_without_info_model(
    case_engine, monkeypatch, waiting_status,
):
    # 진행 상태 질문은 글 대신 [아직 시작 안 했어요 / 진행 중이에요 / 다 끝냈어요]로 받는다
    fake = ScenarioModel(report_progress=True)
    monkeypatch.setattr(runtime.StructuredLLMClient, "from_env", classmethod(lambda cls, *a, **k: fake))
    monkeypatch.setattr(runtime.LangfuseTraceSink, "from_env", classmethod(lambda cls, *a, **k: None))
    flow = CafeFlow(case_engine)
    flow.plan()
    flow.submit(raw_input=LANDLORD)
    for _ in range(25):
        entry, _ = flow.entry()
        if entry.judgment_status == "NEEDS_MORE_INFO":
            break
        flow.submit(action_done=True)
    else:
        pytest.fail(f"진행 상태 질문에 도달하지 못함: {flow.turns}")
    assert entry.result_input_kind == "RESTORATION_STATUS"
    called, generate = [], fake.generate

    async def counted(response_model, messages, **kwargs):
        called.append(kwargs["schema_name"])
        return await generate(response_model, messages, **kwargs)

    monkeypatch.setattr(fake, "generate", counted)
    if waiting_status is None:
        completed = flow.submit(restoration_status="COMPLETED")
        assert completed.review_proof.verdict == "PASS"
        assert not any("info" in name for name in called), called
        assert_completion_proof_cannot_be_reused(completed, fake)
        assert flow.progress()["PERFORM_RESTORATION"] == ("COMPLETED", True, False)
        with Session(case_engine) as session:
            assert session.get(Case, flow.case_id).restoration_status == "COMPLETED"
        assert flow.entry()[1] == "CONFIRM_PREMISES_RETURN_REQUIREMENTS"
        flow.submit(action_done=True)
        terminal = flow.submit(action_done=True)
        assert terminal.review_subject.supervisor_draft.decision.decision_type == "PROCEDURES_COMPLETED"
        return
    waiting = flow.submit(restoration_status=waiting_status)
    assert not any("info" in name for name in called), called
    decision = waiting.review_subject.supervisor_draft.decision
    assert ("아직 시작 전" if waiting_status == "NOT_STARTED" else "진행 중") in " ".join(decision.questions_for_user)
    assert flow.progress()["PERFORM_RESTORATION"] == ("IN_PROGRESS", True, False)
    with Session(case_engine) as session:
        assert session.get(Case, flow.case_id).restoration_status == waiting_status
        history = session.get(CaseHistory, flow.history_id)
        assert history.restoration_status_answer == {"restoration_status": waiting_status}
        assert history.raw_input == ("원상복구와 철거 작업은 아직 시작하지 않았어요."
                                     if waiting_status == "NOT_STARTED" else "원상복구와 철거 작업을 진행하고 있어요.")
    # 철거 준비 뒤 기다리는 질문도 같은 버튼으로 받는다
    assert flow.entry()[0].result_input_kind == "RESTORATION_STATUS"
    # 저장된 미완료 상태와 다르므로 글로 알려줬을 때처럼 사장님 확인(충돌)을 거친다
    assert flow.submit(restoration_status="COMPLETED").outcome_type == "CONFLICT"
    with Session(case_engine) as session:
        pending = conflict_reference.get_pending_conflicts_by_case_id(session, flow.case_id)
        assert {row.canonical_field for row in pending} == {"restoration_status"}
        choices = {row.id: "PROPOSED" for row in pending}
        accepted = case_service.submit_case_conflicts_decision(session, flow.member_id,
            CaseConflictsDecisionRequest(decisions=[{"conflict_reference_id": key, "side": value}
                                                   for key, value in choices.items()]))
        flow.history_id = accepted.case_history_id
    flow.plan(choices=choices)
    with Session(case_engine) as session:
        assert session.get(Case, flow.case_id).restoration_status == "COMPLETED"
    assert flow.entry()[1] == "CONFIRM_PREMISES_RETURN_REQUIREMENTS"
