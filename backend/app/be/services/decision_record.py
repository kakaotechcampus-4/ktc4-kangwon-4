"""AI 판단 결과를 DB에 저장한다.

결과는 세 가지다. 검수를 통과한 판단(REVIEWED_PLAN)만 Case 값을 바꾸고, 충돌(CONFLICT)과
실패(SAFE_FAILURE)는 화면이 다음 행동을 안내할 수 있을 만큼만 남긴다. 사용자 확인 전에
충돌값을 Case에 반영하면 안 되기 때문이다(AI팀 스펙).
"""


import logging
import re
from collections.abc import Mapping
from datetime import datetime

from sqlmodel import Session

from app.agent.roadmap import build_roadmap
from app.agent.schemas import (
    CaseFieldKey,
    CaseSnapshot,
    ConflictOutcome,
    EvidenceRecord,
    FactChangeCandidate,
    FactOperation,
    MutationSet,
    ProcedureProgressChangeCandidate,
    ReviewedPlanOutcome,
    SafeFailureOutcome,
    SupportMatchUpdateCandidate,
)
from app.be.crud import blocker as blocker_crud
from app.be.crud import case as case_crud
from app.be.crud import case_field_history as case_field_history_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import conflict_reference as conflict_reference_crud
from app.be.crud import evidence as evidence_crud
from app.be.crud import procedure_step as procedure_step_crud
from app.be.crud import support_item as support_item_crud
from app.be.models.blocker import Blocker
from app.be.models.case import Case
from app.be.models.case_field_history import CaseFieldHistory
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import ConflictReference, DecisionRecord, Evidence, EvidenceLineage
from app.be.models.mixins import KST, kst_now
from app.be.models.procedure_step import CaseProcedureStepHistory
from app.be.models.support_item import SupportMatch
from app.be.services import roadmap as roadmap_service
from app.be.services.case_snapshot import UNKNOWN_SENTINEL_FIELDS

logger = logging.getLogger(__name__)


