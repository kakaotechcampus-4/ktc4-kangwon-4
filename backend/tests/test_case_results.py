"""결과 알려주기 흐름의 세 API. 준비물은 case_world.py.

- POST /cases/results — 결과 제출 접수
- GET /cases/results — /case의 "결과 알려주기" 진입 조회
- GET /cases/results/status — 제출 뒤 처리 상태 조회
"""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session

from app.agent.schemas import ProcedureProgressChangeCandidate
from app.be.crud import procedure_step as procedure_step_crud
from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
from app.be.schemas.case import CaseResultsSubmitRequest
from app.be.services import decision_record
from app.be.services.case import (
    get_case_results_entry,
    get_case_results_submit_status,
    retry_case_judgment,
    submit_case_results,
)

from case_world import case_engine, case_world  # noqa: F401 — 픽스처


def submit(engine, member_id: int, case_history_id: int):
    with Session(engine) as session:
        return submit_case_results(
            session, member_id, CaseResultsSubmitRequest(raw_input="전체 철거래요", case_history_id=case_history_id)
        )


def entry(engine, member_id: int):
    with Session(engine) as session:
        return get_case_results_entry(session, member_id)


def status(engine, member_id: int, case_history_id: int):
    with Session(engine) as session:
        return get_case_results_submit_status(session, member_id, case_history_id)


def error_of(call) -> tuple[int, str]:
    with pytest.raises(HTTPException) as error:
        call()
    return error.value.status_code, error.value.detail


# ---------- POST /cases/results ----------

def test_a_result_on_the_latest_judgment_is_accepted(case_engine, case_world):
    member_id, _, signed_up = case_world.sign_up()

    accepted = submit(case_engine, member_id, signed_up)

    with Session(case_engine) as session:
        history = session.get(CaseHistory, accepted.case_history_id)
        assert (history.source, history.judgment_status, history.raw_input) == ("USER_INPUT", "PENDING", "전체 철거래요")


def test_new_text_after_none_failure_preserves_the_failed_history_and_case(case_engine, case_world):
    member_id, case_id, signed_up = case_world.sign_up()
    record_progress(case_engine, case_id, signed_up, "PERFORM_RESTORATION",
                    ("IN_PROGRESS", False, False), ("IN_PROGRESS", True, False))
    failed_id = case_world.add_history(case_id, "USER_INPUT", "FAILED")
    with Session(case_engine) as session:
        failed = session.get(CaseHistory, failed_id)
        failed.failure_code = "REVIEW_RETRY_EXHAUSTED"
        failed.recovery_action_code, failed.retryable = "NONE", False
        session.commit()
        session.refresh(failed)
        original = failed.model_dump()
        case = session.get(Case, case_id)
        case_before = case.model_dump()
        progress_before = {step.id: step.model_dump() for step in case.case_procedure_steps}
        assert error_of(lambda: retry_case_judgment(session, member_id))[0] == 409

    response = entry(case_engine, member_id)
    assert (response.judgment_status, response.recovery_action_code, response.case_history_id,
            response.result_input_kind) == ("FAILED", "NONE", failed_id, "TEXT")
    accepted = submit(case_engine, member_id, failed_id)

    with Session(case_engine) as session:
        saved = session.get(CaseHistory, accepted.case_history_id)
        assert saved.id != failed_id
        assert (saved.source, saved.judgment_status, saved.raw_input) == ("USER_INPUT", "PENDING", "전체 철거래요")
        assert saved.restoration_answer is None
        assert session.get(CaseHistory, failed_id).model_dump() == original
        case = session.get(Case, case_id)
        assert case.model_dump() == case_before
        assert {step.id: step.model_dump() for step in case.case_procedure_steps} == progress_before


def test_submitting_without_a_case_is_404(case_engine, case_world):
    assert error_of(lambda: submit(case_engine, case_world.stranger(), 1))[0] == 404


