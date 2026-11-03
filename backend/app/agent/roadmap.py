"""Project saved Case state and a reviewed plan onto the five prototype stages.

No LLM, DB writes or submissions. Callers authenticate the Case, bind its
document Context UUID to the numeric Case ID, and persist checklist reports.
"""

from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from app.agent.action_catalog import (
    ProcedureBindings,
    effective_procedure_progress,
    resolve_procedure_bindings,
)
from app.agent.document_tool.models import DocumentContext
from app.agent.procedure_tool.rules import business_type_code, procedure_applicability
from app.agent.schemas import (
    AgentSchema,
    CaseSnapshot,
    KnownProcedureStep,
    MutationSet,
    NextAction,
    ProcedureStepRef,
    ReviewedPlanOutcome,
    canonical_digest,
    validate_procedure_registry,
)

TaskStatus = Literal["NOT_STARTED", "IN_PROGRESS", "COMPLETED", "NOT_APPLICABLE", "NEEDS_CONFIRMATION"]

STAGES = ("폐업 준비", "원상복구·철거", "영업 마무리·폐업 신고", "지원금 정산·가게 반환", "세금·마무리")
# Checklist titles intentionally omit unverified legal deadlines and amounts.
TASKS = (
    (1, "intake", "상황 진단", "always", ()),
    (1, "closure_date", "폐업 날짜 정하기", "always", ()),
    (1, "notify_landlord", "임대인에게 폐업 알리고 계약 종료일 맞추기", "lease", ()),
    (1, "notify_employees", "직원에게 폐업 알리기", "staff", ()),
    (1, "check_loan", "은행에 폐업 후 상환 조건 확인", "loan", ()),
    (2, "restoration", "원상복구 범위 확인", "lease", ("CONFIRM_RESTORATION_SCOPE",)),
    (2, "support_conditions", "점포철거비 조건 확인", "demolition", ()),
    (2, "support_application", "소상공인24 사전 신청", "demolition", ()),
    (2, "support_approval", "1차 적격심사 결과 확인", "demolition", ()),
    (2, "choose_contractor", "철거 업체 정하기", "demolition", ()),
    (2, "before_photo", "철거 전 사진", "demolition", ()),
    (2, "restoration_work", "원상복구·철거 작업", "lease", ("PERFORM_RESTORATION",)),
    (2, "contractor_documents", "철거 후 서류 받기", "demolition", ()),
    (3, "dispose_stock", "재고·장비 처분", "always", ()),
    (3, "terminate_contracts", "렌탈·공과금 해지", "contracts", ()),
    (3, "employee_payments", "직원 임금·퇴직급여 정산", "always", ("SETTLE_EMPLOYEE_PAYMENTS",)),
    (3, "employee_insurance", "4대보험 상실·탈퇴 신고", "always",
     ("REPORT_EMPLOYEE_INSURANCE_LOSS", "REPORT_WORKPLACE_INSURANCE_CLOSURE")),
    (3, "closure_submission", "통합 폐업 신고", "always", ("FILE_TAX_BUSINESS_CLOSURE", "FILE_FOOD_SERVICE_CLOSURE")),
    (4, "closure_certificate", "폐업사실증명원 발급", "settlement", ()),
    (4, "document_check", "AI 서류 점검", "settlement", ()),
    (4, "settlement_submission", "소상공인24 정산 제출", "settlement", ()),
    (4, "return_premises", "가게 반환", "lease", ("RETURN_PREMISES",)),
    (4, "deposit_settlement", "보증금 정산 기록", "lease", ()),
    (5, "vat_submission", "부가세 폐업 확정신고", "always", ()),
    (5, "income_tax", "종합소득세 신고 여부 확인", "always", ()),
    (5, "post_closure_support", "폐업 후 지원 안내 확인", "always", ()),
)
CHECKLIST_IDS = {key for _, key, _, _, codes in TASKS if not codes} - {
    "intake", "closure_date", "support_approval", "document_check",
}


class CompletedRoadmapSnapshot(CaseSnapshot):
    case_status: Literal["COMPLETED"]


