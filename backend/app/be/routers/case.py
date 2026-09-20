from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.be.db import get_db
from app.be.dependencies.auth import get_current_member_id
from app.be.schemas.case import CaseCreateRequest, CaseResponse
from app.be.services import case as case_service

router = APIRouter()


@router.post("/cases", response_model=CaseResponse)
def create_case(
    case_request: CaseCreateRequest,
    member_id: int = Depends(get_current_member_id),
    session: Session = Depends(get_db),
):
    return case_service.create_case(session, member_id, case_request)
