"""case 생성 직후 AI 첫 판단을 실행한다.

입력 조립(case_snapshot) → AI 호출 → 결과 저장(decision_record)을 한 줄로 잇는다.
"""

from sqlmodel import Session

from app.agent.schemas import AgentGraphOutput
from app.be.crud import case_history as case_history_crud
from app.be.models.evidence import DecisionRecord
from app.be.services import agent_runtime as agent_runtime_service
from app.be.services import case_snapshot as case_snapshot_service
from app.be.services import decision_record as decision_record_service


async def run_first_judgment(
    session: Session, case_id: int
) -> tuple[AgentGraphOutput, DecisionRecord | None]:
    """판단 결과와, 저장된 검수 기록(정상 판단일 때만)을 함께 돌려준다."""

    # 이번 판단이 어느 입력에 대한 것인지는 여기서 정한다. Case 생성 판단이므로
    # CASE_CREATED 이력이고, 결과 입력 판단이 붙으면 그때 그 입력의 이력을 넘기면 된다.
    history = case_history_crud.get_case_created_history(session, case_id)
    if history is None:
        raise ValueError(f"case {case_id} has no CASE_CREATED history")

    graph_input = case_snapshot_service.build_case_created_input(session, case_id)

    # 호출할 때마다 런타임을 새로 만든다 = LLM 연결도 매번 새로 열고 닫는다. AgentRuntime은
    # 원래 "여러 판단 요청에 답할 수 있게 한 번 만들어 두는" 물건(app/agent/runtime.py:118)이라
    # 서버 시작 시 한 번 만들어 재사용하는 게 맞다. 다만 그러면 AI가 아는 절차 목록이 서버
    # 시작 시점에 고정되므로(DB에서 절차가 바뀌어도 재시작 전엔 반영 안 됨) 그 결정을 함께
    # 해야 해서, 지금은 단순하게 매번 만든다.
    runtime = await agent_runtime_service.build_agent_runtime(session)
    try:
        outcome = await runtime.run_planning(graph_input)
    finally:
        await runtime.aclose()

    if outcome.outcome_type != "REVIEWED_PLAN":
        # TODO: CONFLICT는 사용자에게 되물어 확인받는 흐름이 필요하고, SAFE_FAILURE는 실패
        # 이유를 화면에 보여줘야 한다. 둘 다 저장 스펙상 정상 결과로는 저장하지 않는데,
        # 호출한 쪽에 무엇을 어떻게 돌려줄지는 아직 정하지 않았다.
        return outcome, None

    return outcome, decision_record_service.save_reviewed_plan(session, history, outcome)
