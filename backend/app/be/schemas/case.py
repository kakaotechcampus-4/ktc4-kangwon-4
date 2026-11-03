from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.agent.roadmap import CHECKLIST_IDS

BusinessType = Literal["CAFE", "RESTAURANT"]
LeaseStatus = Literal["LEASED_PAID", "LEASED_FREE", "OWNED"]
CaseStatus = Literal["IN_PROGRESS", "COMPLETED"]
RestorationStatus = Literal["UNKNOWN", "NOT_STARTED", "IN_PROGRESS", "COMPLETED", "NOT_REQUIRED"]
RestorationScope = Literal["UNKNOWN", "PARTIAL", "FULL", "NOT_REQUIRED"]
DemolitionRequired = Literal["UNKNOWN", "REQUIRED", "NOT_REQUIRED"]
RestorationClause = Literal["EXISTS", "NOT_EXISTS", "UNKNOWN"]
JudgmentStatus = Literal["PENDING", "DONE", "NEEDS_MORE_INFO", "CONFLICT", "FAILED"]
RecoveryActionCode = Literal["RETRY", "RESUBMIT_INPUT", "CONTACT_SUPPORT", "NONE"]
ResultsSubmitResult = Literal["PENDING", "UPDATED", "NO_CHANGE", "NEEDS_MORE_INFO", "CONFLICT", "FAILED"]
ConflictSide = Literal["PROPOSED", "STORED"]
ClosureReason = Literal["BUSINESS_SLUMP", "PERSONAL", "OTHER"]
DepositReturnResult = Literal["FULL", "PARTIAL", "NONE"]
# 사장님이 직접 체크하는 로드맵 항목. AI 로드맵(#132)의 목록을 그대로 쓴다.
ChecklistTaskId = Literal[tuple(sorted(CHECKLIST_IDS))]
CaseLogActor = Literal["OWNER", "RIBBON"]
CaseLogEvent = Literal[
    # 사장님이 한 일
    "CASE_CREATED",
    "RESULT_SUBMITTED",
    "CONFLICT_DECIDED",
    "CHECKLIST_COMPLETED",
    "CHECKLIST_UNCHECKED",
    "SUPPORT_RESULT_REPORTED",
    "DOCUMENT_UPLOADED",
    # 리본이 한 일
    "NEXT_ACTION_DECIDED",
    "MORE_INFO_REQUESTED",
    "CONFLICT_FOUND",
    "JUDGMENT_FAILED",
    "DOCUMENTS_CHECKED",
]


class CaseCreateRequest(BaseModel):
    store_name: str | None = Field(default=None, max_length=50)
    business_type: BusinessType
    franchise_status: bool
    employee_count: int | None = Field(default=None, ge=0, le=1000)
    has_business_loan: bool | None = None
    has_service_contracts: bool | None = None
    lease_status: LeaseStatus
    restoration_clause: RestorationClause = "UNKNOWN"
    planned_closure_date: date | None = None
    # 날짜를 못 정했으면 예상 달만 "YYYY-MM"으로 받는다. 화면에서 셋 중 하나만 고르므로
    # 둘 다 오는 건 FE 실수다. 조용히 하나를 버리면 실수가 묻혀서 422로 거절한다(#145 리뷰)
    planned_closure_month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    # 직원 고용 이력과 사업장 4대보험 가입 이력. 넷 다 "지금"이 아니라 "있었던 적"을 묻는다.
    # 안 보내면 None(=안 물어봄)이고 AI에는 모름으로 넘어간다. 안 물어본 것을 false로
    # 채우면 AI가 해당 절차를 "해당 없음"으로 보고 로드맵에서 빼버린다.
    #
    # 보험 네 칸은 같이 보내야 뜻이 산다. 하나만 false로 오고 나머지가 None이면
    # "해당 없음"이 아니라 "모름"으로 남는다(rules.py:129-136).
    had_employees: bool | None = None
    pension_enrolled: bool | None = None
    health_insurance_enrolled: bool | None = None
    employment_insurance_enrolled: bool | None = None
    industrial_accident_insurance_enrolled: bool | None = None

    @model_validator(mode="after")
    def reject_both_closure_date_and_month(self) -> "CaseCreateRequest":
        if self.planned_closure_date is not None and self.planned_closure_month is not None:
            raise ValueError("planned_closure_date와 planned_closure_month는 하나만 보낸다")
        return self


class CaseCreateResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    member_id: int
    store_name: str | None
    business_type: str
    franchise_status: bool
    employee_count: int | None
    has_business_loan: bool | None
    has_service_contracts: bool | None
    case_status: CaseStatus
    lease_status: LeaseStatus
    restoration_clause: RestorationClause
    restoration_status: RestorationStatus
    restoration_scope: RestorationScope
    restoration_scope_detail: str | None
    demolition_required: DemolitionRequired
    planned_closure_date: date | None
    planned_closure_month: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    
    
class CaseGetDetailResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    member_id: int
    store_name: str | None
    business_type: str
    franchise_status: bool
    employee_count: int | None
    has_business_loan: bool | None
    has_service_contracts: bool | None
    lease_status: LeaseStatus
    restoration_clause: RestorationClause
    restoration_status: RestorationStatus
    restoration_scope: RestorationScope
    restoration_scope_detail: str | None
    demolition_required: DemolitionRequired
    planned_closure_date: date | None
    planned_closure_month: str | None
    # COMPLETED면 폐업 정리를 마친 것. 사장님이 부가세 폐업 확정신고(vat_submission)를 마쳤다고 체크하면 바뀐다
    case_status: CaseStatus
    completed_at: datetime | None

    closure_date: date | None
    closure_reason: ClosureReason | None
    road_address: str | None
    address_detail: str | None
    deposit_return_result: DepositReturnResult | None

class NextActionResponse(BaseModel):
    title: str
    reason: str | None
    questions_to_ask: list[str]


class FieldChangeResponse(BaseModel):
    field: str
    stored_value: str | None
    new_value: str | None


class CaseGetResponse(BaseModel):
    case: CaseGetDetailResponse | None
    blocker: str | None
    next_action: NextActionResponse | None
    judgment_status: JudgmentStatus | None
    case_history_id: int | None
    questions_for_user: list[str] | None
    recovery_action_code: RecoveryActionCode | None
    requested_field_paths: list[str] | None
    retryable: bool | None
    changes: list[FieldChangeResponse] | None


class ConflictItemResponse(BaseModel):
    id: int
    field: str
    stored_value: str | None
    proposed_value: str


class CaseResultsEntryResponse(BaseModel):
    judgment_status: JudgmentStatus
    case_history_id: int | None = None
    raw_input: str | None = None
    conflicts: list[ConflictItemResponse] | None = None
    next_action: NextActionResponse | None = None
    questions_for_user: list[str] | None = None
    recovery_action_code: RecoveryActionCode | None = None
    requested_field_paths: list[str] | None = None
    retryable: bool | None = None


class CaseResultsSubmitRequest(BaseModel):
    raw_input: str
    case_history_id: int


class CaseResultsSubmitAcceptedResponse(BaseModel):
    case_history_id: int


class CaseConflictsDecisionItem(BaseModel):
    conflict_reference_id: int
    side: ConflictSide


class CaseConflictsDecisionRequest(BaseModel):
    decisions: list[CaseConflictsDecisionItem]


class CaseResultsSubmitResponse(BaseModel):
    result: ResultsSubmitResult
    changes: list[FieldChangeResponse] | None = None
    blocker: str | None = None
    next_action: NextActionResponse | None = None
    questions_for_user: list[str] | None = None
    raw_input: str | None = None
    conflicts: list[ConflictItemResponse] | None = None
    recovery_action_code: RecoveryActionCode | None = None
    retryable: bool | None = None
    requested_field_paths: list[str] | None = None


class CaseChecklistUpdateRequest(BaseModel):
    completed: bool


class CaseChecklistResponse(BaseModel):
    task_id: ChecklistTaskId
    completed: bool


class CaseSupportApprovalRequest(BaseModel):
    # 키는 꼭 보내야 하고 값은 null(아직 모름)도 된다. 빠뜨린 요청을 "모름"으로 저장하지 않으려고 기본값을 두지 않는다.
    approved: bool | None


class CaseSupportApprovalResponse(BaseModel):
    approved: bool | None
class CaseLogItem(BaseModel):
    actor: CaseLogActor
    event: CaseLogEvent
    # 한국 시각(+09:00)을 붙여 내려준다. 시간대 없이 주면 브라우저가 자기 시간대로 읽어 시각이 밀린다.
    occurred_at: datetime
    # 체크 기록(CHECKLIST_*)일 때 어떤 항목인지. 그 밖에는 null
    task_id: ChecklistTaskId | None
    # 문구를 만들 때 쓸 값. NEXT_ACTION_DECIDED는 정한 할 일 제목,
    # SUPPORT_RESULT_REPORTED는 APPROVED/REJECTED/UNKNOWN, DOCUMENT_UPLOADED는 올린 서류 종류(예: TRANSFER).
    # 그 밖에는 null
    detail: str | None


class CaseLogResponse(BaseModel):
    logs: list[CaseLogItem]


class CaseClosureReportRequest(BaseModel):
    closure_date: date
    closure_reason: ClosureReason
    road_address: str = Field(min_length=1, max_length=200)
    # 단독 건물처럼 상세 주소가 없을 수도 있다
    address_detail: str | None = Field(default=None, max_length=100)


class CaseClosureReportResponse(BaseModel):
    closure_date: date
    closure_reason: ClosureReason
    road_address: str
    address_detail: str | None


class CaseDepositReturnRequest(BaseModel):
    result: DepositReturnResult


class CaseDepositReturnResponse(BaseModel):
    result: DepositReturnResult
