"""사장님이 고른 충돌 결정을 AI에 넘기고, 돌아온 결과를 반영한다.

충돌이 나면 AI는 아무것도 바꾸지 않고 "이게 어긋난다"만 돌려준다(decision_record.save_conflict).
사장님이 새 값과 기존 값 중 하나를 고르면 그때 다시 판단을 돌려서, 고른 값을 Case에 반영하고
충돌을 해결 처리한다.

가입·결과 제출 판단(judgment.run_judgment)과 AI 입구가 다르다. 저쪽은 "이 글을 읽어라"이고
여기는 "네가 물어본 것에 답한다"라서, 보관해 둔 충돌 원본과 그때의 Case 상태를 그대로
돌려줘야 한다. 그래서 run_judgment를 재사용하지 않는다.
"""

import logging
from uuid import UUID

from sqlmodel import Session

from app.agent.schemas import CaseSnapshot, ConflictCandidate, ConflictSelection
from app.be.models.evidence import DecisionRecord
from app.common.agent_dto import AgentGraphOutput
from app.be.crud import case_history as case_history_crud
from app.be.crud import conflict_reference as conflict_reference_crud
from app.be.db import get_engine
from app.be.models.case_history import CaseHistory
from app.be.models.mixins import KST
from app.be.services import agent_runtime as agent_runtime_service
from app.be.services import case_snapshot as case_snapshot_service
from app.be.services import decision_record as decision_record_service
from app.be.services import reviewed_procedure as reviewed_procedure_service
from app.common.agent_service import build_conflict_input, run_case_planning

logger = logging.getLogger(__name__)

__all__ = ["run_conflict_decision_in_background", "run_conflict_decision"]


class ConflictDecisionInputError(ValueError):
    """고른 충돌로 AI 입력을 만들 수 없는 상태.

    방금 들어온 선택이 아니라 보관해 둔 행이 원인이라, 같은 선택으로 다시 눌러도 같은 자리에서
    또 터진다. 그래서 "다시 시도"가 아니라 "문의"로 안내한다(decision_record.mark_judgment_failed).
    """

    retryable = False


async def run_conflict_decision_in_background(
    case_history_id: int, choices: dict[int, str]
) -> None:
    """응답을 보낸 뒤 뒤에서 도는 진입점.

    사용자 선택은 DB에 남기지 않기로 해서(현석님 #108) 인자로 받아 여기까지 들고 온다.
    요청에 딸린 세션은 응답과 함께 닫히므로 세션을 새로 연다.
    """

    try:
        with Session(get_engine()) as session:
            await run_conflict_decision(session, case_history_id, choices)
    except Exception as error:
        logger.exception("case_history %s 충돌 결정 판단 실패", case_history_id)
        try:
            with Session(get_engine()) as session:
                decision_record_service.mark_judgment_failed(session, case_history_id, error)
        except Exception:
            logger.exception("case_history %s 실패 상태 기록도 실패", case_history_id)