class RoadmapInput(AgentSchema):
    case_snapshot: CaseSnapshot | CompletedRoadmapSnapshot
    known_procedure_steps: list[KnownProcedureStep] = Field(default_factory=list)
    has_business_loan: StrictBool | None = None
    has_service_contracts: StrictBool | None = None
    restoration_clause: Literal["EXISTS", "NOT_EXISTS", "UNKNOWN"] = "UNKNOWN"
    # 사장님이 알려준 점포철거비 1차 적격심사 결과. AI의 자격 판단이 아니고, 뒤의 정산 검토·비용 지급과도 다르다.
    support_approved: StrictBool | None = None
    completed_checklists: set[str] = Field(default_factory=set)
    reviewed_plan: ReviewedPlanOutcome | None = None
    documents: DocumentContext | None = None

    @model_validator(mode="after")
    def check_checklist_ids(self):
        if self.completed_checklists - CHECKLIST_IDS:
            raise ValueError("only user checklists can be checked manually")
        return self


class RoadmapTask(AgentSchema):
    task_id: str
    title: str
    kind: Literal["CHECKLIST", "PROCEDURE", "DOCUMENT_CHECK", "CASE_FACT"]
    status: TaskStatus
    procedure_steps: list[ProcedureStepRef] = Field(default_factory=list)


class RoadmapStage(AgentSchema):
    stage: int
    title: str
    tasks: list[RoadmapTask]


class Roadmap(AgentSchema):
    case_id: int
    snapshot_id: UUID
    supported: StrictBool = True
    unsupported_reason: str | None = None
    stages: list[RoadmapStage]
    next_action: NextAction | None
    next_task_id: str | None
    questions_for_user: list[str]


def _all_conditions(*values: bool | None) -> bool | None:
    if False in values:
        return False
    if None in values:
        return None
    return True


def _procedure_status(codes, steps, bindings, snapshot, mutations, progress):
    states, refs = [], []
    for code in codes:
        ref = bindings.get(code)
        if ref is None:
            states.append("NEEDS_CONFIRMATION")
            continue
        refs.append(ref)
        applies = procedure_applicability(steps[ref.step_code], snapshot, mutations.fact_changes)
        if applies is False:
            states.append("NOT_APPLICABLE")
        elif applies is None:
            states.append("NEEDS_CONFIRMATION")
        else:
            states.append(progress.get((ref.procedure_step_id, ref.step_code), "NOT_STARTED"))
    active = [s for s in states if s != "NOT_APPLICABLE"]
    if not active:
        status = "NOT_APPLICABLE"
    elif "NEEDS_CONFIRMATION" in active:
        status = "NEEDS_CONFIRMATION"
    elif all(s == "COMPLETED" for s in active):
        status = "COMPLETED"
    elif any(s in {"COMPLETED", "IN_PROGRESS"} for s in active):
        status = "IN_PROGRESS"
    else:
        status = "NOT_STARTED"
    return status, refs


