from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

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
