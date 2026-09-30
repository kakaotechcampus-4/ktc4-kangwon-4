"""검수를 통과한 AI 판단을 DB에 저장한다.

CONFLICT와 SAFE_FAILURE는 저장하지 않는다(AI팀 스펙: "CONFLICT·SAFE_FAILURE의 정상
결과 저장 제외"). 사용자 확인 전 충돌값을 Case에 반영하면 안 되기 때문이다.
"""


from sqlmodel import Session

from app.agent.schemas import ReviewedPlanOutcome
from app.be.crud import blocker as blocker_crud
from app.be.crud import evidence as evidence_crud
from app.be.models.blocker import Blocker
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import DecisionRecord
from app.be.models.mixins import KST


def save_reviewed_plan(
    session: Session, history: CaseHistory, outcome: ReviewedPlanOutcome, *, trace_id: str | None = None
) -> DecisionRecord:
    """판단 이력·Blocker·검수 기록을 한 트랜잭션으로 저장한다.

    `history`는 이번 판단을 일으킨 입력 이력이다. 어느 입력에 대한 판단인지는 부르는 쪽이
    정한다 — 이 함수는 Case 생성 판단인지 결과 입력 판단인지 알 필요가 없다.
    """

    # 저장 직전에 검수 증거를 다시 대조한다(AI팀 스펙의 처리 설명).
    outcome.assert_integrity()

    decision = outcome.review_subject.supervisor_draft.decision
    proof = outcome.review_proof

    blocker = blocker_crud.create_blocker(
        session,
        Blocker(
            case_id=history.case_id,
            created_from_case_history_id=history.id,
            description=decision.blocker.description,
            blocker_evidence_refs=list(decision.blocker.evidence_refs),
            status="ACTIVE",
        ),
    )

    # blocker와 case_history가 서로를 참조해서, blocker를 먼저 만들고 그 id를 채운다.
    # NEEDS_MORE_INFO는 다음 행동 자체가 없어서 next_action 관련 컬럼을 전부 NULL로 둔다
    # ("다음 행동이 없음"과 "행동은 있는데 질문이 0개"를 구분하기 위해 빈 배열을 쓰지 않는다).
    next_action = decision.next_action
    history.next_action = next_action.title if next_action else None
    history.next_action_reason = next_action.reason if next_action else None
    history.next_action_questions_to_ask = list(next_action.questions_to_ask) if next_action else None
    history.next_action_evidence_refs = list(next_action.evidence_refs) if next_action else None
    history.priority_blocker_id = blocker.id

    record = evidence_crud.create_decision_record(
        session,
        DecisionRecord(
            case_id=history.case_id,
            case_history_id=history.id,
            run_id=str(proof.run_id),
            snapshot_id=str(proof.snapshot_id),
            trace_id=trace_id,
            review_subject_id=str(proof.review_subject_id),
            review_attempt=outcome.review_subject.review_attempt,
            subject_digest=proof.reviewed_subject_digest,
            verdict=proof.verdict.value,
            decision_type=decision.decision_type.value,
            summary=decision.selection_summary,
            questions_for_user=list(decision.questions_for_user) or None,
            human_confirmation_required=decision.requires_human,
            # DB는 timezone 없는 시각을 쓰므로 한국 시각으로 맞춘 뒤 tzinfo를 뗀다.
            reviewed_at=proof.reviewed_at.astimezone(KST).replace(tzinfo=None),
        ),
    )

    # TODO: 아직 저장하지 못하는 것들 — AI팀 스펙의 "확인_필요"가 풀려야 한다.
    #  - evidence_refs가 가리키는 evidence 본문. AI가 실행 중 만든 근거(procedure:reviewed:...)는
    #    메모리에만 있어서, 지금 저장한 refs로 조회하면 evidence 테이블에 행이 없다.
    #  - mutations.fact_changes -> case / case_field_history
    #  - mutations.procedure_progress_changes -> case_procedure_step(_history)
    #  - mutations.support_match_updates -> support_match
    #  - 판단에 쓰인 evidence / evidence_lineage
    session.commit()
    session.refresh(record)
    return record
