"""들어온 입력 하나를 AI 판단에 태운다.

입력 조립(case_snapshot) → AI 호출 → 결과 저장(decision_record)을 한 줄로 잇는다.

처음에는 가입 직후 첫 판단에만 썼지만 결과 제출도 같은 길을 탄다. 어느 입력을
판단할지는 부르는 쪽이 정해서 넘긴다.
"""

import logging
from typing import Literal

from sqlmodel import Session

from app.be.crud import case_history as case_history_crud
from app.be.db import get_engine
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import DecisionRecord
from app.be.services import agent_runtime as agent_runtime_service
from app.be.services import case_snapshot as case_snapshot_service
from app.be.services import decision_record as decision_record_service
from app.be.services import document as document_service
from app.be.services import reviewed_procedure as reviewed_procedure_service
from app.agent.schemas import KnownProcedureStep
from app.common.agent_dto import AgentGraphInput, AgentGraphOutput
from app.common.agent_service import build_planning_input, run_case_planning

logger = logging.getLogger(__name__)


async def run_judgment_in_background(case_history_id: int) -> None:
    """응답을 보낸 뒤 뒤에서 도는 진입점.

    요청에 딸린 세션은 응답과 함께 닫히므로 여기서 세션을 새로 연다. 실패해도 사용자에게
    돌려줄 응답이 이미 나갔기 때문에, 예외를 밖으로 던지지 않고 판단 상태만 FAILED로 남긴다.
    """

    try:
        # 세션을 셋으로 끊는다. AI가 도는 50초 동안 DB 커넥션을 쥐고 있으면, 자리가 15개뿐이라
        # 판단 15건이 겹치는 순간 판단과 상관없는 사장님의 조회·로그인까지 막힌다
        # (실측: 14건 51ms, 15건 실패. tests/test_pool_capacity.py).
        with Session(get_engine()) as session:
            graph_input, known_procedure_steps = _read_judgment_input(session, case_history_id)
        outcome = await _ask_agent(graph_input, known_procedure_steps)
        with Session(get_engine()) as session:
            _save_judgment_outcome(session, case_history_id, outcome)
    except Exception as error:
        logger.exception("case_history %s 판단 실패", case_history_id)
        try:
            with Session(get_engine()) as session:
                # 무엇 때문에 끊겼는지 함께 넘긴다. 다시 해도 안 풀리는 종류면 화면에
                # "다시 시도"를 띄우면 안 된다.
                decision_record_service.mark_judgment_failed(session, case_history_id, error)
        except Exception:
            logger.exception("case_history %s 판단 실패 상태 기록도 실패", case_history_id)
    await judge_owed_documents(case_history_id)


async def judge_owed_documents(case_history_id: int) -> None:
    """판단(case_history_id)이 끝난 뒤, 그동안 판단에 못 넘긴 서류가 있으면 이어서 판단한다.

    판단 중이거나 충돌 확인을 기다리는 동안 올린 서류는 저장만 되고 판단은 미뤄진다(#173 리뷰).
    성공·실패 모두 부른다. 끝난 판단과 상관없이 서류는 새로 받은 입력이기 때문이다.
    이어서 돈 판단이 끝나면 여기를 또 부르지만, 그때는 판단에 넘긴 서류와 지금 서류가 같아 멈춘다.
    """

    try:
        with Session(get_engine()) as session:
            next_history_id = document_service.queue_owed_document_judgment(
                session, document_service.document_directory(), case_history_id
            )
    except Exception:
        logger.exception("case_history %s 뒤 서류 재판단 확인 실패", case_history_id)
        return
    if next_history_id is not None:
        await run_judgment_in_background(next_history_id)


class UnknownJudgmentTriggerError(ValueError):
    """입력의 출처를 AI가 받는 트리거로 옮길 수 없는 상태.

    방금 들어온 글이 아니라 그 입력을 만든 코드가 원인이라, 같은 입력으로 다시 판단해도
    같은 자리에서 또 터진다. 그래서 "다시 시도"가 아니라 "문의"로 안내한다
    (decision_record.mark_judgment_failed).
    """

    retryable = False


