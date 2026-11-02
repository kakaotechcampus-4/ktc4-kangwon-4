"""Completion limits use synthetic HTTP responses, never a provider or real .env."""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from app.agent.llm import (
    LLMConfig,
    LLMConfigurationError,
    LLMRequestError,
    LLMResponseError,
    StructuredLLMClient,
    candidate_config,
    restrict_string_enums,
    sanitize_json_schema,
)
from app.agent.runtime import resolve_run_deadline_seconds
from app.agent.supervisor.agent import SupervisorModelOutput
from app.agent.tracing import capture_usage
from pydantic import BaseModel


class Answer(BaseModel):
    ok: bool


def test_supervisor_model_selector_preserves_strong_review_and_requires_own_key(tmp_path):
    env = tmp_path / ".env"
    text = (
        "CHAT_PROXY_URL=https://proxy.example.org/shared/v1\nPROXY_TOKEN=shared-synthetic-key\n"
        "OPENAI_MODEL=gpt-6.1-sol\nOPENAI_REASONING_EFFORT=xhigh\n"
        "AGENT_SUPERVISOR_MODEL_PREFIX=LUNA6_\n"
        "LUNA6_CHAT_PROXY_URL=https://proxy.example.org/luna6/v1\n"
        "LUNA6_PROXY_TOKEN=luna6-synthetic-key\nLUNA6_MODEL=gpt-6-luna\n"
        "LUNA6_REASONING_EFFORT=low\n"
    )
    env.write_text(text)
    supervisor = LLMConfig.from_env(env_file=env, environ={}, env_prefix="SUPERVISOR_")
    review = LLMConfig.from_env(env_file=env, environ={})
    assert supervisor.model == "gpt-6-luna" and supervisor.reasoning_effort == "low"
    assert supervisor.api_token == "luna6-synthetic-key"
    assert review.model == "gpt-6.1-sol" and review.reasoning_effort == "xhigh"
    env.write_text(text.replace("LUNA6_PROXY_TOKEN=luna6-synthetic-key", "LUNA6_PROXY_TOKEN="))
    with pytest.raises(LLMConfigurationError):
        LLMConfig.from_env(env_file=env, environ={}, env_prefix="SUPERVISOR_")


def test_failed_schema_attempt_is_counted_with_its_tokens_before_retry():
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(200, json={
            "model": "actual-model",
            "choices": [{"message": {"content": '{"wrong":true}' if len(attempts) == 1 else '{"ok":true}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 7,
                      "completion_tokens_details": {"reasoning_tokens": 3},
                      "prompt_tokens_details": {"cached_tokens": 4}},
        })

    with capture_usage() as calls:
        assert generate(config(reasoning_effort="low"), handler).ok
    assert len(calls) == 2
    assert sum(call.prompt_tokens for call in calls) == 20
    assert calls[0].status == "ERROR" and calls[0].error_code == "SCHEMA_VALIDATION_FAILED"
    assert calls[1].status == "SUCCESS" and calls[1].attempt == 2
    assert all(call.model == "actual-model" and call.requested_model == "gpt-5.6-sol" for call in calls)
    assert calls[0].reasoning_tokens == 3 and calls[0].cached_prompt_tokens == 4
    assert "synthetic-test-token" not in repr(calls) and "example.org" not in repr(calls)


def test_http_retry_and_refusal_record_unknown_and_known_usage_once_each():
    count = 0

    def handler(_):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(503, json={"error": "private provider message"})
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "length", "message": {"content": ""}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 30},
        })

    with capture_usage() as calls, pytest.raises(LLMResponseError):
        generate(config(), handler)
    assert len(calls) == 2
    assert calls[0].prompt_tokens is None and calls[0].status_code == 503
    assert calls[1].completion_tokens == 30 and calls[1].error_code == "OUTPUT_TOKEN_LIMIT"
    assert "private provider message" not in repr(calls)


def test_candidate_does_not_inherit_shared_credentials_model_or_effort(tmp_path):
    env = {"CHAT_PROXY_URL": "https://shared.example", "PROXY_TOKEN": "shared-secret",
           "OPENAI_MODEL": "shared", "OPENAI_REASONING_EFFORT": "xhigh"}
    options = {"env_file": tmp_path / "absent", "environ": env}
    assert candidate_config("HAIKU_", **options) is None
    env["HAIKU_MODEL"] = "haiku"
    with pytest.raises(LLMConfigurationError):
        candidate_config("HAIKU_", **options)
    env.update(HAIKU_CHAT_PROXY_URL="https://haiku.example", HAIKU_PROXY_TOKEN="own-secret")
    candidate = candidate_config("HAIKU_", **options)
    assert candidate.api_token == "own-secret" and candidate.reasoning_effort is None
    env["AGENT_INFO_MODEL_PREFIX"] = "HAIKU_"
    assert LLMConfig.from_env(env_prefix="INFO_", **options) == candidate


