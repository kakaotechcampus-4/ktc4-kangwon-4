"""충돌 결정 접수(POST /cases/results/decision)의 검사들. 준비물은 case_world.py."""

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.be.models.case_history import CaseHistory
from app.be.models.evidence import ConflictReference
from app.be.schemas.case import CaseConflictsDecisionRequest
from app.be.services.case import submit_case_conflicts_decision

from case_world import case_engine, case_world  # noqa: F401 — 픽스처


@pytest.fixture
def waiting(case_world):
    """결과 제출이 충돌 두 개로 끝나 결정을 기다리는 Case. (member_id, case_id, 충돌 id 둘)"""

    member_id, case_id, _ = case_world.sign_up()
    submitted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    first = case_world.add_conflict(case_id, submitted, "restoration_scope")
    second = case_world.add_conflict(case_id, submitted, "demolition_required")
    return member_id, case_id, first, second


def decide(engine, member_id: int, *ids: int):
    with Session(engine) as session:
        return submit_case_conflicts_decision(session, member_id, CaseConflictsDecisionRequest(
            decisions=[{"conflict_reference_id": i, "side": "PROPOSED"} for i in ids],
        ))


def rejected(engine, member_id: int, *ids: int) -> tuple[int, str]:
    with pytest.raises(HTTPException) as error:
        decide(engine, member_id, *ids)
    return error.value.status_code, error.value.detail


def test_deciding_every_conflict_is_accepted_and_leaves_them_open_until_judged(case_engine, waiting):
    member_id, case_id, first, second = waiting

    accepted = decide(case_engine, member_id, first, second)

    with Session(case_engine) as session:
        history = session.get(CaseHistory, accepted.case_history_id)
        assert (history.source, history.judgment_status, history.raw_input) == ("CONFLICT_DECISION", "PENDING", None)
        # 판단이 성공해야 닫는다. 접수만으로 닫으면 판단이 실패했을 때 다시 고를 길이 없다.
        statuses = session.exec(select(ConflictReference.status).where(ConflictReference.case_id == case_id)).all()
        assert set(statuses) == {"PENDING"}


def test_someone_without_a_case_gets_404(case_engine, case_world):
    assert rejected(case_engine, case_world.stranger(), 1)[0] == 404


def test_nothing_to_decide_is_409(case_engine, case_world):
    member_id, _, _ = case_world.sign_up()

    assert rejected(case_engine, member_id, 1) == (409, "확인 대기 중인 충돌이 없습니다.")


def test_a_decision_still_being_judged_is_409(case_engine, case_world, waiting):
    member_id, case_id, first, second = waiting
    case_world.add_history(case_id, "CONFLICT_DECISION", "PENDING")

    assert rejected(case_engine, member_id, first, second) == (409, "직전 충돌 결정을 아직 처리 중입니다.")


def test_after_a_failed_decision_the_owner_can_decide_again(case_engine, case_world, waiting):
    member_id, case_id, first, second = waiting
    case_world.add_history(case_id, "CONFLICT_DECISION", "FAILED")

    assert decide(case_engine, member_id, first, second).case_history_id


def test_the_same_conflict_twice_is_422(case_engine, waiting):
    member_id, _, first, _ = waiting

    assert rejected(case_engine, member_id, first, first) == (422, "같은 충돌에 대한 결정이 중복되었습니다.")


def test_an_already_resolved_conflict_is_409(case_engine, case_world, waiting):
    member_id, case_id, first, second = waiting
    old_submission = case_world.add_history(case_id, "USER_INPUT", "DONE")
    resolved = case_world.add_conflict(case_id, old_submission, status="CONFIRMED")

    assert rejected(case_engine, member_id, first, second, resolved) == (409, "이미 해결된 충돌입니다.")


def test_a_conflict_that_is_not_this_cases_is_422(case_engine, case_world, waiting):
    member_id, _, first, second = waiting
    other_member, other_case, _ = case_world.sign_up()
    other_submission = case_world.add_history(other_case, "USER_INPUT", "CONFLICT")
    others = case_world.add_conflict(other_case, other_submission)

    for unknown in (others, 999_999):
        assert rejected(case_engine, member_id, first, second, unknown) == (422, "존재하지 않는 충돌입니다.")


def test_leaving_a_conflict_undecided_is_422(case_engine, waiting):
    member_id, _, first, _ = waiting

    assert rejected(case_engine, member_id, first) == (422, "결정하지 않은 충돌이 있습니다.")
