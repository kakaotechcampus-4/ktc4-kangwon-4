"""Metadata-only tracing boundary for the Agent runtime.

Prompt text, evidence excerpts and user-visible prose are intentionally absent
from this interface.  A future Langfuse adapter can implement ``TraceSink``
without changing the graph.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from dotenv import dotenv_values


@dataclass(frozen=True, slots=True)
class TraceEvent:
    run_id: str
    call_id: str
    component: str
    status: str
    latency_ms: int
    attempt: int
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error_code: str | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


class TraceSink(Protocol):
    def emit(self, event: TraceEvent) -> None: ...


class NullTraceSink:
    def emit(self, event: TraceEvent) -> None:
        del event


@dataclass(slots=True)
class MemoryTraceSink:
    """Test-only sink that retains metadata, never prompt or evidence content."""

    events: list[TraceEvent] = field(default_factory=list)

    def emit(self, event: TraceEvent) -> None:
        self.events.append(event)


@dataclass(slots=True)
class UsageAccumulator:
    """Collect provider usage between two reads.

    One component call can spend several provider calls (local retries), so the
    graph drains the accumulator once per component call and attaches the total
    to that call's trace event.
    """

    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def record(self, usage: Any) -> None:
        self.model = usage.model
        if usage.prompt_tokens is not None:
            self.prompt_tokens = (self.prompt_tokens or 0) + usage.prompt_tokens
        if usage.completion_tokens is not None:
            self.completion_tokens = (
                self.completion_tokens or 0
            ) + usage.completion_tokens

    def drain(self) -> tuple[str | None, int | None, int | None]:
        taken = (self.model, self.prompt_tokens, self.completion_tokens)
        self.model = None
        self.prompt_tokens = None
        self.completion_tokens = None
        return taken


class LangfuseTraceSink:
    """Forward metadata-only trace events to Langfuse.

    Only the fields on ``TraceEvent`` are sent. Prompts, evidence excerpts and
    user text never reach this class, so there is nothing here to redact.
    Telemetry never changes planning: every failure is swallowed.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> LangfuseTraceSink | None:
        """Build a sink when credentials are configured, otherwise ``None``.

        Settings are read the same way the LLM client reads them: the process
        environment wins, then the repository-root ``.env``. Credentials are
        passed to the SDK explicitly because it only inspects ``os.environ``,
        which a ``.env`` file does not populate.
        """

        environment = os.environ if environ is None else environ
        dotenv_path = Path(env_file) if env_file is not None else _repo_root() / ".env"
        file_values: Mapping[str, str | None] = {}
        if dotenv_path.is_file():
            try:
                file_values = dotenv_values(dotenv_path)
            except (OSError, ValueError):
                file_values = {}

        def value(key: str) -> str:
            raw = environment.get(key) or file_values.get(key) or ""
            return str(raw).strip()

        public_key, secret_key = value("LANGFUSE_PUBLIC_KEY"), value("LANGFUSE_SECRET_KEY")
        if not (public_key and secret_key):
            return None
        try:
            from langfuse import Langfuse
        except ImportError:
            return None
        try:
            return cls(
                Langfuse(
                    public_key=public_key,
                    secret_key=secret_key,
                    base_url=value("LANGFUSE_BASE_URL") or None,
                )
            )
        except Exception:  # noqa: BLE001 - observability must not block a run
            return None

    def emit(self, event: TraceEvent) -> None:
        try:
            observation = self._client.start_observation(
                name=event.component,
                as_type="generation",
                model=event.model,
            )
            usage = {}
            if event.prompt_tokens is not None:
                usage["input_tokens"] = event.prompt_tokens
            if event.completion_tokens is not None:
                usage["output_tokens"] = event.completion_tokens
            observation.update(
                metadata={
                    "run_id": event.run_id,
                    "call_id": event.call_id,
                    "status": event.status,
                    "latency_ms": event.latency_ms,
                    "attempt": event.attempt,
                    "error_code": event.error_code,
                },
                **({"usage_details": usage} if usage else {}),
            )
            observation.end()
        except Exception:  # noqa: BLE001 - observability must not change behavior
            return

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception:  # noqa: BLE001 - best-effort delivery on shutdown
            return
