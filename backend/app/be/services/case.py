import hashlib
import json
import logging

from fastapi import HTTPException
from sqlmodel import Session

from app.be.crud import case as case_crud
from app.be.crud import case_checklist as case_checklist_crud
from app.be.crud import case_field_history as case_field_history_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import conflict_reference as conflict_reference_crud
from app.be.crud import evidence as evidence_crud
from app.be.crud import procedure_step as procedure_step_crud
from app.be.models.case import Case
from app.be.models.case_checklist import CaseChecklist, CaseChecklistHistory
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import ConflictReference, Evidence
from app.be.models.mixins import KST, kst_now
from app.be.models.procedure_step import CaseProcedureStep
from app.be.schemas.case import (
    CaseClosureReportRequest,
    CaseClosureReportResponse,
    CaseDepositReturnResponse,
    CaseChecklistResponse,
    CaseSupportApprovalResponse,
    CaseConflictsDecisionRequest,
    CaseCreateRequest,
    CaseGetDetailResponse,
    CaseGetResponse,
    CaseLogItem,
    CaseLogResponse,
    CaseResultsEntryResponse,
    CaseResultsSubmitAcceptedResponse,
    CaseResultsSubmitRequest,
    CaseResultsSubmitResponse,
    ConflictItemResponse,
    FieldChangeResponse,
    NewTaskResponse,
    NextActionResponse,
)
from app.agent.procedure_tool.store import ReviewedProcedureStore
from app.agent.roadmap import TASKS as ROADMAP_TASKS, record_checklist
from app.be.services import procedure_registry
from app.be.services import reviewed_procedure as reviewed_procedure_service
from app.be.services import roadmap as roadmap_service
from app.be.services.unmasking import build_restorer

logger = logging.getLogger(__name__)


def _field_changes(session: Session, case_id: int, case_history_id: int) -> list[FieldChangeResponse]:
    """이 제출에서 바뀐 값들. 화면에 낼 때만 가림 문구를 원래 글자로 되돌린다.

    이전 값과 새 값은 서로 다른 제출에서 나온다. 한쪽 기준으로 되돌리면 이전 값 자리에
    남의 주소가 들어간다.
    """

    rows = case_field_history_crud.get_case_field_histories_by_case_history_id(session, case_history_id)
    restorer = build_restorer(
        session, case_id, [row.before_value for row in rows] + [row.after_value for row in rows]
    )
    return [
        FieldChangeResponse(
            field=row.canonical_field,
            stored_value=restorer.restore(row.before_value, restorer.source_of_previous(row.id)),
            new_value=restorer.restore(row.after_value, row.case_history_id),
        )
        for row in rows
    ]


def _conflict_items(
    session: Session, case_id: int, conflicts: list[ConflictReference]
) -> list[ConflictItemResponse]:
    """확인 화면에 띄울 충돌들.

    아직 확인 전이라 Case에는 이전 값이 그대로 있다. 새 값만 이번 제출에서 나온다.
    """

    restorer = build_restorer(
        session,
        case_id,
        [conflict.committed_value for conflict in conflicts]
        + [conflict.proposed_value for conflict in conflicts],
    )
    return [
        ConflictItemResponse(
            id=conflict.id,
            field=conflict.canonical_field,
            stored_value=restorer.restore(
                conflict.committed_value, restorer.source_of_current(conflict.canonical_field)
            ),
            proposed_value=restorer.restore(conflict.proposed_value, conflict.case_history_id),
        )
        for conflict in conflicts
    ]


def _case_detail(session: Session, case: Case) -> CaseGetDetailResponse:
    """Case 자체를 화면에 낼 때. 자유 글 칸에만 가림 문구가 들어올 수 있다."""

    detail = CaseGetDetailResponse(**case.model_dump())
    restorer = build_restorer(
        session, case.id, [detail.business_type, detail.restoration_scope_detail]
    )
    return detail.model_copy(
        update={
            field: restorer.restore(getattr(detail, field), restorer.source_of_current(field))
            for field in ("business_type", "restoration_scope_detail")
        }
    )


