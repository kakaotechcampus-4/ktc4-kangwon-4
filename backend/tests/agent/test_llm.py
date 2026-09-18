from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agent.llm import (
    LLMBudgetExceededError,
    LLMCallBudget,
    LLMConfig,
    LLMConfigurationError,
    LLMRequestError,
    LLMResponseError,
    LLMUsage,
    StructuredLLMClient,
    sanitize_json_schema,
)


class NestedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    labels: set[str] = Field(default_factory=set)
    optional_note: str | None = None


class StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    answer: str
    count: int


class FirstTarget(BaseModel):
    kind: Literal["FIRST"]
    value: str


class SecondTarget(BaseModel):
    kind: Literal["SECOND"]
    count: int


class DiscriminatedOutput(BaseModel):
    target: Annotated[FirstTarget | SecondTarget, Field(discriminator="kind")]


def _config(
    *,
    model: str = "openai/gpt-4.1-mini",
    max_retries: int = 2,
    reasoning_effort: str | None = "low",
    max_response_bytes: int = 1_000_000,
    timeout_seconds: float = 45.0,
    retry_backoff_seconds: float = 0,
) -> LLMConfig:
    return LLMConfig(
        base_url="https://proxy.example.test/v1/",
        api_token="top-secret-token",
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        max_response_bytes=max_response_bytes,
    )


def _chat_response(content: Any) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "fake-completion",
            "choices": [{"message": {"role": "assistant", "content": content}}],
        },
    )


class ChunkedResponseStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.started = False
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.started = True
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class FailingResponseStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"choices":['
        raise httpx.ReadError("private upstream stream detail")

    async def aclose(self) -> None:
        self.closed = True


def _assert_keyword_absent(value: Any, keyword: str) -> None:
    if isinstance(value, dict):
        assert keyword not in value
        for child in value.values():
            _assert_keyword_absent(child, keyword)
    elif isinstance(value, list):
        for child in value:
            _assert_keyword_absent(child, keyword)


def test_config_loads_root_style_env_with_process_precedence_and_redacted_repr(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CHAT_PROXY_URL=https://file-proxy.example.test/v1\n"
        "PROXY_TOKEN=file-secret-token\n"
        "OPENAI_MODEL=file-model\n"
        "AGENT_LLM_MAX_RETRIES=1\n",
        encoding="utf-8",
    )

    config = LLMConfig.from_env(
        env_file=env_file,
        environ={"OPENAI_MODEL": "process-model"},
    )

    assert config.base_url == "https://file-proxy.example.test/v1"
    assert config.model == "process-model"
    assert config.max_retries == 1
    assert "file-secret-token" not in repr(config)


def test_config_reports_only_missing_setting_names(tmp_path: Path) -> None:
    with pytest.raises(LLMConfigurationError) as caught:
        LLMConfig.from_env(env_file=tmp_path / "missing.env", environ={})

    message = str(caught.value)
    assert "CHAT_PROXY_URL" in message
    assert "PROXY_TOKEN" in message
    assert "OPENAI_MODEL" in message
    assert caught.value.retryable is False


def test_config_requires_tls_for_non_loopback_proxy() -> None:
    with pytest.raises(LLMConfigurationError, match="must use HTTPS"):
        LLMConfig(
            base_url="http://proxy.example.test/v1",
            api_token="test-token",
            model="openai/gpt-4.1-mini",
        )


def test_config_allows_plain_http_only_for_loopback_development() -> None:
    config = LLMConfig(
        base_url="http://127.0.0.1:8080/v1",
        api_token="test-token",
        model="openai/gpt-4.1-mini",
    )

    assert config.base_url == "http://127.0.0.1:8080/v1"


@pytest.mark.parametrize(
    ("setting_name", "raw_value"),
    [
        ("AGENT_LLM_TIMEOUT_SECONDS", "nan"),
        ("AGENT_LLM_TIMEOUT_SECONDS", "inf"),
        ("AGENT_LLM_TIMEOUT_SECONDS", "-inf"),
        ("AGENT_LLM_RETRY_BACKOFF_SECONDS", "nan"),
        ("AGENT_LLM_RETRY_BACKOFF_SECONDS", "inf"),
        ("AGENT_LLM_RETRY_BACKOFF_SECONDS", "-inf"),
    ],
)
def test_config_rejects_non_finite_environment_values(
    tmp_path: Path,
    setting_name: str,
    raw_value: str,
) -> None:
    environment = {
        "CHAT_PROXY_URL": "https://proxy.example.test/v1",
        "PROXY_TOKEN": "top-secret-token",
        "OPENAI_MODEL": "openai/gpt-4.1-mini",
        setting_name: raw_value,
    }

    with pytest.raises(LLMConfigurationError, match="finite"):
        LLMConfig.from_env(
            env_file=tmp_path / "missing.env",
            environ=environment,
        )


def test_config_rejects_backoff_above_operational_limit() -> None:
    with pytest.raises(LLMConfigurationError, match="between 0 and 60"):
        _config(retry_backoff_seconds=61)


@pytest.mark.parametrize("max_retries", [True, 1.5])
def test_config_rejects_non_integer_retry_count(max_retries: Any) -> None:
    with pytest.raises(LLMConfigurationError, match="between 0 and 4"):
        _config(max_retries=max_retries)


def test_config_loads_bounded_response_limit_from_environment(tmp_path: Path) -> None:
    config = LLMConfig.from_env(
        env_file=tmp_path / "missing.env",
        environ={
            "CHAT_PROXY_URL": "https://proxy.example.test/v1",
            "PROXY_TOKEN": "top-secret-token",
            "OPENAI_MODEL": "openai/gpt-4.1-mini",
            "AGENT_LLM_MAX_RESPONSE_BYTES": "2048",
        },
    )

    assert config.max_response_bytes == 2_048
    assert _config().max_response_bytes == 1_000_000


@pytest.mark.parametrize("raw_value", ["1023", "10000001", "2048.5"])
def test_config_rejects_invalid_response_limit_environment_values(
    tmp_path: Path,
    raw_value: str,
) -> None:
    environment = {
        "CHAT_PROXY_URL": "https://proxy.example.test/v1",
        "PROXY_TOKEN": "top-secret-token",
        "OPENAI_MODEL": "openai/gpt-4.1-mini",
        "AGENT_LLM_MAX_RESPONSE_BYTES": raw_value,
    }

    with pytest.raises(LLMConfigurationError):
        LLMConfig.from_env(
            env_file=tmp_path / "missing.env",
            environ=environment,
        )


def test_schema_sanitizer_removes_unsupported_keywords_without_mutating_source() -> (
    None
):
    original = NestedOutput.model_json_schema(mode="validation")
    projected = sanitize_json_schema(original)

    _assert_keyword_absent(projected, "uniqueItems")
    _assert_keyword_absent(projected, "default")
    assert "uniqueItems" in json.dumps(original)
    assert set(projected["required"]) == {"labels", "optional_note"}
    assert projected["additionalProperties"] is False


def test_schema_sanitizer_removes_local_extension_metadata() -> None:
    schema = {
        "type": "object",
        "properties": {
            "runtime_id": {
                "type": "string",
                "format": "uuid",
                "x-runtime-injected": True,
            }
        },
        "x-local-contract": "not-for-provider",
    }

    projected = sanitize_json_schema(schema)

    assert "x-local-contract" not in projected
    assert "x-runtime-injected" not in projected["properties"]["runtime_id"]
    assert projected["properties"]["runtime_id"]["format"] == "uuid"


def test_schema_sanitizer_projects_discriminated_one_of_to_supported_any_of() -> None:
    original = DiscriminatedOutput.model_json_schema(mode="validation")
    projected = sanitize_json_schema(original)

    _assert_keyword_absent(projected, "oneOf")
    assert "anyOf" in projected["properties"]["target"]
    assert "discriminator" not in projected["properties"]["target"]


def test_generate_sends_strict_schema_and_omits_reasoning_for_gpt_4_1() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["accept_encoding"] = request.headers["Accept-Encoding"]
        captured["timeout"] = request.extensions["timeout"]
        captured["payload"] = json.loads(request.content)
        return _chat_response('{"answer":"확인 필요","count":1}')

    async def run() -> StrictOutput:
        client = StructuredLLMClient(
            _config(),
            transport=httpx.MockTransport(handler),
        )
        try:
            return await client.generate(
                StrictOutput,
                [{"role": "user", "content": "redacted input"}],
            )
        finally:
            await client.aclose()

    result = asyncio.run(run())

    assert result == StrictOutput(answer="확인 필요", count=1)
    assert captured["url"] == "https://proxy.example.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer top-secret-token"
    assert captured["accept_encoding"] == "identity"
    assert set(captured["timeout"].values()) == {45.0}
    payload = captured["payload"]
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert "reasoning_effort" not in payload


def test_generate_includes_reasoning_effort_only_for_reasoning_model() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _chat_response('{"answer":"ok","count":1}')

    async def run() -> None:
        client = StructuredLLMClient(
            _config(model="openai/gpt-5.2", reasoning_effort="low"),
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "system", "content": "return JSON"}],
            )
        finally:
            await client.aclose()

    asyncio.run(run())
    assert captured["reasoning_effort"] == "low"