def _trigger_type_of(history: CaseHistory) -> Literal["CASE_CREATED", "RESULT_SUBMITTED", "DOCUMENT_SUBMITTED"]:
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
    if history.source == "DOCUMENT_SUBMITTED":
        # 서류 글(document_replan_text)도 근거는 사장님 입력(USER_INPUT)으로 남지만, AI는
        # "사장님이 말한 결과"가 아니라 "서류에서 꺼낸 값"으로 읽어야 해서 트리거를 나눈다(#137).
        return "DOCUMENT_SUBMITTED"
    raise UnknownJudgmentTriggerError(
        f"case_history {history.id}의 source {history.source}는 판단 트리거가 없다"
    )


async def run_judgment(
    session: Session, case_history_id: int
) -> tuple[AgentGraphOutput, DecisionRecord | None]:
    """판단 결과와, 저장된 검수 기록(정상 판단일 때만)을 함께 돌려준다.

    어느 입력을 판단할지는 호출부가 정해서 넘긴다. 여기서 CASE_CREATED 이력을 직접 찾으면
    결과 제출 판단이 붙었을 때 방금 들어온 입력이 아니라 가입 때 입력을 판단하게 된다.
    """

    graph_input, known_procedure_steps = _read_judgment_input(session, case_history_id)
    outcome = await _ask_agent(graph_input, known_procedure_steps)
    return outcome, _save_judgment_outcome(session, case_history_id, outcome)


def _read_judgment_input(
    session: Session, case_history_id: int
) -> tuple[AgentGraphInput, list[KnownProcedureStep]]:
    """AI에 넘길 것을 DB에서 전부 읽어 둔다. 여기까지 끝나면 세션을 닫아도 된다."""

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
    return graph_input, agent_runtime_service.build_known_procedure_steps(session)


async def _ask_agent(
    graph_input: AgentGraphInput, known_procedure_steps: list[KnownProcedureStep]
) -> AgentGraphOutput:
    """AI 호출. 여기서는 DB를 쓰지 않는다 — 커넥션을 쥔 채로 기다리지 않게 하려고 떼어 뒀다."""

    # AI 호출은 AI팀이 공개한 입구 하나로만 한다(app/common/agent_service.py). 런타임을 우리가
    # 직접 조립하면 AI 내부가 바뀔 때 BE만 깨지고, 추가 입력·충돌 확인 트리거를 만들 수도 없다.
    return await run_case_planning(
        graph_input,
        known_procedure_steps=known_procedure_steps,
        # None은 "절차 목록의 step_code가 AI 논리 코드와 같으면 알아서 맺어라"는 뜻이고,
        # 빈 표({})는 "맺을 게 없다"는 뜻이라 서로 다르다(action_catalog.resolve_procedure_bindings).
        # 절차의 step_code를 AI 논리 코드와 같게 적재하므로 자동으로 맺힌다
        # (procedure_registry.ensure_cafe_procedure_registry).
        procedure_bindings=None,
        procedure_store=reviewed_procedure_service.load_reviewed_procedures(),
        support_catalog=agent_runtime_service.empty_support_catalog(),
    )


def _save_judgment_outcome(
    session: Session, case_history_id: int, outcome: AgentGraphOutput
) -> DecisionRecord | None:
    """판단 결과를 남긴다. 이력은 번호로 다시 읽는다 — 읽을 때 쓴 세션은 이미 닫혔을 수 있다."""

    history = case_history_crud.get_case_history_by_id(session, case_history_id)
    if history is None:
        raise ValueError(f"case_history {case_history_id} not found")

    # 결과는 세 가지이고 화면이 할 일이 각각 다르다. 검수를 통과한 판단만 Case 값을 바꾸고,
    # 충돌은 되물을 거리를, 실패는 다음 행동을 남긴다.
    if outcome.outcome_type == "CONFLICT":
        decision_record_service.save_conflict(session, history, outcome)
        return None

    if outcome.outcome_type == "SAFE_FAILURE":
        decision_record_service.save_safe_failure(session, history, outcome)
        return None

    return decision_record_service.save_reviewed_plan(session, history, outcome)
