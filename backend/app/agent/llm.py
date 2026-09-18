"""Small OpenAI-compatible client for Agent structured outputs.

The Agent runtime talks to the configured chat proxy directly through ``httpx``.
This module deliberately does not log prompts, responses, endpoint URLs, or
credentials: all of those can contain user data or deployment details.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self, TypeVar
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, ValidationError

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)
SleepCallable = Callable[[float], Awaitable[None]]
UsageSink = Callable[["LLMUsage"], None]

_DEFAULT_TIMEOUT_SECONDS = 45.0
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_RETRY_BACKOFF_SECONDS = 0.25
_DEFAULT_MAX_RESPONSE_BYTES = 1_000_000
# This counts HTTP attempts, not component attempts: each semantic attempt is a
# generate() call that retries up to max_retries times. With the defaults that
# makes the component limits worth 57 provider calls (Info 3x3 + Support 3x3 +
# three Review rounds of Supervisor 3x3 + Review 2x2), and more when a rework
# reruns Info or Support. 40 is deliberately below that ceiling: it is a cost
# stop that can end a run whose component limits are not yet spent.
_DEFAULT_MAX_CALLS_PER_RUN = 40
_MAX_ALLOWED_RETRIES = 4
_MAX_RETRY_BACKOFF_SECONDS = 60.0
_MIN_RESPONSE_BYTES = 1_024
_MAX_RESPONSE_BYTES = 10_000_000
_TRANSIENT_STATUS_CODES = frozenset({408, 409, 425, 429})
_UNSUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "default",
        "discriminator",
        "example",
        "examples",
        "uniqueItems",
    }
)


class LLMClientError(RuntimeError):
    """Base exception whose message is safe to surface in operational logs."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool,
        attempts: int = 0,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.attempts = attempts
        self.status_code = status_code


class LLMConfigurationError(LLMClientError):
    """Raised before a request when required client configuration is invalid."""


