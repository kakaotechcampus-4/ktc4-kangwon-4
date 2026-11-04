"""결과 화면의 "새로 생긴 할 일"(GET /cases/results/status의 new_tasks). 진짜 MySQL이 필요하다(Docker).

판단을 실제로 돌리지 않고, 판단이 끝난 이력을 DB에 직접 만든다(case_world). 모델 호출은 없다.
"""

from sqlmodel import Session

from app.be.crud.case import get_case_by_member_id
from app.be.crud.case_history import get_case_history_by_id
from app.be.models.mixins import kst_now
from app.be.services.case import get_case_logs, get_case_results_submit_status
from app.be.services.decision_record import _roadmap_task_ids
from case_world import case_engine, case_world  # noqa: F401

DEMOLITION_TASKS = {"support_conditions", "support_application", "choose_contractor", "before_photo",
                    "contractor_documents"}


def _set_task_ids(engine, history_id: int, task_ids: list[str] | None) -> None:
    with Session(engine) as session:
        history = get_case_history_by_id(session, history_id)
        history.roadmap_task_ids = task_ids
        session.commit()


def _new_tasks(engine, member_id: int, history_id: int):
    with Session(engine) as session:
        return get_case_results_submit_status(session, member_id, history_id).new_tasks


def test_demolition_tasks_open_once_demolition_is_known(case_world):
    """가입 직후엔 철거 필요 여부를 몰라 철거비 항목이 빠지고, 정해지면 들어온다(시안 "할 일 3개")."""

    member_id, case_id, _ = case_world.sign_up()
    with Session(case_world.engine) as session:
        before = set(_roadmap_task_ids(session, case_id))
        case = get_case_by_member_id(session, member_id)
        case.demolition_required = "REQUIRED"
        session.flush()
        after = set(_roadmap_task_ids(session, case_id))

    assert {"dispose_stock", "notify_landlord"} <= before
    assert not DEMOLITION_TASKS & before
    assert DEMOLITION_TASKS <= after


def test_new_tasks_are_what_this_judgment_added(case_world):
    member_id, case_id, created_id = case_world.sign_up()
    _set_task_ids(case_world.engine, created_id, ["intake", "dispose_stock"])
    submitted_id = case_world.add_history(case_id, "USER_INPUT", "DONE")
    _set_task_ids(case_world.engine, submitted_id, ["intake", "dispose_stock", "before_photo", "support_application"])

    new_tasks = _new_tasks(case_world.engine, member_id, submitted_id)

    assert [(task.task_id, task.title) for task in new_tasks] == [
        ("before_photo", "철거 전 사진"), ("support_application", "소상공인24 사전 신청"),
    ]


def test_nothing_new_is_an_empty_list(case_world):
    member_id, case_id, created_id = case_world.sign_up()
    _set_task_ids(case_world.engine, created_id, ["intake"])
    submitted_id = case_world.add_history(case_id, "USER_INPUT", "DONE")
    _set_task_ids(case_world.engine, submitted_id, ["intake"])

    assert _new_tasks(case_world.engine, member_id, submitted_id) == []


def test_compares_with_the_latest_judgment_that_kept_a_list(case_world):
    """충돌·실패로 끝난 판단은 목록이 없다. 그 앞의 판단과 비교한다."""

    member_id, case_id, created_id = case_world.sign_up()
    _set_task_ids(case_world.engine, created_id, ["intake"])
    first_id = case_world.add_history(case_id, "USER_INPUT", "DONE")
    _set_task_ids(case_world.engine, first_id, ["intake", "dispose_stock"])
    case_world.add_history(case_id, "USER_INPUT", "FAILED")
    latest_id = case_world.add_history(case_id, "USER_INPUT", "DONE")
    _set_task_ids(case_world.engine, latest_id, ["intake", "dispose_stock", "before_photo"])

    assert [task.task_id for task in _new_tasks(case_world.engine, member_id, latest_id)] == ["before_photo"]


def test_without_a_list_to_compare_it_is_null(case_world):
    """이 기능 전에 만든 이력이나 계산이 실패한 판단은 목록이 없어 비교할 수 없다."""

    member_id, case_id, _ = case_world.sign_up()
    submitted_id = case_world.add_history(case_id, "USER_INPUT", "DONE")
    _set_task_ids(case_world.engine, submitted_id, ["intake"])

    assert _new_tasks(case_world.engine, member_id, submitted_id) is None


# 기록 탭 "답변대로 할 일 3개를 추가했어요"(ROADMAP_TASKS_ADDED). 결과 화면과 같은 뺄셈을 쓴다.

def _judged(engine, history_id: int, task_ids: list[str] | None) -> None:
    with Session(engine) as session:
        history = get_case_history_by_id(session, history_id)
        history.roadmap_task_ids = task_ids
        history.judged_at = kst_now()
        session.commit()


def _added_logs(engine, member_id: int) -> list[str | None]:
    with Session(engine) as session:
        return [
            log.detail for log in get_case_logs(session, member_id).logs
            if log.event == "ROADMAP_TASKS_ADDED"
        ]


def test_the_log_counts_tasks_this_judgment_added(case_world):
    member_id, case_id, created_id = case_world.sign_up()
    _judged(case_world.engine, created_id, ["intake"])
    submitted_id = case_world.add_history(case_id, "USER_INPUT", "DONE")
    _judged(case_world.engine, submitted_id, ["intake", "support_application", "choose_contractor", "before_photo"])

    assert _added_logs(case_world.engine, member_id) == ["3"]
    with Session(case_world.engine) as session:
        added = next(log for log in get_case_logs(session, member_id).logs if log.event == "ROADMAP_TASKS_ADDED")
    assert added.actor == "RIBBON"


def test_no_log_when_nothing_was_added_or_on_the_first_judgment(case_world):
    """가입 판단은 비교할 앞 판단이 없어 이 줄이 없다("폐업 순서를 만들었어요"는 NEXT_ACTION_DECIDED가 맡는다)."""

    member_id, case_id, created_id = case_world.sign_up()
    _judged(case_world.engine, created_id, ["intake", "dispose_stock"])
    submitted_id = case_world.add_history(case_id, "USER_INPUT", "DONE")
    _judged(case_world.engine, submitted_id, ["intake", "dispose_stock"])

    assert _added_logs(case_world.engine, member_id) == []


def test_the_log_skips_judgments_without_a_list(case_world):
    member_id, case_id, created_id = case_world.sign_up()
    _judged(case_world.engine, created_id, ["intake"])
    failed_id = case_world.add_history(case_id, "USER_INPUT", "FAILED")
    _judged(case_world.engine, failed_id, None)
    latest_id = case_world.add_history(case_id, "USER_INPUT", "DONE")
    _judged(case_world.engine, latest_id, ["intake", "before_photo"])

    assert _added_logs(case_world.engine, member_id) == ["1"]
