from datetime import datetime
from uuid import uuid4

from sqlmodel import Session

from app.agent.schemas import (
    CASE_FIELD_SPECS,
    AgentGraphInput,
    CaseCreatedTrigger,
    CaseFact,
    CaseFieldKey,
    CaseSnapshot,
    CaseStatus,
    EvidenceRecord,
    EvidenceSourceType,
    FactStatus,
    FreshnessStatus,
    InputSourceType,
    ProcedureProgress,
    ProcedureProgressStatus,
    ProcedureStepRef,
    RedactedInput,
)
from app.be.crud import case as case_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import evidence as evidence_crud
from app.be.crud import procedure_step as procedure_step_crud
from app.be.models.case import Case
from app.be.models.evidence import Evidence
from app.be.models.mixins import KST
from app.be.models.procedure_step import CaseProcedureStep

# restoration_status/restoration_scope/demolition_required는 DB에서 "UNKNOWN"이라는 enum 값 자체가
# "아직 확인 안 됨"을 뜻한다(NULL이 아님). 나머지 필드는 컬럼 값이 NULL이면 미확인이다.
_UNKNOWN_SENTINEL_FIELDS = {
    CaseFieldKey.RESTORATION_STATUS,
    CaseFieldKey.RESTORATION_SCOPE,
    CaseFieldKey.DEMOLITION_REQUIRED,
}


def build_case_created_input(session: Session, case_id: int) -> AgentGraphInput:
    """case 생성 직후 첫 판단을 요청할 때 AI에 넘기는 입력 한 벌(트리거 + 스냅샷)."""

    history = case_history_crud.get_case_created_history(session, case_id)
    if history is None:
        raise ValueError(f"case {case_id} has no CASE_CREATED history")

    # DB에는 한국 시각을 저장하고(mixins.kst_now) AI 쪽은 timezone이 붙은 시각만 받으므로 tzinfo만 붙인다.
    submitted_at = history.created_at.replace(tzinfo=KST)
    input_event_id = f"case_history:{history.id}"

    return AgentGraphInput(
        trigger=CaseCreatedTrigger(
            trigger_type="CASE_CREATED",
            input_event_id=input_event_id,
            # TODO: 프론트가 자기 쪽 이벤트 식별자를 보내주기로 하면 그 값을 넣는다. 아직 미협의.
            client_event_id=None,
            input=RedactedInput(
                input_event_id=input_event_id,
                source_type=InputSourceType.USER_INPUT,
                redacted_text=history.raw_input,
                # case 생성 폼은 업종/임차형태 같은 정해진 값만 받아서 지울 개인정보가 없다.
                # 자유 입력을 받는 화면이 생기면 그때 민감정보 제거 목록을 채워야 한다.
                redactions=[],
                submitted_at=submitted_at,
            ),
            submitted_at=submitted_at,
        ),
        case_snapshot=build_case_snapshot(session, case_id),
    )


def build_case_snapshot(session: Session, case_id: int) -> CaseSnapshot:
    case = case_crud.get_case_by_id(session, case_id)
    if case is None:
        raise ValueError(f"case {case_id} not found")

    evidences = evidence_crud.get_evidence_by_case_id(session, case_id)
    case_procedure_steps = procedure_step_crud.get_case_procedure_steps_by_case_id(session, case_id)

    return CaseSnapshot(
        # TODO: snapshot_id 재사용 정책 미확정(AI팀 2026-09-29 답변 — "발급·보관·재사용 방식은
        # 구현돼 있지 않음, BE·AI가 함께 확정 필요"). 정책 정해지기 전까지는 매번 새로 발급한다.
        snapshot_id=uuid4(),
        case_id=case.id,
        case_status=CaseStatus(case.case_status),
        facts=_build_facts(case, evidences),
        procedure_progress=[_build_procedure_progress(step) for step in case_procedure_steps],
        evidence_records=[_build_evidence_record(e) for e in evidences],
        captured_at=datetime.now(KST),
    )


def _build_facts(case: Case, evidences: list[Evidence]) -> list[CaseFact]:
    # 지금은 case 생성 시 만든 근거 evidence 하나만 있다는 전제(app/be/services/case.py의
    # _create_case_creation_evidence). 나중에 다른 트리거(RESULT_SUBMITTED 등)로 evidence가 더
    # 생기면 필드별로 어떤 evidence를 참조할지 다시 설계해야 한다.
    creation_evidence_id = evidence_crud.creation_form_evidence_id(case.id)
    known_evidence_ids = {e.evidence_id for e in evidences}
    evidence_id = creation_evidence_id if creation_evidence_id in known_evidence_ids else None
    return [_build_fact(case, field_key, evidence_id) for field_key in CaseFieldKey]


def _build_fact(case: Case, field_key: CaseFieldKey, evidence_id: str | None) -> CaseFact:
    value_type, _ = CASE_FIELD_SPECS[field_key]
    raw_value = getattr(case, field_key.value)
    is_unset = raw_value is None or (field_key in _UNKNOWN_SENTINEL_FIELDS and raw_value == "UNKNOWN")
    if is_unset:
        return CaseFact(
            field_path=field_key, value_type=value_type, value=None, status=FactStatus.UNKNOWN, evidence_refs=[], updated_at=None
        )

    if evidence_id is None:
        raise ValueError(f"case {case.id} has confirmed field {field_key.value} but no creation-form evidence")

    return CaseFact(
        field_path=field_key,
        value_type=value_type,
        value=raw_value,
        status=FactStatus.CONFIRMED,
        evidence_refs=[evidence_id],
        # TODO: 개별 fact 확인 시각(updated_at)은 AI팀 확인_필요 항목("Case 행 updated_at과 구분;
        # 미확인 시각 추정 금지") — 값을 추정하지 않고 비워둔다. updated_at은 옵셔널 필드라 None 허용.
        updated_at=None,
    )


def _build_procedure_progress(step: CaseProcedureStep) -> ProcedureProgress:
    return ProcedureProgress(
        procedure_step=ProcedureStepRef(procedure_step_id=step.procedure_step_id, step_code=step.procedure_step.step_code),
        status=ProcedureProgressStatus(step.status),
        evidence_refs=[],
        updated_at=step.updated_at.replace(tzinfo=KST),
    )


def _build_evidence_record(evidence: Evidence) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence.evidence_id,
        source_type=EvidenceSourceType(evidence.source_type),
        source_ref=evidence.source_ref,
        source_version=evidence.source_version,
        locator=evidence.locator,
        excerpt=evidence.excerpt,
        parent_evidence_refs=[],
        published_at=evidence.published_at.replace(tzinfo=KST) if evidence.published_at else None,
        retrieved_at=evidence.retrieved_at.replace(tzinfo=KST),
        freshness_status=FreshnessStatus(evidence.freshness_status),
        # DB는 64자 hex만 저장하고, AI 쪽은 "sha256:" 접두사가 붙은 형식만 받는다.
        content_hash=f"sha256:{evidence.content_hash}" if evidence.content_hash else None,
    )
