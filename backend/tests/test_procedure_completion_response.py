"""절차 안내 종료를 전체 폐업 완료·손상된 DONE과 구분한다. 실제 MySQL, 모델 호출 없음."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import DecisionRecord
from app.be.models.mixins import kst_now
from app.be.schemas.case import CaseResultsSubmitRequest
from app.be.services.case import (
    get_case,
    get_case_logs,
    get_case_results_entry,
    get_case_results_submit_status,
    retry_case_judgment,
    submit_case_results,
)

from case_world import case_engine, case_world  # noqa: F401 — 픽스처


def completed_history(world, *, proof="PASS", proof_on_previous=False):
    member_id, case_id, previous_id = world.sign_up()
    history_id = world.add_history(case_id, "USER_INPUT", "DONE")
    with Session(world.engine) as session:
        history = session.get(CaseHistory, history_id)
        history.next_action = history.next_action_code = history.next_action_reason = None
        history.next_action_questions_to_ask = history.next_action_evidence_refs = None
        history.priority_blocker_id = history.questions_for_user = None
        history.judged_at = kst_now()
        if proof is not None:
            session.add(DecisionRecord(
                case_id=case_id, case_history_id=previous_id if proof_on_previous else history_id,
                run_id=str(uuid4()), snapshot_id=str(uuid4()), review_subject_id=str(uuid4()),
                subject_digest="completion-proof", decision_type="PROCEDURES_COMPLETED",
                verdict=proof, reviewed_at=kst_now(),
            ))
        session.commit()
    return member_id, case_id, history_id


def test_completion_is_readable_without_an_action_and_does_not_complete_case(case_engine, case_world):
    member_id, case_id, history_id = completed_history(case_world)
    # 각각 새 DB 세션에서 조회해 일시적인 메모리 상태가 아닌 저장된 판단을 읽는다.
    with Session(case_engine) as session:
        home = get_case(session, member_id)
        assert home.judgment_status == "PROCEDURES_COMPLETED"
        assert (home.blocker, home.next_action, home.questions_for_user) == (None, None, None)
        assert (home.case.case_status, home.case.completed_at) == ("IN_PROGRESS", None)
    with Session(case_engine) as session:
        entry = get_case_results_entry(session, member_id)
        assert (entry.judgment_status, entry.case_history_id) == ("PROCEDURES_COMPLETED", history_id)
        assert entry.next_action is None and entry.questions_for_user is None
    with Session(case_engine) as session:
        status = get_case_results_submit_status(session, member_id, history_id)
        assert status.result == "PROCEDURES_COMPLETED"
        assert (status.blocker, status.next_action, status.questions_for_user) == (None, None, None)
        events = [row.event for row in get_case_logs(session, member_id).logs]
        assert events.count("PROCEDURES_COMPLETED") == 1
        # 마지막 완료가 가짜 다음 행동 기록을 만들지 않는다.
        assert "NEXT_ACTION_DECIDED" not in events
        assert session.get(Case, case_id).case_status == "IN_PROGRESS"
        assert session.get(CaseHistory, history_id).judgment_status == "DONE"


@pytest.mark.parametrize("proof,previous", [(None, False), ("FAIL", False), ("PASS", True)])
def test_missing_or_wrong_completion_proof_does_not_hide_a_broken_done(
    case_engine, case_world, proof, previous,
):
    member_id, _, history_id = completed_history(case_world, proof=proof, proof_on_previous=previous)
    for read in (
        lambda session: get_case(session, member_id),
        lambda session: get_case_results_entry(session, member_id),
        lambda session: get_case_results_submit_status(session, member_id, history_id),
    ):
        with Session(case_engine) as session, pytest.raises(HTTPException) as error:
            read(session)
        assert error.value.status_code == 500


def test_completion_proof_does_not_allow_a_stale_action_or_another_done_button(case_engine, case_world):
    member_id, _, history_id = completed_history(case_world)
    with Session(case_engine) as session, pytest.raises(HTTPException) as error:
        submit_case_results(session, member_id, CaseResultsSubmitRequest(
            case_history_id=history_id, action_done=True,
        ))
    assert error.value.status_code == 422
    with Session(case_engine) as session, pytest.raises(HTTPException) as error:
        retry_case_judgment(session, member_id)
    assert error.value.status_code == 409
    with Session(case_engine) as session:
        session.get(CaseHistory, history_id).next_action = "끝난 일을 다시 하세요"
        session.commit()
    with Session(case_engine) as session, pytest.raises(HTTPException) as error:
        get_case(session, member_id)
    assert error.value.status_code == 500
