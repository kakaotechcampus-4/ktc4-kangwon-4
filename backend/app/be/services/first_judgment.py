"""들어온 입력 하나를 AI 판단에 태운다.

입력 조립(case_snapshot) → AI 호출 → 결과 저장(decision_record)을 한 줄로 잇는다.

처음에는 가입 직후 첫 판단에만 썼지만 결과 제출도 같은 길을 타서, 이름과 달리
"첫" 판단 전용이 아니다. 어느 입력을 판단할지는 부르는 쪽이 정해서 넘긴다.
"""

import logging
from typing import Literal

from sqlmodel import Session

from app.be.crud import case_history as case_history_crud
from app.be.db import _engine
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import DecisionRecord
from app.be.services import agent_runtime as agent_runtime_service
from app.be.services import case_snapshot as case_snapshot_service
from app.be.services import decision_record as decision_record_service
from app.be.services import reviewed_procedure as reviewed_procedure_service
from app.common.agent_dto import AgentGraphOutput
from app.common.agent_service import build_planning_input, run_case_planning

logger = logging.getLogger(__name__)


async def run_first_judgment_in_background(case_history_id: int) -> None:
    """응답을 보낸 뒤 뒤에서 도는 진입점.

    요청에 딸린 세션은 응답과 함께 닫히므로 여기서 세션을 새로 연다. 실패해도 사용자에게
    돌려줄 응답이 이미 나갔기 때문에, 예외를 밖으로 던지지 않고 판단 상태만 FAILED로 남긴다.
    """

    try:
        with Session(_engine) as session:
            await run_first_judgment(session, case_history_id)
    except Exception as error:
        logger.exception("case_history %s 첫 판단 실패", case_history_id)
        try:
            with Session(_engine) as session:
                # 무엇 때문에 끊겼는지 함께 넘긴다. 다시 해도 안 풀리는 종류면 화면에
                # "다시 시도"를 띄우면 안 된다.
                decision_record_service.mark_judgment_failed(session, case_history_id, error)
        except Exception:
            logger.exception("case_history %s 판단 실패 상태 기록도 실패", case_history_id)


def _trigger_type_of(history: CaseHistory) -> Literal["CASE_CREATED", "RESULT_SUBMITTED"]:
    """이 입력이 "가입하면서 받은 것"인지 "사장님이 결과를 알려준 것"인지 고른다.

    AI는 둘을 다르게 읽는다. 가입 입력은 처음 보는 Case를 세우는 것이고, 결과 보고는
    이미 세워둔 계획이 어디까지 갔는지를 고쳐 쓰는 것이다. 전부 가입으로 넘기면 AI가
    사장님이 방금 알려준 진행 상황을 "처음 받은 값"으로 읽는다.

    SYSTEM_BATCH는 아직 만드는 곳이 없다. 둘 중 아무 쪽으로 넘겨도 AI에게 틀리게
    알려주는 것이라, 그 길이 생길 때 무엇으로 볼지 정하도록 여기서 멈춘다.
    """

    if history.source == "CASE_CREATED":
        return "CASE_CREATED"
    if history.source == "USER_INPUT":
        return "RESULT_SUBMITTED"
    raise ValueError(f"case_history {history.id}의 source {history.source}는 판단 트리거가 없다")


async def run_first_judgment(
    session: Session, case_history_id: int
) -> tuple[AgentGraphOutput, DecisionRecord | None]:
    """판단 결과와, 저장된 검수 기록(정상 판단일 때만)을 함께 돌려준다.

    어느 입력을 판단할지는 호출부가 정해서 넘긴다. 여기서 CASE_CREATED 이력을 직접 찾으면
    결과 제출 판단이 붙었을 때 방금 들어온 입력이 아니라 가입 때 입력을 판단하게 된다.
    """

    history = case_history_crud.get_case_history_by_id(session, case_history_id)
    if history is None:
        raise ValueError(f"case_history {case_history_id} not found")

    graph_input = build_planning_input(
        trigger_type=_trigger_type_of(history),
        case_snapshot=case_snapshot_service.build_case_snapshot(session, history.case_id),
        user_input=case_snapshot_service.build_user_input(
            case_history_id=history.id,
            raw_input=history.raw_input,
            submitted_at=history.created_at,
        ),
        # TODO: 프론트가 자기 쪽 이벤트 식별자를 보내주기로 하면 그 값을 넣는다. 아직 미협의.
        client_event_id=None,
    )

    # AI 호출은 AI팀이 공개한 입구 하나로만 한다(app/common/agent_service.py). 런타임을 우리가
    # 직접 조립하면 AI 내부가 바뀔 때 BE만 깨지고, 추가 입력·충돌 확인 트리거를 만들 수도 없다.
    outcome = await run_case_planning(
        graph_input,
        known_procedure_steps=agent_runtime_service.build_known_procedure_steps(session),
        # None은 "절차 목록의 step_code가 AI 논리 코드와 같으면 알아서 맺어라"는 뜻이고,
        # 빈 표({})는 "맺을 게 없다"는 뜻이라 서로 다르다(action_catalog.resolve_procedure_bindings).
        # 지금은 임시 절차의 이름을 논리 코드와 같게 둬서 자동으로 맺는다(case.py).
        # TODO: 실제 폐업절차 데이터가 들어오면 이름이 달라진다. 그때는 어느 절차에 맺을지
        # 정해 여기에 직접 넘겨야 한다.
        procedure_bindings=None,
        procedure_store=reviewed_procedure_service.load_reviewed_procedures(),
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
