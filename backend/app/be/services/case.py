from fastapi import HTTPException
from sqlmodel import Session

from app.be.crud import case as case_crud
from app.be.models.case import Case
from app.be.schemas.case import CaseCreateRequest


def create_case(session: Session, member_id: int, case_request: CaseCreateRequest) -> Case:
    if case_crud.get_case_by_member_id(session, member_id) is not None:
        raise HTTPException(status_code=409, detail="이미 등록된 Case가 있습니다.")

    case = Case(
        member_id=member_id,
        business_type=case_request.business_type,
        franchise_status=case_request.franchise_status,
        employee_count=case_request.employee_count,
        lease_status=case_request.lease_status,
        planned_closure_date=case_request.planned_closure_date,
    )
    case = case_crud.create_case(session, case)
    session.commit()
    session.refresh(case)
    return case


def get_case(session: Session, member_id: int) -> Case | None:
    return case_crud.get_case_by_member_id(session, member_id)