def create_case(session: Session, member_id: int, case_request: CaseCreateRequest) -> tuple[Case, int]:
    """만들어진 Case와, 첫 판단이 대상으로 삼을 입력 이력의 id를 함께 돌려준다."""

    if case_crud.get_case_by_member_id(session, member_id) is not None:
        raise HTTPException(status_code=409, detail="이미 등록된 Case가 있습니다.")

    # 검수 문서를 Case보다 먼저 읽는다. 파일이 깨져 있으면 판단도 같은 파일을 읽어서
    # (judgment.py) AI를 부르기 전에 터진다. 그 상태로 Case만 만들어 두면 가입 직후
    # FAILED인데 재판단 API가 없고 다시 가입하면 409라 빠져나올 길이 없다. 여기서 터지면
    # 가입 자체가 실패하므로, 파일을 고친 뒤 다시 시도하면 된다.
    procedure_store = reviewed_procedure_service.load_reviewed_procedures()

    case = Case(
        member_id=member_id,
        store_name=case_request.store_name,
        business_type=case_request.business_type,
        franchise_status=case_request.franchise_status,
        employee_count=case_request.employee_count,
        has_business_loan=case_request.has_business_loan,
        has_service_contracts=case_request.has_service_contracts,
        lease_status=case_request.lease_status,
        restoration_clause=case_request.restoration_clause,
        planned_closure_date=case_request.planned_closure_date,
        planned_closure_month=case_request.planned_closure_month,
        had_employees=case_request.had_employees,
        pension_enrolled=case_request.pension_enrolled,
        health_insurance_enrolled=case_request.health_insurance_enrolled,
        employment_insurance_enrolled=case_request.employment_insurance_enrolled,
        industrial_accident_insurance_enrolled=case_request.industrial_accident_insurance_enrolled,
    )
    case = case_crud.create_case(session, case)
    _fill_case_procedure_steps(session, case.id)
    history = _create_case_creation_evidence(session, case, case_request)
    # 문서 적재보다 먼저 확정한다. 적재가 터져도 가입은 남아야 하기 때문이다.
    session.commit()

    _import_reviewed_procedures(session, case.id, procedure_store)

    session.refresh(case)
    return case, history.id


def _import_reviewed_procedures(session: Session, case_id: int, store: ReviewedProcedureStore) -> None:
    """검수된 절차 문서를 이 Case의 근거로 저장한다. 실패해도 Case는 그대로 둔다.

    AI는 이 문서를 직접 읽지 않고 BE가 Case의 근거로 저장해 둔 것만 쓴다. 적재해 두지
    않으면 절차조회가 짝을 못 찾아 그 문서를 아예 안 쓴다.

    여기서 터지는 건 사장님 입력이 아니라 우리 쪽 문서 문제다 — 버전을 올리지 않고 본문만
    고쳤거나, 본문이 DB 칸 길이를 넘은 경우다. 그걸로 가입을 막으면 우리가 문서를 잘못 건드린
    동안 들어온 사장님이 전부 500을 받는다.

    그래서 Case를 먼저 확정한 뒤 여기서 따로 커밋한다. 터지면 되돌려서 문서가 일부만
    저장된 상태를 남기지 않고, 예외는 밖으로 던지지 않는다. 이미 Case가 저장된 뒤라
    여기서 던져 봐야 화면에는 "가입 실패"로 보이고 다시 하면 "이미 있다"가 된다.

    파일을 못 읽는 경우는 여기까지 오지 않는다. 호출부가 Case를 만들기 전에 읽어서 넘긴다.
    판단도 같은 파일을 읽기 때문에, 파일이 깨진 채로 Case만 남으면 빠져나올 길이 없다.

    DB 쪽 이유로만 실패하면 판단은 그대로 돈다. 다만 절차조회가 0건이라 절차 안내가 안 나온다.
    TODO: 적재는 멱등이므로 판단 전에 한 번 더 부르면 다음 판단에서 저절로 채워진다
    (승준님 #65 리뷰 2번과 같은 작업이라 거기서 함께 한다).
    """

    try:
        reviewed_procedure_service.import_reviewed_procedures(
            session,
            case_id,
            store,
            as_of=kst_now().date(),
        )
        session.commit()
    except Exception:
        session.rollback()
        # 판단 백그라운드 실행과 같은 방식이다. 되돌릴 수 없는 일이 이미 끝났으므로
        # 예외를 삼키되, 원인을 알 수 있게 traceback까지 남긴다.
        logger.exception("case %s 검수 절차 문서 적재 실패 — 문서 없이 판단한다", case_id)


