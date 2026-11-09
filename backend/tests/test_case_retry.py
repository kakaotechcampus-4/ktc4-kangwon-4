"""실패한 가입·결과 알려주기·서류 판단 다시 돌리기(POST /cases/retry). 진짜 MySQL이 필요하다(Docker).

판단을 실제로 돌리지 않고, 가입 판단이 끝난 상태를 DB에 직접 만든다(case_world). 모델 호출은 없다.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError
from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlmodel import Session

from app.be.crud import case_history as case_history_crud
from app.be.crud.case_history import get_case_history_by_id
from app.be.routers import case as case_router
from app.be.schemas.case import CaseRetryResponse
from app.be.services import case as case_service
from app.be.services import judgment
from app.be.services.case import retry_case_judgment, update_case_checklist
from app.common.agent_dto import RestorationAnswer
from case_world import case_engine, case_world  # noqa: F401


def _fail_signup(engine, history_id: int, recovery_action_code: str = "RETRY") -> None:
    """가입 판단을 실패로 바꾼다. 실패할 때 채워지는 필드만 채운다(decision_record.save_safe_failure)."""

    with Session(engine) as session:
        history = get_case_history_by_id(session, history_id)
        history.judgment_status = "FAILED"
        history.next_action = None
        history.next_action_reason = None
        history.priority_blocker_id = None
        history.failure_code = "RUN_DEADLINE_EXCEEDED"
        history.recovery_action_code = recovery_action_code
        history.retryable = recovery_action_code == "RETRY"
        history.requested_field_paths = ["restoration_scope"] if recovery_action_code == "RESUBMIT_INPUT" else []
        session.commit()


def _retry(engine, member_id: int) -> CaseRetryResponse:
    with Session(engine) as session:
        return retry_case_judgment(session, member_id)


def test_a_failed_signup_judgment_goes_back_to_pending(case_world):
    member_id, _, history_id = case_world.sign_up()
    _fail_signup(case_world.engine, history_id)

    response = _retry(case_world.engine, member_id)

    # 새 이력을 만들지 않고 실패한 그 이력을 다시 돌린다. 가입 이력이 둘이면 가입 근거 조회가 깨진다.
    assert response.case_history_id == history_id
    with Session(case_world.engine) as session:
        history = get_case_history_by_id(session, history_id)
        assert history.judgment_status == "PENDING"
        assert (history.judged_at, history.failure_code, history.recovery_action_code, history.retryable,
                history.requested_field_paths) == (None, None, None, None, None)


def test_a_failed_document_judgment_goes_back_to_pending(case_world):
    # 같은 서류를 다시 올려도 판단에 넘긴 기준이 이미 옮겨져 있어 다시 판단하지 않는다. 이 길뿐이다.
    member_id, case_id, _ = case_world.sign_up()
    history_id = case_world.add_history(case_id, "DOCUMENT_SUBMITTED", "FAILED")

    response = _retry(case_world.engine, member_id)

    assert response.case_history_id == history_id
    with Session(case_world.engine) as session:
        assert get_case_history_by_id(session, history_id).judgment_status == "PENDING"


def test_a_completed_case_keeps_its_failed_document_judgment(case_world):  # noqa: F811
    member_id, case_id, _ = case_world.sign_up()
    history_id = case_world.add_history(case_id, "DOCUMENT_SUBMITTED", "FAILED")
    _fail_signup(case_world.engine, history_id)
    with Session(case_world.engine) as session:
        update_case_checklist(session, member_id, "vat_submission", True)

    with pytest.raises(HTTPException) as error:
        _retry(case_world.engine, member_id)

    assert (error.value.status_code, error.value.detail) == (409, "폐업 정리를 마친 Case입니다.")
    with Session(case_world.engine) as session:
        history = get_case_history_by_id(session, history_id)
        assert (history.judgment_status, history.failure_code, history.recovery_action_code,
                history.retryable, history.requested_field_paths) == (
            "FAILED", "RUN_DEADLINE_EXCEEDED", "RETRY", True, [],
        )


def test_a_finished_signup_judgment_is_not_retried(case_world):
    member_id, _, _ = case_world.sign_up()

    with pytest.raises(HTTPException) as error:
        _retry(case_world.engine, member_id)

    assert error.value.status_code == 409


@pytest.mark.parametrize("recovery_action_code", ["RESUBMIT_INPUT", "CONTACT_SUPPORT"])
def test_only_failures_marked_retry_are_retried(case_world, recovery_action_code):
    # RESUBMIT_INPUT은 [다시 알려주기]로 결과 입력에 간다. CONTACT_SUPPORT는 같은 입력으로 다시 해도 안 풀린다.
    member_id, _, history_id = case_world.sign_up()
    _fail_signup(case_world.engine, history_id, recovery_action_code)

    with pytest.raises(HTTPException) as error:
        _retry(case_world.engine, member_id)

    assert error.value.status_code == 409


def test_a_failed_result_report_keeps_its_input(case_world):
    # 쓴 글은 화면에만 있어서 홈으로 나오면 사라진다(시우님 #196). 서버에 남은 입력으로 다시 판단한다.
    member_id, case_id, _ = case_world.sign_up()
    history_id = case_world.add_history(case_id, "USER_INPUT", "FAILED")
    answer = RestorationAnswer(restoration_scope="PARTIAL", demolition_required="NOT_REQUIRED")
    with Session(case_world.engine) as session:
        history = get_case_history_by_id(session, history_id)
        history.raw_input = answer.to_input_text()
        history.restoration_answer = answer.model_dump(mode="json")
        session.commit()

    response = _retry(case_world.engine, member_id)

    assert response.case_history_id == history_id
    with Session(case_world.engine) as session:
        history = get_case_history_by_id(session, history_id)
        assert history.judgment_status == "PENDING"
        assert history.raw_input == answer.to_input_text()
        assert history.restoration_answer == answer.model_dump(mode="json")


def test_a_failed_conflict_decision_is_not_retried(case_world):
    # 충돌 선택은 고른 값을 남기지 않아(#108) 같은 입력으로 다시 돌릴 수 없다.
    member_id, case_id, _ = case_world.sign_up()
    case_world.add_history(case_id, "CONFLICT_DECISION", "FAILED")

    with pytest.raises(HTTPException) as error:
        _retry(case_world.engine, member_id)

    assert error.value.status_code == 409


def test_pressing_twice_starts_one_judgment(case_world):
    member_id, _, history_id = case_world.sign_up()
    _fail_signup(case_world.engine, history_id)
    _retry(case_world.engine, member_id)

    with pytest.raises(HTTPException) as error:
        _retry(case_world.engine, member_id)

    assert error.value.status_code == 409


def test_two_retries_at_the_same_time_accept_only_one(case_world, monkeypatch):  # noqa: F811
    member_id, case_id, history_id = case_world.sign_up()
    _fail_signup(case_world.engine, history_id)
    gate = Barrier(2, timeout=2)
    original = case_history_crud.get_latest_user_driven_case_history

    def read_before_either_request_can_save(session, case_id):
        history = original(session, case_id)
        # 잠금이 없으면 둘 다 FAILED를 읽고 나서 저장한다. 잠금이 있으면 둘째 요청은
        # Case 줄에서 기다리므로 첫째만 통과해 PENDING으로 저장한 뒤 둘째가 409를 받는다.
        try:
            gate.wait()
        except BrokenBarrierError:
            pass
        return history

    monkeypatch.setattr(case_history_crud, "get_latest_user_driven_case_history", read_before_either_request_can_save)

    def retry():
        try:
            return "접수", _retry(case_world.engine, member_id).case_history_id
        except HTTPException as error:
            return "거절", error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [pool.submit(retry) for _ in range(2)]]

    assert sorted(results) == [("거절", 409), ("접수", history_id)]
    with Session(case_world.engine) as session:
        histories = case_history_crud.get_case_histories_by_case_id(session, case_id)
        assert [(history.id, history.judgment_status) for history in histories] == [(history_id, "PENDING")]


def test_a_member_without_a_case_gets_404(case_world):
    with pytest.raises(HTTPException) as error:
        _retry(case_world.engine, case_world.stranger())

    assert error.value.status_code == 404


def test_retrying_schedules_the_judgment_of_that_history(monkeypatch):
    """되돌리기만 하고 판단을 걸지 않으면 그 이력은 PENDING에서 영영 안 바뀐다."""

    monkeypatch.setattr(case_service, "retry_case_judgment", lambda *_a: CaseRetryResponse(case_history_id=42))
    background_tasks = BackgroundTasks()

    case_router.retry_case_judgment(background_tasks, member_id=1, session=MagicMock(spec=Session))

    assert [(task.func, task.args) for task in background_tasks.tasks] == [
        (judgment.run_judgment_in_background, (42,))
    ]


def _fail_without_recovery(engine, history_id: int, judged_version: str | None) -> None:
    """고칠 수 없다고 끝난 실패(NONE). 그 판단을 돌린 서버의 커밋을 남긴다."""

    with Session(engine) as session:
        history = get_case_history_by_id(session, history_id)
        history.failure_code = "STRUCTURED_OUTPUT_FAILED"
        history.recovery_action_code = "NONE"
        history.retryable = False
        history.judged_version = judged_version
        session.commit()


def test_a_no_recovery_failure_is_retried_after_a_new_server_is_deployed(case_world, monkeypatch):
    # 11/09 운영: 코드 검사에 걸린 실패(NONE)는 고친 코드를 올려도 같은 입력으로 다시 판단할 길이 없었다
    member_id, case_id, _ = case_world.sign_up()
    history_id = case_world.add_history(case_id, "USER_INPUT", "FAILED")
    _fail_without_recovery(case_world.engine, history_id, judged_version="a6ed43a")
    monkeypatch.setenv("APP_VERSION", "6f8b619")

    with Session(case_world.engine) as session:
        home = case_service.get_case(session, member_id)
        assert (home.recovery_action_code, home.retryable) == ("RETRY", True)
        # 저장된 실패 기록은 그대로다. 화면에 보여줄 안내만 바뀐다
        assert get_case_history_by_id(session, history_id).recovery_action_code == "NONE"

    assert _retry(case_world.engine, member_id).case_history_id == history_id
    with Session(case_world.engine) as session:
        history = get_case_history_by_id(session, history_id)
        assert (history.judgment_status, history.judged_version) == ("PENDING", None)


@pytest.mark.parametrize(("judged_version", "app_version"), [
    ("6f8b619", "6f8b619"),  # 같은 코드로 다시 돌리면 같은 이유로 또 실패한다
    (None, "6f8b619"),       # 판단한 서버를 모른다(이 칸이 생기기 전 실패)
    ("a6ed43a", None),       # 지금 서버를 모른다(GIT_SHA를 빠뜨린 배포)
])
def test_a_no_recovery_failure_stays_without_retry_unless_both_versions_differ(
    case_world, monkeypatch, judged_version, app_version,
):
    member_id, case_id, _ = case_world.sign_up()
    history_id = case_world.add_history(case_id, "USER_INPUT", "FAILED")
    _fail_without_recovery(case_world.engine, history_id, judged_version)
    if app_version is None:
        monkeypatch.delenv("APP_VERSION", raising=False)
    else:
        monkeypatch.setenv("APP_VERSION", app_version)

    with Session(case_world.engine) as session:
        home = case_service.get_case(session, member_id)
        assert (home.recovery_action_code, home.retryable) == ("NONE", False)
    with pytest.raises(HTTPException) as error:
        _retry(case_world.engine, member_id)
    assert error.value.status_code == 409


def test_a_failed_judgment_shows_the_last_task_it_was_about(case_world):
    # 실패 화면의 [새 상황 알려주기]가 무엇에 대해 알려줄지 보이게 마지막 할 일 제목을 준다
    member_id, case_id, signup_id = case_world.sign_up()
    with Session(case_world.engine) as session:
        last_task = get_case_history_by_id(session, signup_id).next_action
    assert last_task is not None
    case_world.add_history(case_id, "USER_INPUT", "FAILED")

    with Session(case_world.engine) as session:
        assert case_service.get_case(session, member_id).last_next_action_title == last_task
