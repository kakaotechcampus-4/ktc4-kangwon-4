"""Metadata-only tracing boundary for the Agent runtime.

Prompt text, evidence excerpts and user-visible prose are intentionally absent
from this interface.  A future Langfuse adapter can implement ``TraceSink``
without changing the graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


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
