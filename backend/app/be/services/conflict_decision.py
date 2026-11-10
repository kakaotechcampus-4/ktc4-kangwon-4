"""사장님이 고른 충돌 결정을 AI에 넘기고, 돌아온 결과를 반영한다.

충돌이 나면 AI는 아무것도 바꾸지 않고 "이게 어긋난다"만 돌려준다(decision_record.save_conflict).
사장님이 새 값과 기존 값 중 하나를 고르면 그때 다시 판단을 돌려서, 고른 값을 Case에 반영하고
충돌을 해결 처리한다.

가입·결과 제출 판단(judgment.run_judgment)과 AI 입구가 다르다. 저쪽은 "이 글을 읽어라"이고
여기는 "네가 물어본 것에 답한다"라서, 보관해 둔 충돌 원본과 그때의 Case 상태를 그대로
돌려줘야 한다. 그래서 run_judgment를 재사용하지 않는다.
"""

import logging

from sqlmodel import Session, select

from app.agent.enrichment import confirmation_state
from app.agent.schemas import (
    CaseSnapshot,
    ConflictCandidate,
    ConflictSelection,
    KnownProcedureStep,
    RetainedInfoResult,
    SafeFailureOutcome,
)
from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import ConflictReference, DecisionRecord
from app.common.agent_dto import AgentGraphInput, AgentGraphOutput
from app.be.crud import case_history as case_history_crud
from app.be.crud import conflict_reference as conflict_reference_crud
from app.be.db import get_engine
from app.be.models.mixins import KST
from app.be.services import agent_runtime as agent_runtime_service
from app.be.services import case_snapshot as case_snapshot_service
from app.be.services import decision_record as decision_record_service
from app.be.services import judgment as judgment_service
from app.be.services import reviewed_procedure as reviewed_procedure_service
from app.be.services.redaction import has_numbered_placeholders
from app.be.services.unmasking import build_case_placeholders
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
        # 판단과 같은 이유로 세션을 끊는다(judgment.run_judgment_in_background).
        with Session(get_engine()) as session:
            graph_input, known_procedure_steps = _read_decision_input(
                session, case_history_id, choices
            )
        outcome = await _ask_agent(graph_input, known_procedure_steps)
        with Session(get_engine()) as session:
            _save_decision_outcome(session, case_history_id, outcome, choices)
    except Exception as error:
        logger.exception("case_history %s 충돌 결정 판단 실패", case_history_id)
        try:
            with Session(get_engine()) as session:
                decision_record_service.mark_judgment_failed(session, case_history_id, error)
        except Exception:
            logger.exception("case_history %s 실패 상태 기록도 실패", case_history_id)
    # 충돌 확인을 기다리는 동안 올린 서류는 판단이 미뤄져 있다. 확인 처리가 끝났으니 이어서 본다.
    await judgment_service.judge_owed_documents(case_history_id)


async def run_conflict_decision(
    session: Session, case_history_id: int, choices: dict[int, str]
) -> tuple[AgentGraphOutput, DecisionRecord | None]:
    """고른 값을 AI에 넘겨 재판단하고 결과를 저장한다.

    choices는 화면이 보낸 {conflict_reference.id: "PROPOSED"|"STORED"}다. 화면에는 DB 번호를
    주고 AI는 자기 식별자(conflict_ref)를 받으므로, 보관한 행에서 꺼내 바꿔 넘긴다.
    """

    graph_input, known_procedure_steps = _read_decision_input(session, case_history_id, choices)
    outcome = await _ask_agent(graph_input, known_procedure_steps)
    return outcome, _save_decision_outcome(session, case_history_id, outcome, choices)