def test_generate_rejects_non_integer_per_call_retry_count() -> None:
    async def run() -> None:
        client = StructuredLLMClient(
            _config(),
            transport=httpx.MockTransport(lambda _: _chat_response("{}")),
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "user", "content": "redacted"}],
                max_retries=1.5,  # type: ignore[arg-type]
            )
        finally:
            await client.aclose()

    with pytest.raises(ValueError, match="between 0 and 4"):
        asyncio.run(run())


def test_generate_retries_transient_http_and_schema_failures() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                503,
                json={"error": {"message": "private-input top-secret-token"}},
            )
        if calls == 2:
            return _chat_response("not-json")
        return _chat_response('{"answer":"ok","count":2}')

    async def run() -> StrictOutput:
        client = StructuredLLMClient(
            _config(max_retries=2),
            transport=httpx.MockTransport(handler),
        )
        try:
            return await client.complete_structured(
                [{"role": "user", "content": "redacted"}],
                StrictOutput,
            )
        finally:
            await client.aclose()

    assert asyncio.run(run()) == StrictOutput(answer="ok", count=2)
    assert calls == 3


def test_generate_retries_midstream_transport_failure_and_closes_response() -> None:
    calls = 0
    failing_stream = FailingResponseStream()

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, stream=failing_stream)
        return _chat_response('{"answer":"ok","count":2}')

    async def run() -> StrictOutput:
        client = StructuredLLMClient(
            _config(max_retries=1),
            transport=httpx.MockTransport(handler),
        )
        try:
            return await client.generate(
                StrictOutput,
                [{"role": "user", "content": "redacted"}],
            )
        finally:
            await client.aclose()

    assert asyncio.run(run()) == StrictOutput(answer="ok", count=2)
    assert calls == 2
    assert failing_stream.closed is True


def test_generate_applies_end_to_end_attempt_deadline_and_closes_response() -> None:
    class SlowDripStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            for chunk in (b'{"choices":', b"[]}"):
                await asyncio.sleep(0.03)
                yield chunk

        async def aclose(self) -> None:
            self.closed = True

    stream = SlowDripStream()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async def run() -> None:
        client = StructuredLLMClient(
            _config(max_retries=0, timeout_seconds=0.05),
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "user", "content": "redacted"}],
            )
        finally:
            await client.aclose()

    with pytest.raises(LLMRequestError) as caught:
        asyncio.run(run())

    assert caught.value.code == "UPSTREAM_UNAVAILABLE"
    assert caught.value.attempts == 1
    assert stream.closed is True