def get_case(session: Session, member_id: int) -> CaseGetResponse:
    case = case_crud.get_case_by_member_id(session, member_id)
    if case is None:
        return CaseGetResponse(
            case=None,
            blocker=None,
            next_action=None,
            judgment_status=None,
            case_history_id=None,
            questions_for_user=None,
            recovery_action_code=None,
            requested_field_paths=None,
            retryable=None,
            changes=None,
        )

    latest_history = case_history_crud.get_latest_user_driven_case_history(session, case.id)
    if latest_history is None:
        raise HTTPException(status_code=500, detail="Case에 대한 최초 판단 기록이 없습니다.")

    _assert_judgment_is_showable(latest_history)

    # 충돌 결정이 실패하면 충돌은 미결로 남지만 마지막 이력은 FAILED다. 그대로 내보내면 홈이
    # 실패 카드를 그려서 충돌 확인으로 돌아갈 길이 없다. 진입 조회(get_case_results_entry)처럼
    # 처리 중이 아니고 미결 충돌이 있으면 CONFLICT로 본다.
    if latest_history.judgment_status != "PENDING" and conflict_reference_crud.get_pending_conflicts_by_case_id(
        session, case.id
    ):
        return CaseGetResponse(
            case=_case_detail(session, case),
            blocker=None,
            next_action=None,
            judgment_status="CONFLICT",
            case_history_id=None,
            questions_for_user=None,
            recovery_action_code=None,
            requested_field_paths=None,
            retryable=None,
            changes=None,
        )

    next_action = (
        NextActionResponse(
            title=latest_history.next_action,
            reason=latest_history.next_action_reason,
            questions_to_ask=latest_history.next_action_questions_to_ask or [],
        )
        if latest_history.next_action is not None
        else None
    )

    changes = (
        _field_changes(session, case.id, latest_history.id)
        # 충돌을 확인한 뒤 되묻는 경우(NEEDS_MORE_INFO)에도 검수를 통과한 변경은 저장된다.
        # DONE만 보면 그 변경이 화면에 안 보인다.
        if latest_history.judgment_status in ("DONE", "NEEDS_MORE_INFO")
        else None
    )

    return CaseGetResponse(
        case=_case_detail(session, case),
        blocker=(
            latest_history.priority_blocker.description if latest_history.priority_blocker else None
        ),
        next_action=next_action,
        judgment_status=latest_history.judgment_status,
        case_history_id=latest_history.id if latest_history.judgment_status != "CONFLICT" else None,
        questions_for_user=latest_history.questions_for_user,
        # 실패했을 때만 채워진다. 화면은 이 값으로 "다시 시도" / "다시 말씀해 주세요" /
        # "문의" 중 무엇을 보여줄지 정한다.
        recovery_action_code=latest_history.recovery_action_code,
        requested_field_paths=latest_history.requested_field_paths,
        retryable=latest_history.retryable,
        changes=changes,
    )