class LLMBudgetExceededError(LLMClientError):
    """Raised when one run has spent its whole allowance of provider calls."""


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Metadata-only record of what one provider call cost.

    Prompt text, evidence and completions are deliberately absent so this can
    be forwarded to observability backends without carrying user data.
    """

    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMCallBudget:
    """Provider-call allowance shared by every client used within one run.

    Each HTTP attempt costs money, so retries consume the allowance too. The
    graph resets the counter when a run starts, which makes the cap per-run.
    """

    # TODO: a single shared instance is not safe once one process serves
    # concurrent runs; scope it per run (contextvar) when the server is wired.
    def __init__(self, max_calls: int = _DEFAULT_MAX_CALLS_PER_RUN) -> None:
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("max_calls must be a positive integer")
        self._max_calls = max_calls
        self._spent = 0

    @property
    def max_calls(self) -> int:
        return self._max_calls

    @property
    def spent(self) -> int:
        return self._spent

    def reset(self) -> None:
        self._spent = 0

    def consume(self) -> None:
        if self._spent >= self._max_calls:
            raise LLMBudgetExceededError(
                f"Run exhausted its budget of {self._max_calls} provider call(s)",
                code="LOOP_LIMIT_REACHED",
                retryable=False,
                attempts=self._spent,
            )
        self._spent += 1


class LLMRequestError(LLMClientError):
    """Raised when the provider request cannot complete successfully."""


class LLMResponseError(LLMClientError):
    """Raised when the provider response cannot satisfy the local model."""


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Validated chat proxy settings.

    ``api_token`` is excluded from the dataclass representation to reduce the
    chance of accidental credential disclosure.
    """

    base_url: str
    api_token: str = field(repr=False)
    model: str
    reasoning_effort: str | None = None
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_retries: int = _DEFAULT_MAX_RETRIES
    retry_backoff_seconds: float = _DEFAULT_RETRY_BACKOFF_SECONDS
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _validate_base_url(self.base_url))

        if not self.api_token.strip():
            raise _configuration_error("PROXY_TOKEN is required")
        if not self.model.strip():
            raise _configuration_error("OPENAI_MODEL is required")
        if (
            type(self.timeout_seconds) not in {int, float}
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise _configuration_error("Agent LLM timeout must be finite and positive")
        if (
            type(self.max_retries) is not int
            or not 0 <= self.max_retries <= _MAX_ALLOWED_RETRIES
        ):
            raise _configuration_error(
                f"Agent LLM retries must be between 0 and {_MAX_ALLOWED_RETRIES}"
            )
        if (
            type(self.retry_backoff_seconds) not in {int, float}
            or isinstance(self.retry_backoff_seconds, bool)
            or not math.isfinite(self.retry_backoff_seconds)
            or self.retry_backoff_seconds < 0
            or self.retry_backoff_seconds > _MAX_RETRY_BACKOFF_SECONDS
            or not math.isfinite(
                self.retry_backoff_seconds * (2 ** (_MAX_ALLOWED_RETRIES - 1))
            )
        ):
            raise _configuration_error(
                "Agent LLM retry backoff must be finite and between 0 and 60 seconds"
            )
        if (
            type(self.max_response_bytes) is not int
            or not _MIN_RESPONSE_BYTES <= self.max_response_bytes <= _MAX_RESPONSE_BYTES
        ):
            raise _configuration_error(
                "Agent LLM response limit must be between 1024 and 10000000 bytes"
            )

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
        env_prefix: str = "",
    ) -> LLMConfig:
        """Load settings with process environment taking precedence over `.env`.

        By default the repository-root ``.env`` is loaded, independent of the
        current working directory. Tests can inject both the file and mapping.

        ``env_prefix`` reads component-specific overrides: ``SUPERVISOR_MODEL``
        for the shared ``OPENAI_MODEL``, and ``SUPERVISOR_CHAT_PROXY_URL`` /
        ``SUPERVISOR_PROXY_TOKEN`` for their same-named shared keys. The model
        is the one key whose override drops the ``OPENAI_`` part. Each key
        falls back on its own, so a component can override only the model —
        but overriding the endpoint requires its own token.
        """

        environment = os.environ if environ is None else environ
        dotenv_path = Path(env_file) if env_file is not None else _repo_root() / ".env"
        file_values: Mapping[str, str | None]
        if dotenv_path.is_file():
            try:
                file_values = dotenv_values(dotenv_path)
            except (OSError, ValueError) as exc:
                raise _configuration_error(
                    "Agent environment file could not be read"
                ) from exc
        else:
            file_values = {}

        def value(*names: str) -> str | None:
            for name in names:
                raw = environment.get(name)
                if raw is None:
                    raw = file_values.get(name)
                if raw is None:
                    continue
                normalized = str(raw).strip()
                if normalized:
                    return normalized
            return None

        def overridable(shared_key: str, override_suffix: str) -> str | None:
            if not env_prefix:
                return value(shared_key)
            return value(f"{env_prefix}{override_suffix}", shared_key)

        base_url = overridable("CHAT_PROXY_URL", "CHAT_PROXY_URL")
        api_token = overridable("PROXY_TOKEN", "PROXY_TOKEN")
        model = overridable("OPENAI_MODEL", "MODEL")

        # Falling back on the token alone would send the shared credential to
        # whichever vendor the overridden endpoint belongs to.
        if (
            env_prefix
            and value(f"{env_prefix}CHAT_PROXY_URL")
            and not value(f"{env_prefix}PROXY_TOKEN")
        ):
            raise _configuration_error(
                f"{env_prefix}PROXY_TOKEN is required when "
                f"{env_prefix}CHAT_PROXY_URL overrides the shared endpoint"
            )
        missing = [
            key
            for key, configured in (
                ("CHAT_PROXY_URL", base_url),
                ("PROXY_TOKEN", api_token),
                ("OPENAI_MODEL", model),
            )
            if configured is None
        ]
        if missing:
            raise _configuration_error(
                "Missing Agent LLM configuration: " + ", ".join(missing)
            )

        timeout_seconds = _parse_float(
            value("AGENT_LLM_TIMEOUT_SECONDS"),
            default=_DEFAULT_TIMEOUT_SECONDS,
            setting_name="AGENT_LLM_TIMEOUT_SECONDS",
        )
        max_retries = _parse_int(
            value("AGENT_LLM_MAX_RETRIES"),
            default=_DEFAULT_MAX_RETRIES,
            setting_name="AGENT_LLM_MAX_RETRIES",
        )
        retry_backoff_seconds = _parse_float(
            value("AGENT_LLM_RETRY_BACKOFF_SECONDS"),
            default=_DEFAULT_RETRY_BACKOFF_SECONDS,
            setting_name="AGENT_LLM_RETRY_BACKOFF_SECONDS",
        )
        max_response_bytes = _parse_int(
            value("AGENT_LLM_MAX_RESPONSE_BYTES"),
            default=_DEFAULT_MAX_RESPONSE_BYTES,
            setting_name="AGENT_LLM_MAX_RESPONSE_BYTES",
        )

        return cls(
            base_url=base_url or "",
            api_token=api_token or "",
            model=model or "",
            reasoning_effort=value("OPENAI_REASONING_EFFORT"),
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            max_response_bytes=max_response_bytes,
        )