async def run_conflict_decision(
    session: Session, case_history_id: int, choices: dict[int, str]
) -> tuple[AgentGraphOutput, DecisionRecord | None]:
    """고른 값을 AI에 넘겨 재판단하고 결과를 저장한다.

    choices는 화면이 보낸 {conflict_reference.id: "PROPOSED"|"STORED"}다. 화면에는 DB 번호를
    주고 AI는 자기 식별자(conflict_ref)를 받으므로, 보관한 행에서 꺼내 바꿔 넘긴다.
    """

    history = case_history_crud.get_case_history_by_id(session, case_history_id)
    if history is None:
        raise ValueError(f"case_history {case_history_id} not found")

    conflicts, selections, conflict_snapshot = _restore_batch(session, history.case_id, choices)

    outcome = await run_case_planning(
        build_conflict_input(
            # 보관한 번호를 그대로 쓴다. 새로 찍으면 AI가 전부 STALE로 거절한다.
            case_snapshot=case_snapshot_service.build_case_snapshot(
                session, history.case_id, snapshot_id=conflict_snapshot.snapshot_id
            ),
            conflicts=conflicts,
            selections=selections,
            conflict_snapshot=conflict_snapshot,
            input_event_id=str(history.id),
            confirmed_at=history.created_at.replace(tzinfo=KST),
            # TODO: 프론트가 자기 쪽 이벤트 식별자를 보내주기로 하면 그 값을 넣는다. 아직 미협의.
            client_event_id=None,
        ),
        known_procedure_steps=agent_runtime_service.build_known_procedure_steps(session),
        procedure_bindings=None,
        procedure_store=reviewed_procedure_service.load_reviewed_procedures(),
        support_catalog=agent_runtime_service.empty_support_catalog(),
    )

    # 어디까지 반영할지는 결과에 따라 다르다(현석님 #108에서 정함).
    #
    #   DONE / NEEDS_MORE_INFO  고른 값 저장 + 충돌 닫기
    #   또 다른 충돌            새 충돌 저장 + 방금 고른 것은 닫기
    #   실패                    아무것도 안 함 — 충돌이 남아야 다시 결정할 수 있다
    #
    # 되물을 것이 또 생겨도(NEEDS_MORE_INFO) 고른 값은 저장한다. 안 그러면 사장님이 답을
    # 했는데 Case가 그대로라 같은 질문을 또 받는다.
    if outcome.outcome_type == "CONFLICT":
        decision_record_service.save_conflict(session, history, outcome, resolved_conflicts=choices)
        return outcome, None

    if outcome.outcome_type == "SAFE_FAILURE":
        decision_record_service.save_safe_failure(session, history, outcome)
        return outcome, None

    return outcome, decision_record_service.save_reviewed_plan(
        session, history, outcome, resolved_conflicts=choices
    )


def _restore_batch(
    session: Session, case_id: int, choices: dict[int, str]
) -> tuple[list[ConflictCandidate], list[ConflictSelection], CaseSnapshot]:
    """보관해 둔 충돌 원본·그때의 Case 상태를 되살리고, 고른 값을 AI 모양으로 바꾼다.

    AI는 받은 충돌이 자기가 준 것과 같은지 다이제스트로 대조한다. 그래서 화면에 보여주려고
    글자로 바꾼 committed_value·proposed_value가 아니라, 통째로 보관해 둔 candidate_payload를
    되살려 넘긴다.
    """

    pending = conflict_reference_crud.get_pending_conflicts_by_case_id(session, case_id)
    if not pending:
        raise ConflictDecisionInputError(f"case {case_id}에 확인 대기 중인 충돌이 없다")

    missing = {row.id for row in pending} - set(choices)
    if missing:
        raise ConflictDecisionInputError(f"결정하지 않은 충돌이 있다: {sorted(missing)}")

    conflicts, selections = [], []
    for row in pending:
        if row.candidate_payload is None:
            raise ConflictDecisionInputError(
                f"충돌 {row.id}에 AI로 돌려줄 원본이 없다"
            )
        conflicts.append(ConflictCandidate.model_validate(row.candidate_payload))
        # "새 값"을 고르면 채택, "기존 값 유지"면 거절이다. 둘 다 결정이므로 어느 쪽이든
        # 충돌은 해결된 것으로 처리한다(save 쪽).
        selections.append(
            ConflictSelection(conflict_ref=row.conflict_ref, accepted=choices[row.id] == "PROPOSED")
        )

    # 충돌을 낸 제출 이력에 그때의 Case 상태가 통째로 들어 있다(decision_record.save_conflict).
    # 묶음은 한 판단에서 나오므로 어느 행을 따라가도 같은 이력이다.
    origin = case_history_crud.get_case_history_by_id(session, pending[0].case_history_id)
    if origin is None or origin.conflict_snapshot is None:
        raise ConflictDecisionInputError(
            f"충돌 {pending[0].id}을 낸 판단에 보관된 Case 상태가 없다"
        )
    return conflicts, selections, CaseSnapshot.model_validate(origin.conflict_snapshot)