def save_reviewed_plan(
    session: Session,
    history: CaseHistory,
    outcome: ReviewedPlanOutcome,
    *,
    trace_id: str | None = None,
    resolved_conflicts: Mapping[int, str] | None = None,
) -> DecisionRecord:
    """판단 이력·Blocker·검수 기록을 한 트랜잭션으로 저장한다.

    `history`는 이번 판단을 일으킨 입력 이력이다. 어느 입력에 대한 판단인지는 부르는 쪽이
    정한다 — 이 함수는 Case 생성 판단인지 결과 입력 판단인지 알 필요가 없다.
    """

    # 저장 직전에 검수 증거를 다시 대조한다(AI팀 스펙의 처리 설명).
    outcome.assert_integrity()
    if trace_id is None:
        source_trace_ids = {source.meta.trace_id for source in outcome.review_subject.source_results
                            if source.meta.trace_id is not None}
        if len(source_trace_ids) == 1:
            candidate = source_trace_ids.pop()
            if re.fullmatch(r"[0-9a-f]{32}", candidate) and candidate != "0" * 32:
                trace_id = candidate
    # 대조 전에 읽기 트랜잭션을 끊는다. 이 세션은 판단 시작 때 스냅샷을 읽고 그대로 36~120초를
    # 기다렸는데, MySQL 기본 격리 수준(REPEATABLE READ)에서는 같은 트랜잭션 안의 재조회가 처음
    # 읽은 시점을 계속 본다. SQLAlchemy도 이미 읽어둔 객체를 그대로 돌려준다. 끊지 않으면 그
    # 사이 바뀐 값을 못 보고 대조가 한 번도 걸리지 않는다.
    # 여기까지 읽기만 했으므로 되돌릴 것이 없고, 대조와 쓰기는 그다음 트랜잭션에 함께 들어간다.
    session.rollback()
    # 쓰기 전에 본다. 하나라도 어긋나면 아무것도 반영하지 않는다.
    _assert_changes_are_current(
        session, history, outcome.review_subject.supervisor_draft.mutations,
        snapshot=outcome.review_subject.snapshot,
    )

    decision = outcome.review_subject.supervisor_draft.decision
    proof = outcome.review_proof

    blocker = _save_blockers(session, history, outcome)

    # blocker와 case_history가 서로를 참조해서, blocker를 먼저 만들고 그 id를 채운다.
    # NEEDS_MORE_INFO·절차 안내 종료는 다음 행동이 없어 관련 컬럼을 전부 NULL로 둔다
    # ("다음 행동이 없음"과 "행동은 있는데 질문이 0개"를 구분하기 위해 빈 배열을 쓰지 않는다).
    next_action = decision.next_action
    history.next_action = next_action.title if next_action else None
    history.next_action_code = next_action.action_code if next_action else None
    history.next_action_reason = next_action.reason if next_action else None
    history.next_action_questions_to_ask = list(next_action.questions_to_ask) if next_action else None
    history.next_action_evidence_refs = list(next_action.evidence_refs) if next_action else None
    history.priority_blocker_id = blocker.id if blocker is not None else None
    # 화면이 읽는 값들은 case_history 한 행에 모아둔다(GET /cases가 이 행만 조회한다).
    history.questions_for_user = list(decision.questions_for_user) or None
    # 절차 안내 종료도 판단 실행은 DONE이다. 기존 DecisionRecord의 decision_type으로
    # 조회 응답을 구분하므로 DB ENUM과 Case 전체 폐업 완료 상태는 바꾸지 않는다.
    history.judgment_status = (
        "NEEDS_MORE_INFO" if decision.decision_type.value == "NEEDS_MORE_INFO" else "DONE"
    )
    history.judged_at = kst_now()

    # 검수를 통과한 변경 제안을 실제 테이블에 반영한다. AI는 이것들을 "제안"으로만 돌려주기
    # 때문에, 저장하지 않으면 다음 판단의 스냅샷이 그대로여서 같은 판단이 반복된다.
    # 판단에 인용된 근거를 먼저 저장한다. AI가 돌려주는 evidence_refs는 번호뿐이라,
    # 본문을 남기지 않으면 나중에 그 번호로 조회해도 우리 테이블에 행이 없다.
    _save_evidence_records(session, history, _evidence_records_of(outcome.review_subject.source_results))

    mutations = outcome.review_subject.supervisor_draft.mutations
    _apply_fact_changes(session, history, mutations.fact_changes)
    _apply_procedure_progress_changes(session, history, mutations.procedure_progress_changes)
    _apply_support_match_updates(session, history, mutations.support_match_updates)

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
            human_confirmation_required=decision.requires_human,
            # DB는 timezone 없는 시각을 쓰므로 한국 시각으로 맞춘 뒤 tzinfo를 뗀다.
            reviewed_at=proof.reviewed_at.astimezone(KST).replace(tzinfo=None),
        ),
    )

    # 사장님이 고른 값이 위에서 Case에 반영됐으니 그 충돌도 같이 닫는다. 한 트랜잭션이어야
    # 한다 — 값만 들어가고 충돌이 남으면 같은 것을 또 묻고, 충돌만 닫히고 값이 빠지면 고른
    # 내용이 사라진다.
    _resolve_conflicts(session, history, resolved_conflicts)
    history.roadmap_task_ids = _roadmap_task_ids(session, history.case_id)

    # TODO: grounded_claims(확인이 필요한 문장 표시)와 snapshot/known_procedure_steps(판단 당시
    # 입력)는 아직 담을 화면·테이블이 없어 저장하지 않는다.
    session.commit()
    session.refresh(record)
    return record


def _roadmap_task_ids(session: Session, case_id: int) -> list[str] | None:
    """방금 반영한 값으로 로드맵을 계산해 해야 할 일인 항목만 남긴다. 결과 화면의 "새로 생긴 할 일" 재료.

    로드맵 계산이 실패해도 판단 저장은 막지 않는다. 그때는 NULL이고 결과 화면은 그 칸을 비운다.
    """

    session.flush()
    try:
        roadmap = build_roadmap(roadmap_service.build_roadmap_input(session, case_crud.get_case_by_id(session, case_id)))
    except Exception:  # noqa: BLE001 - 화면용 부가 정보라 판단 저장을 실패시키지 않는다
        logger.exception("Case %s 로드맵 계산 실패, 새로 생긴 할 일을 비운다", case_id)
        return None
    return [
        task.task_id
        for stage in roadmap.stages
        for task in stage.tasks
        if task.status not in {"NOT_APPLICABLE", "NEEDS_CONFIRMATION"}
    ]


