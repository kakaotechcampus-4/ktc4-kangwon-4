from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

LeaseStatus = Literal["LEASED_PAID", "LEASED_FREE", "OWNED"]
CaseStatus = Literal["IN_PROGRESS", "COMPLETED"]
RestorationStatus = Literal["UNKNOWN", "NOT_STARTED", "IN_PROGRESS", "COMPLETED", "NOT_REQUIRED"]
RestorationScope = Literal["UNKNOWN", "PARTIAL", "FULL", "NOT_REQUIRED"]
DemolitionRequired = Literal["UNKNOWN", "REQUIRED", "NOT_REQUIRED"]
JudgmentStatus = Literal["PENDING", "DONE", "NEEDS_MORE_INFO", "CONFLICT", "FAILED"]
RecoveryActionCode = Literal["RETRY", "RESUBMIT_INPUT", "CONTACT_SUPPORT", "NONE"]


class CaseCreateRequest(BaseModel):
    business_type: str
    franchise_status: bool
    employee_count: int | None = None
    lease_status: LeaseStatus
    planned_closure_date: date | None = None


class CaseCreateResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    member_id: int
    business_type: str
    franchise_status: bool
    employee_count: int | None
    case_status: CaseStatus
    lease_status: LeaseStatus
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
    business_type: str
    franchise_status: bool
    employee_count: int | None
    lease_status: LeaseStatus
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
    questions_for_user: list[str] | None
    recovery_action_code: RecoveryActionCode | None
    requested_field_paths: list[str] | None
    retryable: bool | None
    changes: list[FieldChangeResponse] | None


NextScreen = Literal["CONFLICT_CONFIRM", "RESULT_INPUT_PENDING", "RESULT_INPUT"]


class ConflictItemResponse(BaseModel):
    id: int
    field: str
    stored_value: str | None
    proposed_value: str


class CaseResultsEntryResponse(BaseModel):
    next_screen: NextScreen
    raw_input: str | None = None
    conflicts: list[ConflictItemResponse] | None = None
    next_action: NextActionResponse | None = None
