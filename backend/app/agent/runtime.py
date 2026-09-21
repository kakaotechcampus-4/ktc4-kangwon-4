"""Composition root: build the Agent once, then run it per request.

Until now the only way to run a planning pass was the CLI, which assembled the
graph inline.  A backend route has nothing to call.  This module is that call.

Two things are deliberately separated:

* **Build once** -- clients, the reviewed procedure store and the trace sink are
  expensive to create and safe to share, so they are built when the process
  starts.
* **Scope per run** -- the call budget and the time limit belong to one run, so
  each ``run_planning`` installs its own.  Sharing them, as the CLI used to,
  means two overlapping requests spend one counter and neither reading is
  right.  That was harmless while only a CLI existed and stops being harmless
  the moment a route serves two users at once.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from app.agent.graph import AgentGraph
from app.agent.info_agent import InfoAnalysisAgent
from app.agent.llm import (
    LLMCallBudget,
    ScopedCallBudget,
    StructuredLLMClient,
    call_budget_scope,
    configuration_error,
    resolve_max_calls_per_run,
)
from app.agent.procedure_tool import (
    JsonFileProcedureStore,
    ReviewedProcedureStore,
    StoredProcedureLookupTool,
)
from app.agent.review_tool import ReviewTool
from app.agent.run_scope import RunDeadline, run_deadline_scope
from app.agent.schemas import (
    AgentGraphInput,
    AgentGraphOutput,
    KnownProcedureStep,
)
from app.agent.supervisor import SupervisorAgent
from app.agent.support_agent import ReviewedSupportCatalog, SupportAgent
from app.agent.support_agent.wiki import SupportWikiStore
from app.agent.tracing import (
    LangfuseTraceSink,
    ScopedUsageAccumulator,
    TraceSink,
    UsageAccumulator,
    usage_scope,
)

__all__ = ["AgentRuntime", "RuntimeLimits", "build_runtime"]

_DEFAULT_RUN_DEADLINE_SECONDS = 60.0
_MAX_RUN_DEADLINE_SECONDS = 600.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    """What one run may spend: provider calls, and wall-clock time.

    Both are cost stops of different kinds. The call cap bounds money; the
    deadline bounds how long a person sits looking at a spinner. Neither
    implies the other, so both are needed.
    """

    max_llm_calls_per_run: int
    run_deadline_seconds: float

    def __post_init__(self) -> None:
        if type(self.max_llm_calls_per_run) is not int or (
            self.max_llm_calls_per_run < 1
        ):
            raise ValueError("max_llm_calls_per_run must be a positive integer")
        if (
            not isinstance(self.run_deadline_seconds, (int, float))
            or isinstance(self.run_deadline_seconds, bool)
            or not 0 < self.run_deadline_seconds <= _MAX_RUN_DEADLINE_SECONDS
        ):
            raise ValueError(
                "run_deadline_seconds must be between 0 and "
                f"{_MAX_RUN_DEADLINE_SECONDS}"
            )


def resolve_run_deadline_seconds(
    *,
    env_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> float:
    """Read ``AGENT_RUN_DEADLINE_SECONDS``, falling back to one minute."""

    environment = os.environ if environ is None else environ
    dotenv_path = Path(env_file) if env_file is not None else _repo_root() / ".env"
    file_values: Mapping[str, str | None] = {}
    if dotenv_path.is_file():
        try:
            file_values = dotenv_values(dotenv_path)
        except (OSError, ValueError) as exc:
            raise configuration_error(
                "Agent runtime environment file could not be read"
            ) from exc
    raw = environment.get("AGENT_RUN_DEADLINE_SECONDS")
    if raw is None:
        raw = file_values.get("AGENT_RUN_DEADLINE_SECONDS")
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return _DEFAULT_RUN_DEADLINE_SECONDS
    try:
        value = float(text)
    except ValueError as exc:
        raise configuration_error(
            "AGENT_RUN_DEADLINE_SECONDS must be a positive number of seconds"
        ) from exc
    if not 0 < value <= _MAX_RUN_DEADLINE_SECONDS:
        raise configuration_error(
            "AGENT_RUN_DEADLINE_SECONDS must be between 0 and "
            f"{_MAX_RUN_DEADLINE_SECONDS}"
        )
    return value


class AgentRuntime:
    """A built Agent that can answer many planning requests."""

    def __init__(
        self,
        *,
        graph: AgentGraph,
        limits: RuntimeLimits,
        clients: Sequence[StructuredLLMClient],
        procedure_tool: StoredProcedureLookupTool,
        trace_sink: TraceSink | None = None,
    ) -> None:
        self._graph = graph
        self._limits = limits
        self._clients = tuple(clients)
        self._procedure_tool = procedure_tool
        self._trace_sink = trace_sink

    @property
    def limits(self) -> RuntimeLimits:
        return self._limits

    async def run_planning(
        self,
        request: AgentGraphInput,
        *,
        deadline_seconds: float | None = None,
    ) -> AgentGraphOutput:
        """Run one planning pass under this run's own budget and deadline.

        ``deadline_seconds`` lets a caller that already has its own timeout --
        an HTTP gateway, say -- hand down whatever time is actually left,
        instead of this runtime assuming it owns the whole window.
        """

        seconds = (
            self._limits.run_deadline_seconds
            if deadline_seconds is None
            else deadline_seconds
        )
        if seconds <= 0:
            raise ValueError("deadline_seconds must be positive")
        budget = LLMCallBudget(max_calls=self._limits.max_llm_calls_per_run)
        usage = UsageAccumulator()
        deadline = RunDeadline.after(seconds)
        with (
            call_budget_scope(budget),
            usage_scope(usage),
            run_deadline_scope(deadline),
        ):
            return await self._graph.run(request)

    async def aclose(self) -> None:
        for client in self._clients:
            await client.aclose()
        await self._procedure_tool.aclose()

    def flush(self) -> None:
        flush = getattr(self._trace_sink, "flush", None)
        if callable(flush):
            flush()


async def build_runtime(
    *,
    known_procedure_steps: Sequence[KnownProcedureStep],
    support_catalog: ReviewedSupportCatalog,
    procedure_store: ReviewedProcedureStore | None = None,
    support_wiki: SupportWikiStore | None = None,
    limits: RuntimeLimits | None = None,
) -> AgentRuntime:
    """Assemble the Agent from environment configuration.

    ``known_procedure_steps`` and ``support_catalog`` stay parameters rather
    than being read here: they are the two inputs that must come from reviewed
    team data. The caller supplies actual backend references; this function
    never generates Case or support identifiers to replace missing data.

    ``procedure_store`` accepts an already loaded snapshot whose ``records()``
    and ``snapshot_version`` are synchronous in-memory reads. The caller must
    preload backend data through agreed BE functions; the Agent executes no
    SQL. Omitting this store retains the environment-configured JSON source.

    ``support_wiki`` optionally resolves exact support ID/UUID pairs from
    reviewed notes before comparison. Misses remain unavailable; they never
    silently use catalog rules or an unimplemented RAG fallback.

    Async only so a half-built runtime can close the transports it already
    opened; nothing here awaits I/O.
    """

    resolved = limits or RuntimeLimits(
        max_llm_calls_per_run=resolve_max_calls_per_run(),
        run_deadline_seconds=resolve_run_deadline_seconds(),
    )
    scoped_budget = ScopedCallBudget()
    scoped_usage = ScopedUsageAccumulator()
    clients: list[StructuredLLMClient] = []
    try:
        client = StructuredLLMClient.from_env(
            call_budget=scoped_budget,
            usage_sink=scoped_usage.record,
        )
        clients.append(client)
        supervisor_client = StructuredLLMClient.from_env(
            env_prefix="SUPERVISOR_",
            call_budget=scoped_budget,
            usage_sink=scoped_usage.record,
        )
        clients.append(supervisor_client)
        resolved_store = (
            JsonFileProcedureStore.from_env()
            if procedure_store is None
            else procedure_store
        )
        procedure_tool = StoredProcedureLookupTool(resolved_store)
        trace_sink = LangfuseTraceSink.from_env()
        graph = AgentGraph(
            info_agent=InfoAnalysisAgent(client),
            procedure_tool=procedure_tool,
            support_agent=SupportAgent(
                client, support_catalog, wiki_store=support_wiki
            ),
            supervisor=SupervisorAgent(supervisor_client),
            review_tool=ReviewTool(client),
            known_procedure_steps=known_procedure_steps,
            # No budget or usage object is handed to the graph: both belong to
            # a run, and run_planning installs them per run.
            trace_sink=trace_sink,
            usage=scoped_usage,
        )
    except Exception:
        # The caller never received the runtime, so nothing else can close
        # these transports.
        for opened in clients:
            await opened.aclose()
        raise
    return AgentRuntime(
        graph=graph,
        limits=resolved,
        clients=clients,
        procedure_tool=procedure_tool,
        trace_sink=trace_sink,
    )