def build_roadmap(request: RoadmapInput, *, procedure_bindings: ProcedureBindings | None = None) -> Roadmap:
    """Return a read view; only the existing Review PASS can supply next_action."""
    request = RoadmapInput.model_validate(request.model_dump(mode="python"))
    snapshot, known = request.case_snapshot, request.known_procedure_steps
    mutations = MutationSet(fact_changes=[], procedure_progress_changes=[], support_match_updates=[])
    action, questions = None, []
    if request.reviewed_plan is not None:
        subject = request.reviewed_plan.review_subject
        if canonical_digest(subject.snapshot) != canonical_digest(snapshot):
            raise ValueError("reviewed plan belongs to a different or stale Case snapshot")
        if known and known != subject.known_procedure_steps:
            raise ValueError("procedure registry differs from the reviewed plan")
        known = subject.known_procedure_steps
        mutations = subject.supervisor_draft.mutations
        decision = subject.supervisor_draft.decision
        action, questions = decision.next_action, list(decision.questions_for_user)
    validate_procedure_registry(known)
    bindings = resolve_procedure_bindings(known, procedure_bindings)
    steps = {s.procedure_step.step_code: s for s in known}
    progress = {(p.procedure_step.procedure_step_id, p.procedure_step.step_code): p.status.value
                for p in effective_procedure_progress(snapshot, mutations, known_steps=known, procedure_bindings=bindings)}
    facts = {f.field_path: f.value for f in snapshot.facts if f.status == "CONFIRMED"}
    for change in mutations.fact_changes:
        facts[change.field_path] = change.proposed_value
    if business_type_code(facts.get("business_type")) != "CAFE" or facts.get("franchise_status") is not False:
        return Roadmap(
            case_id=snapshot.case_id, snapshot_id=snapshot.snapshot_id, supported=False,
            unsupported_reason="현재 로드맵은 업종 코드 CAFE인 개인 카페만 지원합니다. 프랜차이즈 카페와 일반 음식점은 지원 준비 중입니다.",
            stages=[], next_action=None, next_task_id=None, questions_for_user=[],
        )
    lease = facts.get("lease_status") in {"LEASED_PAID", "LEASED_FREE"}
    staff = None if facts.get("employee_count") is None else facts["employee_count"] > 0
    demolition = _all_conditions(lease, {"REQUIRED": True, "NOT_REQUIRED": False}.get(facts.get("demolition_required")))
    conditions = {"always": True, "lease": lease, "staff": staff, "loan": request.has_business_loan,
                  "contracts": request.has_service_contracts, "demolition": demolition,
                  "settlement": _all_conditions(demolition, request.support_approved)}
    stages = [RoadmapStage(stage=i, title=t, tasks=[]) for i, t in enumerate(STAGES, 1)]
    for stage, key, title, condition, codes in TASKS:
        applicable = conditions[condition]
        # No service contract still leaves rental and utility cleanup on the roadmap.
        if key == "terminate_contracts":
            if applicable is True:
                title = "카드단말기·배달앱·렌탈·공과금 해지"
            elif applicable is None:
                title = "배달앱·카드단말기 계약 여부 확인 및 렌탈·공과금 해지"
            applicable = None if applicable is None else True
        if codes:
            kind = "PROCEDURE"
        elif key == "document_check":
            kind = "DOCUMENT_CHECK"
        elif key in {"intake", "closure_date", "support_approval"}:
            kind = "CASE_FACT"
        else:
            kind = "CHECKLIST"
        refs = []
        if applicable is False:
            status = "NOT_APPLICABLE"
        elif applicable is None:
            status = "NEEDS_CONFIRMATION"
        else:
            status = "NOT_STARTED"
        if applicable is True:
            if codes:
                status, refs = _procedure_status(codes, steps, bindings, snapshot, mutations, progress)
            elif key in {"intake", "closure_date", "support_approval"}:
                if key == "intake":
                    value = True
                elif key == "closure_date":
                    value = facts.get("planned_closure_date")
                else:
                    value = request.support_approved
                status = "COMPLETED" if value is not None else "NEEDS_CONFIRMATION"
            elif key == "document_check":
                documents = request.documents
                check = documents.document_check if documents else None
                if check is not None:
                    from app.agent.document_tool.checks import document_digest

                    status = ("COMPLETED" if check.document_digest == document_digest(documents)
                              and check.status == "COMPLETE" else "NEEDS_CONFIRMATION")
            elif key in request.completed_checklists:
                status = "COMPLETED"
        stages[stage - 1].tasks.append(RoadmapTask(task_id=key, title=title, kind=kind, status=status, procedure_steps=refs))
    next_task = None
    if action is not None and action.target.target_kind == "PROCEDURE":
        next_task = next((t.task_id for s in stages for t in s.tasks if action.target.procedure_step in t.procedure_steps), None)
    return Roadmap(case_id=snapshot.case_id, snapshot_id=snapshot.snapshot_id, stages=stages,
                   next_action=action, next_task_id=next_task, questions_for_user=questions)


def record_checklist(request: RoadmapInput, task_id: str, *, completed: bool) -> RoadmapInput:
    """Record a user report; this never completes an official procedure or submits."""
    if type(completed) is not bool or task_id not in CHECKLIST_IDS:
        raise ValueError("select a checklist and an explicit boolean completion")
    view = build_roadmap(request)
    if not view.supported:
        raise ValueError(view.unsupported_reason)
    task = next(t for s in view.stages for t in s.tasks if t.task_id == task_id)
    if completed and task.status in {"NOT_APPLICABLE", "NEEDS_CONFIRMATION"}:
        raise ValueError("confirm checklist applicability before checking it")
    result = request.model_copy(deep=True)
    if completed:
        result.completed_checklists.add(task_id)
    else:
        result.completed_checklists.discard(task_id)
    return RoadmapInput.model_validate(result.model_dump(mode="python"))