def _read_decision_input(
    session: Session, case_history_id: int, choices: dict[int, str]
) -> tuple[AgentGraphInput, list[KnownProcedureStep]]:
    """AI에 넘길 것을 DB에서 전부 읽어 둔다. 여기까지 끝나면 세션을 닫아도 된다."""

    history = case_history_crud.get_case_history_by_id(session, case_history_id)
    if history is None:
        raise ValueError(f"case_history {case_history_id} not found")

    conflicts, selections, conflict_snapshot, retained = _restore_batch(
        session, history.case_id, choices
    )

    placeholders, _ = build_case_placeholders(session, history.case_id)
    current = case_snapshot_service.build_case_snapshot(
        session, history.case_id, snapshot_id=conflict_snapshot.snapshot_id, placeholders=placeholders,
    )
    frozen_state = confirmation_state(conflict_snapshot)
    if confirmation_state(current) != frozen_state and not has_numbered_placeholders(frozen_state):
        # 번호 도입 전 충돌은 같은 DB를 예전 가림 방식으로 읽어 전체 상태가 같을 때만 쓴다.
        legacy = case_snapshot_service.build_case_snapshot(
            session, history.case_id, snapshot_id=conflict_snapshot.snapshot_id,
        )
        if confirmation_state(legacy) == frozen_state:
            current = legacy

    return (
        build_conflict_input(
            # 보관한 번호를 그대로 쓴다. 새로 찍으면 AI가 전부 STALE로 거절한다.
            case_snapshot=current,
            conflicts=conflicts,
            selections=selections,
            conflict_snapshot=conflict_snapshot,
            # 충돌이 아니었던 사실·진행 보고. 없으면 None이고, 그때는 예전처럼 충돌만 다룬다.
            retained_info_result=retained,
            input_event_id=str(history.id),
            confirmed_at=history.created_at.replace(tzinfo=KST),
            # TODO: 프론트가 자기 쪽 이벤트 식별자를 보내주기로 하면 그 값을 넣는다. 아직 미협의.
            client_event_id=None,
        ),
        agent_runtime_service.build_known_procedure_steps(session),
    )


async def _ask_agent(
    graph_input: AgentGraphInput, known_procedure_steps: list[KnownProcedureStep]
) -> AgentGraphOutput:
    """AI 호출. 여기서는 DB를 쓰지 않는다 — 커넥션을 쥔 채로 기다리지 않게 하려고 떼어 뒀다."""

    return await run_case_planning(
        graph_input,
        known_procedure_steps=known_procedure_steps,
        procedure_bindings=None,
        procedure_store=reviewed_procedure_service.load_reviewed_procedures(),
        support_catalog=agent_runtime_service.empty_support_catalog(),
    )


def _save_decision_outcome(
    session: Session, case_history_id: int, outcome: AgentGraphOutput, choices: dict[int, str]
) -> DecisionRecord | None:
    """결정 결과를 남긴다. 이력은 번호로 다시 읽는다 — 읽을 때 쓴 세션은 이미 닫혔을 수 있다."""

    history = case_history_crud.get_case_history_by_id(session, case_history_id)
    if history is None:
        raise ValueError(f"case_history {case_history_id} not found")

    # 어디까지 반영할지는 결과에 따라 다르다(현석님 #108에서 정함).
    #
    #   DONE / NEEDS_MORE_INFO  고른 값 저장 + 충돌 닫기
    #   또 다른 충돌            새 충돌 저장 + 방금 고른 것은 닫기
    #   실패                    충돌 유지. 단, 재입력이 필요한 묶음은 미채택으로 정리한다.
    #
    # 되물을 것이 또 생겨도(NEEDS_MORE_INFO) 고른 값은 저장한다. 안 그러면 사장님이 답을
    # 했는데 Case가 그대로라 같은 질문을 또 받는다.
    if outcome.outcome_type == "CONFLICT":
        # 이 분기에서는 고른 값이 Case에 들어가지 않는다. CONFLICT에는 검수를 통과한 변경이
        # 없어서 반영할 것이 없고, 그런데도 고른 충돌은 닫는다. 결정이 기록(CONFIRMED/
        # REJECTED)으로만 남고 값은 사라지는 셈이라, 조용히 넘기지 않고 남긴다.
        #
        # 안 닫을 수는 없다. 남겨두면 다음 확인 묶음에 판단이 다른 충돌 두 개가 섞이는데,
        # 되살릴 Case 상태는 첫 줄의 판단에서 한 벌만 꺼내므로(_restore_batch) AI가 묶음
        # 전체를 STALE로 거절한다.
        #
        # TODO: 정상적인 확인 결과로 새 충돌이 생기는 경로는 지금 Agent에 없다고 확인받았다
        # (승준님 #136). 이 분기가 실제로 돌면 사라진 값을 어떻게 할지 정해야 한다.
        logger.warning(
            "case_history %s 재판단에서 또 충돌이 나서 사장님이 고른 값 %s는 반영하지 않고 "
            "충돌만 닫는다", case_history_id, choices,
        )
        decision_record_service.save_conflict(session, history, outcome, resolved_conflicts=choices)
        return None

    if outcome.outcome_type == "SAFE_FAILURE":
        if (outcome.recovery_action_code == "RESUBMIT_INPUT"
                and history.source == "CONFLICT_DECISION"):
            if not _prepare_resubmit_failure(session, history, outcome, choices):
                return None
        decision_record_service.save_safe_failure(session, history, outcome)
        return None

    return decision_record_service.save_reviewed_plan(
        session, history, outcome, resolved_conflicts=choices
    )