class StructuredLLMClient:
    """Async structured-output client for an OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepCallable = asyncio.sleep,
        call_budget: LLMCallBudget | None = None,
        usage_sink: UsageSink | None = None,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("Pass either an HTTP client or a transport, not both")

        self.config = config
        self._sleep = sleep
        self._call_budget = call_budget
        self._usage_sink = usage_sink
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=config.timeout_seconds,
            transport=transport,
        )

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
        env_prefix: str = "",
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepCallable = asyncio.sleep,
        call_budget: LLMCallBudget | None = None,
        usage_sink: UsageSink | None = None,
    ) -> StructuredLLMClient:
        return cls(
            LLMConfig.from_env(
                env_file=env_file, environ=environ, env_prefix=env_prefix
            ),
            client=client,
            transport=transport,
            sleep=sleep,
            call_budget=call_budget,
            usage_sink=usage_sink,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close only clients created by this wrapper."""

        if self._owns_client:
            await self._client.aclose()

    async def generate(
        self,
        response_model: type[ResponseModelT],
        messages: Sequence[Mapping[str, Any]],
        *,
        schema_name: str | None = None,
        max_retries: int | None = None,
        temperature: float | None = None,
    ) -> ResponseModelT:
        """Return a locally validated Pydantic model.

        Provider schema sanitization only affects the schema sent over HTTP.
        The original Pydantic model performs the final validation on every
        response, including after retries.
        """

        _validate_response_model(response_model)
        normalized_messages = _normalize_messages(messages)
        retries = self.config.max_retries if max_retries is None else max_retries
        if type(retries) is not int or not 0 <= retries <= _MAX_ALLOWED_RETRIES:
            raise ValueError(
                f"max_retries must be between 0 and {_MAX_ALLOWED_RETRIES}"
            )

        payload = self._build_payload(
            response_model=response_model,
            messages=normalized_messages,
            schema_name=schema_name,
            temperature=temperature,
        )
        total_attempts = retries + 1
        last_status_code: int | None = None
        last_failure_code = "MALFORMED_RESPONSE"

        for attempt_index in range(total_attempts):
            attempt = attempt_index + 1
            response: httpx.Response | None = None
            should_retry = False
            try:
                if self._call_budget is not None:
                    self._call_budget.consume()
                async with asyncio.timeout(self.config.timeout_seconds):
                    request = self._client.build_request(
                        "POST",
                        _chat_completions_url(self.config.base_url),
                        headers={
                            "Authorization": f"Bearer {self.config.api_token}",
                            "Content-Type": "application/json",
                            "Accept-Encoding": "identity",
                        },
                        json=payload,
                        timeout=self.config.timeout_seconds,
                    )
                    response = await self._client.send(request, stream=True)
                    last_status_code = response.status_code
                    if not response.is_success:
                        retryable = _is_transient_status(response.status_code)
                        if retryable and attempt < total_attempts:
                            should_retry = True
                        else:
                            raise LLMRequestError(
                                f"LLM provider returned HTTP {response.status_code} after "
                                f"{attempt} attempt(s)",
                                code="UPSTREAM_HTTP_ERROR",
                                retryable=retryable,
                                attempts=attempt,
                                status_code=response.status_code,
                            )
                    else:
                        body = await _read_bounded_response_body(
                            response,
                            max_bytes=self.config.max_response_bytes,
                        )
                        parsed, usage = _parse_response(
                            body, response_model, self.config.model
                        )
                        self._report_usage(usage)
                        return parsed
            except (TimeoutError, httpx.TimeoutException, httpx.TransportError):
                last_failure_code = "UPSTREAM_UNAVAILABLE"
                if attempt < total_attempts:
                    should_retry = True
                else:
                    raise LLMRequestError(
                        f"LLM provider request failed after {attempt} attempt(s)",
                        code=last_failure_code,
                        retryable=True,
                        attempts=attempt,
                    ) from None
            except _InvalidStructuredResponse as exc:
                last_failure_code = exc.code
                if exc.retryable and attempt < total_attempts:
                    should_retry = True
                else:
                    raise LLMResponseError(
                        "LLM structured response failed local validation after "
                        f"{attempt} attempt(s)",
                        code=last_failure_code,
                        retryable=exc.retryable,
                        attempts=attempt,
                        status_code=last_status_code,
                    ) from None
            finally:
                if response is not None:
                    await response.aclose()

            if should_retry:
                await self._backoff(attempt_index)
                continue

        # The bounded loop always returns or raises. Keep a safe defensive error
        # in case future refactoring changes that invariant.
        raise LLMResponseError(
            "LLM structured response could not be produced",
            code=last_failure_code,
            retryable=True,
            attempts=total_attempts,
            status_code=last_status_code,
        )

    async def complete_structured(
        self,
        messages: Sequence[Mapping[str, Any]],
        response_model: type[ResponseModelT],
        *,
        schema_name: str | None = None,
        max_retries: int | None = None,
        temperature: float | None = None,
    ) -> ResponseModelT:
        """Keyword-friendly alias for callers that place messages first."""

        return await self.generate(
            response_model,
            messages,
            schema_name=schema_name,
            max_retries=max_retries,
            temperature=temperature,
        )

    def _build_payload(
        self,
        *,
        response_model: type[BaseModel],
        messages: list[dict[str, Any]],
        schema_name: str | None,
        temperature: float | None,
    ) -> dict[str, Any]:
        schema = sanitize_json_schema(
            response_model.model_json_schema(mode="validation")
        )
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": _normalize_schema_name(
                        schema_name or response_model.__name__
                    ),
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if self.config.reasoning_effort and _supports_reasoning_effort(
            self.config.model
        ):
            payload["reasoning_effort"] = self.config.reasoning_effort
        return payload

    def _report_usage(self, usage: LLMUsage | None) -> None:
        if self._usage_sink is None:
            return
        reported = usage or LLMUsage(model=self.config.model)
        try:
            self._usage_sink(reported)
        except Exception:  # noqa: BLE001 - telemetry must not change call results
            return

    async def _backoff(self, attempt_index: int) -> None:
        delay = self.config.retry_backoff_seconds * (2**attempt_index)
        if delay > 0:
            await self._sleep(delay)