def test_non_transient_http_failure_is_not_retried_or_leaked() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            400,
            json={"error": {"message": "private-address top-secret-token"}},
        )

    async def run() -> None:
        client = StructuredLLMClient(
            _config(max_retries=2),
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "user", "content": "private-address"}],
            )
        finally:
            await client.aclose()

    with pytest.raises(LLMRequestError) as caught:
        asyncio.run(run())

    assert calls == 1
    assert caught.value.status_code == 400
    assert caught.value.retryable is False
    assert "private-address" not in str(caught.value)
    assert "top-secret-token" not in str(caught.value)


def test_schema_failure_exhaustion_is_bounded_and_redacted() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _chat_response('{"answer":"private-address","count":"wrong"}')

    async def run() -> None:
        client = StructuredLLMClient(
            _config(max_retries=1),
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "user", "content": "top-secret-token"}],
            )
        finally:
            await client.aclose()

    with pytest.raises(LLMResponseError) as caught:
        asyncio.run(run())

    assert calls == 2
    assert caught.value.attempts == 2
    assert caught.value.code == "SCHEMA_VALIDATION_FAILED"
    assert "private-address" not in str(caught.value)
    assert "top-secret-token" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_declared_oversized_response_is_rejected_without_read_or_retry() -> None:
    calls = 0
    stream = ChunkedResponseStream([b"must-not-be-read"])

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-length": "1025"},
            stream=stream,
        )

    async def run() -> None:
        client = StructuredLLMClient(
            _config(max_retries=2, max_response_bytes=1_024),
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "user", "content": "private-input"}],
            )
        finally:
            await client.aclose()

    with pytest.raises(LLMResponseError) as caught:
        asyncio.run(run())

    assert caught.value.code == "PROVIDER_RESPONSE_TOO_LARGE"
    assert caught.value.retryable is False
    assert caught.value.attempts == 1
    assert calls == 1
    assert stream.started is False
    assert stream.closed is True
    assert "top-secret-token" not in str(caught.value)
    assert "proxy.example.test" not in str(caught.value)


def test_chunked_oversized_response_is_bounded_and_closed() -> None:
    calls = 0
    stream = ChunkedResponseStream([b"{" + b"x" * 700, b"x" * 400])

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-length": "100"},
            stream=stream,
        )

    async def run() -> None:
        client = StructuredLLMClient(
            _config(max_retries=2, max_response_bytes=1_024),
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "user", "content": "private-input"}],
            )
        finally:
            await client.aclose()

    with pytest.raises(LLMResponseError) as caught:
        asyncio.run(run())

    assert caught.value.code == "PROVIDER_RESPONSE_TOO_LARGE"
    assert caught.value.retryable is False
    assert caught.value.attempts == 1
    assert calls == 1
    assert stream.started is True
    assert stream.closed is True


def test_response_at_exact_byte_limit_is_accepted() -> None:
    encoded = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"answer":"ok","count":1}',
                    }
                }
            ]
        }
    ).encode()
    body = encoded + b" " * (1_024 - len(encoded))
    assert len(body) == 1_024

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async def run() -> StrictOutput:
        client = StructuredLLMClient(
            _config(max_retries=0, max_response_bytes=1_024),
            transport=httpx.MockTransport(handler),
        )
        try:
            return await client.generate(
                StrictOutput,
                [{"role": "user", "content": "redacted"}],
            )
        finally:
            await client.aclose()

    assert asyncio.run(run()) == StrictOutput(answer="ok", count=1)


