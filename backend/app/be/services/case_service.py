"""Case Service (B7).

Case에 접근하는 문을 하나로 만든다: 소유권 검증 포함 단일 조회 경로, 필드 변경 단일 경로,
Agent에 넘길 CaseSnapshot 조립. 배경과 결정 사항은 `docs/case-service.md` 참고.

이 모듈이 하지 않는 일:
- 상태 전이 유효성 검증 (B10)
- 충돌 자동 덮어쓰기 방지의 CAS 로직 (B10/B12, CONFLICT_REFERENCE 필요)
- Agent 실행 orchestration (B11)
- JWT 인증·소유권 판별 자체 — 이미 검증된 member_id를 받는다고 가정 (B6)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlmodel import Session

from app.be.crud import case as case_crud
from app.be.models.case import Case

# TODO(PM): PRD에 history 개수 정책 없음. 확정 전까지의 임시 기본값.
DEFAULT_HISTORY_WINDOW = 20


class CaseNotFoundError(Exception):
    """조회자가 소유하지 않았거나 존재하지 않는 Case.

    라우터는 이 예외를 반드시 404로만 변환한다 — 소유권 없음과 존재하지 않음을
    구분해서 응답하지 않는다 (B6, Case 존재 여부 비노출).
    """


@dataclass(frozen=True)
class ProcedureProgressView:
    procedure_step_id: int
    status: str


@dataclass(frozen=True)
class BlockerView:
    id: int
    description: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class HistoryEntryView:
    id: int
    raw_input: str
    source: str
    next_action: str | None
    created_at: datetime


@dataclass(frozen=True)
class InternalCaseSnapshot:
    """BE 내부 read model.

    AI가 실제로 소비하는 `app.agent.schemas.CaseSnapshot`과 1:1 대응이 아니다.
    그 변환은 `to_agent_case_snapshot`을 참고 — 지금은 계약 미확정으로 보류 상태다.
    """

    case_id: int
    case_version: int | None  # TODO(schema): CASE.case_version 컬럼 병합 전까지 항상 None
    case_status: str
    business_type: str
    franchise_status: bool
    employee_count: int | None
    lease_status: str
    restoration_status: str
    restoration_scope: str
    restoration_scope_detail: str | None
    demolition_required: str
    planned_closure_date: date | None
    procedure_progress: list[ProcedureProgressView]
    active_blockers: list[BlockerView]
    recent_history: list[HistoryEntryView]
    captured_at: datetime


def get_case_for_member(session: Session, *, case_id: int, member_id: int) -> Case:
    """Case 조회의 단일 경로.

    다른 코드는 이 함수를 거치지 않고 `Case`를 직접 select하지 않는다
    (architecture.md의 "Agent와 Tool은 DB를 직접 변경하지 않는다" 불변식의 조회측 강제 지점).
    """
    case = case_crud.get_case_by_id_and_member(session, case_id=case_id, member_id=member_id)
    if case is None:
        raise CaseNotFoundError(case_id)
    return case


def assemble_case_snapshot(
    session: Session,
    case: Case,
    *,
    history_window: int = DEFAULT_HISTORY_WINDOW,
) -> InternalCaseSnapshot:
    """한 읽기 시점의 Case 상태를 고정한 스냅샷을 조립한다.

    Agent/Tool은 이 함수가 반환한 스냅샷만 보고, DB를 직접 조회하지 않는다.
    """
    progress_rows = case_crud.list_case_procedure_progress(session, case_id=case.id)
    blocker_rows = case_crud.list_active_blockers(session, case_id=case.id)
    history_rows = case_crud.list_recent_case_history(
        session, case_id=case.id, limit=history_window
    )

    return InternalCaseSnapshot(
        case_id=case.id,
        # TODO(schema): CASE.case_version 컬럼이 아직 모델에 없다 (별도 팀원 작업, schema_table.md 기준).
        # 컬럼이 생기면 getattr 제거하고 case.case_version을 직접 읽는다.
        case_version=getattr(case, "case_version", None),
        case_status=case.case_status,
        business_type=case.business_type,
        franchise_status=case.franchise_status,
        employee_count=case.employee_count,
        lease_status=case.lease_status,
        restoration_status=case.restoration_status,
        restoration_scope=case.restoration_scope,
        restoration_scope_detail=case.restoration_scope_detail,
        demolition_required=case.demolition_required,
        planned_closure_date=case.planned_closure_date,
        procedure_progress=[
            ProcedureProgressView(procedure_step_id=row.procedure_step_id, status=row.status)
            for row in progress_rows
        ],
        active_blockers=[
            BlockerView(
                id=blocker.id,
                description=blocker.description,
                status=blocker.status,
                created_at=blocker.created_at,
            )
            for blocker in blocker_rows
        ],
        recent_history=[
            HistoryEntryView(
                id=entry.id,
                raw_input=entry.raw_input,
                source=entry.source,
                next_action=entry.next_action,
                created_at=entry.created_at,
            )
            for entry in history_rows
        ],
        captured_at=datetime.now(),
    )


def to_agent_case_snapshot(snapshot: InternalCaseSnapshot):
    """`InternalCaseSnapshot`을 AI가 실제로 쓰는 `app.agent.schemas.CaseSnapshot`으로 변환한다.

    아직 구현하지 않는다. DB의 `lease_status`(LEASED_PAID/LEASED_FREE/OWNED, 임대 조건)와
    `restoration_scope`(UNKNOWN/PARTIAL/FULL/NOT_REQUIRED, 복구 범위)가, AI 내부
    `CASE_FIELD_SPECS`(lease_status: ACTIVE/TERMINATION_NOTIFIED/TERMINATED/OWNED — 해지 통보
    진행 단계, restoration_scope: AGREEMENT_REQUIRED/TENANT_ALL/LANDLORD_ALL/SHARED/NOT_REQUIRED
    — 복구 비용 부담 주체)와 다른 사실을 나타낸다 (2026-09-19 팀 확인).

    AI 쪽 계약 변경 없이 임의로 값을 매핑하면 근거 없는 단정을 만드는 것과 같다
    (루트 CLAUDE.md "뚫리면 안 되는 선 2·3"). AI 리드가 `CASE_FIELD_SPECS`를 schema_table.md
    기준으로 갱신하거나 별도 매핑을 승인하면 이 함수를 구현한다. 자세한 내용은
    `docs/case-service.md`의 "열린 이슈" 참고.
    """
    raise NotImplementedError(
        "AI CaseSnapshot 변환 보류 — lease_status/restoration_scope 계약 미확정 "
        "(docs/case-service.md 참고)"
    )


def apply_case_field_changes(session: Session, case: Case, changes: dict[str, object]) -> Case:
    """Case 필드를 바꾸는 단일 경로.

    다른 코드는 이 함수를 거치지 않고 `Case` 컬럼을 직접 assign하지 않는다.
    상태 전이 유효성 검증(B10)과 충돌 감지(B12)는 이 함수의 책임이 아니다 — 호출자가
    그 검증을 먼저 통과시킨 변경만 넘겨야 한다. 이 함수는 반영과 저장만 한다.
    """
    for field_name, value in changes.items():
        if not hasattr(case, field_name):
            raise ValueError(f"unknown case field: {field_name}")
        setattr(case, field_name, value)

    # TODO(schema): CASE.case_version 컬럼이 아직 모델에 없다 (별도 팀원 작업 예정).
    # 컬럼이 생기면 아래 줄의 주석을 풀어 낙관적 동시성 증가를 강제한다.
    # case.case_version = (case.case_version or 0) + 1

    # TODO(schema): CASE_FIELD_HISTORY 테이블이 아직 모델에 없다. 생기면 여기서
    # canonical_field/before_value/after_value/source/reason/resulting_case_version을 append한다.

    session.add(case)
    session.commit()
    session.refresh(case)
    return case
