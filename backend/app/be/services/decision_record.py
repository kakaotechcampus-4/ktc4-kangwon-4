"""AI 판단 결과를 DB에 저장한다.

결과는 세 가지다. 검수를 통과한 판단(REVIEWED_PLAN)만 Case 값을 바꾸고, 충돌(CONFLICT)과
실패(SAFE_FAILURE)는 화면이 다음 행동을 안내할 수 있을 만큼만 남긴다. 사용자 확인 전에
충돌값을 Case에 반영하면 안 되기 때문이다(AI팀 스펙).
"""


from sqlmodel import Session

from datetime import datetime

from app.agent.schemas import (
    ConflictOutcome,
    EvidenceRecord,
    FactChangeCandidate,
    FactOperation,
    ProcedureProgressChangeCandidate,
    ReviewedPlanOutcome,
    SafeFailureOutcome,
    SupportMatchUpdateCandidate,
)
from app.be.crud import blocker as blocker_crud
from app.be.crud import case as case_crud
from app.be.crud import case_field_history as case_field_history_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import evidence as evidence_crud
from app.be.crud import procedure_step as procedure_step_crud
from app.be.crud import support_item as support_item_crud
from app.be.models.blocker import Blocker
from app.be.models.case_field_history import CaseFieldHistory
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import ConflictReference, DecisionRecord, Evidence, EvidenceLineage
from app.be.models.mixins import KST
from app.be.models.procedure_step import CaseProcedureStepHistory
from app.be.models.support_item import SupportMatch
from app.be.services.case_snapshot import UNKNOWN_SENTINEL_FIELDS

# 충돌 확인 기한을 아직 정하지 않아, 만료로 막히지 않도록 멀리 둔다.
_NO_EXPIRY = datetime(9999, 12, 31)


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
    # 화면이 읽는 값들은 case_history 한 행에 모아둔다(GET /cases가 이 행만 조회한다).
    history.questions_for_user = list(decision.questions_for_user) or None
    history.judgment_status = (
        "NEEDS_MORE_INFO" if decision.decision_type.value == "NEEDS_MORE_INFO" else "DONE"
    )

    # 검수를 통과한 변경 제안을 실제 테이블에 반영한다. AI는 이것들을 "제안"으로만 돌려주기
    # 때문에, 저장하지 않으면 다음 판단의 스냅샷이 그대로여서 같은 판단이 반복된다.
    # 판단에 인용된 근거를 먼저 저장한다. AI가 돌려주는 evidence_refs는 번호뿐이라,
    # 본문을 남기지 않으면 나중에 그 번호로 조회해도 우리 테이블에 행이 없다.
    _save_evidence_records(session, history, outcome.review_subject.source_results)

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

    # TODO: grounded_claims(확인이 필요한 문장 표시)와 snapshot/known_procedure_steps(판단 당시
    # 입력)는 아직 담을 화면·테이블이 없어 저장하지 않는다.
    session.commit()
    session.refresh(record)
    return record


def save_conflict(session: Session, history: CaseHistory, outcome: ConflictOutcome) -> None:
    """사용자에게 되물을 충돌을 보관한다. Case 값은 건드리지 않는다.

    AI는 확인받기 전에는 아무것도 바꾸지 말라고 충돌만 돌려준다. 그래서 여기서는 어떤 필드가
    무엇에서 무엇으로 어긋났는지만 남기고, 반영은 사용자가 고른 뒤에 한다.
    """

    for conflict in outcome.conflicts:
        if evidence_crud.get_conflict_reference(session, conflict.conflict_ref) is not None:
            continue
        evidence_crud.create_conflict_reference(
            session,
            ConflictReference(
                conflict_ref=conflict.conflict_ref,
                case_id=history.case_id,
                canonical_field=conflict.field_path.value,
                committed_value=_history_value(conflict.committed_value),
                proposed_value=_history_value(conflict.proposed_value),
                conflict_digest=conflict.conflict_digest,
                # TODO: 충돌 확인에 기한을 둘지 정하지 않았다. AI가 주는 값이 아니라 BE가 정해야
                # 하는데, 기준이 없어 당장은 만료되지 않게 둔다. 충돌 확인 API를 만들 때 정한다.
                expires_at=_NO_EXPIRY,
            ),
        )
    history.judgment_status = "CONFLICT"
    session.commit()


