"""Completion limits use synthetic HTTP responses, never a provider or real .env."""

import asyncio
import json

import httpx
import pytest
from app.agent.llm import (
    LLMConfig,
    LLMConfigurationError,
    LLMRequestError,
    LLMResponseError,
    StructuredLLMClient,
)
from pydantic import BaseModel


class Answer(BaseModel):
    ok: bool


def config(**changes):
    return LLMConfig(
        base_url="https://example.org/synthetic",
        api_token="synthetic-test-token",
        model="gpt-5.6-sol",
        retry_backoff_seconds=0,
        **changes,
    )


def generate(settings, handler):
    async def run():
        async with StructuredLLMClient(
            settings, transport=httpx.MockTransport(handler)
        ) as client:
            return await client.generate(Answer, [{"role": "user", "content": "test"}])

    return asyncio.run(run())


@pytest.mark.parametrize("limit", [None, 24000])
def test_completion_limit_is_sent_only_when_configured(limit):
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok":true}'}}]}
        )

    assert generate(config(max_completion_tokens=limit), handler).ok is True
    assert len(payloads) == 1
    if limit is None:
        assert "max_completion_tokens" not in payloads[0]
    else:
        assert payloads[0]["max_completion_tokens"] == limit


@pytest.mark.parametrize("content", ["", '{"ok":true}'])
def test_output_token_limit_stops_after_one_http_attempt(content):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "length", "message": {"content": content}}
                ]
            },
        )

    with pytest.raises(LLMResponseError) as raised:
        generate(config(max_retries=2), handler)
    assert len(calls) == 1
    assert raised.value.code == "OUTPUT_TOKEN_LIMIT"
    assert raised.value.retryable is False
    assert raised.value.attempts == 1
    assert raised.value.status_code == 200


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "24000"])
def test_invalid_completion_limit_is_rejected(limit):
    with pytest.raises(LLMConfigurationError):
        config(max_completion_tokens=limit)


@pytest.mark.parametrize("raw", [None, "24000", "0", "-1", "1.5", "bad"])
def test_completion_limit_from_environment(tmp_path, raw):
    environment = {
        "CHAT_PROXY_URL": "https://example.org/synthetic",
        "PROXY_TOKEN": "synthetic-test-token",
        "OPENAI_MODEL": "gpt-5.6-sol",
    }
    if raw is not None:
        environment["AGENT_LLM_MAX_COMPLETION_TOKENS"] = raw
    kwargs = {"env_file": tmp_path / "absent.env", "environ": environment}
    if raw in (None, "24000"):
        assert LLMConfig.from_env(**kwargs).max_completion_tokens == (
            None if raw is None else 24000
        )
    else:
        with pytest.raises(LLMConfigurationError):
            LLMConfig.from_env(**kwargs)


def event(delta=None, finish=None):
    return (
        "data: "
        + json.dumps(
            {"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]},
            ensure_ascii=False,
        )
        + "\n\n"
    )


class ChunkedBody(httpx.AsyncByteStream):
    def __init__(self, text, *, disconnect=False):
        self.body, self.disconnect = text.encode(), disconnect

    async def __aiter__(self):
        for start in range(0, len(self.body), 7):
            yield self.body[start : start + 7]
        if self.disconnect:
            raise httpx.ReadError("synthetic disconnect")


def test_stream_handles_split_bytes_multiline_data_and_final_usage():
    payloads, usages = [], []
    first = json.dumps(
        {"choices": [{"index": 0, "delta": {"reasoning_content": "합성 추론"}}]},
        ensure_ascii=False,
        indent=2,
    )
    body = (
        ": keepalive\r\n\r\n"
        + "\r\n".join("data: " + line for line in first.splitlines())
        + "\r\n\r\n"
    )
    body += event({"content": '{"ok":'}) + event({"content": "true}"}, "stop")
    body += 'data: {"choices":[],"usage":{"completion_tokens":12}}\n\n'
    body += "data: [DONE]\n\n"

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, stream=ChunkedBody(body))

    async def run():
        async with StructuredLLMClient(
            config(stream=True),
            transport=httpx.MockTransport(handler),
            usage_sink=usages.append,
        ) as client:
            return await client.generate(Answer, [{"role": "user", "content": "test"}])

    assert asyncio.run(run()).ok is True
    assert payloads[0]["stream"] is True
    assert "stream_options" not in payloads[0]
    assert usages[0].completion_tokens == 12


