"""필드마다 어느 근거를 달아 AI에 넘기는지. DB 연결 없이 crud만 바꿔 끼운다.

가입 폼 근거와 변경 이력 근거를 섞으면 AI가 값의 출처를 틀리게 받는다. 그 경계만 본다.
"""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session

from app.agent.schemas import FactStatus
from app.be.crud import case as case_crud
from app.be.crud import case_field_history as case_field_history_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import evidence as evidence_crud
from app.be.crud import procedure_step as procedure_step_crud
from app.be.models.case import Case
from app.be.services.case_snapshot import build_case_snapshot

CASE_ID = 7
CREATION_HISTORY_ID = 11
SUBMITTED_AT = datetime(2026, 10, 4, 9, 0, 0)
CHANGED_AT = datetime(2026, 10, 5, 9, 0, 0)
FORM_EVIDENCE_ID = evidence_crud.case_history_evidence_id(CASE_ID, CREATION_HISTORY_ID)
JUDGMENT_EVIDENCE_ID = "ev_judgment_1"


def case() -> Case:
    return Case(
        id=CASE_ID,
        member_id=1,
        business_type="한식음식점",
        franchise_status=False,
        employee_count=2,
        case_status="IN_PROGRESS",
        lease_status="LEASED_PAID",
        restoration_status="NOT_STARTED",
        restoration_scope="FULL",
        restoration_scope_detail=None,
        demolition_required="NOT_REQUIRED",
        planned_closure_date=date(2026, 12, 1),
    )


def evidence(evidence_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=hash(evidence_id) % 1000,
        evidence_id=evidence_id,
        source_type="USER_INPUT",
        source_ref="case_history",
        source_version=None,
        locator=None,
        excerpt="합성 발췌",
        published_at=None,
        retrieved_at=SUBMITTED_AT,
        freshness_status="CURRENT",
        content_hash=None,
    )


def field_history(canonical_field: str, source_evidence_refs) -> SimpleNamespace:
    return SimpleNamespace(
        canonical_field=canonical_field,
        source_evidence_refs=source_evidence_refs,
        created_at=CHANGED_AT,
    )


@pytest.fixture
def snapshot_of(monkeypatch):
    """field_histories를 넣으면 그 상태의 스냅샷을 만들어 주는 호출기."""

    def build(field_histories, evidence_ids=(FORM_EVIDENCE_ID, JUDGMENT_EVIDENCE_ID)):
        monkeypatch.setattr(case_crud, "get_case_by_id", lambda *_: case())
        monkeypatch.setattr(
            evidence_crud, "get_evidence_by_case_id",
            lambda *_: [evidence(eid) for eid in evidence_ids],
        )
        monkeypatch.setattr(evidence_crud, "get_evidence_lineages_by_case_id", lambda *_: [])
        monkeypatch.setattr(procedure_step_crud, "get_case_procedure_steps_by_case_id", lambda *_: [])
        monkeypatch.setattr(
            case_history_crud, "get_case_created_history",
            lambda *_: SimpleNamespace(id=CREATION_HISTORY_ID, created_at=SUBMITTED_AT),
        )
        monkeypatch.setattr(
            case_field_history_crud, "get_case_field_histories_by_case_id",
            lambda *_: list(field_histories),
        )
        return build_case_snapshot(MagicMock(spec=Session), CASE_ID)

    return build


def fact_of(snapshot, field: str):
    return next(fact for fact in snapshot.facts if fact.field_path.value == field)


def test_unchanged_field_uses_the_signup_form_evidence(snapshot_of):
    snapshot = snapshot_of([])

    fact = fact_of(snapshot, "business_type")
    assert fact.status is FactStatus.CONFIRMED
    assert fact.evidence_refs == [FORM_EVIDENCE_ID]
    assert fact.updated_at.replace(tzinfo=None) == SUBMITTED_AT


def test_changed_field_uses_only_the_evidence_of_the_judgment_that_changed_it(snapshot_of):
    snapshot = snapshot_of([field_history("business_type", [JUDGMENT_EVIDENCE_ID])])

    fact = fact_of(snapshot, "business_type")
    assert fact.evidence_refs == [JUDGMENT_EVIDENCE_ID]
    assert FORM_EVIDENCE_ID not in fact.evidence_refs
    assert fact.updated_at.replace(tzinfo=None) == CHANGED_AT


@pytest.mark.parametrize(
    "stored_refs",
    [
        pytest.param([], id="근거를 아예 안 적은 이력"),
        pytest.param(None, id="근거 칸이 NULL인 이력"),
        pytest.param(["ev_from_another_case"], id="이 Case에 없는 근거만 적은 이력"),
    ],
)
def test_changed_field_without_evidence_is_an_error_not_a_fallback_to_the_form(snapshot_of, stored_refs):
    # 폼 근거로 되돌리면 판단이 바꿔 넣은 값을 "가입할 때 받은 값"이라고 AI에게 알려주게 된다.
    with pytest.raises(ValueError) as error:
        snapshot_of([field_history("business_type", stored_refs)])

    assert "business_type" in str(error.value)
    assert "변경 이력" in str(error.value)


def test_unset_field_stays_unknown_and_does_not_demand_evidence(snapshot_of):
    # 값이 비워진 칸은 근거를 요구하지 않는다. 이력이 있어도 위 오류와 섞이면 안 된다.
    snapshot = snapshot_of([field_history("restoration_scope_detail", [])])

    fact = fact_of(snapshot, "restoration_scope_detail")
    assert fact.status is FactStatus.UNKNOWN
    assert fact.evidence_refs == []
