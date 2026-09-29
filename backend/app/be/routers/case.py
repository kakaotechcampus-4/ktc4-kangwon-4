import logging

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.be.db import get_db
from app.be.dependencies.auth import get_current_member_id
from app.be.schemas.case import CaseCreateRequest, CaseResponse
from app.be.services import case as case_service
from app.be.services import first_judgment as first_judgment_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/cases", response_model=CaseResponse)
async def create_case(
    case_request: CaseCreateRequest,
    member_id: int = Depends(get_current_member_id),
    session: Session = Depends(get_db),
):
    case = case_service.create_case(session, member_id, case_request)

    # 첫 판단은 LLM을 여러 번 부르는 작업이라 실측 55~120초가 걸린다(설정 상한 300초).
    # 그동안 이 요청은 응답을 주지 못한다.
    try:
        await first_judgment_service.run_first_judgment(session, case.id)
    except Exception:
        # Case는 이미 저장됐다. 여기서 500을 내면 사용자는 실패로 보는데 다시 만들려 하면
        # 409(이미 등록된 Case)가 나서 아무것도 못 하게 된다. 그래서 판단 실패는 삼키고
        # Case 생성은 성공으로 응답한다.
        # TODO: 판단이 없는 Case를 나중에 다시 판단시킬 방법이 필요하다.
        logger.exception("case %s 첫 판단 실패", case.id)

    return case


@router.get("/cases", response_model=CaseResponse | dict)
def get_case(
    member_id: int = Depends(get_current_member_id),
    session: Session = Depends(get_db),
):
    case = case_service.get_case(session, member_id)
    return case if case is not None else {}
