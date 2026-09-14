from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agent.llm import (
    LLMConfig,
    LLMConfigurationError,
    LLMRequestError,
    LLMResponseError,
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


def _config(
    *,
    model: str = "openai/gpt-4.1-mini",
    max_retries: int = 2,
    reasoning_effort: str | None = "low",
) -> LLMConfig:
    return LLMConfig(
        base_url="https://proxy.example.test/v1/",
        api_token="top-secret-token",
        model=model,
        reasoning_effort=reasoning_effort,
        max_retries=max_retries,
        retry_backoff_seconds=0,
    )


def _chat_response(content: Any) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "fake-completion",
            "choices": [{"message": {"role": "assistant", "content": content}}],
        },
    )


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


def test_generate_sends_strict_schema_and_omits_reasoning_for_gpt_4_1() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
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
