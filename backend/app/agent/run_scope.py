"""Per-run limits that follow one planning run without being passed by hand.

Two limits bound a run: how many provider calls it may spend, and how long it
may take in total.  Both are properties of *a run*, not of a client, but the
code that has to honour them sits several layers down -- inside the HTTP client
and inside each graph node.

Threading two extra arguments through every Agent, Tool and protocol would
touch a lot of signatures for something no caller chooses per call.  A context
variable carries them instead: ``asyncio`` copies the context into each task,
so two runs in one process get their own limits rather than sharing a single
mutable counter.  That sharing is the bug ``llm.py`` warned about, and it turns
real the moment this runtime is served from an HTTP route.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

__all__ = [
    "RunDeadline",
    "RunDeadlineExceededError",
    "current_deadline",
    "run_deadline_scope",
]


class RunDeadlineExceededError(RuntimeError):
    """Raised when a run has no time left to do more work.

    Carries the same ``code``/``retryable`` shape the LLM client errors use so
    the graph can classify it the same way.
    """

    def __init__(self, message: str = "run exceeded its time limit") -> None:
        super().__init__(message)
        self.code = "RUN_DEADLINE_EXCEEDED"
        self.retryable = False


@dataclass(frozen=True, slots=True)
class RunDeadline:
    """A monotonic instant after which a run must stop producing work.

    Monotonic rather than wall-clock on purpose: a clock adjustment during a
    run must not extend or cut the budget.
    """

    expires_at: float

    @classmethod
    def after(cls, seconds: float) -> RunDeadline:
        if seconds <= 0:
            raise ValueError("run deadline must be a positive number of seconds")
        return cls(expires_at=time.monotonic() + seconds)

    def remaining_seconds(self) -> float:
        return self.expires_at - time.monotonic()

    def is_expired(self) -> bool:
        return self.remaining_seconds() <= 0

    def check(self) -> None:
        if self.is_expired():
            raise RunDeadlineExceededError()


_CURRENT_DEADLINE: ContextVar[RunDeadline | None] = ContextVar(
    "agent_run_deadline",
    default=None,
)


def current_deadline() -> RunDeadline | None:
    """Return the deadline of the run in progress, if one was installed.

    ``None`` means unbounded, which is what a unit test or a one-off script
    gets. Only the runtime installs a deadline.
    """

    return _CURRENT_DEADLINE.get()


@contextmanager
def run_deadline_scope(deadline: RunDeadline | None) -> Iterator[RunDeadline | None]:
    token = _CURRENT_DEADLINE.set(deadline)
    try:
        yield deadline
    finally:
        _CURRENT_DEADLINE.reset(token)
