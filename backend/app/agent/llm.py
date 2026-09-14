"""Small OpenAI-compatible client for Agent structured outputs.

The Agent runtime talks to the configured chat proxy directly through ``httpx``.
This module deliberately does not log prompts, responses, endpoint URLs, or
credentials: all of those can contain user data or deployment details.
"""

from __future__ import annotations

import asyncio
import json
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

_DEFAULT_TIMEOUT_SECONDS = 45.0
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_RETRY_BACKOFF_SECONDS = 0.25
_MAX_ALLOWED_RETRIES = 4
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _validate_base_url(self.base_url))

        if not self.api_token.strip():
            raise _configuration_error("PROXY_TOKEN is required")
        if not self.model.strip():
            raise _configuration_error("OPENAI_MODEL is required")
        if self.timeout_seconds <= 0:
            raise _configuration_error("Agent LLM timeout must be positive")
        if not 0 <= self.max_retries <= _MAX_ALLOWED_RETRIES:
            raise _configuration_error(
                f"Agent LLM retries must be between 0 and {_MAX_ALLOWED_RETRIES}"
            )
        if self.retry_backoff_seconds < 0:
            raise _configuration_error("Agent LLM retry backoff cannot be negative")

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> LLMConfig:
        """Load settings with process environment taking precedence over `.env`.

        By default the repository-root ``.env`` is loaded, independent of the
        current working directory. Tests can inject both the file and mapping.
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

        def value(key: str) -> str | None:
            raw = environment.get(key)
            if raw is None:
                raw = file_values.get(key)
            if raw is None:
                return None
            normalized = str(raw).strip()
            return normalized or None

        base_url = value("CHAT_PROXY_URL")
        api_token = value("PROXY_TOKEN")
        model = value("OPENAI_MODEL")
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

        return cls(
            base_url=base_url or "",
            api_token=api_token or "",
            model=model or "",
            reasoning_effort=value("OPENAI_REASONING_EFFORT"),
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
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
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("Pass either an HTTP client or a transport, not both")

        self.config = config
        self._sleep = sleep
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
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepCallable = asyncio.sleep,
    ) -> StructuredLLMClient:
        return cls(
            LLMConfig.from_env(env_file=env_file, environ=environ),
            client=client,
            transport=transport,
            sleep=sleep,
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
        if not 0 <= retries <= _MAX_ALLOWED_RETRIES:
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
            try:
                response = await self._client.post(
                    _chat_completions_url(self.config.base_url),
                    headers={
                        "Authorization": f"Bearer {self.config.api_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except (httpx.TimeoutException, httpx.TransportError):
                last_failure_code = "UPSTREAM_UNAVAILABLE"
                if attempt < total_attempts:
                    await self._backoff(attempt_index)
                    continue
                raise LLMRequestError(
                    f"LLM provider request failed after {attempt} attempt(s)",
                    code=last_failure_code,
                    retryable=True,
                    attempts=attempt,
                ) from None

            last_status_code = response.status_code
            if not response.is_success:
                retryable = _is_transient_status(response.status_code)
                if retryable and attempt < total_attempts:
                    await self._backoff(attempt_index)
                    continue
                raise LLMRequestError(
                    f"LLM provider returned HTTP {response.status_code} after "
                    f"{attempt} attempt(s)",
                    code="UPSTREAM_HTTP_ERROR",
                    retryable=retryable,
                    attempts=attempt,
                    status_code=response.status_code,
                )

            try:
                return _parse_response(response, response_model)
            except _InvalidStructuredResponse as exc:
                last_failure_code = exc.code
                if attempt < total_attempts:
                    await self._backoff(attempt_index)
                    continue
                raise LLMResponseError(
                    f"LLM structured response failed local validation after "
                    f"{attempt} attempt(s)",
                    code=last_failure_code,
                    retryable=True,
                    attempts=attempt,
                    status_code=last_status_code,
                ) from None

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
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _parse_response(
    response: httpx.Response,
    response_model: type[ResponseModelT],
) -> ResponseModelT:
    try:
        body = response.json()
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

    try:
        if isinstance(candidate, Mapping):
            return response_model.model_validate(candidate)
        if isinstance(candidate, str):
            return response_model.model_validate_json(candidate)
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError):
        raise _InvalidStructuredResponse("SCHEMA_VALIDATION_FAILED") from None
    raise _InvalidStructuredResponse("EMPTY_PROVIDER_CONTENT")


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
    "LLMClientError",
    "LLMConfig",
    "LLMConfigurationError",
    "LLMRequestError",
    "LLMResponseError",
    "StructuredLLMClient",
    "sanitize_json_schema",
]
