from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

LeaseStatus = Literal["LEASED_PAID", "LEASED_FREE", "OWNED"]
CaseStatus = Literal["IN_PROGRESS", "COMPLETED"]
RestorationStatus = Literal["UNKNOWN", "NOT_STARTED", "IN_PROGRESS", "COMPLETED", "NOT_REQUIRED"]
RestorationScope = Literal["UNKNOWN", "PARTIAL", "FULL", "NOT_REQUIRED"]
DemolitionRequired = Literal["UNKNOWN", "REQUIRED", "NOT_REQUIRED"]


class CaseCreateRequest(BaseModel):
    business_type: str
    franchise_status: bool
    employee_count: int | None = None
    lease_status: LeaseStatus
    planned_closure_date: date | None = None


class CaseResponse(BaseModel):
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