def _save_blockers(session: Session, history: CaseHistory, outcome: ReviewedPlanOutcome) -> Blocker | None:
    draft = outcome.review_subject.supervisor_draft
    resolved = set(draft.resolved_blocker_candidate_ids)
    if resolved:
        for row in blocker_crud.get_active_blockers_by_case_id(session, history.case_id):
            if row.candidate_id in resolved:
                row.status = "RESOLVED"
                row.resolved_from_case_history_id = history.id
                row.resolved_at = kst_now()

    # 같은 후보여도 판단별 문구·근거를 새 행에 남긴다. 기존 행을 고치면 과거 판단의
    # priority_blocker_id가 가리키는 설명까지 달라진다. 해결할 때는 해당 후보의 행을 모두 닫는다.
    priority = None
    for candidate in draft.decision.blockers:
        row = blocker_crud.create_blocker(session, Blocker(
            case_id=history.case_id, candidate_id=candidate.candidate_id,
            created_from_case_history_id=history.id, description=candidate.description,
            blocker_evidence_refs=list(candidate.evidence_refs), status="ACTIVE",
        ))
        if candidate == draft.decision.blocker:
            priority = row
    if priority is None and draft.decision.decision_type.value != "PROCEDURES_COMPLETED":
        raise ValueError("reviewed blockers must contain the priority blocker")
    return priority


def save_conflict(
    session: Session,
    history: CaseHistory,
    outcome: ConflictOutcome,
    *,
    resolved_conflicts: Mapping[int, str] | None = None,
) -> None:
    """사용자에게 되물을 충돌을 보관한다. Case 값은 건드리지 않는다.

    AI는 확인받기 전에는 아무것도 바꾸지 말라고 충돌만 돌려준다. 그래서 여기서는 어떤 필드가
    무엇에서 무엇으로 어긋났는지만 남기고, 반영은 사용자가 고른 뒤에 한다.
    """

    # 충돌에 딸려 온 근거 본문도 남긴다. 되묻는 화면과 확인 뒤 판단이 이 번호로 조회하는데,
    # 저장해 두지 않으면 우리 테이블에 행이 없다.
    _save_evidence_records(session, history, outcome.evidence_records)

    # 충돌이 난 시점의 Case 상태를 통째로 보관한다. 사용자가 고른 뒤 AI에 그대로 돌려줘야
    # 하는데(ConflictConfirmedTrigger.conflict_snapshot), 다시 만들어서 넘기면 안 된다 —
    # AI가 받은 것이 자기가 준 것과 같은지 대조하고 한 글자라도 다르면 STALE로 거절한다.
    #
    # 충돌 묶음 하나당 한 벌이라 이 이력 행에 둔다. 충돌마다 한 줄인 conflict_reference에
    # 두면 충돌이 셋이면 같은 상태가 세 벌 쌓인다.
    #
    # TODO: 판단 당시 입력(snapshot·known_procedure_steps)을 담을 자리가 아직 없다
    # (save_reviewed_plan의 TODO). 그 자리가 생기면 이 칸도 거기로 옮기는 것이 맞다.
    history.conflict_snapshot = outcome.conflict_snapshot.model_dump(mode="json")

    # 같은 글에서 충돌이 아니었던 사실·진행 보고도 함께 보관한다. 사장님이 셋을 말했는데
    # 하나만 충돌이면, 이것을 안 들고 있다가 확인 뒤 재판단에 못 돌려줘서 나머지 둘이
    # 사라졌다. AI는 확인 뒤에 원문을 다시 읽지 않으므로(ConflictConfirmedTrigger에 입력 글이
    # 없다) 여기서 통째로 들고 있다가 그대로 돌려주는 것 말고는 되살릴 길이 없다.
    #
    # 한 글자도 바꾸지 않는다. 비식별 입력·Info 결과·meta·다이제스트를 AI가 다시 대조한다.
    # 화면이 보낸 값이 아니라 이 보관값을 쓴다(승준님 #154).
    if outcome.retained_info_result is not None:
        history.retained_info_result = outcome.retained_info_result.model_dump(mode="json")

    # 같은 충돌이 두 번 저장되는 것을 따로 막지 않는다. 전에 두었던 "이미 있으면 건너뛰기"는
    # conflict_ref로 비교했는데, AI가 판단할 때마다 새 UUID로 만들어서(info_agent/agent.py의
    # _conflict) 내용이 같아도 값이 달라 한 번도 걸리지 않았다.
    # 막을 상황도 없다. 아직 안 고른 충돌이 있는 동안은 새 제출이 거부돼 두 번째 판단이 돌지
    # 않고, 이미 고른 충돌은 그 사이 사정이 달라졌을 수 있어 다시 물어보는 쪽이 맞다.
    for conflict in outcome.conflicts:
        evidence_crud.create_conflict_reference(
            session,
            ConflictReference(
                conflict_ref=conflict.conflict_ref,
                case_id=history.case_id,
                case_history_id=history.id,
                canonical_field=conflict.field_path.value,
                committed_value=_history_value(conflict.committed_value),
                proposed_value=_history_value(conflict.proposed_value),
                conflict_digest=conflict.conflict_digest,
                # 위 두 값은 화면에 보여주려고 글자로 바꾼 것이라 숫자·참거짓·빈 값을
                # 되돌릴 수 없다. 사용자가 고른 뒤 AI에 그대로 돌려주려면 원본이 따로
                # 있어야 하고, AI는 받은 내용의 다이제스트를 대조해 다르면 거절한다.
                candidate_payload=conflict.model_dump(mode="json"),
            ),
        )
    # 결정 뒤 재판단에서 또 다른 충돌이 나올 수 있다. 그때도 방금 고른 것은 닫아야 한다 —
    # 안 닫으면 다음 확인 화면이 이미 답한 충돌을 다시 묻고, 그 Case는 영영 안 풀린다.
    _resolve_conflicts(session, history, resolved_conflicts)

    history.judgment_status = "CONFLICT"
    history.judged_at = kst_now()
    session.commit()