def test_encoded_response_is_rejected_before_decompression_or_read() -> None:
    stream = ChunkedResponseStream([b"compressed-data-must-not-be-read"])

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            stream=stream,
        )

    async def run() -> None:
        client = StructuredLLMClient(
            _config(max_retries=2, max_response_bytes=1_024),
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "user", "content": "redacted"}],
            )
        finally:
            await client.aclose()

    with pytest.raises(LLMResponseError) as caught:
        asyncio.run(run())

    assert caught.value.code == "UNSUPPORTED_PROVIDER_CONTENT_ENCODING"
    assert caught.value.retryable is False
    assert caught.value.attempts == 1
    assert stream.started is False
    assert stream.closed is True


@pytest.mark.parametrize("declared_length", ["invalid", "-1"])
def test_invalid_content_length_is_rejected_without_body_read(
    declared_length: str,
) -> None:
    stream = ChunkedResponseStream([b"must-not-be-read"])

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": declared_length},
            stream=stream,
        )

    async def run() -> None:
        client = StructuredLLMClient(
            _config(max_retries=0, max_response_bytes=1_024),
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "user", "content": "redacted"}],
            )
        finally:
            await client.aclose()

    with pytest.raises(LLMResponseError) as caught:
        asyncio.run(run())

    assert caught.value.code == "INVALID_PROVIDER_CONTENT_LENGTH"
    assert caught.value.retryable is False
    assert stream.started is False
    assert stream.closed is True


def test_extracts_content_parts_and_json_fence() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return _chat_response(
            [
                {"type": "text", "text": "```json\n"},
                {"type": "text", "text": '{"answer":"ok","count":3}'},
                {"type": "text", "text": "\n```"},
            ]
        )

    async def run() -> StrictOutput:
        client = StructuredLLMClient(
            _config(),
            transport=httpx.MockTransport(handler),
        )
        try:
            return await client.generate(
                StrictOutput,
                [{"role": "developer", "content": "return JSON"}],
            )
        finally:
            await client.aclose()

    assert asyncio.run(run()) == StrictOutput(answer="ok", count=3)


def test_call_budget_allows_calls_up_to_limit_then_refuses() -> None:
    budget = LLMCallBudget(max_calls=2)

    budget.consume()
    budget.consume()

    with pytest.raises(LLMBudgetExceededError) as caught:
        budget.consume()

    assert caught.value.retryable is False
    assert caught.value.code == "LOOP_LIMIT_REACHED"


def test_call_budget_reset_restores_full_allowance() -> None:
    budget = LLMCallBudget(max_calls=1)
    budget.consume()

    budget.reset()

    budget.consume()
    with pytest.raises(LLMBudgetExceededError):
        budget.consume()


@pytest.mark.parametrize("max_calls", [0, -1, 1.5, True])
def test_call_budget_rejects_invalid_limits(max_calls: Any) -> None:
    with pytest.raises(ValueError):
        LLMCallBudget(max_calls=max_calls)


def test_config_reads_prefixed_settings_when_present(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CHAT_PROXY_URL=https://shared.example.test/v1\n"
        "PROXY_TOKEN=shared-token\n"
        "OPENAI_MODEL=shared-model\n"
        "SUPERVISOR_CHAT_PROXY_URL=https://supervisor.example.test/v1\n"
        "SUPERVISOR_PROXY_TOKEN=supervisor-token\n"
        "SUPERVISOR_MODEL=supervisor-model\n",
        encoding="utf-8",
    )

    config = LLMConfig.from_env(env_file=env_file, environ={}, env_prefix="SUPERVISOR_")

    assert config.base_url == "https://supervisor.example.test/v1"
    assert config.model == "supervisor-model"
    assert "supervisor-token" not in repr(config)


def test_config_falls_back_to_shared_settings_when_prefix_unset(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CHAT_PROXY_URL=https://shared.example.test/v1\n"
        "PROXY_TOKEN=shared-token\n"
        "OPENAI_MODEL=shared-model\n",
        encoding="utf-8",
    )

    config = LLMConfig.from_env(env_file=env_file, environ={}, env_prefix="SUPERVISOR_")

    assert config.base_url == "https://shared.example.test/v1"
    assert config.model == "shared-model"


