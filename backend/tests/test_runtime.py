"""Runtime wiring and per-run limits. No network or environment files."""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from app.agent import runtime as runtime_module
from app.agent.content_safety import ContentSafetyGuard, CrisisSupportRequired
from app.agent.llm import (
    LLMBudgetExceededError,
    LLMCallBudget,
    LLMConfig,
    ScopedCallBudget,
    StructuredLLMClient,
    call_budget_scope,
    current_call_budget,
)
from app.agent.run_scope import RunDeadline, current_deadline, run_deadline_scope
from app.agent.runtime import AgentRuntime, RuntimeLimits
from app.agent.schemas import CrisisSupportGuidance, RedactedInput


class Answer(BaseModel):
    ok: bool


class GraphStub:
    def __init__(self):
        self.calls = 0

    async def run(self, request):
        current_deadline().check()
        current_call_budget().consume()
        self.calls += 1
        return request


def test_each_run_gets_its_own_budget_and_respects_the_caller_deadline():
    async def run():
        graph = GraphStub()
        runtime = AgentRuntime(
            graph=graph, limits=RuntimeLimits(1, 60), clients=[], procedure_tool=None
        )
        # One call per run: a budget shared across runs would fail the second run.
        await runtime.run_planning("first")
        await runtime.run_planning("second")
        assert graph.calls == 2
        with run_deadline_scope(RunDeadline.after(0.000000001)):
            with pytest.raises(Exception) as error:
                await runtime.run_planning("late")
            assert error.value.code == "RUN_DEADLINE_EXCEEDED"
        assert graph.calls == 2

    asyncio.run(run())


def test_real_clients_share_one_run_budget():
    # 예산 연결이 빠진 클라이언트는 호출 횟수 제한 없이 돈다. 실제 클라이언트로 확인한다.
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok":true}'}}]}
        )

    config = LLMConfig(
        base_url="https://example.org/test", api_token="synthetic", model="test"
    )
    messages = [{"role": "user", "content": "test"}]

    async def run():
        shared = ScopedCallBudget()
        async with StructuredLLMClient(
            config, transport=httpx.MockTransport(handler), call_budget=shared
        ) as first, StructuredLLMClient(
            config, transport=httpx.MockTransport(handler), call_budget=shared
        ) as second:
            with call_budget_scope(LLMCallBudget(1)):
                await first.generate(Answer, messages)
                with pytest.raises(LLMBudgetExceededError) as error:
                    await second.generate(Answer, messages)
        assert error.value.code == "LOOP_LIMIT_REACHED"
        assert len(requests) == 1  # 두 번째는 AI를 부르기 전에 막힌다

    asyncio.run(run())


def test_build_runtime_gives_each_component_its_configured_client(monkeypatch):
    async def run():
        config = LLMConfig(
            base_url="https://example.org/test",
            api_token="synthetic",
            model="gpt-5.6-luna",
            reasoning_effort="xhigh",
        )
        clients = []
        clients_by_prefix = {}

        async def close():
            pass

        def client_factory(**kwargs):
            prefix = kwargs.get("env_prefix", "")
            client_config = (
                replace(config, model="gpt-5.6-sol")
                if prefix == "SUPERVISOR_"
                else config
            )
            client = SimpleNamespace(
                config=client_config, aclose=close, call_budget=kwargs.get("call_budget")
            )
            clients.append(client)
            clients_by_prefix[prefix] = client
            return client

        monkeypatch.setattr(
            runtime_module.StructuredLLMClient, "from_env", client_factory
        )
        monkeypatch.setattr(runtime_module.LangfuseTraceSink, "from_env", lambda: None)
        graph_components = {}

        def graph_factory(**kwargs):
            graph_components.update(kwargs)
            return GraphStub()

        monkeypatch.setattr(runtime_module, "AgentGraph", graph_factory)
        runtime = await runtime_module.build_runtime(
            known_procedure_steps=[],
            procedure_store=SimpleNamespace(snapshot_version="v", records=list),
            limits=RuntimeLimits(1, 60),
        )
        assert graph_components["info_agent"]._llm is clients_by_prefix["INFO_"]
        assert "support_agent" not in graph_components
        assert graph_components["supervisor"]._llm is clients_by_prefix["SUPERVISOR_"]
        assert graph_components["review_tool"]._client is clients_by_prefix[""]
        assert graph_components["content_safety"]._client is clients_by_prefix[""]
        assert (
            graph_components["review_tool"]._client
            is not clients_by_prefix["SUPERVISOR_"]
        )
        assert [client.config.model for client in clients] == [
            "gpt-5.6-luna",
            "gpt-5.6-sol",
            "gpt-5.6-luna",
        ]
        assert all(client.config.reasoning_effort == "xhigh" for client in clients)
        # 세 클라이언트가 모두 같은 실행 예산에 묶여 있어야 한다.
        assert isinstance(clients[0].call_budget, ScopedCallBudget)
        assert all(client.call_budget is clients[0].call_budget for client in clients)
        await runtime.aclose()

    asyncio.run(run())


def test_submission_safety_has_a_fresh_budget_and_obeys_the_outer_deadline():
    calls = []

    class Safety:
        async def check_submission(self, text, facts):
            current_deadline().check()
            current_call_budget().consume()
            calls.append((text, facts))

    async def run():
        runtime = AgentRuntime(
            graph=GraphStub(), limits=RuntimeLimits(1, 60), clients=[],
            procedure_tool=None, submission_safety=Safety(),
        )
        await runtime.check_submission("합성 검사 입력")
        submission = RedactedInput(
            input_event_id="synthetic-submission", source_type="USER_INPUT",
            redacted_text="합성 검사 입력", redactions=[],
            submitted_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
        )
        await runtime.check_submission(submission)
        with run_deadline_scope(RunDeadline.after(0.000000001)):
            with pytest.raises(Exception) as error:
                await runtime.check_submission("시간이 지난 입력")
            assert error.value.code == "RUN_DEADLINE_EXCEEDED"
        assert len(calls) == 2
        assert calls[1][0] is submission
        assert runtime._graph.calls == 0

    asyncio.run(run())


@pytest.mark.parametrize("limit,expired", [(2, False), (1, False), (2, True)])
def test_crisis_submission_checks_output_with_the_same_budget_and_deadline(limit, expired):
    calls = []

    def handler(request):
        calls.append(request)
        decision = "CRISIS_SUPPORT" if len(calls) == 1 else "ALLOW"
        return httpx.Response(200, json={"choices": [{
            "message": {"content": '{"decision":"' + decision + '"}'},
        }]})

    async def run():
        config = LLMConfig(base_url="https://example.org/test", api_token="synthetic", model="test")
        async with StructuredLLMClient(
            config, transport=httpx.MockTransport(handler), call_budget=ScopedCallBudget(),
        ) as client:
            runtime = AgentRuntime(
                graph=GraphStub(), limits=RuntimeLimits(limit, 60), clients=[],
                procedure_tool=None, submission_safety=ContentSafetyGuard(client),
            )
            expected = Exception if expired else LLMBudgetExceededError if limit == 1 else CrisisSupportRequired
            with run_deadline_scope(RunDeadline(0) if expired else None), pytest.raises(expected) as raised:
                await runtime.check_submission("지금 안전한 위기 도움을 받고 싶어요.")
            if expired:
                assert raised.value.code == "RUN_DEADLINE_EXCEEDED"
            elif limit == 2:
                assert raised.value.guidance == CrisisSupportGuidance()
            assert runtime._graph.calls == 0

    asyncio.run(run())
    assert len(calls) == (0 if expired else limit)
