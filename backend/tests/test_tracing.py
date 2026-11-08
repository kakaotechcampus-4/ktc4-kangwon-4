"""Real span lifetime, parentage and usage accounting without a remote backend."""

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.agent.llm import LLMUsage
from app.agent.tracing import (
    LangfuseTraceSink,
    TraceEvent,
    capture_usage,
    current_trace_id,
    observation_scope,
    record_provider_usage,
)


class Client:
    def __init__(self, trace_id=None):
        self.active = []
        self.observations = []
        self.trace_id = trace_id

    @contextmanager
    def start_as_current_observation(self, *, name, **options):
        observation = SimpleNamespace(
            name=name, parent=self.active[-1] if self.active else None,
            options=options, updates=[], ended=False, trace_id=self.trace_id,
        )
        observation.update = lambda **values: observation.updates.append(values)
        self.observations.append(observation)
        self.active.append(observation)
        try:
            yield observation
        finally:
            self.active.pop()
            observation.ended = True


def test_run_component_and_attempt_live_in_one_tree_without_duplicate_usage():
    client = Client()
    sink = LangfuseTraceSink(client)
    event = TraceEvent("run", "component", "INFO_AGENT", "SUCCESS", 12, 1,
                       prompt_tokens=10, completion_tokens=7)
    with observation_scope("RUN", sink=sink, as_type="span") as root:
        with observation_scope("INFO_AGENT", as_type="span") as component:
            with observation_scope("LLM", as_type="generation") as generation:
                assert not generation.ended
                record_provider_usage(LLMUsage(
                    "test", 10, 7, reasoning_tokens=3, cached_prompt_tokens=4,
                ))
            sink.emit(event)
        assert not root.ended
    assert all(item.ended for item in client.observations)
    assert component.parent is root and generation.parent is component
    usage = generation.updates[-1]["usage_details"]
    assert usage == {"input_cached": 4, "input": 6, "output_reasoning": 3, "output": 4}
    assert sum(usage.values()) == 17
    metadata = generation.updates[-1]["metadata"]
    assert metadata["component"] == "INFO_AGENT"
    assert metadata["prompt_tokens"] == 10 and metadata["completion_tokens"] == 7
    assert metadata["cached_prompt_tokens"] == 4 and metadata["reasoning_tokens"] == 3
    assert metadata["usage_complete"] is True
    assert all("usage_details" not in update for update in component.updates)


def test_missing_usage_remains_missing_and_business_exception_closes_span():
    client = Client()
    with (
        pytest.raises(ValueError, match="business"),
        observation_scope("LLM", sink=LangfuseTraceSink(client), as_type="generation"),
    ):
        record_provider_usage(LLMUsage("test", status="ERROR"))
        raise ValueError("business")
    generation = client.observations[0]
    assert generation.ended
    assert all("usage_details" not in update for update in generation.updates)
    assert generation.updates[0]["metadata"]["usage_complete"] is False
    assert generation.updates[0]["metadata"]["prompt_tokens"] is None
    assert generation.updates[-1] == {"level": "ERROR", "metadata": {"error_type": "ValueError"}}


def test_broken_sink_never_suppresses_business_result_or_exception():
    @contextmanager
    def broken(**_):
        raise RuntimeError("telemetry unavailable")
        yield

    sink = LangfuseTraceSink(SimpleNamespace(start_as_current_observation=broken))
    with observation_scope("RUN", sink=sink, as_type="span"):
        sink.emit(TraceEvent("run", "run", "RUN", "SUCCESS", 1, 1))
    with pytest.raises(KeyError), observation_scope("RUN", sink=sink, as_type="span"):
        raise KeyError("business")


def test_concurrent_captures_do_not_mix_or_leak_into_next_run():
    async def one(model):
        with capture_usage() as calls:
            await asyncio.sleep(0)
            record_provider_usage(LLMUsage(model, 1, 2))
            await asyncio.sleep(0)
        return calls

    async def run():
        first, second = await asyncio.gather(one("one"), one("two"))
        assert [item.model for item in first] == ["one"]
        assert [item.model for item in second] == ["two"]
        with capture_usage() as calls:
            assert calls == []

    asyncio.run(run())


@pytest.mark.parametrize("trace_id", [None, "external-label", "0" * 32, "ab" * 16])
def test_current_trace_id_accepts_only_an_actual_nonzero_sdk_id(trace_id):
    with observation_scope("RUN", sink=LangfuseTraceSink(Client(trace_id))):
        assert current_trace_id() == (trace_id if trace_id == "ab" * 16 else None)
    assert current_trace_id() is None


@pytest.mark.parametrize("sink_mode", ["available", "unconfigured", "start_failure", "id_failure"])
def test_graph_links_the_sdk_trace_without_changing_the_callers_input(sink_mode):
    import json
    from test_procedure_only_graph import graph_run_inputs

    graph, request, _, _, _ = graph_run_inputs("CASE_CREATED")
    request.trace_id = "external-label"
    before = request.model_dump_json()
    trace_id = "ab" * 16
    client = Client(trace_id)

    @contextmanager
    def broken_start(**_):
        raise RuntimeError("telemetry unavailable")
        yield

    class BrokenId:
        @property
        def trace_id(self):
            raise RuntimeError("telemetry unavailable")

        def update(self, **_):
            pass

    @contextmanager
    def broken_id(**_):
        yield BrokenId()

    if sink_mode == "unconfigured":
        graph._trace_sink = None
    else:
        if sink_mode != "available":
            client.start_as_current_observation = broken_start if sink_mode == "start_failure" else broken_id
        graph._trace_sink = LangfuseTraceSink(client)
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN"
    assert request.model_dump_json() == before
    expected = trace_id if sink_mode == "available" else "external-label"
    assert {source.meta.trace_id for source in outcome.review_subject.source_results} == {expected}
    assert request.trigger.input.redacted_text not in json.dumps([
        update for observation in client.observations for update in observation.updates
    ])