def _resolve_conflicts(
    session: Session, history: CaseHistory, choices: Mapping[int, str] | None
) -> None:
    """사장님이 결정한 충돌을 닫는다. 고른 쪽과 닫은 이력을 함께 남긴다.

    "새 값"은 채택(CONFIRMED), "기존 값 유지"는 거절(REJECTED)이다. 둘 다 결정이므로 어느
    쪽이든 더는 되묻지 않는다. 결정 접수 시점이 아니라 판단이 성공해서 값을 저장할 때
    닫는다 — 접수 때 닫으면 판단이 실패했을 때 값은 그대로인데 충돌만 사라져서, 사장님이
    다시 결정할 길이 없어진다(현석님 #108).

    닫은 이력(`history`)에는 글이 없어서 이 관계로 충돌을 일으킨 제출의 출처를 추적한다.
    과거 고정 표식을 번호와 호환할 때 사용하며 화면을 원문으로 복원하지 않는다.
    """

    for conflict_reference_id, side in (choices or {}).items():
        reference = conflict_reference_crud.get_conflict_reference_by_id(
            session, conflict_reference_id
        )
        if reference is None:
            raise ValueError(f"conflict_reference {conflict_reference_id} not found")
        reference.status = "CONFIRMED" if side == "PROPOSED" else "REJECTED"
        reference.decided_at = kst_now()
        reference.resolved_by_case_history_id = history.id
        session.add(reference)


def save_safe_failure(session: Session, history: CaseHistory, outcome: SafeFailureOutcome) -> None:
    """실패를 화면이 안내할 수 있는 만큼 남긴다.

    검수를 통과하지 않은 판단은 저장하지 않는다(AI팀 스펙). 다만 상태만 남기면 화면이 모든
    실패를 "다시 시도"로만 보여주게 되므로, 다음 행동과 멈추게 한 필드는 함께 적는다.
    """

    history.judgment_status = "FAILED"
    history.judged_at = kst_now()
    # 왜 실패했는지. 이게 없으면 쌓인 실패가 전부 "다시 시도해보세요"로만 남아서,
    # 형식이 틀린 건지 호출 예산을 다 쓴 건지 구분할 수 없다.
    history.failure_code = outcome.failure_code
    history.recovery_action_code = outcome.recovery_action_code
    history.retryable = outcome.retryable
    history.requested_field_paths = [field.value for field in outcome.requested_field_paths]
    session.commit()


