"""Build shared Agent clients and isolate each request's budget and deadline."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from app.agent.action_catalog import ProcedureBindings, resolve_procedure_bindings
from app.agent.content_safety import ContentSafetyGuard
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
    ReviewedProcedureStore,
    StoredProcedureLookupTool,
)
from app.agent.review_tool import ReviewTool
from app.agent.run_scope import RunDeadline, current_deadline, run_deadline_scope
from app.agent.schemas import CaseFact, KnownProcedureStep, RedactedInput
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
from app.common.agent_dto import AgentGraphInput, AgentGraphOutput

__all__ = ["AgentRuntime", "RuntimeLimits", "build_runtime"]

_DEFAULT_RUN_DEADLINE_SECONDS = 420.0
_MAX_RUN_DEADLINE_SECONDS = 600.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    """Provider-call and wall-clock limits for one planning run."""

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
    """Read ``AGENT_RUN_DEADLINE_SECONDS``, falling back to seven minutes."""

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
        submission_safety: ContentSafetyGuard | None = None,
    ) -> None:
        self._graph = graph
        self._limits = limits
        self._clients = tuple(clients)
        self._procedure_tool = procedure_tool
        self._trace_sink = trace_sink
        self._submission_safety = submission_safety

    @property
    def limits(self) -> RuntimeLimits:
        return self._limits

    async def run_planning(
        self,
        request: AgentGraphInput,
        *,
        deadline_seconds: float | None = None,
    ) -> AgentGraphOutput:
        """Run with an isolated budget and the caller's remaining time limit."""

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
        outer_deadline = current_deadline()
        if outer_deadline is not None:
            deadline = RunDeadline(min(deadline.expires_at, outer_deadline.expires_at))
        with (
            call_budget_scope(budget),
            usage_scope(usage),
            run_deadline_scope(deadline),
        ):
            return await self._graph.run(request)

    async def check_submission(
        self, redacted_text: str | RedactedInput, facts: Sequence[CaseFact] = (),
    ) -> None:
        """BE may call this before saving, without inventing a Case/snapshot ID.

        ALLOW returns None; refusal/unavailability raises the safety exception.
        Crisis support raises its signal only after checking the fixed guidance;
        BE must stop saving business data and return that guidance to the user.
        This performs no storage, redaction, authentication or user messaging.
        """
        if self._submission_safety is None:
            raise configuration_error("submission safety is not configured")
        budget = LLMCallBudget(max_calls=self._limits.max_llm_calls_per_run)
        deadline = RunDeadline.after(self._limits.run_deadline_seconds)
        outer = current_deadline()
        if outer is not None:
            deadline = RunDeadline(min(deadline.expires_at, outer.expires_at))
        with (call_budget_scope(budget), usage_scope(UsageAccumulator()), run_deadline_scope(deadline)):
            deadline.check()
            await self._submission_safety.check_submission(redacted_text, facts)

    async def aclose(self) -> None:
        # Cleanup must attempt every transport and must not discard a reviewed
        # outcome because one provider's connection failed to close.
        await asyncio.gather(
            *(client.aclose() for client in self._clients),
            self._procedure_tool.aclose(),
            return_exceptions=True,
        )

    def flush(self) -> None:
        flush = getattr(self._trace_sink, "flush", None)
        if callable(flush):
            flush()


async def build_runtime(
    *,
    known_procedure_steps: Sequence[KnownProcedureStep],
    support_catalog: ReviewedSupportCatalog,
    procedure_store: ReviewedProcedureStore,
    procedure_bindings: ProcedureBindings | None = None,
    support_wiki: SupportWikiStore | None = None,
    limits: RuntimeLimits | None = None,
) -> AgentRuntime:
    """Assemble the Agent with reviewed data supplied by the caller.

    An empty store stays empty: the caller states what it has, and that
    statement is not overridden here. Source text and evidence IDs come from
    the BE Case snapshot; missing DB sources stay unavailable. No SQL runs
    here. Wiki misses also remain unavailable.
    """

    bindings = resolve_procedure_bindings(known_procedure_steps, procedure_bindings)
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
        info_client = StructuredLLMClient.from_env(
            env_prefix="INFO_",
            call_budget=scoped_budget,
            usage_sink=scoped_usage.record,
        )
        clients.append(info_client)
        procedure_tool = StoredProcedureLookupTool(
            procedure_store, procedure_bindings=bindings
        )
        trace_sink = LangfuseTraceSink.from_env()
        safety = ContentSafetyGuard(client)
        graph = AgentGraph(
            info_agent=InfoAnalysisAgent(info_client, procedure_bindings=bindings),
            procedure_tool=procedure_tool,
            support_agent=SupportAgent(
                client, support_catalog, wiki_store=support_wiki
            ),
            supervisor=SupervisorAgent(supervisor_client, procedure_bindings=bindings),
            review_tool=ReviewTool(client, procedure_bindings=bindings),
            content_safety=safety,
            known_procedure_steps=known_procedure_steps,
            # No budget or usage object is handed to the graph: both belong to
            # a run, and run_planning installs them per run.
            trace_sink=trace_sink,
            usage=scoped_usage,
        )
    except Exception:
        # The caller never received the runtime, so nothing else can close
        # these transports.
        await asyncio.gather(
            *(opened.aclose() for opened in clients), return_exceptions=True
        )
        raise

    return AgentRuntime(
        graph=graph,
        limits=resolved,
        clients=clients,
        procedure_tool=procedure_tool,
        trace_sink=trace_sink,
        submission_safety=safety,
    )
