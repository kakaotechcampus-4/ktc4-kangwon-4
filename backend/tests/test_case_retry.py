"""실패한 가입·결과 알려주기·서류 판단 다시 돌리기(POST /cases/retry). 진짜 MySQL이 필요하다(Docker).

판단을 실제로 돌리지 않고, 가입 판단이 끝난 상태를 DB에 직접 만든다(case_world). 모델 호출은 없다.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlmodel import Session

from app.be.crud.case_history import get_case_history_by_id
from app.be.routers import case as case_router
from app.be.schemas.case import CaseRetryResponse
from app.be.services import case as case_service
from app.be.services import judgment
from app.be.services.case import retry_case_judgment
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