@pytest.mark.parametrize(
    "body,code",
    [
        (event({"content": '{"ok":true}'}, "stop"), "INCOMPLETE_PROVIDER_STREAM"),
        (
            event({"content": '{"ok":true}'}) + "data: [DONE]\n\n",
            "INCOMPLETE_PROVIDER_STREAM",
        ),
        (
            event({"content": '{"ok":true}'}, "stop") + "data: [DONE]",
            "INCOMPLETE_PROVIDER_STREAM",
        ),
        (
            event({"content": '{"ok":true}'}, "length") + "data: [DONE]\n\n",
            "OUTPUT_TOKEN_LIMIT",
        ),
        (
            event({"refusal": "synthetic refusal"}, "stop") + "data: [DONE]\n\n",
            "PROVIDER_REFUSAL",
        ),
        (
            event({"content": '{"ok":true}'}, "content_filter") + "data: [DONE]\n\n",
            "PROVIDER_REFUSAL",
        ),
        (
            event({"content": '{"ok":[]}'}, "stop") + "data: [DONE]\n\n",
            "SCHEMA_VALIDATION_FAILED",
        ),
        (
            event({"content": '{"ok":true}'}, "stop")
            + 'data: {"error":{"code":"bad"}}\n\ndata: [DONE]\n\n',
            "INVALID_PROVIDER_STREAM",
        ),
        (
            event({"content": '{"ok":true}'}, "stop")
            + "data: [DONE]\n\n"
            + event({"content": "extra"}),
            "INVALID_PROVIDER_STREAM",
        ),
    ],
)
def test_invalid_stream_is_never_accepted(body, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=ChunkedBody(body))

    retries = 2 if code == "OUTPUT_TOKEN_LIMIT" else 0
    with pytest.raises(LLMResponseError) as raised:
        generate(config(stream=True, max_retries=retries), handler)
    assert raised.value.code == code
    assert len(calls) == 1


@pytest.mark.parametrize("disconnect", [False, True])
def test_stream_keeps_body_limit_and_rejects_disconnect(disconnect):
    body = event({"content": '{"ok":true}'}, "stop") + "data: [DONE]\n\n"
    if not disconnect:
        body = ": " + "x" * 1024 + "\n\n" + body
    expected = LLMRequestError if disconnect else LLMResponseError
    with pytest.raises(expected) as raised:
        generate(
            config(stream=True, max_retries=0, max_response_bytes=1024),
            lambda request: httpx.Response(
                200, stream=ChunkedBody(body, disconnect=disconnect)
            ),
        )
    assert raised.value.code == (
        "UPSTREAM_UNAVAILABLE" if disconnect else "PROVIDER_RESPONSE_TOO_LARGE"
    )


@pytest.mark.parametrize("raw", [None, "true", "false", "TRUE", "1", "bad"])
def test_stream_environment_is_optional_and_boolean(tmp_path, raw):
    environment = {
        "CHAT_PROXY_URL": "https://example.org/synthetic",
        "PROXY_TOKEN": "synthetic-test-token",
        "OPENAI_MODEL": "gpt-5.6-sol",
    }
    if raw is not None:
        environment["AGENT_LLM_STREAM"] = raw
    kwargs = {"env_file": tmp_path / "absent.env", "environ": environment}
    if raw in ("1", "bad"):
        with pytest.raises(LLMConfigurationError):
            LLMConfig.from_env(**kwargs)
    else:
        assert LLMConfig.from_env(**kwargs).stream is (raw in ("true", "TRUE"))


@pytest.mark.parametrize("value", ["true", 1])
def test_stream_config_rejects_non_boolean(value):
    with pytest.raises(LLMConfigurationError):
        config(stream=value)
