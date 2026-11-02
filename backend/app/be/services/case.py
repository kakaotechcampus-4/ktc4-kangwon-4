import hashlib
import json
import logging

from fastapi import HTTPException
from sqlmodel import Session

from app.be.crud import case as case_crud
from app.be.crud import case_field_history as case_field_history_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import conflict_reference as conflict_reference_crud
from app.be.crud import evidence as evidence_crud
from app.be.crud import procedure_step as procedure_step_crud
from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import ConflictReference, Evidence
from app.be.models.mixins import kst_now
from app.be.models.procedure_step import CaseProcedureStep, ProcedureStep
from app.be.schemas.case import (
    CaseConflictsDecisionRequest,
    CaseCreateRequest,
    CaseGetDetailResponse,
    CaseGetResponse,
    CaseResultsEntryResponse,
    CaseResultsSubmitAcceptedResponse,
    CaseResultsSubmitRequest,
    CaseResultsSubmitResponse,
    ConflictItemResponse,
    FieldChangeResponse,
    NextActionResponse,
)
from app.agent.procedure_tool.store import ReviewedProcedureStore
from app.be.services import reviewed_procedure as reviewed_procedure_service
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
        business_type=case_request.business_type,
        franchise_status=case_request.franchise_status,
        employee_count=case_request.employee_count,
        lease_status=case_request.lease_status,
        planned_closure_date=case_request.planned_closure_date,
    )
    case = case_crud.create_case(session, case)
    _fill_temp_case_procedure_steps(session, case.id)
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
    )


def _create_case_creation_evidence(
    session: Session, case: Case, case_request: CaseCreateRequest
) -> CaseHistory:
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
    return history


def _fill_temp_case_procedure_steps(session: Session, case_id: int) -> None:
    # TODO: 실제 폐업절차 마스터 데이터/조건(step_eligibility)로 교체 필요. 폐업절차 DB 구조가 아직
    # 확정되지 않아, 지금은 case_procedure_step 채우는 흐름 검증용 임시 더미 절차 4개만 사용한다.
    #
    # step_code를 AI가 아는 논리 코드와 똑같이 둔다. 이름이 정확히 같을 때만 절차 대응표
    # (procedure_bindings)가 자동으로 맺어지고(app/agent/action_catalog.py의
    # resolve_procedure_bindings), 대응표가 비면 공식 문서를 찾아도 Supervisor가
    # AGENT_PROCEDURE_BINDINGS_MISSING으로 판단을 멈춘다.
    #
    # TODO: 실제 폐업절차는 이보다 많고 이름도 다를 것이다. 그때는 이 4개를 어느 실제 절차에
    # 맺을지 정해 procedure_bindings를 직접 넘겨야 한다(judgment.py).
    temp_procedure_steps = [
        ("CONFIRM_RESTORATION_SCOPE", "원상복구 범위 확인"),
        ("FILE_TAX_BUSINESS_CLOSURE", "세무서 폐업 신고"),
        ("FILE_FOOD_SERVICE_CLOSURE", "영업신고증 폐업 신고"),
        ("REPORT_WORKPLACE_INSURANCE_CLOSURE", "4대보험 상실 신고"),
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