def test_config_falls_back_per_setting_not_all_or_nothing(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CHAT_PROXY_URL=https://shared.example.test/v1\n"
        "PROXY_TOKEN=shared-token\n"
        "OPENAI_MODEL=shared-model\n"
        "SUPERVISOR_MODEL=supervisor-model\n",
        encoding="utf-8",
    )

    config = LLMConfig.from_env(env_file=env_file, environ={}, env_prefix="SUPERVISOR_")

    assert config.model == "supervisor-model"
    assert config.base_url == "https://shared.example.test/v1"


def test_generate_consumes_budget_once_per_http_attempt() -> None:
    budget = LLMCallBudget(max_calls=5)
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return _chat_response('{"answer":"ok","count":1}')

    async def run() -> None:
        client = StructuredLLMClient(
            _config(),
            transport=httpx.MockTransport(handler),
            call_budget=budget,
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "developer", "content": "return JSON"}],
            )
        finally:
            await client.aclose()

    asyncio.run(run())

    assert attempts == 2
    assert budget.spent == 2


def test_generate_stops_when_budget_is_exhausted() -> None:
    budget = LLMCallBudget(max_calls=1)
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    async def run() -> None:
        client = StructuredLLMClient(
            _config(max_retries=4),
            transport=httpx.MockTransport(handler),
            call_budget=budget,
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "developer", "content": "return JSON"}],
            )
        finally:
            await client.aclose()

    with pytest.raises(LLMBudgetExceededError):
        asyncio.run(run())

    assert attempts == 1


def test_two_clients_share_one_budget() -> None:
    budget = LLMCallBudget(max_calls=2)

    def handler(_: httpx.Request) -> httpx.Response:
        return _chat_response('{"answer":"ok","count":1}')

    async def run() -> None:
        shared = StructuredLLMClient(
            _config(model="openai/gpt-4.1-mini"),
            transport=httpx.MockTransport(handler),
            call_budget=budget,
        )
        supervisor = StructuredLLMClient(
            _config(model="supervisor-model"),
            transport=httpx.MockTransport(handler),
            call_budget=budget,
        )
        try:
            messages = [{"role": "developer", "content": "return JSON"}]
            await shared.generate(StrictOutput, messages)
            await supervisor.generate(StrictOutput, messages)
            await shared.generate(StrictOutput, messages)
        finally:
            await shared.aclose()
            await supervisor.aclose()

    with pytest.raises(LLMBudgetExceededError):
        asyncio.run(run())

    assert budget.spent == 2


def test_generate_without_budget_is_unbounded() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return _chat_response('{"answer":"ok","count":1}')

    async def run() -> StrictOutput:
        client = StructuredLLMClient(
            _config(),
            transport=httpx.MockTransport(handler),
        )
        try:
            messages = [{"role": "developer", "content": "return JSON"}]
            for _ in range(20):
                result = await client.generate(StrictOutput, messages)
            return result
        finally:
            await client.aclose()

    assert asyncio.run(run()) == StrictOutput(answer="ok", count=1)


def _chat_response_with_usage(
    content: Any,
    *,
    usage: dict[str, Any] | None = None,
    model: str | None = "openai/gpt-4.1-mini",
) -> httpx.Response:
    body: dict[str, Any] = {
        "id": "fake-completion",
        "choices": [{"message": {"role": "assistant", "content": content}}],
    }
    if usage is not None:
        body["usage"] = usage
    if model is not None:
        body["model"] = model
    return httpx.Response(200, json=body)


