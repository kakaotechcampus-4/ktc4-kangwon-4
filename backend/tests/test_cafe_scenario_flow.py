"""개인 카페 한 Case를 실제 DB에 계속 저장하며 검증한다. 모델 응답만 가짜다."""

import asyncio
import json
from uuid import uuid4

import pytest
from sqlmodel import Session

from app.agent import runtime
from app.be.crud import conflict_reference, member
from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
from app.be.schemas.case import CaseConflictsDecisionRequest, CaseCreateRequest, CaseResultsSubmitRequest
from app.be.services import case as case_service
from app.be.services import conflict_decision, judgment

from case_world import case_engine  # noqa: F401 — 격리 MySQL 픽스처


LANDLORD = "카운터랑 싱크대는 빼고, 간판도 떼야 한대요. 바닥 타일은 그대로 둬도 된대요."
NOT_STARTED = "원상복구와 철거 작업은 아직 시작하지 않았습니다."
RESTORED = "확인한 원상복구와 철거 작업을 모두 완료했습니다."
FOOD_SUBMITTED = "식품영업 폐업신고 했어요."


class ScenarioModel:
    """입력 추출은 합성 응답, 순서는 그 판단의 실제 허용 후보 중 첫 항목을 고른다."""

    def __init__(self, *, report_progress=False):
        self.contracts = []
        self.report_progress = report_progress

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
        self.plan(choices=choices)
        with Session(self.engine) as session:
            case = session.get(Case, self.case_id)
            assert (case.restoration_status, case.demolition_required) == ("COMPLETED", "REQUIRED")


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
    flow.confirm_restored()
    allowed = {action["action_code"] for row in fake.contracts[-1]["blocker_candidates"] for action in row["actions"]}
    assert "CONFIRM_PREMISES_RETURN_REQUIREMENTS" in allowed, (flow.turns, allowed)
    assert "PERFORM_RESTORATION" not in allowed
    with Session(case_engine) as session:
        restoration = next(row for row in session.get(Case, flow.case_id).case_procedure_steps
                           if row.procedure_step.step_code == "PERFORM_RESTORATION")
        assert all(row["candidate_id"] != f"procedure:{restoration.procedure_step_id}"
                   for row in fake.contracts[-1]["information_blockers"]), fake.contracts[-1]["information_blockers"]
