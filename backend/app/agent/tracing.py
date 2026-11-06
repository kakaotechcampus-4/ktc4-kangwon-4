"""Metadata-only tracing boundary for the Agent runtime.

Prompt text, evidence excerpts and user-visible prose are intentionally absent
from this interface, so nothing a sink forwards can carry user data.  The
default sink discards events; ``LangfuseTraceSink`` forwards them and is used
only when both Langfuse credentials resolve.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager, suppress
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Literal, Protocol

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
    # How many provider HTTP calls this event covers. ``attempt`` is the
    # component's semantic attempt number, which can hide several HTTP calls,
    # so it cannot answer "how much of the run budget did this spend".
    provider_calls: int | None = None
    outcome_type: str | None = None
    # A successful Review call may return REVISE; status describes execution,
    # while this bounded value records the independent review decision.
    review_verdict: Literal["PASS", "REVISE"] | None = None
    # 모델이 쓴 사실·문장이 없는 판단은 Review 모델 없이 코드 검사만 한다(CODE_ONLY).
    review_mode: Literal["MODEL", "CODE_ONLY"] | None = None
    # RUN-only totals: returned verdicts, returned REVISE verdicts, and distinct
    # rework rounds that actually reached a component call after its deadline check.
    # Failed review calls are not verdicts and do not enter review_count.
    review_count: int | None = None
    review_revise_count: int | None = None
    rework_count: int | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


class TraceSink(Protocol):
    def emit(self, event: TraceEvent) -> None: ...


class NullTraceSink:
    def emit(self, event: TraceEvent) -> None:
        del event


_CURRENT_SINK: ContextVar[Any] = ContextVar("agent_trace_sink", default=None)
_CURRENT_OBSERVATION: ContextVar[Any] = ContextVar("agent_observation", default=None)
_CURRENT_COMPONENT: ContextVar[str | None] = ContextVar("agent_trace_component", default=None)
_CAPTURED_USAGE: ContextVar[list[Any] | None] = ContextVar("agent_captured_usage", default=None)


@contextmanager
def capture_usage() -> Iterator[list[Any]]:
    """Capture provider attempts for an evaluation, without prompts or secrets."""
    calls: list[Any] = []
    token = _CAPTURED_USAGE.set(calls)
    try:
        yield calls
    finally:
        _CAPTURED_USAGE.reset(token)


@contextmanager
def observation_scope(name: str, *, sink: Any = None, **options: Any) -> Iterator[Any]:
    """Keep actual timing and parentage; telemetry errors never escape."""
    resolved = sink if sink is not None else _CURRENT_SINK.get()
    stack = ExitStack()
    observation = None
    try:
        if isinstance(resolved, LangfuseTraceSink):
            observation = stack.enter_context(
                resolved._client.start_as_current_observation(name=name, **options)
            )
    except Exception:  # noqa: BLE001 - telemetry cannot prevent business work
        with suppress(Exception):
            stack.close()
    sink_token = _CURRENT_SINK.set(resolved)
    observation_token = _CURRENT_OBSERVATION.set(observation)
    component_token = _CURRENT_COMPONENT.set(
        _CURRENT_COMPONENT.get() if options.get("as_type") == "generation" else name
    )
    try:
        yield observation
    except BaseException as exc:
        update_observation(level="ERROR", metadata={"error_type": type(exc).__name__})
        raise
    finally:
        _CURRENT_COMPONENT.reset(component_token)
        _CURRENT_OBSERVATION.reset(observation_token)
        _CURRENT_SINK.reset(sink_token)
        with suppress(Exception):
            stack.close()


def update_observation(**values: Any) -> None:
    observation = _CURRENT_OBSERVATION.get()
    if observation is not None:
        with suppress(Exception):
            observation.update(**values)


def traced_component(name: str):
    """Wrap an existing graph method without changing its input or output."""
    def decorate(method):
        @wraps(method)
        async def wrapped(self, *args, **kwargs):
            with observation_scope(name, sink=self._trace_sink, as_type="span"):
                return await method(self, *args, **kwargs)
        return wrapped
    return decorate


def record_provider_usage(usage: Any) -> None:
    calls = _CAPTURED_USAGE.get()
    if calls is not None:
        calls.append(usage)
    details = {}
    # Reasoning is a subset of completion tokens; cache reads are a subset of
    # prompt tokens. Send exclusive categories so Langfuse cannot count twice.
    for total_key, detail_key, total, subset in (
        ("input", "input_cached", usage.prompt_tokens, usage.cached_prompt_tokens),
        ("output", "output_reasoning", usage.completion_tokens, usage.reasoning_tokens),
    ):
        if total is not None:
            if subset is not None and subset <= total:
                details[detail_key], details[total_key] = subset, total - subset
            else:
                details[total_key] = total
    update_observation(
        model=usage.model,
        level="ERROR" if usage.status == "ERROR" else "DEFAULT",
        metadata={
            "component": _CURRENT_COMPONENT.get() or usage.schema_name,
            "usage_complete": usage.prompt_tokens is not None and usage.completion_tokens is not None,
            **{
                key: getattr(usage, key) for key in (
                    "schema_name", "attempt", "reasoning_effort", "status", "status_code",
                    "error_code", "latency_ms", "requested_model", "prompt_tokens",
                    "completion_tokens", "cached_prompt_tokens", "reasoning_tokens",
                )
            },
        },
        model_parameters={"reasoning_effort": usage.reasoning_effort},
        **({"usage_details": details} if details else {}),
    )


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

    def reset(self) -> None:
        self.model = None
        self.prompt_tokens = None
        self.completion_tokens = None

    def drain(self) -> tuple[str | None, int | None, int | None]:
        taken = (self.model, self.prompt_tokens, self.completion_tokens)
        self.reset()
        return taken


_CURRENT_USAGE: ContextVar[UsageAccumulator | None] = ContextVar(
    "agent_usage_accumulator",
    default=None,
)


@contextmanager
def usage_scope(usage: UsageAccumulator) -> Iterator[UsageAccumulator]:
    """Install ``usage`` as the accumulator for work done inside this block."""

    token = _CURRENT_USAGE.set(usage)
    try:
        yield usage
    finally:
        _CURRENT_USAGE.reset(token)


@dataclass(slots=True)
class ScopedUsageAccumulator:
    """Usage stand-in that defers to whichever run is currently in scope.

    Same reason as the call budget: a client is built once and serves many
    runs, so token counts must follow the run rather than sit on the client.
    Outside any run scope it records nothing, which keeps direct client use in
    tests and scripts working unchanged.
    """

    def record(self, usage: Any) -> None:
        accumulator = _CURRENT_USAGE.get()
        if accumulator is not None:
            accumulator.record(usage)

    def reset(self) -> None:
        accumulator = _CURRENT_USAGE.get()
        if accumulator is not None:
            accumulator.reset()

    def drain(self) -> tuple[str | None, int | None, int | None]:
        accumulator = _CURRENT_USAGE.get()
        if accumulator is None:
            return (None, None, None)
        return accumulator.drain()


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

        public_key, secret_key = (
            value("LANGFUSE_PUBLIC_KEY"),
            value("LANGFUSE_SECRET_KEY"),
        )
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
        values = {
            "metadata": asdict(event),
            "level": "ERROR" if event.status == "ERROR" else "DEFAULT",
        }
        # Only actual HTTP attempts are generations with usage. Component and
        # RUN summaries must not charge the same tokens again.
        if _CURRENT_OBSERVATION.get() is not None:
            update_observation(**values)
        else:
            with observation_scope(event.component, sink=self, as_type="span"):
                update_observation(**values)

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception:  # noqa: BLE001 - best-effort delivery on shutdown
            return