def save_safe_failure(session: Session, history: CaseHistory, outcome: SafeFailureOutcome) -> None:
    """실패를 화면이 안내할 수 있는 만큼 남긴다.

    검수를 통과하지 않은 판단은 저장하지 않는다(AI팀 스펙). 다만 상태만 남기면 화면이 모든
    실패를 "다시 시도"로만 보여주게 되므로, 다음 행동과 멈추게 한 필드는 함께 적는다.
    """

    history.judgment_status = "FAILED"
    history.recovery_action_code = outcome.recovery_action_code
    history.retryable = outcome.retryable
    history.requested_field_paths = [field.value for field in outcome.requested_field_paths]
    session.commit()


def mark_judgment_failed(session: Session, case_id: int) -> None:
    """판단이 결과를 내놓기도 전에 끊겼을 때 상태를 남긴다.

    AI가 돌려준 실패(SAFE_FAILURE)가 아니라, 그 전에 예외로 끊긴 경우다. 상태를 PENDING으로
    두면 화면이 영영 "분석 중"에 머물게 된다. 우리 쪽 문제라 같은 입력으로 다시 해볼 만하므로
    다음 행동은 RETRY로 둔다.
    """

    history = case_history_crud.get_case_created_history(session, case_id)
    if history is None:
        return
    history.judgment_status = "FAILED"
    history.recovery_action_code = "RETRY"
    history.retryable = True
    history.requested_field_paths = []
    session.commit()


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

    for change in fact_changes:
        before = getattr(case, change.field_path.value)
        setattr(case, change.field_path.value, _column_value(change))
        case_field_history_crud.create_case_field_history(
            session,
            CaseFieldHistory(
                case_id=case.id,
                # 어느 제출에서 나온 변경인지. 이 값이 있어야 "이번 판단에서 뭐가 바뀌었나"를
                # 골라낼 수 있다(GET /cases의 changes).
                case_history_id=history.id,
                canonical_field=change.field_path.value,
                before_value=_history_value(before),
                after_value=_history_value(change.proposed_value),
                # AI가 보내는 값(INFO_ANALYSIS / CONFIRMED_CONFLICT)을 그대로 쓴다. 우리 식으로
                # 다시 이름 붙이면 AI가 값을 늘릴 때마다 변환을 따라 고쳐야 한다.
                source=change.source_type.value,
                reason=change.reason_summary,
            ),
        )


def _column_value(change: FactChangeCandidate) -> object | None:
    """Case 컬럼에 넣을 값. CLEAR(=모름으로 되돌리기)는 필드마다 표현이 다르다."""

    if change.operation != FactOperation.CLEAR:
        return change.proposed_value
    # restoration_status/restoration_scope/demolition_required는 "UNKNOWN"이라는 enum 값 자체가
    # 미확인을 뜻한다(case_snapshot.UNKNOWN_SENTINEL_FIELDS). 나머지는 컬럼을 NULL로 비운다.
    return "UNKNOWN" if change.field_path in UNKNOWN_SENTINEL_FIELDS else None


def _history_value(value: object | None) -> str:
    """변경 이력에 적을 값. after_value가 NOT NULL이라 둘 다 같은 규칙으로 적는다.

    값이 없을 때 한쪽은 NULL, 한쪽은 "UNKNOWN"으로 적으면 같은 상태가 두 모양으로 남는다.
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


def _save_evidence_records(session: Session, history: CaseHistory, source_results: list) -> None:
    """판단에 쓰인 근거 본문을 Case의 evidence로 남긴다.

    절차 문서처럼 BE가 미리 넣어둔 근거는 그대로 다시 오므로 건너뛰고, 정보분석이 사용자
    글에서 떼어내 만든 근거(input:...)처럼 새로 생긴 것만 저장한다.
    """

    records: dict[str, EvidenceRecord] = {}
    for source in source_results:
        for record in getattr(source.output, "evidence_records", []):
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