def sanitize_json_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Project a Pydantic schema into the provider's supported strict subset.

    Keywords removed here remain enforced by local Pydantic validation. Object
    properties are made required because OpenAI strict structured outputs use
    required nullable properties rather than omitted optional properties.
    """

    def sanitize(value: Any) -> Any:
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        if not isinstance(value, Mapping):
            return deepcopy(value)

        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key in _UNSUPPORTED_SCHEMA_KEYWORDS or key.startswith("x-"):
                continue
            if key == "oneOf":
                # Pydantic emits ``oneOf`` for discriminated unions, while the
                # configured OpenAI-compatible strict schema accepts nested
                # unions only as ``anyOf``. Local Pydantic validation still
                # enforces the discriminator and exactly one matching variant.
                cleaned["anyOf"] = sanitize(item)
                continue
            cleaned[key] = sanitize(item)

        properties = cleaned.get("properties")
        if isinstance(properties, Mapping):
            cleaned["required"] = list(properties.keys())
            cleaned["additionalProperties"] = False
        return cleaned

    projected = sanitize(schema)
    if not isinstance(projected, dict):
        raise TypeError("Pydantic JSON schema must be an object")
    return projected


class _InvalidStructuredResponse(ValueError):
    def __init__(self, code: str, *, retryable: bool = True) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def _coerce_token_count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _extract_usage(body: Mapping[str, Any], fallback_model: str) -> LLMUsage:
    """Read the metadata-only parts of a provider envelope.

    Providers disagree on token field names, and some omit usage entirely, so
    every field degrades to ``None`` rather than failing the call.
    """

    reported_model = body.get("model")
    model = (
        reported_model
        if isinstance(reported_model, str) and reported_model.strip()
        else fallback_model
    )
    usage = body.get("usage")
    if not isinstance(usage, Mapping):
        return LLMUsage(model=model)
    prompt_tokens = _coerce_token_count(
        usage.get("prompt_tokens", usage.get("input_tokens"))
    )
    completion_tokens = _coerce_token_count(
        usage.get("completion_tokens", usage.get("output_tokens"))
    )
    return LLMUsage(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def _parse_response(
    response_body: bytes,
    response_model: type[ResponseModelT],
    fallback_model: str = "",
) -> tuple[ResponseModelT, LLMUsage | None]:
    try:
        body = json.loads(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        raise _InvalidStructuredResponse("INVALID_PROVIDER_JSON") from None

    if not isinstance(body, Mapping):
        raise _InvalidStructuredResponse("INVALID_PROVIDER_ENVELOPE")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise _InvalidStructuredResponse("MISSING_PROVIDER_CHOICE")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise _InvalidStructuredResponse("INVALID_PROVIDER_CHOICE")
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise _InvalidStructuredResponse("MISSING_PROVIDER_MESSAGE")
    if message.get("refusal"):
        raise _InvalidStructuredResponse("PROVIDER_REFUSAL")

    parsed = message.get("parsed")
    candidate: Any
    if isinstance(parsed, Mapping):
        candidate = dict(parsed)
    elif isinstance(parsed, str) and parsed.strip():
        candidate = _strip_json_fence(parsed)
    else:
        candidate = _extract_message_content(message.get("content"))

    usage = _extract_usage(body, fallback_model)
    try:
        if isinstance(candidate, Mapping):
            return response_model.model_validate(candidate), usage
        if isinstance(candidate, str):
            return response_model.model_validate_json(candidate), usage
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError):
        raise _InvalidStructuredResponse("SCHEMA_VALIDATION_FAILED") from None
    raise _InvalidStructuredResponse("EMPTY_PROVIDER_CONTENT")


async def _read_bounded_response_body(
    response: httpx.Response,
    *,
    max_bytes: int,
) -> bytes:
    content_encoding = response.headers.get("content-encoding")
    if content_encoding is not None and content_encoding.strip().lower() != "identity":
        raise _InvalidStructuredResponse(
            "UNSUPPORTED_PROVIDER_CONTENT_ENCODING",
            retryable=False,
        )

    declared = response.headers.get("content-length")
    if declared is not None:
        try:
            declared_length = int(declared)
        except ValueError:
            raise _InvalidStructuredResponse(
                "INVALID_PROVIDER_CONTENT_LENGTH",
                retryable=False,
            ) from None
        if declared_length < 0:
            raise _InvalidStructuredResponse(
                "INVALID_PROVIDER_CONTENT_LENGTH",
                retryable=False,
            )
        if declared_length > max_bytes:
            raise _InvalidStructuredResponse(
                "PROVIDER_RESPONSE_TOO_LARGE",
                retryable=False,
            )

    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(chunk) > max_bytes - len(body):
            raise _InvalidStructuredResponse(
                "PROVIDER_RESPONSE_TOO_LARGE",
                retryable=False,
            )
        body.extend(chunk)
    return bytes(body)


def _extract_message_content(content: Any) -> Any:
    if isinstance(content, Mapping):
        return dict(content)
    if isinstance(content, str):
        stripped = content.strip()
        if not stripped:
            raise _InvalidStructuredResponse("EMPTY_PROVIDER_CONTENT")
        return _strip_json_fence(stripped)
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
                continue
            if not isinstance(part, Mapping):
                continue
            text = part.get("text")
            if isinstance(text, str):
                text_parts.append(text)
            elif isinstance(text, Mapping) and isinstance(text.get("value"), str):
                text_parts.append(text["value"])
        joined = "".join(text_parts).strip()
        if joined:
            return _strip_json_fence(joined)
    raise _InvalidStructuredResponse("EMPTY_PROVIDER_CONTENT")


def _strip_json_fence(content: str) -> str:
    match = re.fullmatch(
        r"\s*```(?:json)?\s*(.*?)\s*```\s*", content, re.DOTALL | re.IGNORECASE
    )
    return match.group(1).strip() if match else content.strip()


def _normalize_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(messages, (str, bytes)) or not messages:
        raise ValueError("messages must be a non-empty sequence")
    normalized: list[dict[str, Any]] = []
    for item in messages:
        if not isinstance(item, Mapping):
            raise TypeError("each message must be a mapping")
        role = item.get("role")
        if role not in {"developer", "system", "user", "assistant", "tool"}:
            raise ValueError("each message must use a supported chat role")
        copied = dict(item)
        try:
            json.dumps(copied, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("messages must be JSON serializable") from exc
        normalized.append(copied)
    return normalized


def _validate_response_model(response_model: type[BaseModel]) -> None:
    try:
        valid = isinstance(response_model, type) and issubclass(
            response_model, BaseModel
        )
    except TypeError:
        valid = False
    if not valid:
        raise TypeError("response_model must be a Pydantic BaseModel class")


def _supports_reasoning_effort(model: str) -> bool:
    model_name = model.rsplit("/", 1)[-1].lower()
    return model_name.startswith(("gpt-5", "o1", "o3", "o4"))


def _normalize_schema_name(name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", name).strip("_-")
    if not normalized:
        normalized = "structured_response"
    return normalized[:64]


def _chat_completions_url(base_url: str) -> str:
    return (
        base_url
        if base_url.endswith("/chat/completions")
        else f"{base_url}/chat/completions"
    )


def _is_transient_status(status_code: int) -> bool:
    return status_code in _TRANSIENT_STATUS_CODES or status_code >= 500


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _validate_base_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise _configuration_error("CHAT_PROXY_URL must be an absolute HTTP(S) URL")
    if parsed.scheme != "https" and parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise _configuration_error(
            "CHAT_PROXY_URL must use HTTPS except for a loopback development server"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise _configuration_error(
            "CHAT_PROXY_URL must not contain credentials, query, or fragment"
        )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _parse_float(raw: str | None, *, default: float, setting_name: str) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise _configuration_error(f"{setting_name} must be numeric") from exc


def _parse_int(raw: str | None, *, default: int, setting_name: str) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise _configuration_error(f"{setting_name} must be an integer") from exc


def _configuration_error(message: str) -> LLMConfigurationError:
    return LLMConfigurationError(
        message,
        code="INVALID_CONFIGURATION",
        retryable=False,
    )


__all__ = [
    "LLMBudgetExceededError",
    "LLMCallBudget",
    "LLMClientError",
    "LLMConfig",
    "LLMConfigurationError",
    "LLMRequestError",
    "LLMResponseError",
    "StructuredLLMClient",
    "sanitize_json_schema",
]
