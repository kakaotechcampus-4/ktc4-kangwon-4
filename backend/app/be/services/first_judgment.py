"""case 생성 직후 AI 첫 판단을 실행한다.

입력 조립(case_snapshot) → AI 호출 → 결과 저장(decision_record)을 한 줄로 잇는다.
"""

import logging

from sqlmodel import Session

from app.be.crud import case_history as case_history_crud
from app.be.db import _engine
from app.be.models.evidence import DecisionRecord
from app.be.services import agent_runtime as agent_runtime_service
from app.be.services import case_snapshot as case_snapshot_service
from app.be.services import decision_record as decision_record_service
from app.common.agent_dto import AgentGraphOutput
from app.common.agent_service import build_planning_input, run_case_planning

logger = logging.getLogger(__name__)


async def run_first_judgment_in_background(case_id: int) -> None:
    """응답을 보낸 뒤 뒤에서 도는 진입점.

    요청에 딸린 세션은 응답과 함께 닫히므로 여기서 세션을 새로 연다. 실패해도 사용자에게
    돌려줄 응답이 이미 나갔기 때문에, 예외를 밖으로 던지지 않고 판단 상태만 FAILED로 남긴다.
    """

    try:
        with Session(_engine) as session:
            await run_first_judgment(session, case_id)
    except Exception:
        logger.exception("case %s 첫 판단 실패", case_id)
        try:
            with Session(_engine) as session:
                decision_record_service.mark_judgment_failed(session, case_id)
        except Exception:
            logger.exception("case %s 판단 실패 상태 기록도 실패", case_id)


async def run_first_judgment(
    session: Session, case_id: int
) -> tuple[AgentGraphOutput, DecisionRecord | None]:
    """판단 결과와, 저장된 검수 기록(정상 판단일 때만)을 함께 돌려준다."""

    # 이번 판단이 어느 입력에 대한 것인지는 여기서 정한다. Case 생성 판단이므로
    # CASE_CREATED 이력이고, 결과 입력 판단이 붙으면 그때 그 입력의 이력을 넘기면 된다.
    history = case_history_crud.get_case_created_history(session, case_id)
    if history is None:
        raise ValueError(f"case {case_id} has no CASE_CREATED history")

    graph_input = build_planning_input(
        trigger_type="CASE_CREATED",
        case_snapshot=case_snapshot_service.build_case_snapshot(session, case_id),
        user_input=case_snapshot_service.build_user_input(history),
        # TODO: 프론트가 자기 쪽 이벤트 식별자를 보내주기로 하면 그 값을 넣는다. 아직 미협의.
        client_event_id=None,
    )

    # AI 호출은 AI팀이 공개한 입구 하나로만 한다(app/common/agent_service.py). 런타임을 우리가
    # 직접 조립하면 AI 내부가 바뀔 때 BE만 깨지고, 추가 입력·충돌 확인 트리거를 만들 수도 없다.
    outcome = await run_case_planning(
        graph_input,
        known_procedure_steps=agent_runtime_service.build_known_procedure_steps(session),
        # TODO: AI가 아는 절차(원상복구 범위 확인/세무서 폐업 신고/영업신고증 폐업 신고/4대보험
        # 상실 신고)와 우리 DB의 절차를 짝지어야 한다. 지금은 임시 더미 절차뿐이라 비워 둔다
        # — 비면 AI가 절차와 연결된 다음 행동을 내놓지 못한다.
        procedure_bindings={},
        procedure_store=agent_runtime_service.EmptyProcedureStore(),
        support_catalog=agent_runtime_service.empty_support_catalog(),
    )

    # 결과는 세 가지이고 화면이 할 일이 각각 다르다. 검수를 통과한 판단만 Case 값을 바꾸고,
    # 충돌은 되물을 거리를, 실패는 다음 행동을 남긴다.
    if outcome.outcome_type == "CONFLICT":
        decision_record_service.save_conflict(session, history, outcome)
        return outcome, None

    if outcome.outcome_type == "SAFE_FAILURE":
        decision_record_service.save_safe_failure(session, history, outcome)
        return outcome, None

    return outcome, decision_record_service.save_reviewed_plan(session, history, outcome)