def mark_judgment_failed(session: Session, case_history_id: int, error: Exception | None = None) -> None:
    """판단이 결과를 내놓기도 전에 끊겼을 때 상태를 남긴다.

    AI가 돌려준 실패(SAFE_FAILURE)가 아니라, 그 전에 예외로 끊긴 경우다. 상태를 PENDING으로
    두면 화면이 영영 "분석 중"에 머물게 된다. 대개 우리 쪽 일시적인 문제라 같은 입력으로
    다시 해볼 만하므로 다음 행동은 RETRY로 둔다.

    끊긴 그 판단의 이력을 받는다. 여기서 CASE_CREATED 이력을 직접 찾으면, 결과 제출 판단이
    터졌을 때 멀쩡한 가입 판단 결과를 FAILED로 덮고 정작 방금 들어온 입력은 PENDING에 남는다.

    `error`는 무엇 때문에 끊겼는지다. 다시 해도 안 풀리는 종류면 RETRY로 안내하지 않는다.
    """

    history = case_history_crud.get_case_history_by_id(session, case_history_id)
    if history is None:
        return
    history.judgment_status = "FAILED"
    history.judged_at = kst_now()
    # AI가 결과를 내기 전에 끊겨서 실패 종류를 받지 못했다. 없는 값을 지어내지 않는다.
    history.failure_code = None
    # 저장된 데이터나 설정이 원인이면 다시 판단해도 같은 자리에서 또 터진다. 그 Case는
    # 사람이 고치기 전까지 못 빠져나오므로, 눌러도 안 되는 "다시 시도" 대신 문의로 보낸다.
    # 어떤 실패가 그런지는 예외 자신이 들고 온다. 모르면 일시적인 문제로 본다.
    retryable = bool(getattr(error, "retryable", True))
    history.recovery_action_code = "RETRY" if retryable else "CONTACT_SUPPORT"
    history.retryable = retryable
    history.requested_field_paths = []
    session.commit()


class StaleJudgmentError(RuntimeError):
    """판단이 도는 사이 Case가 바뀌어, 그 판단을 반영하면 최신 값을 덮어쓰게 되는 상태."""


def _assert_changes_are_current(
    session: Session, history: CaseHistory, mutations: MutationSet, *, snapshot: CaseSnapshot,
) -> None:
    """AI가 보고 판단한 "바뀌기 전 값"이 지금도 그대로인지 확인한다.

    판단은 실측 36~120초 걸린다. 그 사이 다른 입력이 반영되면 AI가 들고 있는 값은 이미
    옛날 것이다. 그대로 덮어쓰면 최신 값이 사라지고, 완료된 절차가 진행 중으로 되돌아간다.

    한 건이라도 어긋나면 나머지 판단도 같은 옛 스냅샷에서 나온 것이라 믿을 수 없다. 그래서
    일부만 거르지 않고 판단 전체를 버린다. 쓰기 전에 검사해서 일부만 반영된 상태를 남기지
    않는다. 여기서 던진 예외는 판단을 부른 쪽에서 FAILED(RETRY)로 남고, 다시 돌리면 그때는
    최신 값으로 스냅샷을 만든다.
    """

    case = case_crud.get_case_by_id(session, history.case_id)
    if case is None:
        raise ValueError(f"case {history.case_id} not found")

    if _full_restoration_change(case, mutations.fact_changes) is not None:
        # 범위 확정에 따라 함께 비울 세부값도 잠근 최신 행과 판단 당시 값이 같아야 한다.
        session.refresh(case, with_for_update=True)
        detail = next((fact for fact in snapshot.facts
                       if fact.field_path == CaseFieldKey.RESTORATION_SCOPE_DETAIL), None)
        if detail is None or case.restoration_scope_detail != detail.value:
            raise StaleJudgmentError("전체 범위 확정 전 세부 설명이 판단 당시와 다릅니다")

    for change in mutations.fact_changes:
        stored = _comparable_case_value(case, change.field_path)
        if stored != change.before_value:
            raise StaleJudgmentError(
                f"case {case.id}의 {change.field_path.value}: 판단이 본 값은 "
                f"{change.before_value!r}인데 지금은 {stored!r}"
            )

    for change in mutations.procedure_progress_changes:
        step = procedure_step_crud.get_case_procedure_step(
            session, history.case_id, change.procedure_step.procedure_step_id
        )
        if step is None:
            raise ValueError(
                f"case {history.case_id} has no procedure step {change.procedure_step.step_code}"
            )
        before = (change.before_status.value, change.before_requirements_confirmed, change.before_submitted)
        current = (step.status, step.requirements_confirmed, step.submitted)
        if current != before:
            raise StaleJudgmentError(
                f"case {case.id}의 절차 {change.procedure_step.step_code}: 판단이 본 상태는 "
                f"{before}인데 지금은 {current} (진행 상태, 준비사항 확인, 신고 제출)"
            )