def get_case_results_entry(session: Session, member_id: int) -> CaseResultsEntryResponse:
    """`/case`의 "결과 알려주기" 버튼(API 1). `judgment_status`를 그대로 응답에 싣는다."""

    case = case_crud.get_case_by_member_id(session, member_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case를 찾을 수 없습니다.")

    latest_history = case_history_crud.get_latest_user_driven_case_history(session, case.id)
    if latest_history is None:
        raise HTTPException(status_code=500, detail="Case에 대한 최초 판단 기록이 없습니다.")

    # 충돌 결정을 처리하는 동안에도 충돌은 미결로 남아 있다(성공해야 해결 처리한다).
    # 그래서 처리 중인지를 먼저 보지 않으면, 결정을 보낸 직후에도 확인 화면이 다시 나온다.
    if latest_history.judgment_status == "PENDING":
        return CaseResultsEntryResponse(judgment_status="PENDING", case_history_id=latest_history.id)

    pending_conflicts = conflict_reference_crud.get_pending_conflicts_by_case_id(session, case.id)
    if pending_conflicts:
        # 사전 검사 전제(미결 충돌은 항상 최대 1개)상 전부 같은 case_history에서 나온
        # 것이므로, raw_input은 아무 row에서나 꺼내도 같다.
        raw_input = pending_conflicts[0].case_history.raw_input
        return CaseResultsEntryResponse(
            judgment_status="CONFLICT",
            raw_input=raw_input,
            conflicts=_conflict_items(session, case.id, pending_conflicts),
        )

    _assert_judgment_is_showable(latest_history)

    if latest_history.judgment_status == "DONE":
        return CaseResultsEntryResponse(
            judgment_status="DONE",
            case_history_id=latest_history.id,
            next_action=(
                NextActionResponse(
                    title=latest_history.next_action,
                    reason=latest_history.next_action_reason,
                    questions_to_ask=latest_history.next_action_questions_to_ask or [],
                )
                if latest_history.next_action is not None
                else None
            ),
        )

    if latest_history.judgment_status == "NEEDS_MORE_INFO":
        return CaseResultsEntryResponse(
            judgment_status="NEEDS_MORE_INFO",
            case_history_id=latest_history.id,
            questions_for_user=latest_history.questions_for_user,
        )

    return CaseResultsEntryResponse(
        judgment_status="FAILED",
        case_history_id=latest_history.id,
        recovery_action_code=latest_history.recovery_action_code,
        requested_field_paths=latest_history.requested_field_paths,
        retryable=latest_history.retryable,
    )


def _assert_judgment_is_showable(history: CaseHistory) -> None:
    """상태별로 화면이 읽을 값이 다 있는지 본다. 없으면 빈칸을 내보내지 말고 여기서 막는다.

    AI 계약상 next_action이 있으면 reason도 반드시 있고(NextAction.reason은 빈 문자열도
    거부한다), 검수를 통과한 판단은 항상 blocker를 남긴다. 그래서 평소에는 걸리지 않는다.
    걸린다면 AI가 아니라 우리 저장 코드가 깨진 것이고, 그때 조용히 빈 화면을 보여주는 것보다
    멈추고 알아차리는 쪽이 낫다.

    같은 검사를 /cases와 /cases/results가 함께 쓴다. 흩어 두면 화면이 늘 때마다 한쪽만
    고치게 된다.
    """

    if history.judgment_status == "DONE":
        if history.next_action is None or history.next_action_reason is None:
            raise HTTPException(
                status_code=500, detail="판단 완료(DONE) 상태인데 다음 행동이나 그 이유가 없습니다."
            )
        if history.priority_blocker is None:
            raise HTTPException(status_code=500, detail="판단 완료(DONE) 상태인데 Blocker가 없습니다.")
        return

    if history.judgment_status == "NEEDS_MORE_INFO":
        if not history.questions_for_user:
            raise HTTPException(
                status_code=500, detail="정보 부족(NEEDS_MORE_INFO) 상태인데 되물을 질문이 없습니다."
            )
        if history.priority_blocker is None:
            raise HTTPException(
                status_code=500, detail="정보 부족(NEEDS_MORE_INFO) 상태인데 Blocker가 없습니다."
            )
        return

    if history.judgment_status == "FAILED" and (
        history.recovery_action_code is None or history.retryable is None
    ):
        raise HTTPException(
            status_code=500,
            detail="판단 실패(FAILED) 상태인데 recovery_action_code·retryable이 없습니다.",
        )


def submit_case_results(
    session: Session, member_id: int, submit_request: CaseResultsSubmitRequest
) -> CaseResultsSubmitAcceptedResponse:
    """`/results`의 "이 내용으로 알려주기" 버튼. 접수만 하고 끝난다.

    Agent 판단은 최소 30초~2분 걸려서 이 요청·응답 안에서 끝낼 수 없다. 그래서 여기서는
    접수 가능한 상태인지만 확인하고 PENDING 이력을 남긴 뒤 끝난다 — 판단 결과는 이 응답이
    아니라 처리 상태를 조회하는 별도 조회 API가 준다.

    "처리 중인지 확인"과 "새 이력 저장" 사이에 다른 요청이 끼면 같은 Case에 PENDING이 둘
    생긴다. 그러면 판단이 두 번 돌아 서로의 결과를 덮고, 사장님은 같은 충돌을 두 번 확인하게
    된다. 화면에서 버튼을 막는 것만으로는 막히지 않아 여기서 Case를 잠그고 확인한다
    (FE 합의문 2026-10-22 3-3).
    """

    case = case_crud.lock_case_by_member_id(session, member_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case를 찾을 수 없습니다.")

    if case.case_status == "COMPLETED":
        # AI는 진행 중인 Case만 판단한다. 완료된 Case로 판단을 돌리면 AI 입력 검사에서 거절된다.
        raise HTTPException(status_code=409, detail="폐업 정리를 마친 Case입니다.")

    if conflict_reference_crud.get_pending_conflicts_by_case_id(session, case.id):
        raise HTTPException(status_code=409, detail="확인 대기 중인 충돌이 있습니다.")

    latest_history = case_history_crud.get_latest_user_driven_case_history(session, case.id)
    if latest_history is None:
        raise HTTPException(status_code=500, detail="Case에 대한 최초 판단 기록이 없습니다.")

    if latest_history.judgment_status == "PENDING":
        raise HTTPException(status_code=409, detail="직전 제출을 아직 처리 중입니다.")

    if submit_request.case_history_id != latest_history.id:
        raise HTTPException(status_code=409, detail="최신 판단에 대해 요청을 주지 않았습니다.")

    history = case_history_crud.create_case_history(
        session,
        CaseHistory(
            case_id=case.id,
            raw_input=submit_request.raw_input,
            source="USER_INPUT",
            judgment_status="PENDING",
        ),
    )
    session.commit()
    return CaseResultsSubmitAcceptedResponse(case_history_id=history.id)


def submit_case_conflicts_decision(
    session: Session, member_id: int, decision_request: CaseConflictsDecisionRequest
) -> CaseResultsSubmitAcceptedResponse:
    """충돌 확인(`/confirm`)에서 사용자가 충돌마다 고른 결정을 접수한다.

    결과 제출 접수(submit_case_results)처럼 접수만 하고 PENDING 이력을 남긴 뒤 끝난다.
    결과는 GET /cases/results/status로 조회한다.

    결과 제출 접수와 같은 이유로 Case를 잠그고 확인한다. 결정이 동시에 두 번 오면 PENDING이
    둘 생겨 판단이 두 번 돌고 서로의 결과를 덮는다.
    """

    case = case_crud.lock_case_by_member_id(session, member_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case를 찾을 수 없습니다.")

    if case.case_status == "COMPLETED":
        # AI는 진행 중인 Case만 판단한다. 완료된 Case로 판단을 돌리면 AI 입력 검사에서 거절된다.
        raise HTTPException(status_code=409, detail="폐업 정리를 마친 Case입니다.")

    pending_conflicts = conflict_reference_crud.get_pending_conflicts_by_case_id(session, case.id)
    if not pending_conflicts:
        raise HTTPException(status_code=409, detail="확인 대기 중인 충돌이 없습니다.")

    latest_history = case_history_crud.get_latest_user_driven_case_history(session, case.id)
    if latest_history is None:
        raise HTTPException(status_code=500, detail="Case에 대한 최초 판단 기록이 없습니다.")

    if latest_history.judgment_status == "PENDING":
        raise HTTPException(status_code=409, detail="직전 충돌 결정을 아직 처리 중입니다.")

    requested_ids = [decision.conflict_reference_id for decision in decision_request.decisions]
    if len(requested_ids) != len(set(requested_ids)):
        raise HTTPException(status_code=422, detail="같은 충돌에 대한 결정이 중복되었습니다.")

    pending_ids = {conflict.id for conflict in pending_conflicts}
    for conflict_reference_id in requested_ids:
        if conflict_reference_id in pending_ids:
            continue
        conflict = conflict_reference_crud.get_conflict_reference_by_id(session, conflict_reference_id)
        # 남의 Case 충돌도 "없음"과 똑같이 응답해서, 그런 충돌이 있다는 사실을 알려주지 않는다.
        if conflict is None or conflict.case_id != case.id:
            raise HTTPException(status_code=422, detail="존재하지 않는 충돌입니다.")
        raise HTTPException(status_code=409, detail="이미 해결된 충돌입니다.")

    if pending_ids - set(requested_ids):
        raise HTTPException(status_code=422, detail="결정하지 않은 충돌이 있습니다.")

    history = case_history_crud.create_case_history(
        session,
        CaseHistory(case_id=case.id, source="CONFLICT_DECISION", judgment_status="PENDING"),
    )
    session.commit()
    return CaseResultsSubmitAcceptedResponse(case_history_id=history.id)


def get_case_results_submit_status(
    session: Session, member_id: int, case_history_id: int
) -> CaseResultsSubmitResponse:
    """제출(`/results`) 이후 FE가 몇 초 간격으로 묻는 처리 상태 조회.

    `/replan` 화면은 `changes`·`blocker`·`next_action`까지 필요해서, `/case` 진입 판단용인
    `get_case_results_entry()`와 응답 모양이 다르다. 그래서 별도 스키마(`result` 기반)를 쓴다.

    `case_history_id`는 "지금 조회하려는 게 어느 제출이냐"를 밝히는 값이다. Case 생성 판단은
    이 조회 대상이 아니므로, 최신 판단을 찾을 때 USER_INPUT·CONFLICT_DECISION만 본다
    (get_latest_user_driven_case_history와 다른 점).
    """

    case = case_crud.get_case_by_member_id(session, member_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case를 찾을 수 없습니다.")

    latest_history = case_history_crud.get_latest_case_history_by_sources(
        session, case.id, ("USER_INPUT", "CONFLICT_DECISION")
    )
    if latest_history is None:
        raise HTTPException(status_code=404, detail="조회할 제출 기록을 찾을 수 없습니다.")

    if case_history_id != latest_history.id:
        raise HTTPException(status_code=409, detail="최신 판단에 대해 요청을 주지 않았습니다.")

    _assert_judgment_is_showable(latest_history)

    # 충돌은 Case 전체가 아니라 이 이력(latest_history)에 달린 것만 본다.
    # 예: 충돌 결정(CONFLICT_DECISION)이 처리 중이면 이전 이력의 충돌이 아직 미결로 남아 있어서,
    # Case 전체로 찾으면 처리 중(PENDING)인 이 이력을 CONFLICT로 잘못 응답한다.
    if latest_history.judgment_status == "CONFLICT":
        pending_conflicts = conflict_reference_crud.get_pending_conflicts_by_case_history_id(
            session, latest_history.id
        )
        if not pending_conflicts:
            raise HTTPException(
                status_code=500,
                detail=f"case_history {latest_history.id}가 CONFLICT인데 확인 대기 중인 충돌이 없습니다.",
            )
        return CaseResultsSubmitResponse(
            result="CONFLICT",
            raw_input=latest_history.raw_input,
            conflicts=_conflict_items(session, case.id, pending_conflicts),
        )

    if latest_history.judgment_status == "PENDING":
        return CaseResultsSubmitResponse(result="PENDING")

    if latest_history.judgment_status == "NEEDS_MORE_INFO":
        return CaseResultsSubmitResponse(
            result="NEEDS_MORE_INFO",
            questions_for_user=latest_history.questions_for_user,
        )

    if latest_history.judgment_status == "FAILED":
        return CaseResultsSubmitResponse(
            result="FAILED",
            recovery_action_code=latest_history.recovery_action_code,
            requested_field_paths=latest_history.requested_field_paths,
            retryable=latest_history.retryable,
        )

    # 남는 건 DONE뿐이다. 위에서 상태 이름으로 거르지 않고 내려오면, CONFLICT처럼 blocker가
    # 없는 상태가 아래 blocker.description에 닿아 엉뚱한 곳에서 터진다.
    if latest_history.judgment_status != "DONE":
        raise HTTPException(
            status_code=500,
            detail=f"처리 상태 조회가 다루지 않는 판단 상태입니다: {latest_history.judgment_status}",
        )

    changes = _field_changes(session, case.id, latest_history.id)
    return CaseResultsSubmitResponse(
        result="UPDATED" if changes else "NO_CHANGE",
        changes=changes,
        blocker=latest_history.priority_blocker.description,
        next_action=NextActionResponse(
            title=latest_history.next_action,
            reason=latest_history.next_action_reason,
            questions_to_ask=latest_history.next_action_questions_to_ask or [],
        ),
        new_tasks=_new_tasks(session, case.id, latest_history),
    )


# 제목은 AI 로드맵의 할 일 표에서 가져온다. 판단 때 같이 저장하지 않는 것은 제목이 바뀌어도 화면이 따라가게 하려는 것이다.
_ROADMAP_TASK_TITLES = {task_id: title for _, task_id, title, _, _ in ROADMAP_TASKS}


def _new_tasks(session: Session, case_id: int, history: CaseHistory) -> list[NewTaskResponse] | None:
    """직전 판단 뒤에는 해야 할 일이 아니었는데 이번 판단 뒤에 해야 할 일이 된 로드맵 항목.

    판단마다 그 직후의 목록을 남겨 두고(decision_record._roadmap_task_ids) 둘을 뺀다.
    어느 한쪽이라도 목록이 없으면(예전 이력, 계산 실패) 비교할 수 없어 None이다.
    """

    if history.roadmap_task_ids is None:
        return None
    previous = max(
        (
            row for row in case_history_crud.get_case_histories_by_case_id(session, case_id)
            if row.id < history.id and row.roadmap_task_ids is not None
        ),
        key=lambda row: row.id,
        default=None,
    )
    if previous is None:
        return None
    before = set(previous.roadmap_task_ids)
    return [
        NewTaskResponse(task_id=task_id, title=_ROADMAP_TASK_TITLES.get(task_id, task_id))
        for task_id in history.roadmap_task_ids
        if task_id not in before
    ]


# 이 항목을 체크하면 폐업 정리를 마친 것으로 본다(시안 closed 화면).
_CLOSING_TASK_ID = "vat_submission"


def update_case_checklist(
    session: Session, member_id: int, task_id: str, completed: bool
) -> CaseChecklistResponse:
    """로드맵 항목을 사장님이 체크하거나 푼다. 같은 요청을 두 번 보내도 결과가 같다.

    체크할 때는 이 가게에 해당하는 항목인지 AI 로드맵(record_checklist)에 묻는다. "해당 없음"과
    "확인 필요"(예: 철거 필요 여부를 아직 모를 때의 철거비 항목)는 422로 거절한다(승준님 #149).
    푸는 것은 묻지 않는다 — 잘못 눌린 체크를 못 푸는 일이 없어야 한다.
    """

    # 같은 항목 체크가 동시에 두 번 오면 둘 다 "없음"을 보고 만들려다 unique에 걸린다. 줄을 세운다.
    case = case_crud.lock_case_by_member_id(session, member_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case를 찾을 수 없습니다.")

    checklist = case_checklist_crud.get_case_checklist(session, case.id, task_id)
    if completed == (checklist is not None):
        # 이미 그 상태다. 같은 요청을 두 번 보내도 이력이 쌓이지 않게 아무것도 하지 않는다.
        return CaseChecklistResponse(task_id=task_id, completed=completed)

    if completed:
        # 입력 만들기는 try 밖에 둔다. 여기서 나는 오류는 사장님 요청이 아니라 데이터 문제라 422로 덮지 않는다.
        roadmap_input = roadmap_service.build_roadmap_input(session, case)
        try:
            record_checklist(roadmap_input, task_id, completed=True)
        except ValueError:
            raise HTTPException(status_code=422, detail="지금은 체크할 수 없는 항목입니다.") from None
        case_checklist_crud.create_case_checklist(session, CaseChecklist(case_id=case.id, task_id=task_id))
    else:
        case_checklist_crud.delete_case_checklist(session, checklist)
    # 지금 상태(case_checklist)는 풀면 지우지만, 기록 탭에는 체크했다가 푼 것까지 남아야 한다.
    case_checklist_crud.create_case_checklist_history(
        session, CaseChecklistHistory(case_id=case.id, task_id=task_id, completed=completed)
    )
    if task_id == _CLOSING_TASK_ID:
        # 시안: 홈 "홈택스에서 부가세 신고를 마쳐주세요" → [신고했어요] → 폐업 정리 완료.
        # 실수로 눌렀다가 풀면 다시 진행 중으로 돌린다. 완료 뒤에 남는 할 일(종합소득세 등)은
        # 로드맵에 그대로 두고 완료로 본다.
        case.case_status = "COMPLETED" if completed else "IN_PROGRESS"
        case.completed_at = kst_now() if completed else None
    session.commit()
    return CaseChecklistResponse(task_id=task_id, completed=completed)


def update_case_support_approval(
    session: Session, member_id: int, approved: bool | None
) -> CaseSupportApprovalResponse:
    """사장님이 알려 준 점포철거비 1차 적격심사 결과를 저장한다. null은 "아직 모름"으로 되돌린다."""

    case = case_crud.get_case_by_member_id(session, member_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case를 찾을 수 없습니다.")

    case.support_approved = approved
    case.support_approved_at = kst_now()
    session.commit()
    return CaseSupportApprovalResponse(approved=approved)


def update_case_closure_report(
    session: Session, member_id: int, report: CaseClosureReportRequest
) -> CaseClosureReportResponse:
    """통합 폐업 신고 화면에서 확인한 폐업일·폐업 사유·가게 주소를 저장한다. 다시 보내면 덮어쓴다."""

    case = case_crud.get_case_by_member_id(session, member_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case를 찾을 수 없습니다.")

    case.closure_date = report.closure_date
    case.closure_reason = report.closure_reason
    case.road_address = report.road_address
    case.address_detail = report.address_detail
    session.commit()
    return CaseClosureReportResponse(**report.model_dump())


def update_case_deposit_return(session: Session, member_id: int, result: str) -> CaseDepositReturnResponse:
    """가게 반환 화면에서 사장님이 알려 준 보증금 반환 결과를 저장한다. 다시 보내면 덮어쓴다."""

    case = case_crud.get_case_by_member_id(session, member_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case를 찾을 수 없습니다.")

    case.deposit_return_result = result
    session.commit()
    return CaseDepositReturnResponse(result=result)


_LOG_OWNER_EVENTS = {
    "CASE_CREATED": "CASE_CREATED",
    "USER_INPUT": "RESULT_SUBMITTED",
    "CONFLICT_DECISION": "CONFLICT_DECIDED",
}
_LOG_RIBBON_EVENTS = {
    "DONE": "NEXT_ACTION_DECIDED",
    "NEEDS_MORE_INFO": "MORE_INFO_REQUESTED",
    "CONFLICT": "CONFLICT_FOUND",
    "FAILED": "JUDGMENT_FAILED",
}


def get_case_logs(session: Session, member_id: int) -> CaseLogResponse:
    """기록 탭(M08 Log)과 홈의 "리본이 해둔 일" 띠. 문구는 FE가 event 코드로 만든다."""

    case = case_crud.get_case_by_member_id(session, member_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case를 찾을 수 없습니다.")

    logs = []
    for history in case_history_crud.get_case_histories_by_case_id(session, case.id):
        owner_event = _LOG_OWNER_EVENTS.get(history.source)
        if owner_event is None:
            continue
        logs.append(_log("OWNER", owner_event, history.created_at))
        if history.judged_at is not None and history.judgment_status in _LOG_RIBBON_EVENTS:
            logs.append(_log(
                "RIBBON", _LOG_RIBBON_EVENTS[history.judgment_status], history.judged_at,
                detail=history.next_action if history.judgment_status == "DONE" else None,
            ))

    # 체크를 풀어도 체크했던 기록은 남는다(지금 상태가 아니라 이력을 읽는다).
    for checklist in case_checklist_crud.get_case_checklist_histories_by_case_id(session, case.id):
        event = "CHECKLIST_COMPLETED" if checklist.completed else "CHECKLIST_UNCHECKED"
        logs.append(_log("OWNER", event, checklist.created_at, task_id=checklist.task_id))

    # 심사 결과는 마지막으로 알려 준 것 하나만 남는다(값과 시각을 Case에 덮어쓴다).
    if case.support_approved_at is not None:
        result = {True: "APPROVED", False: "REJECTED", None: "UNKNOWN"}[case.support_approved]
        logs.append(_log("OWNER", "SUPPORT_RESULT_REPORTED", case.support_approved_at, detail=result))

    # 최근 것부터. 시각이 같으면 사장님이 보낸 뒤 리본이 판단한 것이라 리본 기록을 위로 둔다.
    logs.sort(key=lambda log: (log.occurred_at, log.actor == "RIBBON"), reverse=True)
    return CaseLogResponse(logs=logs)


def _log(actor: str, event: str, at, *, task_id: str | None = None, detail: str | None = None) -> CaseLogItem:
    # DB에는 시간대 없이 한국 시각이 들어 있다(kst_now, MySQL TZ=Asia/Seoul). 내보낼 때 +09:00을 붙인다.
    return CaseLogItem(actor=actor, event=event, occurred_at=at.replace(tzinfo=KST), task_id=task_id, detail=detail)


def _create_case_creation_evidence(
    session: Session, case: Case, case_request: CaseCreateRequest
) -> CaseHistory:
    # 가입 폼으로 받은 값을 AI 쪽에서 CONFIRMED로 인정하려면 evidence_refs가 있어야 한다
    # (CaseFact.validate_fact_state). 폼 값들이 이 evidence 하나를 같이 참조해도 된다고
    # AI팀 확인함. 폼 전체를 그대로 남기므로 칸이 늘어도 같이 덮인다.
    # 가게 이름은 AI 판단에 쓰지 않으므로 AI에 넘기지 않는다.
    submitted = json.dumps(case_request.model_dump(mode="json", exclude={"store_name"}), ensure_ascii=False)
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
    return history


def _fill_case_procedure_steps(session: Session, case_id: int) -> None:
    """이 Case의 로드맵에 카페 폐업 절차 8개를 모두 올린다.

    해당하지 않는 절차도 함께 올린다. 어떤 절차가 이 가게에 해당하는지는 AI가
    가게 정보를 보고 판단하므로(procedure_tool/rules.py), BE가 여기서 미리 걸러내면
    같은 규칙이 두 벌이 된다. 화면에 "해당 없음"으로 보여주려면 목록에 있어야 하기도 하다.

    절차 자체는 앱이 뜰 때 이미 적재돼 있다(main.lifespan). 여기서는 읽어서 이 Case에
    걸기만 한다. Case별 줄이 미리 있어야 AI가 돌려준 진행 상태를 저장할 수 있다
    (decision_record._apply_procedure_progress_changes는 없는 줄을 만들지 않는다).
    """

    for step_id in procedure_registry.load_cafe_procedure_step_ids(session).values():
        procedure_step_crud.create_case_procedure_step(
            session, CaseProcedureStep(case_id=case_id, procedure_step_id=step_id)
        )
