from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Session

from app.agent.roadmap import CompletedRoadmapSnapshot
from app.agent.schemas import (
    CASE_FIELD_SPECS,
    AgentFieldKey,
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
from app.be.crud import blocker as blocker_crud
from app.be.crud import case as case_crud
from app.be.crud import case_field_history as case_field_history_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import evidence as evidence_crud
from app.be.crud import procedure_step as procedure_step_crud
from app.be.models.case import Case
from app.be.models.evidence import Evidence
from app.be.models.mixins import KST
from app.be.models.procedure_step import CaseProcedureStep
from app.be.services.redaction import redact

# restoration_status/restoration_scope/demolition_required는 DB에서 "UNKNOWN"이라는 enum 값 자체가
# "아직 확인 안 됨"을 뜻한다(NULL이 아님). 나머지 필드는 컬럼 값이 NULL이면 미확인이다.
UNKNOWN_SENTINEL_FIELDS = {
    CaseFieldKey.RESTORATION_STATUS,
    CaseFieldKey.RESTORATION_SCOPE,
    CaseFieldKey.DEMOLITION_REQUIRED,
}


class StoredEvidenceMissingError(ValueError):
    """저장된 Case 값에 달 근거가 DB에 없어, 스냅샷을 만들 수 없는 상태.

    방금 들어온 입력이 아니라 전에 저장된 행이 원인이라, 같은 입력으로 다시 판단해도
    같은 자리에서 또 터진다. 그래서 "다시 시도"가 아니라 "문의"로 안내해야 한다
    (decision_record.mark_judgment_failed).
    """

    # 예외에 직접 붙여 둔다. 실패 상태를 적는 쪽이 예외 종류를 하나씩 알아야 하면,
    # 새 실패를 만들 때마다 그쪽을 같이 고쳐야 하고 빠뜨리면 조용히 RETRY가 된다.
    # AI 쪽도 같은 방식으로 읽는다(graph.py).
    retryable = False


def build_user_input(
    case_history_id: int, raw_input: str, submitted_at: datetime,
    *, placeholders: dict[tuple[str, str], str] | None = None,
) -> RedactedInput:
    """사용자가 넣은 입력 한 건을 AI가 받는 모양으로 바꾼다.

    CaseHistory 행 전체가 아니라 실제로 쓰는 값 세 개만 받는다. 모델을 통째로 받으면 이
    함수가 어느 칼럼까지 보는지 호출부에서 알 수 없고, 입력이 꼭 CaseHistory에서만 와야
    하는 것처럼 묶인다.

    트리거(= 왜 판단을 부르는가)로 감싸는 일은 AI팀 입구(app/common/agent_service.py)가 한다.
    """

    redacted_text, redactions = redact(raw_input, placeholders=placeholders)
    return RedactedInput(
        input_event_id=f"case_history:{case_history_id}",
        source_type=InputSourceType.USER_INPUT,
        # DB에는 사장님이 쓴 글이 그대로 남고, AI에게 넘기는 쪽만 가린다. 화면이 "내가
        # 이렇게 썼지"를 그대로 보여줘야 하고, 가린 글을 저장하면 그걸 되돌릴 수 없다.
        redacted_text=redacted_text,
        redactions=redactions,
        # DB에는 timezone 없는 한국 시각을 저장하고(mixins.kst_now) AI 쪽은 timezone이 붙은
        # 시각만 받으므로, 저장된 값을 그대로 받아 여기서 tzinfo만 붙인다.
        submitted_at=submitted_at.replace(tzinfo=KST),
    )


def build_case_snapshot(
    session: Session, case_id: int, *, snapshot_id: UUID | None = None,
    placeholders: dict[tuple[str, str], str] | None = None,
) -> CaseSnapshot:
    """Case의 지금 상태를 AI가 받는 모양으로 만든다.

    snapshot_id는 보통 새로 발급한다. 딱 하나 예외가 충돌 확인이다 — 그때는 충돌을 보관할 때
    받은 번호를 그대로 써야 한다. 새 번호를 찍으면 AI가 "내가 준 충돌이 아니다"로 보고
    STALE_CONFLICT_CONFIRMATION으로 거절해서, 값이 하나도 안 바뀌었어도 모든 결정이 실패한다
    (schemas.CaseSnapshot.snapshot_id 설명, #114에서 확정).
    """

    return CaseSnapshot.model_validate(_snapshot_fields(session, case_id, snapshot_id, placeholders))


def build_roadmap_snapshot(session: Session, case_id: int) -> CaseSnapshot | CompletedRoadmapSnapshot:
    """로드맵에 넘길 Case 상태. 폐업 정리를 마친 Case도 만든다.

    위 build_case_snapshot은 진행 중인 Case만 만든다 — CaseSnapshot.case_status가
    IN_PROGRESS만 받고, 그게 "AI는 진행 중인 Case만 판단한다"를 지키는 자리다. 로드맵은
    모델을 부르지 않고 계산만 하는 읽기라 그 제한을 받을 이유가 없어서, 완료된 Case는
    AI가 그 용도로 만들어 둔 모양으로 넘긴다(현석님 #167).
    """

    fields = _snapshot_fields(session, case_id, None)
    model = (
        CompletedRoadmapSnapshot
        if fields["case_status"] == CaseStatus.COMPLETED
        else CaseSnapshot
    )
    return model.model_validate(fields)


def _snapshot_fields(
    session: Session, case_id: int, snapshot_id: UUID | None,
    placeholders: dict[tuple[str, str], str] | None = None,
) -> dict:
    """두 모양이 같은 값을 쓰도록, 읽어 오는 일만 한곳에 둔다."""

    case = case_crud.get_case_by_id(session, case_id)
    if case is None:
        raise ValueError(f"case {case_id} not found")

    evidences = evidence_crud.get_evidence_by_case_id(session, case_id)
    case_procedure_steps = procedure_step_crud.get_case_procedure_steps_by_case_id(session, case_id)

    return dict(
        snapshot_id=snapshot_id or uuid4(),
        case_id=case.id,
        case_status=CaseStatus(case.case_status),
        facts=_build_facts(session, case, evidences),
        procedure_progress=[_build_procedure_progress(step) for step in case_procedure_steps],
        evidence_records=_build_evidence_records(session, case.id, evidences, placeholders=placeholders),
        active_blocker_candidate_ids=sorted({
            row.candidate_id for row in blocker_crud.get_active_blockers_by_case_id(session, case.id)
            if row.candidate_id is not None
        }),
        captured_at=datetime.now(KST),
    )


def _build_facts(session: Session, case: Case, evidences: list[Evidence]) -> list[CaseFact]:
    # 지금은 case 생성 시 만든 근거 evidence 하나만 있다는 전제(app/be/services/case.py의
    # _create_case_creation_evidence). 나중에 다른 트리거(RESULT_SUBMITTED 등)로 evidence가 더
    # 생기면 필드별로 어떤 evidence를 참조할지 다시 설계해야 한다.
    creation_history = case_history_crud.get_case_created_history(session, case.id)
    creation_evidence_id = (
        evidence_crud.case_history_evidence_id(case.id, creation_history.id) if creation_history else None
    )
    known_evidence_ids = {e.evidence_id for e in evidences}
    creation_refs = [creation_evidence_id] if creation_evidence_id in known_evidence_ids else []
    # 필드가 마지막으로 바뀐 판단이 무엇을 근거로 댔는지. 오래된 것부터 읽어 덮어쓰므로
    # 마지막에 남는 것이 최신이다. 이 Case에 없는 근거(지난 버전 등)는 빼고 넘긴다 —
    # AI는 스냅샷에 담기지 않은 근거 번호를 받으면 입력 검증에서 거부한다.
    last_change: dict[str, tuple[list[str], datetime]] = {}
    for row in case_field_history_crud.get_case_field_histories_by_case_id(session, case.id):
        refs = [ref for ref in (row.source_evidence_refs or []) if ref in known_evidence_ids]
        last_change[row.canonical_field] = (refs, row.created_at.replace(tzinfo=KST))
    # 폼으로 들어온 뒤 한 번도 안 바뀐 값은 이력이 없다. 그때는 폼을 낸 시각이 곧 확인 시각이다
    # — 추정이 아니라 실제 입력 시각이고, 같은 시각을 그 근거의 retrieved_at에도 적어뒀다.
    submitted_at = creation_history.created_at.replace(tzinfo=KST) if creation_history else None
    facts = []
    # AgentFieldKey를 돈다. CaseFieldKey(9개)만 돌면 직원 고용 이력·4대보험 가입 이력 5개가
    # 스냅샷에 아예 안 실려서, AI가 저장된 답을 못 보고 같은 것을 다시 묻는다.
    for field_key in AgentFieldKey:
        change = last_change.get(field_key.value)
        # 폼 근거는 "한 번도 안 바뀐 값"에만 쓴다. 바뀐 적이 있는데 그 판단의 근거가 비었다고
        # 폼 근거로 되돌리면, 판단이 바꿔 넣은 값을 "가입할 때 받은 값"이라고 AI에게 틀리게
        # 알려주게 된다. 근거가 빈 것은 적재 쪽 결함이므로 덮지 않고 드러낸다.
        if change is None:
            facts.append(_build_fact(case, field_key, creation_refs, submitted_at, source="가입 폼"))
            continue
        refs, changed_at = change
        facts.append(_build_fact(case, field_key, refs, changed_at, source="변경 이력"))
    return facts


def _build_fact(
    case: Case,
    field_key: AgentFieldKey,
    evidence_refs: list[str],
    confirmed_at: datetime | None,
    *,
    source: str,
) -> CaseFact:
    """`source`는 근거가 비었을 때 어느 쪽이 빈 것인지 알려주기 위한 설명 문구다."""

    value_type, _ = CASE_FIELD_SPECS[field_key]
    raw_value = getattr(case, field_key.value)
    is_unset = raw_value is None or (field_key in UNKNOWN_SENTINEL_FIELDS and raw_value == "UNKNOWN")
    if is_unset:
        return CaseFact(
            field_path=field_key, value_type=value_type, value=None, status=FactStatus.UNKNOWN, evidence_refs=[], updated_at=None
        )

    if not evidence_refs:
        raise StoredEvidenceMissingError(
            f"case {case.id}의 {field_key.value}는 확정값인데 {source}에 근거가 없다"
        )

    return CaseFact(
        field_path=field_key,
        value_type=value_type,
        value=raw_value,
        status=FactStatus.CONFIRMED,
        evidence_refs=list(evidence_refs),
        # Case 행의 updated_at은 행 전체가 마지막으로 바뀐 시각이라 필드별 확인 시각이 아니다.
        updated_at=confirmed_at,
    )


def _build_procedure_progress(step: CaseProcedureStep) -> ProcedureProgress:
    return ProcedureProgress(
        procedure_step=ProcedureStepRef(procedure_step_id=step.procedure_step_id, step_code=step.procedure_step.step_code),
        status=ProcedureProgressStatus(step.status),
        requirements_confirmed=step.requirements_confirmed,
        submitted=step.submitted,
        evidence_refs=list(step.evidence_refs or []),
        updated_at=step.updated_at.replace(tzinfo=KST),
    )


def _build_evidence_records(
    session: Session, case_id: int, evidences: list[Evidence],
    *, placeholders: dict[tuple[str, str], str] | None = None,
) -> list[EvidenceRecord]:
    """근거마다 "어느 근거에서 나왔는지"를 채워서 넘긴다(evidence_lineage에 저장해 둔 관계)."""

    evidence_id_by_row_id = {e.id: e.evidence_id for e in evidences}
    parents: dict[int, list[str]] = {}
    for link in evidence_crud.get_evidence_lineages_by_case_id(session, case_id):
        parent = evidence_id_by_row_id.get(link.parent_evidence_id)
        if parent is not None:
            parents.setdefault(link.evidence_id, []).append(parent)
    # 공식 자료는 본문을 Case마다 복사하지 않고 official_document 한 줄에 둔다. AI는 DB 표가
    # 아니라 여기서 조립한 것만 보므로, 넘기기 직전에 본문을 도로 채워 전과 같은 모양을 만든다.
    bodies = evidence_crud.get_official_document_bodies(
        session, [e.official_document_id for e in evidences if e.official_document_id]
    )
    return [_build_evidence_record(e, parents.get(e.id, []), bodies, placeholders=placeholders) for e in evidences]


def _build_evidence_record(
    evidence: Evidence, parent_evidence_refs: list[str], bodies: dict[int, str] | None = None,
    *, placeholders: dict[tuple[str, str], str] | None = None,
) -> EvidenceRecord:
    source_type = EvidenceSourceType(evidence.source_type)
    return EvidenceRecord(
        evidence_id=evidence.evidence_id,
        source_type=source_type,
        source_ref=evidence.source_ref,
        source_version=evidence.source_version,
        locator=evidence.locator,
        # 최신 입력만 가리면 소용이 없다. 같은 글이 근거로도 저장돼 있어서, 여기를 두면
        # 검수 모델이 원문을 그대로 받는다(승준님 #107 리뷰). 공식 자료는 사람이 쓴 글이
        # 아니라 가리지 않는다 — 가리면 저장된 content_hash와 어긋난다.
        excerpt=_excerpt_of(evidence, source_type, bodies, placeholders=placeholders),
        parent_evidence_refs=parent_evidence_refs,
        published_at=evidence.published_at.replace(tzinfo=KST) if evidence.published_at else None,
        retrieved_at=evidence.retrieved_at.replace(tzinfo=KST),
        freshness_status=FreshnessStatus(evidence.freshness_status),
        # DB는 64자 hex만 저장하고, AI 쪽은 "sha256:" 접두사가 붙은 형식만 받는다.
        content_hash=f"sha256:{evidence.content_hash}" if evidence.content_hash else None,
    )


def _excerpt_of(
    evidence: Evidence, source_type: EvidenceSourceType, bodies: dict[int, str] | None,
    *, placeholders: dict[tuple[str, str], str] | None = None,
) -> str | None:
    """이 근거의 본문. 공식 자료는 공용 줄에서 가져온다.

    가리키는 줄이 없으면 빈 본문으로 넘기지 않고 멈춘다. 본문 없는 공식 자료를 넘기면
    절차조회가 짝을 못 찾아 "자료 없음"이 되고, 사장님에게는 근거 없는 안내가 나간다.
    """

    if evidence.official_document_id is None:
        return _redacted_excerpt(evidence.excerpt, source_type, placeholders=placeholders)
    body = (bodies or {}).get(evidence.official_document_id)
    if body is None:
        raise StoredEvidenceMissingError(
            f"근거 {evidence.evidence_id}가 가리키는 공식 자료 "
            f"{evidence.official_document_id}가 DB에 없다"
        )
    return body


def _redacted_excerpt(
    excerpt: str | None, source_type: EvidenceSourceType,
    *, placeholders: dict[tuple[str, str], str] | None = None,
) -> str | None:
    if excerpt is None or source_type is not EvidenceSourceType.USER_INPUT:
        return excerpt
    redacted_text, _ = redact(excerpt, placeholders=placeholders)
    return redacted_text