def _comparable_case_value(case: object, field_key: CaseFieldKey) -> object | None:
    """Case 컬럼 값을 AI가 쓰는 표현으로 맞춘다.

    DB는 "모름"을 필드마다 다르게 적는다 — 어떤 칸은 NULL이고, 어떤 칸은 "UNKNOWN"이라는
    enum 값 자체가 미확인을 뜻한다(case_snapshot.UNKNOWN_SENTINEL_FIELDS). AI는 둘 다
    값이 없는 것으로 본다. 맞춰 두지 않으면 안 바뀐 값도 어긋난 것으로 읽힌다.
    """

    value = getattr(case, field_key.value)
    if value is None or (field_key in UNKNOWN_SENTINEL_FIELDS and value == "UNKNOWN"):
        return None
    return value


def _apply_fact_changes(
    session: Session, history: CaseHistory, fact_changes: list[FactChangeCandidate]
) -> None:
    """검수를 통과한 Case 값 변경을 실제로 반영하고, 바뀐 내역을 한 줄씩 남긴다.

    AI는 변경을 "제안"으로만 돌려준다(MutationSet). 저장하지 않으면 사용자가 답을 해도
    Case 값이 그대로여서, 다음 판단의 스냅샷에도 같은 값이 들어가 AI가 같은 질문을 반복한다.
    """

    if not fact_changes:
        return

    case = case_crud.get_case_by_id(session, history.case_id)
    if case is None:
        raise ValueError(f"case {history.case_id} not found")

    full_change = _full_restoration_change(case, fact_changes)
    old_detail = case.restoration_scope_detail if full_change is not None else None
    for change in fact_changes:
        if full_change is not None and change.field_path == CaseFieldKey.RESTORATION_SCOPE_DETAIL:
            continue  # 같은 묶음의 SET/CLEAR 순서와 관계없이 전체 전환의 정리를 한 번만 남긴다.
        # AI가 대화 중에 바꾸겠다고 보낼 수 있는 필드는 14개(AgentFieldKey)지만, 저장하는
        # 것은 9개(CaseFieldKey)뿐이다. 나머지 5개(직원 고용 이력·4대보험 가입 이력)는
        # 가입 폼으로만 채우기로 했다 — 사장님이 직접 답한 값을 AI가 대화 중에 추정한
        # 값으로 덮으면 안 되기 때문이다(승준님 #132 연동 요청).
        #
        # 컬럼이 있느냐로 가르면 안 된다. 그 5개도 컬럼은 있어서 전부 통과해 버린다.
        # 한 필드 때문에 나머지 변경까지 버리지 않도록 건너뛰되, 반드시 흔적을 남긴다 —
        # 검수를 통과한 변경을 말없이 버리는 것이기 때문이다.
        if change.field_path not in CaseFieldKey:
            logger.warning(
                "case %s의 %s는 AI 대화로 저장하는 값이 아니라 건너뛴다", case.id, change.field_path.value
            )
            continue
        # 컬럼에 글자 "UNKNOWN"이 들어 있는 필드가 있다. 그대로 적으면 "모름"이 이력에
        # 두 모양(NULL과 "UNKNOWN")으로 남는다. AI가 보는 표현으로 맞춰서 적는다.
        before = _comparable_case_value(case, change.field_path)
        setattr(case, change.field_path.value, _column_value(change))
        case_field_history_crud.create_case_field_history(
            session,
            CaseFieldHistory(
                case_id=case.id,
                # 어느 제출에서 나온 변경인지. 이 값이 있어야 "이번 판단에서 뭐가 바뀌었나"를
                # 골라낼 수 있다(GET /cases의 changes).
                case_history_id=history.id,
                # 이 변경을 무엇을 보고 했는지. 다음 판단 스냅샷이 이 필드의 근거로 되돌려
                # 준다(case_snapshot._build_facts). 안 남기면 바뀐 값에도 최초 폼 입력이
                # 근거로 붙어 AI가 출처를 잘못 알게 된다.
                source_evidence_refs=list(change.source_evidence_refs),
                canonical_field=change.field_path.value,
                # 값이 없으면 글자 "UNKNOWN"이 아니라 NULL로 둔다. Case 컬럼의 미확인
                # enum과 이력의 "값이 없음"은 다른 뜻이다.
                before_value=_nullable_value(before),
                after_value=_nullable_value(change.proposed_value),
                # AI가 보내는 값(INFO_ANALYSIS / CONFIRMED_CONFLICT)을 그대로 쓴다. 우리 식으로
                # 다시 이름 붙이면 AI가 값을 늘릴 때마다 변환을 따라 고쳐야 한다.
                source=change.source_type.value,
                reason=change.reason_summary,
            ),
        )

    if full_change is not None and old_detail is not None:
        case.restoration_scope_detail = None
        case_field_history_crud.create_case_field_history(session, CaseFieldHistory(
            case_id=case.id, case_history_id=history.id,
            canonical_field=CaseFieldKey.RESTORATION_SCOPE_DETAIL.value,
            before_value=old_detail, after_value=None,
            source=full_change.source_type.value, source_evidence_refs=list(full_change.source_evidence_refs),
            reason="전체 범위 확정 시 세부 설명을 비우기로 한 사용자 정책을 적용했습니다.",
        ))


