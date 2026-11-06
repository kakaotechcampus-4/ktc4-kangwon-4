"""로드맵 조회(GET /cases/roadmap)의 N+1을 고치기 전/후로 잰다. 모델은 부르지 않는다.

같은 DB에서 전/후를 번갈아 돌려 그 순간의 컴퓨터 상태가 양쪽에 똑같이 들어가게 한다.
기본으로는 돌지 않는다. MySQL 컨테이너에 데이터를 채우느라 몇 분 걸려서 매 CI에 얹을 값은 아니다.

    PERF=1 ./.venv/bin/python -m pytest tests/test_roadmap_query_perf.py -s
"""

import os
import statistics
import time

import httpx
import pytest
from sqlalchemy import event
from sqlmodel import Session, select

from app.be.crud import procedure_step as procedure_step_crud
from app.be.models.procedure_step import CaseProcedureStep
from app.be.services import roadmap as roadmap_service
from case_world import case_engine, case_world  # noqa: F401

RUNS = 200

pytestmark = pytest.mark.skipif(not os.getenv("PERF"), reason="성능 측정. PERF=1 일 때만 돈다")


def _before_fix(session: Session, case_id: int) -> list[CaseProcedureStep]:
    """고치기 전 그대로. 절차 이름은 읽을 때 하나씩 따로 가져온다."""

    return session.exec(select(CaseProcedureStep).where(CaseProcedureStep.case_id == case_id)).all()


@pytest.fixture
def no_model_calls(monkeypatch):
    """모델 호출은 모두 httpx로 나간다(agent/llm.py). 보내는 순간 멈춘다."""

    def refuse(*_args, **_kwargs):
        raise RuntimeError("측정 중 외부 HTTP(모델) 호출")

    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)


@pytest.mark.parametrize("other_owners, histories", [(0, 4), (300, 20)])
def test_roadmap_before_and_after(no_model_calls, case_world, monkeypatch, other_owners, histories):
    for _ in range(other_owners):
        _, case_id, _ = case_world.sign_up()
        for _ in range(histories):
            case_world.add_history(case_id, "USER_INPUT", "DONE")
    member_id, case_id, _ = case_world.sign_up()
    for _ in range(histories):
        case_world.add_history(case_id, "USER_INPUT", "DONE")

    after_fix = procedure_step_crud.get_case_procedure_steps_by_case_id
    count = {"n": 0}

    def _count(*_args):
        count["n"] += 1

    event.listen(case_world.engine, "before_cursor_execute", _count)
    measured = {"before": ([], []), "after": ([], [])}
    try:
        for i in range(RUNS * 2):
            name = "before" if i % 2 == 0 else "after"
            monkeypatch.setattr(
                procedure_step_crud, "get_case_procedure_steps_by_case_id",
                _before_fix if name == "before" else after_fix,
            )
            count["n"] = 0
            with Session(case_world.engine) as session:
                start = time.perf_counter()
                roadmap_service.get_case_roadmap(session, member_id)
                measured[name][0].append((time.perf_counter() - start) * 1000)
            measured[name][1].append(count["n"])
    finally:
        event.remove(case_world.engine, "before_cursor_execute", _count)

    print(f"\n다른 사장님 {other_owners}명, 사장님마다 판단 기록 {histories + 1}개, 번갈아 {RUNS}번씩")
    medians = {}
    for name, (times, queries) in measured.items():
        times = times[10:]  # 처음 몇 번은 연결·캐시를 준비하는 시간이라 뺀다
        medians[name] = statistics.median(times)
        p95 = sorted(times)[int(len(times) * 0.95)]
        print(f"  {name:6s} 쿼리 {max(queries):2d}회  중간값 {medians[name]:5.1f}ms  p95 {p95:5.1f}ms")
    print(f"  중간값 기준 {100 * (1 - medians['after'] / medians['before']):.0f}% 단축")
