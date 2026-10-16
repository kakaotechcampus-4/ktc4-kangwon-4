"""Runtime wiring and per-run limits. No network or environment files."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.agent import runtime as runtime_module
from app.agent.llm import LLMConfig, current_call_budget
from app.agent.run_scope import RunDeadline, current_deadline, run_deadline_scope
from app.agent.runtime import AgentRuntime, RuntimeLimits
from app.agent.support_agent import ReviewedSupportCatalog


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
            client = SimpleNamespace(config=client_config, aclose=close)
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
            support_catalog=ReviewedSupportCatalog(
                catalog_version="synthetic", programs=(), evidence_records=()
            ),
            procedure_store=SimpleNamespace(snapshot_version="v", records=list),
            limits=RuntimeLimits(1, 60),
        )
        assert graph_components["info_agent"]._llm is clients_by_prefix["INFO_"]
        assert graph_components["support_agent"]._llm is clients_by_prefix[""]
        assert graph_components["supervisor"]._llm is clients_by_prefix["SUPERVISOR_"]
        assert graph_components["review_tool"]._client is clients_by_prefix[""]
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
        await runtime.aclose()

    asyncio.run(run())