def _full_restoration_change(case: Case, changes: list[FactChangeCandidate]) -> FactChangeCandidate | None:
    return next((change for change in changes
                 if change.field_path == CaseFieldKey.RESTORATION_SCOPE
                 and change.operation == FactOperation.SET and change.proposed_value == "FULL"
                 and case.restoration_scope != "FULL"), None)


def _column_value(change: FactChangeCandidate) -> object | None:
    """Case 컬럼에 넣을 값. CLEAR(=모름으로 되돌리기)는 필드마다 표현이 다르다."""

    if change.operation != FactOperation.CLEAR:
        return change.proposed_value
    # restoration_status/restoration_scope/demolition_required는 "UNKNOWN"이라는 enum 값 자체가
    # 미확인을 뜻한다(case_snapshot.UNKNOWN_SENTINEL_FIELDS). 나머지는 컬럼을 NULL로 비운다.
    return "UNKNOWN" if change.field_path in UNKNOWN_SENTINEL_FIELDS else None


def _nullable_value(value: object | None) -> str | None:
    """값이 없으면 NULL로 둘 수 있는 칸에 적을 값(case_field_history)."""

    return None if value is None else str(value)


def _history_value(value: object | None) -> str:
    """NULL을 못 받는 칸에 적을 값(conflict_reference.proposed_value 등).

    원래 값이 무엇이었는지는 candidate_payload에 원본 그대로 남는다. 여기는 화면이 읽는
    자리라 사람이 볼 수 있는 글자로 적는다.
    """

    return "UNKNOWN" if value is None else str(value)


def _apply_procedure_progress_changes(
    session: Session, history: CaseHistory, changes: list[ProcedureProgressChangeCandidate]
) -> None:
    """절차 진행 상태를 옮기고, 어느 입력 때문에 옮겼는지 함께 남긴다.

    AI는 앞으로 가는 변경만 보낸다(ProcedureProgressChangeCandidate.validate_forward_transition).
    되돌리는 경로는 여기 없고, 필요해지면 따로 만들어야 한다.
    """

    for change in changes:
        step = procedure_step_crud.get_case_procedure_step(
            session, history.case_id, change.procedure_step.procedure_step_id
        )
        if step is None:
            raise ValueError(
                f"case {history.case_id} has no procedure step {change.procedure_step.step_code}"
            )
        previous = step.status
        step.status = change.proposed_status.value
        step.requirements_confirmed = change.proposed_requirements_confirmed
        step.submitted = change.proposed_submitted
        # 완료된 절차는 근거 없이 스냅샷에 담을 수 없다(ProcedureProgress.completed_requires_evidence).
        # 다음 판단에 그대로 넘겨야 해서 어느 근거로 옮겼는지 함께 남긴다.
        step.evidence_refs = list(change.execution_evidence_refs)
        procedure_step_crud.create_case_procedure_step_history(
            session,
            CaseProcedureStepHistory(
                case_procedure_step_id=step.id,
                case_history_id=history.id,
                previous_status=previous,
                new_status=step.status,
            ),
        )


