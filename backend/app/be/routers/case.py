from fastapi import APIRouter, BackgroundTasks, Depends
from sqlmodel import Session

from app.be.db import get_db
from app.be.dependencies.auth import get_current_member_id
from app.be.schemas.case import CaseCreateRequest, CaseCreateResponse, CaseGetResponse
from app.be.services import case as case_service
from app.be.services import first_judgment as first_judgment_service

router = APIRouter()


@router.post("/cases", response_model=CaseCreateResponse)
def create_case(
    case_request: CaseCreateRequest,
    background_tasks: BackgroundTasks,
    member_id: int = Depends(get_current_member_id),
    session: Session = Depends(get_db),
):
    case = case_service.create_case(session, member_id, case_request)

    # AI 첫 판단은 LLM을 여러 번 불러서 실측 36~120초가 걸린다. 응답을 그만큼 붙잡으면
    # 중간에 끊기거나 사용자가 화면을 떠났을 때 결과를 못 보므로, Case만 저장하고 바로
    # 응답한다. 판단은 뒤에서 돌면서 case_history.judgment_status를 갱신하고,
    # 화면은 GET /cases로 다시 물어본다.
    background_tasks.add_task(first_judgment_service.run_first_judgment_in_background, case.id)

    return case


@router.get("/cases", response_model=CaseGetResponse)
def get_case(
    member_id: int = Depends(get_current_member_id),
    session: Session = Depends(get_db),
):
    return case_service.get_case(session, member_id)