def test_concurrent_graph_runs_keep_their_own_sdk_trace_ids():
    from test_procedure_only_graph import graph_run_inputs

    async def one(trace_id):
        graph, request, _, _, _ = graph_run_inputs("CASE_CREATED")
        graph._trace_sink = LangfuseTraceSink(Client(trace_id))
        before = request.model_dump_json()
        outcome = await graph.run(request)
        assert outcome.outcome_type == "REVIEWED_PLAN"
        assert request.model_dump_json() == before
        return {source.meta.trace_id for source in outcome.review_subject.source_results}

    async def run():
        return await asyncio.gather(one("ab" * 16), one("cd" * 16))

    assert asyncio.run(run()) == [{"ab" * 16}, {"cd" * 16}]


def test_concurrent_roles_and_requested_model_remain_separate():
    client = Client()

    async def one(role):
        with observation_scope(role, sink=LangfuseTraceSink(client), as_type="span"):
            await asyncio.sleep(0)
            with observation_scope("LLM", as_type="generation") as generation:
                record_provider_usage(LLMUsage(
                    "reported", 10, 5, requested_model="requested", reasoning_effort="high",
                ))
            await asyncio.sleep(0)
            update = generation.updates[-1]
            assert update["model"] == "reported"
            assert update["metadata"]["requested_model"] == "requested"
            assert update["metadata"]["component"] == role
            assert update["model_parameters"] == {"reasoning_effort": "high"}

    async def run():
        await asyncio.gather(one("INFO_AGENT"), one("REVIEW_TOOL"))

    asyncio.run(run())


@pytest.mark.parametrize("broken_sink", [False, True])
@pytest.mark.parametrize("reject_review", [False, True])
def test_review_trace_preserves_outcome_and_records_bounded_metadata_without_private_text(broken_sink, reject_review):
    from test_procedure_only_graph import graph_run_inputs

    from app.agent.schemas import ReviewResult

    graph, request, _, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    client = Client()
    private = "PRIVATE_REVIEW_REASON_MUST_NOT_BE_TRACED"

    class BrokenSink:
        def emit(self, event):
            raise RuntimeError(private)

    graph._trace_sink = BrokenSink() if broken_sink else LangfuseTraceSink(client)

    async def reject(subject):
        return ReviewResult(
            reviewed_subject_id=subject.review_subject_id, reviewed_subject_digest=subject.subject_digest,
            verdict="REVISE", issues=[{
                "issue_code": "CASE_MISMATCH", "category": "FACTUALITY", "severity": "BLOCKING",
                "target_component": "SUPERVISOR", "target_call_id": None,
                "target_path": "/supervisor_draft/decision/blockers/0/description",
                "reason_summary": private, "evidence_refs": [],
            } for _ in range(25)], missing_evidence=[], recommended_rework_targets=["SUPERVISOR"],
            resolution_reason=private,
        )

    reviewer = AsyncMock()
    reviewer.review.side_effect = reject
    if reject_review:
        graph._review_tool = reviewer
    before = request.model_dump_json()
    outcome = asyncio.run(graph.run(request))
    assert request.model_dump_json() == before
    if not reject_review:
        assert outcome.outcome_type == "REVIEWED_PLAN"
        if not broken_sink:
            run = next(item for item in client.observations if item.name == "RUN")
            assert run.updates[-1]["metadata"]["case_id"] == request.case_snapshot.case_id
        return
    assert outcome.outcome_type == "SAFE_FAILURE"
    assert outcome.failure_code == "REVIEW_RETRY_EXHAUSTED"
    assert reviewer.review.await_count == graph._supervisor._llm.calls == 1
    if broken_sink:
        return

    review = next(item for item in client.observations if item.name == "REVIEW_TOOL")
    metadata = review.updates[-1]["metadata"]
    assert metadata["case_id"] == request.case_snapshot.case_id
    assert metadata["review_verdict"] == "REVISE"
    assert metadata["draft_action_code"] == "CONFIRM_TAX_CLOSURE_REQUIREMENTS"
    assert metadata["recommended_rework_targets"] == ("SUPERVISOR",)
    assert metadata["review_issue_count"] == 25
    assert len(metadata["review_issues"]) == 20
    assert all(issue == {
        "issue_code": "CASE_MISMATCH", "target_path": "/supervisor_draft/decision/blockers/0/description",
        "severity": "BLOCKING", "target_component": "SUPERVISOR",
    } for issue in metadata["review_issues"])
    run = next(item for item in client.observations if item.name == "RUN")
    assert run.updates[-1]["metadata"]["case_id"] == request.case_snapshot.case_id
    assert run.updates[-1]["metadata"]["review_count"] == 1
    assert run.updates[-1]["metadata"]["rework_count"] == 0
    recorded = json.dumps([(item.options, item.updates) for item in client.observations])
    assert private not in recorded
    assert request.trigger.input.redacted_text not in recorded
    assert all("input" not in item.options and "output" not in item.options for item in client.observations)