def test_submitting_while_a_conflict_waits_is_409(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    case_world.add_conflict(case_id, conflicted)

    assert error_of(lambda: submit(case_engine, member_id, conflicted)) == (409, "확인 대기 중인 충돌이 있습니다.")


def test_submitting_while_the_last_one_is_judged_is_409(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    running = case_world.add_history(case_id, "USER_INPUT", "PENDING")

    assert error_of(lambda: submit(case_engine, member_id, running)) == (409, "직전 제출을 아직 처리 중입니다.")


def test_submitting_on_an_old_judgment_is_409(case_engine, case_world):
    member_id, case_id, signed_up = case_world.sign_up()
    case_world.add_history(case_id, "USER_INPUT", "DONE")

    assert error_of(lambda: submit(case_engine, member_id, signed_up)) == (409, "최신 판단에 대해 요청을 주지 않았습니다.")


def test_restoration_answer_is_persisted_with_its_literal_text(case_engine, case_world):
    member_id, _, history_id = case_world.sign_up()
    with Session(case_engine) as session:
        history = session.get(CaseHistory, history_id)
        history.next_action_code = "CONFIRM_RESTORATION_SCOPE"
        session.commit()
        request = CaseResultsSubmitRequest(case_history_id=history_id, restoration_answer={
            "restoration_scope": "PARTIAL", "demolition_required": "NOT_REQUIRED",
        })
        accepted = submit_case_results(session, member_id, request)
    with Session(case_engine) as session:
        saved = session.get(CaseHistory, accepted.case_history_id)
        assert saved.restoration_answer == request.restoration_answer.model_dump()
        assert saved.raw_input == "원상복구 범위는 일부입니다.\n철거가 필요하지 않습니다."
        assert (saved.source, saved.judgment_status) == ("USER_INPUT", "PENDING")


def _set_next_action(case_engine, history_id, action_code):
    with Session(case_engine) as session:
        session.get(CaseHistory, history_id).next_action_code = action_code
        session.commit()


@pytest.mark.parametrize("action_code,kind", [
    ("CONFIRM_FOOD_SERVICE_CLOSURE_REQUIREMENTS", "REQUIREMENTS_CONFIRMATION"),
    ("CONFIRM_EMPLOYEE_INSURANCE_LOSS_REQUIREMENTS", "REQUIREMENTS_CONFIRMATION"),
    ("CONFIRM_RESTORATION_SCOPE", "RESTORATION_ANSWER"),
    # 실행 행동과 지원사업 확인(MVP 밖)은 글로 받는다
    ("FILE_FOOD_SERVICE_CLOSURE", "TEXT"),
    ("CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS", "TEXT"),
])
def test_results_entry_tells_which_input_the_current_action_takes(case_engine, case_world, action_code, kind):
    member_id, _, history_id = case_world.sign_up()
    _set_next_action(case_engine, history_id, action_code)
    assert entry(case_engine, member_id).result_input_kind == kind


def test_requirements_confirmation_is_persisted_with_the_action_it_answers(case_engine, case_world):
    member_id, _, history_id = case_world.sign_up()
    _set_next_action(case_engine, history_id, "CONFIRM_FOOD_SERVICE_CLOSURE_REQUIREMENTS")
    with Session(case_engine) as session:
        accepted = submit_case_results(session, member_id, CaseResultsSubmitRequest(
            case_history_id=history_id, requirements_confirmed=True,
        ))
    with Session(case_engine) as session:
        saved = session.get(CaseHistory, accepted.case_history_id)
        # 어느 할 일에 답했는지는 화면이 아니라 서버가 지금 할 일에서 정한다
        assert saved.requirements_confirmation == {"action_code": "CONFIRM_FOOD_SERVICE_CLOSURE_REQUIREMENTS"}
        assert saved.raw_input == "준비사항 확인을 마쳤어요."
        assert (saved.source, saved.judgment_status, saved.restoration_answer) == ("USER_INPUT", "PENDING", None)


@pytest.mark.parametrize("action_code", ["FILE_FOOD_SERVICE_CLOSURE", "CONFIRM_RESTORATION_SCOPE", None])
def test_requirements_confirmation_for_another_action_is_422(case_engine, case_world, action_code):
    member_id, _, history_id = case_world.sign_up()
    _set_next_action(case_engine, history_id, action_code)
    with Session(case_engine) as session:
        request = CaseResultsSubmitRequest(case_history_id=history_id, requirements_confirmed=True)
        assert error_of(lambda: submit_case_results(session, member_id, request)) == (
            422, "현재 할 일에는 준비 확인 답변을 보낼 수 없습니다.")


@pytest.mark.parametrize("changes", [
    {}, {"requirements_confirmation": None}, {"raw_input": "다른 입력"},
    {"recovery_action_code": "RESUBMIT_INPUT"}, {"retryable": False},
])
def test_retrying_a_requirements_confirmation_keeps_the_same_action(case_engine, case_world, changes):
    member_id, _, history_id = case_world.sign_up()
    _set_next_action(case_engine, history_id, "CONFIRM_TAX_CLOSURE_REQUIREMENTS")
    with Session(case_engine) as session:
        accepted = submit_case_results(session, member_id, CaseResultsSubmitRequest(
            case_history_id=history_id, requirements_confirmed=True,
        ))
    with Session(case_engine) as session:
        failed = session.get(CaseHistory, accepted.case_history_id)
        failed.judgment_status, failed.recovery_action_code, failed.retryable = "FAILED", "RETRY", True
        for field, value in changes.items():
            setattr(failed, field, value)
        session.commit()
    with Session(case_engine) as session:
        request = CaseResultsSubmitRequest(case_history_id=accepted.case_history_id, requirements_confirmed=True)
        if changes:
            assert error_of(lambda: submit_case_results(session, member_id, request))[0] == 422
            return
        retried = submit_case_results(session, member_id, request)
    with Session(case_engine) as session:
        saved = session.get(CaseHistory, retried.case_history_id)
        assert saved.requirements_confirmation == {"action_code": "CONFIRM_TAX_CLOSURE_REQUIREMENTS"}
        assert saved.raw_input == "준비사항 확인을 마쳤어요."


@pytest.mark.parametrize("changes", [
    {}, {"restoration_answer": None},
    {"restoration_answer": {"restoration_scope": "FULL", "demolition_required": "NOT_REQUIRED"}},
    {"raw_input": "다른 입력"}, {"source": "DOCUMENT_SUBMITTED"},
    {"recovery_action_code": "RESUBMIT_INPUT"}, {"retryable": False},
])
def test_retrying_a_restoration_answer_requires_the_same_accepted_retryable_input(
    case_engine, case_world, changes,
):
    member_id, _, history_id = case_world.sign_up()
    with Session(case_engine) as session:
        session.get(CaseHistory, history_id).next_action_code = "CONFIRM_RESTORATION_SCOPE"
        session.commit()
        answer = {"restoration_scope": "PARTIAL", "demolition_required": "NOT_REQUIRED"}
        accepted = submit_case_results(session, member_id, CaseResultsSubmitRequest(
            case_history_id=history_id, restoration_answer=answer,
        ))
    with Session(case_engine) as session:
        failed = session.get(CaseHistory, accepted.case_history_id)
        failed.judgment_status = "FAILED"
        failed.recovery_action_code = "RETRY"
        failed.retryable = True
        for field, value in changes.items():
            setattr(failed, field, value)
        session.commit()
    with Session(case_engine) as session:
        request = CaseResultsSubmitRequest(case_history_id=accepted.case_history_id, restoration_answer=answer)
        if changes:
            assert error_of(lambda: submit_case_results(session, member_id, request))[0] == 422
            return
        retried = submit_case_results(session, member_id, request)
    with Session(case_engine) as session:
        original = session.get(CaseHistory, accepted.case_history_id)
        saved = session.get(CaseHistory, retried.case_history_id)
        assert (original.judgment_status, saved.judgment_status) == ("FAILED", "PENDING")
        assert saved.restoration_answer == original.restoration_answer == answer
        assert saved.raw_input == original.raw_input == request.restoration_answer.to_input_text()


@pytest.mark.parametrize("judgment_status,code", [
    ("DONE", None), ("DONE", "CONFIRM_RESTORATION_REQUIREMENTS"),
    ("NEEDS_MORE_INFO", "CONFIRM_RESTORATION_SCOPE"), ("FAILED", "CONFIRM_RESTORATION_SCOPE"),
])
def test_restoration_answer_requires_the_current_supported_action(case_engine, case_world, judgment_status, code):
    member_id, case_id, _ = case_world.sign_up()
    history_id = case_world.add_history(case_id, "USER_INPUT", judgment_status)
    with Session(case_engine) as session:
        session.get(CaseHistory, history_id).next_action_code = code
        session.commit()
        request = CaseResultsSubmitRequest(case_history_id=history_id, restoration_answer={
            "restoration_scope": "UNKNOWN", "demolition_required": "UNKNOWN",
        })
        assert error_of(lambda: submit_case_results(session, member_id, request))[0] == 422


@pytest.mark.parametrize("payload", [
    {}, {"raw_input": ""}, {"raw_input": "  "}, {"raw_input": "가" * 2001},
    {"restoration_answer": {}},
    {"restoration_answer": {"restoration_scope": "PARTIAL", "demolition_required": "MAYBE"}},
    {"restoration_answer": {"restoration_scope": "PARTIAL", "demolition_required": "REQUIRED", "detail": "글"}},
    {"raw_input": "추가 글", "restoration_answer": {"restoration_scope": "FULL", "demolition_required": "REQUIRED"}},
    # [아직 안 했어요]는 보내지 않는다. 버튼 답에 글이나 다른 선택을 섞을 수 없다
    {"requirements_confirmed": False},
    {"requirements_confirmed": True, "raw_input": "넵 다 확인 완료했어요"},
    {"requirements_confirmed": True,
     "restoration_answer": {"restoration_scope": "FULL", "demolition_required": "REQUIRED"}},
])
def test_restoration_answer_rejects_incomplete_or_mixed_requests(payload):
    with pytest.raises(ValidationError):
        CaseResultsSubmitRequest(case_history_id=1, **payload)


def test_restoration_answer_is_offered_from_saved_action_code_only(case_engine, case_world):
    member_id, _, history_id = case_world.sign_up()
    # 제목이 원상복구여도 종류가 저장되지 않은 과거 이력은 직접 입력이다.
    assert entry(case_engine, member_id).result_input_kind == "TEXT"
    with Session(case_engine) as session:
        session.get(CaseHistory, history_id).next_action_code = "CONFIRM_RESTORATION_SCOPE"
        session.commit()
    assert entry(case_engine, member_id).result_input_kind == "RESTORATION_ANSWER"


# ---------- GET /cases/results ----------

def test_entry_shows_pending_before_the_conflict_while_a_decision_is_judged(case_engine, case_world):
    """결정을 받아도 충돌은 판단이 성공해야 닫힌다. 처리 중을 먼저 보지 않으면 확인 화면이 다시 뜬다."""

    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    case_world.add_conflict(case_id, conflicted)
    deciding = case_world.add_history(case_id, "CONFLICT_DECISION", "PENDING")

    response = entry(case_engine, member_id)

    assert (response.judgment_status, response.case_history_id) == ("PENDING", deciding)


def test_entry_shows_the_waiting_conflict(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    conflict_id = case_world.add_conflict(case_id, conflicted)

    response = entry(case_engine, member_id)

    assert response.judgment_status == "CONFLICT"
    assert [item.id for item in response.conflicts] == [conflict_id]
    assert response.raw_input == "결과 글"


def test_entry_shows_the_conflict_again_after_a_failed_decision(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    case_world.add_conflict(case_id, conflicted)
    case_world.add_history(case_id, "CONFLICT_DECISION", "FAILED")

    assert entry(case_engine, member_id).judgment_status == "CONFLICT"


def test_entry_shows_the_next_action_when_done(case_engine, case_world):
    member_id, _, signed_up = case_world.sign_up()

    response = entry(case_engine, member_id)

    assert (response.judgment_status, response.case_history_id) == ("DONE", signed_up)
    assert response.next_action.title == "임대인에게 원상복구 범위 묻기"


def test_entry_shows_how_to_recover_when_failed(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    case_world.add_history(case_id, "USER_INPUT", "FAILED")

    response = entry(case_engine, member_id)

    assert (response.judgment_status, response.recovery_action_code, response.retryable) == ("FAILED", "RETRY", True)


# ---------- GET /cases/results/status ----------

def test_status_of_an_old_submission_is_409(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    old = case_world.add_history(case_id, "USER_INPUT", "DONE")
    case_world.add_history(case_id, "USER_INPUT", "DONE")

    assert error_of(lambda: status(case_engine, member_id, old)) == (409, "최신 판단에 대해 요청을 주지 않았습니다.")


def test_status_while_judged_is_pending(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    running = case_world.add_history(case_id, "USER_INPUT", "PENDING")

    assert status(case_engine, member_id, running).result == "PENDING"


def test_status_can_follow_a_conflict_decision(case_engine, case_world):
    """결정 접수도 같은 조회로 결과를 기다린다. 가입·결과 제출 이력만 보면 결정 번호를 못 찾는다."""

    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")
    case_world.add_conflict(case_id, conflicted)
    deciding = case_world.add_history(case_id, "CONFLICT_DECISION", "PENDING")

    assert status(case_engine, member_id, deciding).result == "PENDING"


def test_status_reports_updated_with_the_changes(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    done = case_world.add_history(case_id, "USER_INPUT", "DONE")
    case_world.add_change(case_id, done)

    response = status(case_engine, member_id, done)

    assert response.result == "UPDATED"
    assert [(c.field, c.stored_value, c.new_value) for c in response.changes] == [("restoration_scope", "UNKNOWN", "FULL")]


def test_status_reports_no_change_when_nothing_moved(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    done = case_world.add_history(case_id, "USER_INPUT", "DONE")

    assert status(case_engine, member_id, done).result == "NO_CHANGE"


def record_progress(engine, case_id, history_id, code, before, after):
    with Session(engine) as session:
        definition = procedure_step_crud.get_procedure_step_by_code(session, code)
        step = procedure_step_crud.get_case_procedure_step(session, case_id, definition.id)
        step.status, step.requirements_confirmed, step.submitted = before
        change = ProcedureProgressChangeCandidate(
            candidate_id=uuid4(), procedure_step={"procedure_step_id": definition.id, "step_code": code},
            before_status=before[0], proposed_status=after[0],
            before_requirements_confirmed=before[1], proposed_requirements_confirmed=after[1],
            before_submitted=before[2], proposed_submitted=after[2],
            reason_summary="합성 진행 보고", execution_evidence_refs=["synthetic-progress-report"],
            procedure_analysis_call_id=uuid4(),
        )
        decision_record._apply_procedure_progress_changes(session, session.get(CaseHistory, history_id), [change])
        session.commit()


@pytest.mark.parametrize("source", ["USER_INPUT", "CONFLICT_DECISION"])
@pytest.mark.parametrize("code,before,after", [
    ("PERFORM_RESTORATION", ("IN_PROGRESS", False, False), ("IN_PROGRESS", True, False)),
    ("FILE_TAX_BUSINESS_CLOSURE", ("IN_PROGRESS", True, False), ("IN_PROGRESS", True, True)),
    ("FILE_TAX_BUSINESS_CLOSURE", ("IN_PROGRESS", True, True), ("COMPLETED", True, True)),
])
def test_status_reports_updated_for_progress_without_case_field_changes(
    case_engine, case_world, source, code, before, after,
):
    member_id, case_id, _ = case_world.sign_up()
    done = case_world.add_history(case_id, source, "DONE")
    record_progress(case_engine, case_id, done, code, before, after)

    response = status(case_engine, member_id, done)

    assert response.result == "UPDATED"
    assert response.changes == []
    assert response.next_action is not None


def test_old_progress_changes_do_not_make_a_new_report_updated(case_engine, case_world):
    member_id, case_id, _ = case_world.sign_up()
    old = case_world.add_history(case_id, "USER_INPUT", "DONE")
    record_progress(case_engine, case_id, old, "PERFORM_RESTORATION",
                    ("IN_PROGRESS", False, False), ("IN_PROGRESS", True, False))
    current = case_world.add_history(case_id, "USER_INPUT", "DONE")

    assert status(case_engine, member_id, current).result == "NO_CHANGE"


def test_status_stops_on_a_conflict_without_any_open_conflict(case_engine, case_world):
    """CONFLICT인데 보여줄 충돌이 없으면 빈 확인 화면 대신 멈춘다(저장 코드가 깨진 경우)."""

    member_id, case_id, _ = case_world.sign_up()
    conflicted = case_world.add_history(case_id, "USER_INPUT", "CONFLICT")

    assert error_of(lambda: status(case_engine, member_id, conflicted))[0] == 500