def test_generate_reports_provider_usage_to_the_usage_sink() -> None:
    recorded: list[LLMUsage] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return _chat_response_with_usage(
            '{"answer":"ok","count":1}',
            usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
            model="openai/gpt-4.1-mini",
        )

    async def run() -> None:
        client = StructuredLLMClient(
            _config(),
            transport=httpx.MockTransport(handler),
            usage_sink=recorded.append,
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "developer", "content": "return JSON"}],
            )
        finally:
            await client.aclose()

    asyncio.run(run())

    assert len(recorded) == 1
    assert recorded[0].model == "openai/gpt-4.1-mini"
    assert recorded[0].prompt_tokens == 120
    assert recorded[0].completion_tokens == 30


def test_generate_reports_usage_even_when_provider_omits_token_counts() -> None:
    recorded: list[LLMUsage] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return _chat_response_with_usage('{"answer":"ok","count":1}', usage=None)

    async def run() -> None:
        client = StructuredLLMClient(
            _config(model="configured-model"),
            transport=httpx.MockTransport(handler),
            usage_sink=recorded.append,
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "developer", "content": "return JSON"}],
            )
        finally:
            await client.aclose()

    asyncio.run(run())

    assert len(recorded) == 1
    assert recorded[0].prompt_tokens is None
    assert recorded[0].completion_tokens is None
    assert recorded[0].model == "openai/gpt-4.1-mini"


def test_usage_sink_failure_never_breaks_the_call() -> None:
    def exploding_sink(_: LLMUsage) -> None:
        raise RuntimeError("telemetry backend down")

    def handler(_: httpx.Request) -> httpx.Response:
        return _chat_response_with_usage(
            '{"answer":"ok","count":1}',
            usage={"prompt_tokens": 1, "completion_tokens": 2},
        )

    async def run() -> StrictOutput:
        client = StructuredLLMClient(
            _config(),
            transport=httpx.MockTransport(handler),
            usage_sink=exploding_sink,
        )
        try:
            return await client.generate(
                StrictOutput,
                [{"role": "developer", "content": "return JSON"}],
            )
        finally:
            await client.aclose()

    assert asyncio.run(run()) == StrictOutput(answer="ok", count=1)


def test_overriding_the_endpoint_requires_its_own_token(tmp_path: Path) -> None:
    """Falling back on the shared token would leak it to another vendor."""

    env_file = tmp_path / ".env"
    env_file.write_text(
        "CHAT_PROXY_URL=https://shared.example.test/v1\n"
        "PROXY_TOKEN=shared-token\n"
        "OPENAI_MODEL=shared-model\n"
        "SUPERVISOR_CHAT_PROXY_URL=https://other-vendor.example.test/v1\n",
        encoding="utf-8",
    )

    with pytest.raises(LLMConfigurationError) as caught:
        LLMConfig.from_env(env_file=env_file, environ={}, env_prefix="SUPERVISOR_")

    assert "SUPERVISOR_PROXY_TOKEN" in str(caught.value)


def test_overriding_only_the_model_keeps_the_shared_endpoint_and_token(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CHAT_PROXY_URL=https://shared.example.test/v1\n"
        "PROXY_TOKEN=shared-token\n"
        "OPENAI_MODEL=shared-model\n"
        "SUPERVISOR_MODEL=bigger-model\n",
        encoding="utf-8",
    )

    config = LLMConfig.from_env(env_file=env_file, environ={}, env_prefix="SUPERVISOR_")

    assert config.model == "bigger-model"
    assert config.base_url == "https://shared.example.test/v1"


def test_usage_falls_back_to_configured_model_when_provider_omits_it() -> None:
    recorded: list[LLMUsage] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return _chat_response_with_usage(
            '{"answer":"ok","count":1}',
            usage={"prompt_tokens": 10, "completion_tokens": 2},
            model=None,
        )

    async def run() -> None:
        client = StructuredLLMClient(
            _config(model="configured-model"),
            transport=httpx.MockTransport(handler),
            usage_sink=recorded.append,
        )
        try:
            await client.generate(
                StrictOutput,
                [{"role": "developer", "content": "return JSON"}],
            )
        finally:
            await client.aclose()

    asyncio.run(run())

    assert recorded[0].model == "configured-model"
