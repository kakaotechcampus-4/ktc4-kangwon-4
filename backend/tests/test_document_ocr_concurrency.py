"""긴 스캔 OCR의 동시 실행·순서·중단 경계를 실제 모델 없이 확인한다."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace

import pytest

from app.agent.document_tool import preparation
from app.agent.document_tool.documents import DocumentError, DocumentService
from app.agent.document_tool.models import OCRTranscript
from app.agent.llm import (
    LLMBudgetExceededError, LLMCallBudget, LLMUsage, call_budget_scope, current_call_budget,
)
from app.agent.run_scope import RunDeadline, RunDeadlineExceededError, current_deadline, run_deadline_scope
from app.agent.tracing import LangfuseTraceSink, capture_usage, observation_scope, record_provider_usage


def service_for(tmp_path, monkeypatch, reviewer, count):
    async def render(function, content):
        assert function is preparation.render_images and content == b"masked-pdf"
        return [f"page{i}" for i in range(count)]

    monkeypatch.setattr(preparation, "run_pdf", render)
    return DocumentService(tmp_path, object(), reviewer=reviewer, submission_policy="RRN_BACK_ONLY",
                           private_values=("합성비공개값",))


def page_from(messages):
    return messages[1]["content"][0]["image_url"]["url"].split(",", 1)[1]


class TraceClient:
    def __init__(self):
        self.active = ContextVar("document_test_observation", default=None)
        self.observations = []

    @contextmanager
    def start_as_current_observation(self, *, name, **_):
        row = SimpleNamespace(name=name, parent=self.active.get(), ended=False, updates=[])
        row.update = lambda **values: row.updates.append(values)
        self.observations.append(row)
        token = self.active.set(row)
        try:
            yield row
        finally:
            self.active.reset(token)
            row.ended = True


@pytest.mark.parametrize("count", [1, 6])
def test_ocr_overlaps_at_most_two_pages_keeps_order_and_run_context(tmp_path, monkeypatch, count):
    async def run():
        release_first, others_done = asyncio.Event(), asyncio.Event()
        budget, deadline = LLMCallBudget(count), RunDeadline.after(10)
        active, peak, finished = 0, 0, []

        class Reviewer:
            async def generate(self, model, messages, **_):
                nonlocal active, peak
                assert model is OCRTranscript
                assert current_call_budget() is budget and current_deadline() is deadline
                deadline.check()
                budget.consume()
                page = page_from(messages)
                active += 1
                peak = max(peak, active)
                try:
                    with observation_scope("LLM", as_type="generation"):
                        if count > 1 and page == "page0":
                            await release_first.wait()
                        await asyncio.sleep(0)
                        record_provider_usage(LLMUsage("synthetic", 1, 1))
                    finished.append(page)
                    if len(finished) == count - 1:
                        others_done.set()
                    return OCRTranscript(text=f"{page} 010-1234-5678 합성비공개값")
                finally:
                    active -= 1

        service = service_for(tmp_path, monkeypatch, Reviewer(), count)
        trace = TraceClient()
        with call_budget_scope(budget), run_deadline_scope(deadline), capture_usage() as calls:
            with observation_scope("DOCUMENT_TOOL", sink=LangfuseTraceSink(trace)) as root:
                task = asyncio.create_task(service._read_image_text(b"masked-pdf"))
                try:
                    if count > 1:
                        # 첫 페이지가 느려도 다음 페이지를 읽되, 동시 호출 수는 두 개를 넘지 않는다.
                        await asyncio.wait_for(others_done.wait(), 1)
                        assert finished == [f"page{i}" for i in range(1, count)]
                    release_first.set()
                    pages = await asyncio.wait_for(task, 1)
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        assert peak == min(2, count) and active == 0 and budget.spent == count
        assert len(calls) == count
        assert [page.split()[0] for page in pages] == [f"page{i}" for i in range(count)]
        assert all("010-1234-5678" not in page and "합성비공개값" not in page for page in pages)
        ocr = [row for row in trace.observations if row.name == "DOCUMENT_VISION_OCR"]
        assert len(ocr) == count and all(row.parent is root for row in ocr)
        assert all(row.ended for row in trace.observations)

    asyncio.run(run())


def test_one_page_failure_cancels_other_call_and_does_not_start_pending_pages(tmp_path, monkeypatch):
    async def run():
        second_started, hold = asyncio.Event(), asyncio.Event()
        started, cancelled, workers = [], [], set()
        failure = DocumentError("합성 판독 실패")

        class Reviewer:
            async def generate(self, model, messages, **_):
                page = page_from(messages)
                started.append(page)
                workers.add(asyncio.current_task())
                if page == "page0":
                    await asyncio.wait_for(second_started.wait(), 1)
                    raise failure
                second_started.set()
                try:
                    await hold.wait()
                except asyncio.CancelledError:
                    cancelled.append(page)
                    raise

        service = service_for(tmp_path, monkeypatch, Reviewer(), 6)
        with pytest.raises(DocumentError) as caught:
            await asyncio.wait_for(service._read_image_text(b"masked-pdf"), 1)
        assert caught.value is failure
        assert started == ["page0", "page1"] and cancelled == ["page1"]
        assert all(worker.done() for worker in workers)

    asyncio.run(run())


def test_cancelling_document_waits_for_both_inflight_pages(tmp_path, monkeypatch):
    async def run():
        both_started, hold = asyncio.Event(), asyncio.Event()
        started, cancelled, workers = [], [], set()

        class Reviewer:
            async def generate(self, model, messages, **_):
                page = page_from(messages)
                started.append(page)
                workers.add(asyncio.current_task())
                if len(started) == 2:
                    both_started.set()
                try:
                    await hold.wait()
                except asyncio.CancelledError:
                    cancelled.append(page)
                    raise

        service = service_for(tmp_path, monkeypatch, Reviewer(), 6)
        task = asyncio.create_task(service._read_image_text(b"masked-pdf"))
        await asyncio.wait_for(both_started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert started == ["page0", "page1"] and sorted(cancelled) == started
        assert all(worker.done() for worker in workers)

    asyncio.run(run())


@pytest.mark.parametrize("expired", [False, True])
def test_parallel_pages_share_call_limit_and_stop_at_expired_deadline(tmp_path, monkeypatch, expired):
    async def run():
        budget = LLMCallBudget(2)
        deadline = RunDeadline(0) if expired else RunDeadline.after(10)

        class Reviewer:
            async def generate(self, model, messages, **_):
                assert current_call_budget() is budget and current_deadline() is deadline
                deadline.check()
                budget.consume()
                await asyncio.sleep(0)
                return OCRTranscript(text=page_from(messages))

        service = service_for(tmp_path, monkeypatch, Reviewer(), 6)
        with call_budget_scope(budget), run_deadline_scope(deadline):
            with pytest.raises(RunDeadlineExceededError if expired else LLMBudgetExceededError):
                await service._read_image_text(b"masked-pdf")
        assert budget.spent == (0 if expired else 2)

    asyncio.run(run())