def _prepare_resubmit_failure(
    session: Session, history: CaseHistory, outcome: SafeFailureOutcome, choices: dict[int, str]
) -> bool:
    """현재 결정이면 실패를 저장한다. 원본 묶음도 일치할 때만 미채택 처리를 함께 준비한다."""
    trigger = outcome.trigger
    if outcome.case_id != history.case_id or trigger.input_event_id != str(history.id):
        return False
    case = session.get(Case, history.case_id, with_for_update=True, populate_existing=True)
    if case is None:
        return False
    session.refresh(history, with_for_update=True)
    latest = session.exec(select(CaseHistory.id).where(CaseHistory.case_id == case.id,
        CaseHistory.source.in_(("CASE_CREATED", "USER_INPUT", "CONFLICT_DECISION", "DOCUMENT_SUBMITTED")))
        .order_by(CaseHistory.created_at.desc(), CaseHistory.id.desc()).limit(1).with_for_update()).first()
    if (history.source != "CONFLICT_DECISION" or history.case_id != case.id
            or history.judgment_status != "PENDING" or latest != history.id):
        return False
    if case.case_status != "IN_PROGRESS" or trigger.trigger_type != "CONFLICT_CONFIRMED":
        return True
    # 원본 형식 등이 달라도 현재 판단은 실패로 끝낸다. 충돌 정리만 엄격히 제한한다.
    if trigger.conflict_snapshot is None:
        return True
    pending = session.exec(select(ConflictReference).where(ConflictReference.case_id == case.id,
        ConflictReference.status == "PENDING").with_for_update().execution_options(populate_existing=True)).all()
    if (not pending or {row.id for row in pending} != set(choices)
            or any(side not in {"PROPOSED", "STORED"} for side in choices.values())
            or len({row.case_history_id for row in pending}) != 1):
        return True
    origin = session.get(CaseHistory, pending[0].case_history_id, with_for_update=True, populate_existing=True)
    retained = trigger.retained_info_result.model_dump(mode="json") if trigger.retained_info_result else None
    if (origin is None or origin.case_id != case.id or origin.id >= history.id
            or origin.judgment_status != "CONFLICT" or trigger.conflict_snapshot.case_id != case.id
            or trigger.conflict_snapshot.snapshot_id != outcome.snapshot_id
            or origin.conflict_snapshot != trigger.conflict_snapshot.model_dump(mode="json")
            or origin.retained_info_result != retained
            or {row.conflict_ref: row.candidate_payload for row in pending}
            != {row.conflict_ref: row.model_dump(mode="json") for row in trigger.conflicts}):
        return True
    # PROPOSED 선택도 반영하지 않는다. 새 글로 다시 확인하므로 기존 값 유지로 정리한다.
    decision_record_service._resolve_conflicts(session, history, {row.id: "STORED" for row in pending})
    return True


def _restore_batch(
    session: Session, case_id: int, choices: dict[int, str]
) -> tuple[
    list[ConflictCandidate], list[ConflictSelection], CaseSnapshot, RetainedInfoResult | None
]:
    """보관해 둔 충돌 원본·그때의 Case 상태·충돌 아닌 사실을 되살리고, 고른 값을 AI 모양으로 바꾼다.

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
    # 충돌이 아니었던 사실·진행 보고는 보관해 둔 것을 그대로 쓴다. 화면이 보낸 값을 믿지
    # 않는다(승준님 #154). 이 기능 전에 난 충돌은 NULL이라 그때는 None으로 넘어간다.
    retained = (
        RetainedInfoResult.model_validate(origin.retained_info_result)
        if origin.retained_info_result is not None
        else None
    )
    return conflicts, selections, CaseSnapshot.model_validate(origin.conflict_snapshot), retained