def _apply_support_match_updates(
    session: Session, history: CaseHistory, updates: list[SupportMatchUpdateCandidate]
) -> None:
    """지원사업별 자격 판정 결과를 한 줄씩 남긴다.

    같은 Case·지원사업 조합은 한 줄만 두고 판정만 갱신한다. 자격조건·필요서류 같은 서술형
    정보는 검수 Wiki가 갖는다는 설계라(schema_table.md) 여기 저장하지 않는다.
    """

    for update in updates:
        check = update.support_check
        match = support_item_crud.get_support_match(
            session, history.case_id, check.support_program.support_program_id
        )
        if match is None:
            match = support_item_crud.create_support_match(
                session,
                SupportMatch(
                    case_id=history.case_id,
                    support_item_id=check.support_program.support_program_id,
                    match_status=check.match_status.value,
                    # TODO: 매칭 시점의 카탈로그 버전. 판단 결과에는 안 실려 와서 비워 둔다
                    # — 검수된 지원사업 자료가 생기면 그 버전을 넣을 경로를 정해야 한다.
                    catalog_version=None,
                ),
            )
            continue
        match.match_status = check.match_status.value


def _evidence_records_of(source_results: list) -> list[EvidenceRecord]:
    """검수 대상에 붙어 온 Tool 결과들에서 근거 본문만 모은다."""

    return [
        record
        for source in source_results
        for record in getattr(source.output, "evidence_records", [])
    ]


def _save_evidence_records(
    session: Session, history: CaseHistory, evidence_records: list[EvidenceRecord]
) -> None:
    """판단에 쓰인 근거 본문을 Case의 evidence로 남긴다.

    절차 문서처럼 BE가 미리 넣어둔 근거는 그대로 다시 오므로 건너뛰고, 정보분석이 사용자
    글에서 떼어내 만든 근거(input:...)처럼 새로 생긴 것만 저장한다.

    정상 판단과 충돌이 같이 쓴다. 충돌 쪽은 Tool 결과가 아니라 납작한 목록으로 와서,
    모으는 일은 호출부에 두고 여기는 목록만 받는다.
    """

    records: dict[str, EvidenceRecord] = {}
    for record in evidence_records:
        records.setdefault(record.evidence_id, record)
    if not records:
        return

    rows_by_evidence_id = {
        row.evidence_id: row for row in evidence_crud.get_evidence_by_case_id(session, history.case_id)
    }
    for evidence_id, record in records.items():
        if evidence_id in rows_by_evidence_id:
            continue
        rows_by_evidence_id[evidence_id] = evidence_crud.create_evidence(
            session,
            Evidence(
                evidence_id=record.evidence_id,
                case_id=history.case_id,
                source_type=record.source_type.value,
                source_ref=record.source_ref,
                source_version=record.source_version,
                locator=record.locator,
                excerpt=record.excerpt,
                published_at=_db_time(record.published_at),
                retrieved_at=_db_time(record.retrieved_at),
                freshness_status=record.freshness_status.value,
                content_hash=record.content_hash,
            ),
        )

    # 어느 근거에서 파생됐는지는 별도 접합 테이블에 남긴다. 같은 짝이 두 번 들어가면 UNIQUE에
    # 걸리므로, 이미 저장된 관계를 먼저 읽어 두고 없는 것만 만든다(재판단 때 같은 근거가 다시 온다).
    linked = {
        (row.evidence_id, row.parent_evidence_id)
        for row in evidence_crud.get_evidence_lineages_by_evidence_ids(
            session, [row.id for row in rows_by_evidence_id.values()]
        )
    }
    for evidence_id, record in records.items():
        child = rows_by_evidence_id[evidence_id]
        for parent_ref in record.parent_evidence_refs:
            parent = rows_by_evidence_id.get(parent_ref)
            if parent is None or (child.id, parent.id) in linked:
                continue
            linked.add((child.id, parent.id))
            evidence_crud.create_evidence_lineage(
                session, EvidenceLineage(evidence_id=child.id, parent_evidence_id=parent.id)
            )


def _db_time(value: datetime | None) -> datetime | None:
    """DB는 timezone 없는 한국 시각을 쓰고, MySQL DATETIME은 초까지만 담는다."""

    return None if value is None else value.astimezone(KST).replace(tzinfo=None, microsecond=0)
