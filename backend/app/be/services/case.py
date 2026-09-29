from fastapi import HTTPException
from sqlmodel import Session

from app.be.crud import case as case_crud
from app.be.crud import procedure_step as procedure_step_crud
from app.be.models.case import Case
from app.be.models.procedure_step import CaseProcedureStep, ProcedureStep
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
    _fill_temp_case_procedure_steps(session, case.id)
    session.commit()
    session.refresh(case)
    return case


def _fill_temp_case_procedure_steps(session: Session, case_id: int) -> None:
    # TODO: 실제 폐업절차 마스터 데이터/조건(step_eligibility)로 교체 필요. 폐업절차 DB 구조가 아직
    # 확정되지 않아, 지금은 case_procedure_step 채우는 흐름 검증용 임시 더미 절차 3개만 사용한다.
    temp_procedure_steps = [
        ("TEMP_BUSINESS_CLOSURE_REPORT", "사업자 폐업 신고"),
        ("TEMP_TAX_CLOSURE_REPORT", "세무서 폐업 신고"),
        ("TEMP_FOUR_INSURANCE_CANCEL", "4대보험 상실 신고"),
    ]
    for step_code, step_name in temp_procedure_steps:
        step = procedure_step_crud.get_procedure_step_by_code(session, step_code)
        if step is None:
            step = procedure_step_crud.create_procedure_step(
                session,
                ProcedureStep(step_code=step_code, step_name=step_name, registry_version="temp"),
            )
        procedure_step_crud.create_case_procedure_step(
            session, CaseProcedureStep(case_id=case_id, procedure_step_id=step.id)
        )


def get_case(session: Session, member_id: int) -> Case | None:
    return case_crud.get_case_by_member_id(session, member_id)
