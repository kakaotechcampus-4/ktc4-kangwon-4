"""AI에 넘길 Case 상태를 만들 때 쿼리 수가 절차 수에 따라 늘지 않는지(N+1). 진짜 MySQL이 필요하다(Docker).

판단(build_case_snapshot)과 로드맵(build_roadmap_snapshot)이 같은 읽기(_snapshot_fields)를 쓴다.
절차마다 이름(procedure_step.step_code)을 읽는데, 절차를 가져올 때 이름을 같이 가져오지 않으면
절차 하나에 쿼리가 하나씩 더 나간다. 모델은 부르지 않는다.
"""

from sqlalchemy import delete, event
from sqlmodel import Session, select

from app.be.models.procedure_step import CaseProcedureStep
from app.be.services.case_snapshot import build_case_snapshot
from case_world import case_engine, case_world  # noqa: F401


def _keep_steps(engine, case_id: int, keep: int) -> None:
    with Session(engine) as session:
        steps = session.exec(select(CaseProcedureStep).where(CaseProcedureStep.case_id == case_id)).all()
        session.exec(delete(CaseProcedureStep).where(
            CaseProcedureStep.id.in_([step.id for step in steps[keep:]])
        ))
        session.commit()


def _queries_to_build(engine, case_id: int) -> tuple[int, int]:
    """Case 상태를 한 번 만드는 동안 DB로 보낸 쿼리 수와 그 Case의 절차 수.

    앞서 읽은 값이 세션에 남아 있으면 쿼리 없이 꺼내 쓰므로 새 세션에서 잰다.
    """

    count = 0

    def _count(*_args):
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        with Session(engine) as session:
            snapshot = build_case_snapshot(session, case_id)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    return count, len(snapshot.procedure_progress)


def test_query_count_does_not_grow_with_procedure_steps(case_world):
    _, all_steps_case, _ = case_world.sign_up()
    _, few_steps_case, _ = case_world.sign_up()
    _keep_steps(case_world.engine, few_steps_case, keep=2)

    many, many_steps = _queries_to_build(case_world.engine, all_steps_case)
    few, few_steps = _queries_to_build(case_world.engine, few_steps_case)

    # 절차 수가 정말 다른 두 Case를 비교하는지 먼저 본다. 같으면 아래 검사는 아무것도 지키지 않는다.
    assert (many_steps, few_steps) == (8, 2)
    assert many == few
