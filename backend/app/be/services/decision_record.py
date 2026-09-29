"""검수를 통과한 AI 판단을 DB에 저장한다.

CONFLICT와 SAFE_FAILURE는 저장하지 않는다(AI팀 스펙: "CONFLICT·SAFE_FAILURE의 정상
결과 저장 제외"). 사용자 확인 전 충돌값을 Case에 반영하면 안 되기 때문이다.
"""

from datetime import UTC

from sqlmodel import Session

from app.agent.schemas import ReviewedPlanOutcome
from app.be.crud import blocker as blocker_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import evidence as evidence_crud
from app.be.models.blocker import Blocker
from app.be.models.evidence import DecisionRecord


def save_reviewed_plan(
    session: Session, case_id: int, outcome: ReviewedPlanOutcome, *, trace_id: str | None = None
) -> DecisionRecord:
    """판단 이력·Blocker·검수 기록을 한 트랜잭션으로 저장한다."""

    # 저장 직전에 검수 증거를 다시 대조한다(AI팀 스펙의 처리 설명).
    outcome.assert_integrity()

    history = case_history_crud.get_case_created_history(session, case_id)
    if history is None:
        raise ValueError(f"case {case_id} has no CASE_CREATED history")

    decision = outcome.review_subject.supervisor_draft.decision
    proof = outcome.review_proof

    blocker = blocker_crud.create_blocker(
        session,
        Blocker(
            case_id=case_id,
            created_from_case_history_id=history.id,
            description=decision.blocker.description,
            status="ACTIVE",
        ),
    )

    # blocker와 case_history가 서로를 참조해서, blocker를 먼저 만들고 그 id를 채운다.
    # NEEDS_MORE_INFO는 다음 행동이 없어서 next_action이 NULL로 남는다.
    history.next_action = decision.next_action.title if decision.next_action else None
    history.priority_blocker_id = blocker.id

    record = evidence_crud.create_decision_record(
        session,
        DecisionRecord(
            case_id=case_id,
            run_id=str(proof.run_id),
            trace_id=trace_id,
            review_subject_id=str(proof.review_subject_id),
            review_attempt=outcome.review_subject.review_attempt,
            subject_digest=proof.reviewed_subject_digest,
            verdict=proof.verdict.value,
            decision_type=decision.decision_type.value,
            summary=decision.selection_summary,
            human_confirmation_required=decision.requires_human,
            # DB는 timezone 없는 시각을 쓰므로 UTC로 맞춘 뒤 tzinfo를 뗀다.
            reviewed_at=proof.reviewed_at.astimezone(UTC).replace(tzinfo=None),
        ),
    )

    # TODO: 아직 저장하지 못하는 것들 — AI팀 스펙의 "확인_필요"가 풀려야 한다.
    #  - questions_for_user: NEEDS_MORE_INFO에서 사용자에게 보여줄 질문인데 저장할 컬럼이 없다.
    #    (스펙의 "추가_컬럼_상태: 5개 컬럼 미구현")
    #  - mutations.fact_changes -> case / case_field_history
    #  - mutations.procedure_progress_changes -> case_procedure_step(_history)
    #  - mutations.support_match_updates -> support_match
    #  - 판단에 쓰인 evidence / evidence_lineage
    session.commit()
    session.refresh(record)
    return record