def test_capture_of_cancelled_attempt_is_error_with_unknown_usage():
    async def handler(_):
        raise asyncio.CancelledError

    with capture_usage() as calls, pytest.raises(asyncio.CancelledError):
        generate(config(), handler)
    assert len(calls) == 1 and calls[0].status == "ERROR"
    assert calls[0].error_code == "CALL_INTERRUPTED" and calls[0].prompt_tokens is None


def config(**changes):
    return LLMConfig(
        base_url="https://example.org/synthetic",
        api_token="synthetic-test-token",
        model="gpt-5.6-sol",
        retry_backoff_seconds=0,
        **changes,
    )


@pytest.mark.parametrize("seconds", [None, "30"])
def test_time_limits(tmp_path, seconds):
    env = {
        "CHAT_PROXY_URL": "https://example.org",
        "PROXY_TOKEN": "test",
        "OPENAI_MODEL": "test",
    }
    if seconds:
        env.update(AGENT_LLM_TIMEOUT_SECONDS=seconds, AGENT_RUN_DEADLINE_SECONDS=seconds)
    options = {"env_file": tmp_path / "absent.env", "environ": env}
    assert LLMConfig.from_env(**options).timeout_seconds == (30 if seconds else 180)
    assert resolve_run_deadline_seconds(**options) == (30 if seconds else 420)


def generate(settings, handler, response_model=Answer, enum_constraints=None):
    async def run():
        async with StructuredLLMClient(
            settings, transport=httpx.MockTransport(handler)
        ) as client:
            return await client.generate(
                response_model, [{"role": "user", "content": "test"}],
                enum_constraints=enum_constraints,
            )

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


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-4.1-mini"])
@pytest.mark.parametrize("effort", ["xhigh", None])
def test_reasoning_effort_is_sent_exactly_when_configured(model, effort):
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok":true}'}}]}
        )

    settings = replace(config(reasoning_effort=effort), model=model)
    assert generate(settings, handler).ok is True
    assert payloads[0].get("reasoning_effort") == effort


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


@pytest.mark.parametrize("extra_content", [False, True])
def test_elice_haiku_usage_tail_allows_only_an_empty_choice(extra_content):
    tail = {"choices": [{"index": 0, "delta": {"content": "injected"} if extra_content else {},
                          "finish_reason": None}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3}}
    body = event({"content": '{"ok":true}'}, "stop") + "data: " + json.dumps(tail) + "\n\ndata: [DONE]\n\n"
    with capture_usage() as calls:
        if extra_content:
            with pytest.raises(LLMResponseError):
                generate(config(stream=True, max_retries=0), lambda _: httpx.Response(200, text=body))
        else:
            assert generate(config(stream=True), lambda _: httpx.Response(200, text=body)).ok
            assert len(calls) == 1 and calls[0].completion_tokens == 3


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


def test_supervisor_selection_enums_reach_the_api_and_preserve_nulls():
    constraints = {
        "decision_type": ["ACTION"], "blocker_candidate_id": ["procedure:1"],
        "action_code": ["CONFIRM_TAX_CLOSURE_REQUIREMENTS"],
    }
    selection = {key: values[0] for key, values in constraints.items()}

    def handler(request):
        schema = json.loads(request.content)["response_format"]["json_schema"]["schema"]
        properties = schema["properties"]
        assert set(properties) == set(constraints)
        assert properties["decision_type"]["enum"] == ["ACTION"]
        for key in ("blocker_candidate_id", "action_code"):
            branches = properties[key]["anyOf"]
            assert {"type": "null"} in branches
            assert next(item for item in branches if item.get("type") == "string")["enum"] == constraints[key]
        assert schema["$defs"]["DecisionType"] == SupervisorModelOutput.model_json_schema()["$defs"]["DecisionType"]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(selection)}}]})

    result = generate(config(max_retries=0), handler, SupervisorModelOutput, constraints)
    assert result.model_dump(mode="json") == selection


def test_enum_restrictions_preserve_shared_definitions_and_evidence_items():
    schema = sanitize_json_schema(SupervisorModelOutput.model_json_schema())
    schema["properties"]["other_decision_type"] = {"$ref": "#/$defs/DecisionType"}
    schema["properties"]["evidence_refs"] = {
        "type": "array", "items": {"type": "string", "minLength": 1},
    }
    original = json.dumps(schema, sort_keys=True)
    restricted = restrict_string_enums(schema, {
        "decision_type": ["ACTION", "UNSUPPORTED"], "evidence_refs": ["e1"],
    })
    assert restricted["properties"]["decision_type"]["enum"] == ["ACTION"]
    assert restricted["$defs"] == schema["$defs"]
    assert restricted["properties"]["other_decision_type"] == {"$ref": "#/$defs/DecisionType"}
    assert restricted["properties"]["evidence_refs"]["items"] == {
        "type": "string", "minLength": 1, "enum": ["e1"],
    }
    assert json.dumps(schema, sort_keys=True) == original
    with pytest.raises(ValueError, match="no supported values"):
        restrict_string_enums(schema, {"decision_type": ["UNSUPPORTED"]})
