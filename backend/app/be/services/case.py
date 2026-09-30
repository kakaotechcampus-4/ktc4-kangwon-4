from fastapi import HTTPException
from sqlmodel import Session

from app.be.crud import case as case_crud
from app.be.models.case import Case
from app.be.schemas.case import CaseCreateRequest, CaseGetDetailResponse, CaseGetResponse


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


def get_case(session: Session, member_id: int) -> CaseGetResponse:
    case = case_crud.get_case_by_member_id(session, member_id)
    if case is None:
        return CaseGetResponse(
            case=None, blocker=None, next_action=None, judgment_status=None, questions_for_user=None
        )

    # TODO: create_case가 아직 CaseHistory(judgment_status="PENDING")를 안 만들어서
    # latest_history가 항상 None이다. create_case에서 CaseHistory 생성이 구현되기 전까지
    # blocker/next_action/judgment_status/questions_for_user는 고정 None으로 응답한다.
    # latest_history = case_crud.get_latest_case_history_by_case_id_and_source(session, case.id, "USER_INPUT")

    # if latest_history is None:
    #     raise HTTPException(
    #         status_code=500,
    #         detail="Case에 대한 최초 판단 기록이 없습니다.",
    #     )
    #
    # if latest_history.judgment_status == "DONE" and (
    #     latest_history.next_action is None or latest_history.priority_blocker is None
    # ):
    #     raise HTTPException(
    #         status_code=500,
    #         detail="판단 완료(DONE) 상태인데 Blocker·Next Action이 없습니다.",
    #     )
    #
    # if latest_history.judgment_status == "NEEDS_MORE_INFO" and not latest_history.questions_for_user:
    #     raise HTTPException(
    #         status_code=500,
    #         detail="정보 부족(NEEDS_MORE_INFO) 상태인데 questions_for_user가 없습니다.",
    #     )

    return CaseGetResponse(
        case=CaseGetDetailResponse(**case.model_dump()),
        blocker=None,
        next_action=None,
        judgment_status=None,
        questions_for_user=None,
    )
