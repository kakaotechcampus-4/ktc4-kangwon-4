import hashlib
import json

from fastapi import HTTPException
from sqlmodel import Session

from app.be.crud import case as case_crud
from app.be.crud import case_field_history as case_field_history_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import evidence as evidence_crud
from app.be.crud import procedure_step as procedure_step_crud
from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import Evidence
from app.be.models.mixins import kst_now
from app.be.models.procedure_step import CaseProcedureStep, ProcedureStep
from app.be.schemas.case import (
    CaseCreateRequest,
    CaseGetDetailResponse,
    CaseGetResponse,
    FieldChangeResponse,
    NextActionResponse,
)


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
    _create_case_creation_evidence(session, case, case_request)
    session.commit()
    session.refresh(case)
    return case


def get_case(session: Session, member_id: int) -> CaseGetResponse:
    case = case_crud.get_case_by_member_id(session, member_id)
    if case is None:
        return CaseGetResponse(
            case=None,
            blocker=None,
            next_action=None,
            judgment_status=None,
            questions_for_user=None,
            recovery_action_code=None,
            requested_field_paths=None,
            retryable=None,
            changes=None,
        )

    latest_history = case_crud.get_latest_user_driven_case_history(session, case.id)
    if latest_history is None:
        raise HTTPException(status_code=500, detail="Case에 대한 최초 판단 기록이 없습니다.")

    if latest_history.judgment_status == "DONE" and (
        latest_history.next_action is None or latest_history.priority_blocker is None
    ):
        raise HTTPException(status_code=500, detail="판단 완료(DONE) 상태인데 Blocker·Next Action이 없습니다.")

    if latest_history.judgment_status == "NEEDS_MORE_INFO" and not latest_history.questions_for_user:
        raise HTTPException(status_code=500, detail="정보 부족(NEEDS_MORE_INFO) 상태인데 questions_for_user가 없습니다.")

    if latest_history.judgment_status == "FAILED" and latest_history.recovery_action_code is None:
        raise HTTPException(status_code=500, detail="판단 실패(FAILED) 상태인데 recovery_action_code가 없습니다.")

    # TODO: retryable은 저장하는 쪽(decision_record.py의 save_safe_failure 등)이 아직 안 채워주고
    # 있어서 지금은 가드를 안 건다. 채워주기 시작하면 위 recovery_action_code처럼
    # "FAILED인데 retryable이 없으면 500" 가드를 추가해야 한다.

    next_action = (
        NextActionResponse(
            title=latest_history.next_action,
            reason=latest_history.next_action_reason,
            questions_to_ask=latest_history.next_action_questions_to_ask or [],
        )
        if latest_history.next_action is not None
        else None
    )

    # TODO: case_history_id는 저장하는 쪽(decision_record.py의 _apply_fact_changes)이
    # 아직 안 채워주고 있어서, DONE이어도 실제로는 변경이 있었는데 []로 나올 수 있다.
    changes = (
        [
            FieldChangeResponse(field=h.canonical_field, stored_value=h.before_value, new_value=h.after_value)
            for h in case_field_history_crud.get_case_field_histories_by_case_history_id(session, latest_history.id)
        ]
        if latest_history.judgment_status == "DONE"
        else None
    )

    return CaseGetResponse(
        case=CaseGetDetailResponse(**case.model_dump()),
        blocker=latest_history.priority_blocker.description if latest_history.priority_blocker else None,
        next_action=next_action,
        judgment_status=latest_history.judgment_status,
        questions_for_user=latest_history.questions_for_user,
        # 실패했을 때만 채워진다. 화면은 이 값으로 "다시 시도" / "다시 말씀해 주세요" /
        # "문의" 중 무엇을 보여줄지 정한다.
        recovery_action_code=latest_history.recovery_action_code,
        requested_field_paths=latest_history.requested_field_paths,
        retryable=latest_history.retryable,
        changes=changes,
    )


def _create_case_creation_evidence(session: Session, case: Case, case_request: CaseCreateRequest) -> None:
    # case 생성 폼 입력값(business_type/franchise_status/lease_status)을 AI 쪽에서 CONFIRMED로
    # 인정하려면 evidence_refs가 있어야 한다(CaseFact.validate_fact_state). 세 필드가 이 evidence
    # 하나를 같이 참조해도 된다고 AI팀 확인함.
    submitted = json.dumps(case_request.model_dump(mode="json"), ensure_ascii=False)
    history = case_history_crud.create_case_history(
        session,
        # 판단은 뒤에서 돌기 때문에 지금은 결과가 없다. 화면이 "분석 중"을 보여줄 수 있도록
        # PENDING으로 만들어두고, 판단이 끝나면 이 행을 갱신한다.
        CaseHistory(case_id=case.id, raw_input=submitted, source="CASE_CREATED", judgment_status="PENDING"),
    )
    evidence_crud.create_evidence(
        session,
        Evidence(
            evidence_id=evidence_crud.case_history_evidence_id(case.id, history.id),
            case_id=case.id,
            source_type="USER_INPUT",
            source_ref=f"case_history:{history.id}",
            # 근거 행 하나만 봐도 무엇을 근거로 삼았는지 알 수 있게 입력 내용을 그대로 남긴다.
            excerpt=submitted,
            # DB에는 접두사 없이 64자만 저장한다(스키마 문서). AI에 넘길 때 "sha256:"을 붙인다.
            content_hash=hashlib.sha256(submitted.encode("utf-8")).hexdigest(),
            retrieved_at=kst_now(),
            freshness_status="CURRENT",
        ),
    )


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
