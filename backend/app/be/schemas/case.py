from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

LeaseStatus = Literal["LEASED_PAID", "LEASED_FREE", "OWNED"]
CaseStatus = Literal["IN_PROGRESS", "COMPLETED"]
RestorationStatus = Literal["UNKNOWN", "NOT_STARTED", "IN_PROGRESS", "COMPLETED", "NOT_REQUIRED"]
RestorationScope = Literal["UNKNOWN", "PARTIAL", "FULL", "NOT_REQUIRED"]
DemolitionRequired = Literal["UNKNOWN", "REQUIRED", "NOT_REQUIRED"]
JudgmentStatus = Literal["PENDING", "DONE", "NEEDS_MORE_INFO", "CONFLICT", "FAILED"]
RecoveryActionCode = Literal["RETRY", "RESUBMIT_INPUT", "CONTACT_SUPPORT", "NONE"]
ResultsSubmitResult = Literal["PENDING", "UPDATED", "NO_CHANGE", "NEEDS_MORE_INFO", "CONFLICT", "FAILED"]
ConflictSide = Literal["PROPOSED", "STORED"]


class CaseCreateRequest(BaseModel):
    store_name: str | None = Field(default=None, max_length=50)
    business_type: str = Field(max_length=50)
    franchise_status: bool
    employee_count: int | None = Field(default=None, ge=0, le=1000)
    lease_status: LeaseStatus
    planned_closure_date: date | None = None


class CaseCreateResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    member_id: int
    store_name: str | None
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
    store_name: str | None
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
