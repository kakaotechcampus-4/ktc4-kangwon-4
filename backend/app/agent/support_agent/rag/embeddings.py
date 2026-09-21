"""Bounded OpenAI-compatible embeddings for offline public-notice indexing.

Callers must supply public notice text or non-personal search terms, never Case
data or raw user messages. The existing sensitive-text guardrail is an extra
check, not proof that arbitrary text is public. This client is independent of
the conversational LLM budget and performs no automatic retries or logging.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import dotenv_values

from app.agent.guardrails import GuardrailViolation, ensure_no_sensitive_text

_TIMEOUT_SECONDS = 20.0
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_TEXTS = 32
_MAX_TEXT_CHARS = 8_000
_MAX_TOTAL_CHARS = 64_000
_MAX_DIMENSIONS = 16_384
_MAX_REQUESTS = 64
_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}")
# Verified against the configured proxy's real response. Do not normalize other
# provider namespaces: a different model must still fail the vector contract.
_VERIFIED_MODEL_ALIAS = (
    "openai/text-embedding-3-small",
    "text-embedding-3-small",
)


class EmbeddingClientError(RuntimeError):
    """Safe operational error; never includes input, response, URL, or token."""

    def __init__(
        self, message: str, *, code: str, status_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _configuration_error() -> EmbeddingClientError:
    return EmbeddingClientError(
        "Public-notice embedding configuration is invalid or incomplete",
        code="INVALID_CONFIGURATION",
    )


def _response_error() -> EmbeddingClientError:
    return EmbeddingClientError(
        "Embedding response failed its format or vector contract",
        code="INVALID_RESPONSE",
    )


def _endpoint(base_url: str) -> str:
    if not isinstance(base_url, str):
        raise _configuration_error()
    raw = base_url.strip().rstrip("/")
    if not raw or any(ord(char) <= 32 or ord(char) == 127 for char in raw):
        raise _configuration_error()
    try:
        parsed = urlsplit(raw)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port == 0
            or (
                parsed.scheme != "https"
                and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            raise _configuration_error()
        path = parsed.path.rstrip("/")
        if not path.endswith("/embeddings"):
            path += "/embeddings"
        endpoint = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        httpx.URL(endpoint)
        return endpoint
    except (ValueError, httpx.InvalidURL):
        raise _configuration_error() from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise ValueError("nonstandard JSON constant")


class EmbeddingClient:
    """One offline client's bounded HTTP allowance and stable embedding space.

    ``expected_dimensions`` validates output only; it does not request dimension
    reduction, which is unsupported by some compatible models. When omitted,
    the first successful response pins the dimension for subsequent calls.
    Responses are returned in input order using their validated ``index``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        model: str,
        expected_dimensions: int | None = None,
        max_requests: int = _MAX_REQUESTS,
    ) -> None:
        endpoint = _endpoint(base_url)
        if (
            not isinstance(api_token, str)
            or not 1 <= len(api_token) <= 8_192
            or any(not 33 <= ord(char) <= 126 for char in api_token)
            or not isinstance(model, str)
            or _MODEL_NAME.fullmatch(model) is None
            or type(max_requests) is not int
            or not 1 <= max_requests <= _MAX_REQUESTS
            or (
                expected_dimensions is not None
                and (
                    type(expected_dimensions) is not int
                    or not 1 <= expected_dimensions <= _MAX_DIMENSIONS
                )
            )
        ):
            raise _configuration_error()
        self._endpoint = endpoint
        self._model = model
        self._reported_model: str | None = None
        self._dimensions = expected_dimensions
        self._max_requests = max_requests
        self._request_count = 0
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {api_token}",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
            timeout=httpx.Timeout(_TIMEOUT_SECONDS),
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
        )

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
        expected_dimensions: int | None = None,
        max_requests: int = _MAX_REQUESTS,
    ) -> Self:
        """Use existing proxy settings; process environment overrides repo .env.

        Keys are ``EMBEDDING_PROXY_URL``, ``PROXY_TOKEN``, and
        ``OPENAI_EMBEDDING_MODEL``. A blank process setting fails validation
        rather than silently restoring a credential or endpoint from the file.
        """

        environment = os.environ if environ is None else environ
        path = (
            Path(env_file)
            if env_file is not None
            else Path(__file__).resolve().parents[5] / ".env"
        )
        try:
            file_values = dotenv_values(path) if path.is_file() else {}

            def value(name: str) -> str:
                raw = environment.get(name)
                if raw is None:
                    raw = file_values.get(name)
                return raw.strip() if isinstance(raw, str) else ""

            return cls(
                base_url=value("EMBEDDING_PROXY_URL"),
                api_token=value("PROXY_TOKEN"),
                model=value("OPENAI_EMBEDDING_MODEL"),
                expected_dimensions=expected_dimensions,
                max_requests=max_requests,
            )
        except (OSError, UnicodeError, TypeError, ValueError):
            raise _configuration_error() from None

    @property
    def model(self) -> str:
        return self._model

    @property
    def reported_model(self) -> str | None:
        """Actual model name from the most recent fully validated response."""

        return self._reported_model

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    @property
    def request_count(self) -> int:
        """HTTP attempts consumed, including provider failures; no implicit reset."""

        return self._request_count

    async def __aenter__(self) -> Self:
        if self._client.is_closed:
            raise EmbeddingClientError(
                "Embedding client is closed", code="CLIENT_CLOSED"
            )
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _validated_texts(self, texts: Sequence[str]) -> list[str]:
        if (
            isinstance(texts, (str, bytes, bytearray))
            or not isinstance(texts, Sequence)
            or not 1 <= len(texts) <= _MAX_TEXTS
        ):
            raise EmbeddingClientError(
                "Embedding input must contain 1 to 32 public text chunks",
                code="INVALID_INPUT",
            )
        values = list(texts)
        if (
            any(
                not isinstance(text, str)
                or not text.strip()
                or len(text) > _MAX_TEXT_CHARS
                for text in values
            )
            or sum(map(len, values)) > _MAX_TOTAL_CHARS
        ):
            raise EmbeddingClientError(
                "Embedding text exceeds its nonempty or size contract",
                code="INVALID_INPUT",
            )
        try:
            ensure_no_sensitive_text(values)
            # Reject invalid Unicode before HTTP serialization can expose it in
            # an encoding exception. Source text is otherwise left unchanged.
            for text in values:
                text.encode("utf-8")
        except (GuardrailViolation, UnicodeError):
            raise EmbeddingClientError(
                "Embedding input failed its public-text guardrail",
                code="INVALID_INPUT",
            ) from None
        return values

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        values = self._validated_texts(texts)
        if self._client.is_closed:
            raise EmbeddingClientError(
                "Embedding client is closed", code="CLIENT_CLOSED"
            )
        if self._request_count >= self._max_requests:
            raise EmbeddingClientError(
                "Offline embedding request allowance is exhausted",
                code="REQUEST_LIMIT_REACHED",
            )
        # No await before increment: concurrent calls on this event loop share
        # the same allowance. Each call performs exactly one HTTP attempt.
        self._request_count += 1
        try:
            async with asyncio.timeout(_TIMEOUT_SECONDS):
                async with self._client.stream(
                    "POST",
                    self._endpoint,
                    json={
                        "model": self._model,
                        "input": values,
                        "encoding_format": "float",
                    },
                ) as response:
                    if response.status_code != 200:
                        raise EmbeddingClientError(
                            "Embedding provider rejected the request",
                            code="REQUEST_FAILED",
                            status_code=response.status_code,
                        )
                    media_type = (
                        response.headers.get("content-type", "")
                        .split(";", 1)[0]
                        .strip()
                        .lower()
                    )
                    if media_type != "application/json" and not media_type.endswith(
                        "+json"
                    ):
                        raise _response_error()
                    declared_size = response.headers.get("content-length")
                    if declared_size is not None and (
                        not declared_size.isdecimal()
                        or len(declared_size) > 10
                        or int(declared_size) > _MAX_RESPONSE_BYTES
                    ):
                        raise _response_error()
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65_536):
                        if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                            raise _response_error()
                        body.extend(chunk)
                return self._vectors(bytes(body), len(values))
        except (httpx.HTTPError, OSError, TimeoutError):
            raise EmbeddingClientError(
                "Embedding request could not complete within its network limits",
                code="REQUEST_FAILED",
            ) from None
        except (UnicodeError, TypeError, ValueError, OverflowError, RecursionError):
            raise _response_error() from None

    def _vectors(self, body: bytes, expected_count: int) -> list[list[float]]:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if (
            not isinstance(payload, dict)
            or payload.get("object") != "list"
            or not isinstance(payload.get("model"), str)
            or (
                payload["model"] != self._model
                and (self._model, payload["model"]) != _VERIFIED_MODEL_ALIAS
            )
            or not isinstance(payload.get("data"), list)
            or len(payload["data"]) != expected_count
        ):
            raise _response_error()
        vectors: dict[int, list[float]] = {}
        dimension = self._dimensions
        for item in payload["data"]:
            if not isinstance(item, dict) or item.get("object") != "embedding":
                raise _response_error()
            index = item.get("index")
            vector = item.get("embedding")
            if (
                type(index) is not int
                or not 0 <= index < expected_count
                or index in vectors
                or not isinstance(vector, list)
                or not 1 <= len(vector) <= _MAX_DIMENSIONS
            ):
                raise _response_error()
            if dimension is None:
                dimension = len(vector)
            if len(vector) != dimension or any(
                type(value) not in {int, float} or not math.isfinite(value)
                for value in vector
            ):
                raise _response_error()
            vectors[index] = [float(value) for value in vector]
        # Pin only after validating the entire response; partial or failed
        # provider data must not change the client's embedding-space contract.
        self._dimensions = dimension
        self._reported_model = payload["model"]
        return [vectors[index] for index in range(expected_count)]


__all__ = ["EmbeddingClient", "EmbeddingClientError"]
