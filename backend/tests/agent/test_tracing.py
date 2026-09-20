from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agent.llm import LLMUsage
from app.agent.tracing import LangfuseTraceSink, TraceEvent, UsageAccumulator


def event(**overrides: Any) -> TraceEvent:
    defaults: dict[str, Any] = {
        "run_id": "run-1",
        "call_id": "call-1",
        "component": "SUPERVISOR",
        "status": "SUCCESS",
        "latency_ms": 120,
        "attempt": 1,
    }
    defaults.update(overrides)
    return TraceEvent(**defaults)


class FakeObservation:
    def __init__(self, recorder: dict[str, Any]) -> None:
        self._recorder = recorder

    def update(self, **kwargs: Any) -> None:
        self._recorder["update"] = kwargs

    def end(self) -> None:
        self._recorder["ended"] = True


class FakeLangfuse:
    def __init__(self) -> None:
        self.started: dict[str, Any] = {}
        self.observation: dict[str, Any] = {}
        self.flushed = False

    def start_observation(self, **kwargs: Any) -> FakeObservation:
        self.started = kwargs
        return FakeObservation(self.observation)

    def flush(self) -> None:
        self.flushed = True


def test_accumulator_sums_tokens_until_drained() -> None:
    usage = UsageAccumulator()

    usage.record(LLMUsage(model="m", prompt_tokens=10, completion_tokens=2))
    usage.record(LLMUsage(model="m", prompt_tokens=5, completion_tokens=3))

    assert usage.drain() == ("m", 15, 5)
    assert usage.drain() == (None, None, None)


def test_accumulator_tolerates_providers_that_omit_tokens() -> None:
    usage = UsageAccumulator()

    usage.record(LLMUsage(model="m"))

    assert usage.drain() == ("m", None, None)


def test_sink_sends_only_metadata_and_usage() -> None:
    client = FakeLangfuse()
    sink = LangfuseTraceSink(client)

    sink.emit(event(model="gpt-5.6-luna", prompt_tokens=100, completion_tokens=20))

    assert client.started["as_type"] == "generation"
    assert client.started["model"] == "gpt-5.6-luna"
    assert client.observation["update"]["usage_details"] == {
        "input_tokens": 100,
        "output_tokens": 20,
    }
    metadata = client.observation["update"]["metadata"]
    assert metadata["run_id"] == "run-1"
    assert metadata["latency_ms"] == 120
    # Prompt, evidence and user text must never reach the observability backend.
    sent = repr(client.started) + repr(client.observation)
    assert "input" not in client.observation["update"]
    assert "output" not in client.observation["update"]
    assert "prompt" not in sent.lower().replace("prompt_tokens", "")
    assert client.observation["ended"] is True


def test_sink_omits_usage_when_provider_reported_none() -> None:
    client = FakeLangfuse()

    LangfuseTraceSink(client).emit(event(model=None))

    assert "usage_details" not in client.observation["update"]


def test_sink_swallows_backend_failures() -> None:
    class ExplodingClient:
        def start_observation(self, **_: Any) -> Any:
            raise RuntimeError("langfuse unreachable")

        def flush(self) -> None:
            raise RuntimeError("langfuse unreachable")

    sink = LangfuseTraceSink(ExplodingClient())

    sink.emit(event())
    sink.flush()


def test_sink_is_disabled_without_credentials(tmp_path: Path) -> None:
    empty = tmp_path / ".env"
    empty.write_text("", encoding="utf-8")

    assert LangfuseTraceSink.from_env(environ={}, env_file=empty) is None
    assert (
        LangfuseTraceSink.from_env(
            environ={"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "  "},
            env_file=empty,
        )
        is None
    )


def test_sink_reads_credentials_from_env_file(tmp_path: Path) -> None:
    """The CLI does not load .env into os.environ, so the sink must read it."""

    env_file = tmp_path / ".env"
    env_file.write_text(
        "LANGFUSE_PUBLIC_KEY=pk-lf-file\n"
        "LANGFUSE_SECRET_KEY=sk-lf-file\n"
        "LANGFUSE_BASE_URL=https://cloud.langfuse.test\n",
        encoding="utf-8",
    )
    captured: dict[str, Any] = {}

    class FakeLangfuseModule:
        def __call__(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return FakeLangfuse()

    import app.agent.tracing as tracing_module

    original = tracing_module.LangfuseTraceSink.from_env.__func__

    def build(**kwargs: Any) -> Any:
        return original(tracing_module.LangfuseTraceSink, **kwargs)

    import langfuse

    real_client = langfuse.Langfuse
    langfuse.Langfuse = FakeLangfuseModule()
    try:
        sink = build(environ={}, env_file=env_file)
    finally:
        langfuse.Langfuse = real_client

    assert sink is not None
    assert captured["public_key"] == "pk-lf-file"
    assert captured["secret_key"] == "sk-lf-file"
    assert captured["base_url"] == "https://cloud.langfuse.test"
