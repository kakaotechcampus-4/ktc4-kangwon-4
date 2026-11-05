"""판단이 도는 동안 DB 커넥션을 쥐고 있어 다른 요청이 막히는지, 실제 판단 경로로 잰다.

모델은 부르지 않는다. run_case_planning 자리에 "50초 걸리는 무언가"를 끼운다
(50초는 #189~#191 뒤 실제 판단 시간).

기본으로는 돌지 않는다. MySQL 컨테이너를 띄우고 판단마다 50초를 기다려서 4분쯤 걸리는데,
매 CI에 얹을 값은 아니다. 다시 재고 싶을 때만 켠다.

    PERF=1 ./.venv/bin/python -m pytest tests/test_pool_capacity.py -s
"""

import asyncio
import os
import time

import pytest
from sqlmodel import Session

from app.be.services import case as case_service
from app.be.services import judgment as judgment_service
from tests.case_world import CaseWorld, case_engine, case_world  # noqa: F401

MODEL_SECONDS = 50.0

pytestmark = pytest.mark.skipif(
    not os.getenv("PERF"), reason="성능 측정. PERF=1 일 때만 돈다"
)


@pytest.fixture
def judging(case_engine, monkeypatch):
    """판단 경로를 그대로 쓰되, 모델 호출만 기다림으로 바꾼다."""

    monkeypatch.setattr(judgment_service, "get_engine", lambda: case_engine)

    async def slow_model(*args, **kwargs):
        await asyncio.sleep(MODEL_SECONDS)
        raise RuntimeError("측정용: 여기서 멈춘다")

    monkeypatch.setattr(judgment_service, "run_case_planning", slow_model)
    return case_engine


@pytest.mark.parametrize("concurrent", [10, 15, 20, 30, 40])
def test_other_requests_while_judgments_run(judging, case_world, concurrent):  # noqa: F811
    engine = judging
    members = []
    histories = []
    for _ in range(concurrent):
        member_id, case_id, _ = case_world.sign_up()
        members.append(member_id)
        histories.append(case_world.add_history(case_id, "USER_INPUT", "PENDING"))
    watcher = case_world.sign_up()[0]  # 판단을 돌리지 않는, 그냥 화면을 보는 사장님

    async def main():
        tasks = [
            asyncio.create_task(judgment_service.run_judgment_in_background(h))
            for h in histories
        ]
        await asyncio.sleep(5.0)  # 판단들이 자리를 잡을 시간
        held = engine.pool.checkedout()

        def read_screen():
            with Session(engine) as session:
                case_service.get_case(session, watcher)

        start = time.perf_counter()
        try:
            await asyncio.wait_for(asyncio.to_thread(read_screen), timeout=40)
            answer = f"{(time.perf_counter() - start) * 1000:8.1f}ms"
        except asyncio.TimeoutError:
            answer = "40초 넘게 막힘"
        except Exception as error:
            answer = f"실패 {type(error).__name__}"

        await asyncio.gather(*tasks, return_exceptions=True)
        return held, answer

    held, answer = asyncio.run(main())
    print(f"RESULT 판단 {concurrent:2d}건 | 쥔 커넥션 {held:2d}개 | 그냥 보던 사장님의 GET /cases: {answer}")
