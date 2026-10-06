"""Build shared Agent clients and isolate each request's budget and deadline."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from app.agent import prompts
from app.agent.action_catalog import ProcedureBindings, resolve_procedure_bindings
from app.agent.decision_cache import DecisionCache, fingerprint
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
from app.agent.schemas import KnownProcedureStep
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
from app.common.agent_data import load_reviewed_procedures
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
        decision_cache: DecisionCache | None = None,
        cache_context: Callable[[], Mapping[str, object] | None] | None = None,
    ) -> None:
        self._graph = graph
        self._limits = limits
        self._clients = tuple(clients)
        self._procedure_tool = procedure_tool
        self._trace_sink = trace_sink
        self._decision_cache = decision_cache
        self._cache_context = cache_context

    @property
    def limits(self) -> RuntimeLimits:
        return self._limits

    @property
    def decision_cache(self) -> DecisionCache | None:
        """Inspect, clear, or invalidate a Case without exposing cached data."""

        return self._decision_cache

    def _cache_key(self, request: AgentGraphInput) -> str | None:
        if self._decision_cache is None or self._cache_context is None:
            return None
        try:
            context = self._cache_context()
            return (
                self._decision_cache.key(request, context)
                if context is not None
                else None
            )
        except Exception:  # noqa: BLE001 - cache failure must defer to the Graph
            return None

    async def run_planning(
        self,
        request: AgentGraphInput,
        *,
        deadline_seconds: float | None = None,
        use_cache: bool = True,
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
            cache = self._decision_cache if use_cache else None
            key = self._cache_key(request) if cache is not None else None
            if key is not None and not deadline.is_expired():
                cached = cache.get(key)
                if cached is not None and not deadline.is_expired():
                    # Preserve the original run, subject and proof; this is reuse.
                    return cached
            outcome = await self._graph.run(request)
            if (
                key is not None
                and not deadline.is_expired()
                and self._cache_key(request) == key
            ):
                cache.put(key, request, outcome)
            return outcome

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
    use_decision_cache: bool = True,
) -> AgentRuntime:
    """Assemble the Agent with reviewed data supplied by the caller.

    An empty store uses the bundled review metadata. Source text and evidence
    IDs must still come from the BE Case snapshot; missing DB sources stay
    unavailable. No SQL runs here. Wiki misses also remain unavailable.
    """

    if not procedure_store.records():
        procedure_store = load_reviewed_procedures()
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
        graph = AgentGraph(
            info_agent=InfoAnalysisAgent(info_client, procedure_bindings=bindings),
            procedure_tool=procedure_tool,
            support_agent=SupportAgent(
                client, support_catalog, wiki_store=support_wiki
            ),
            supervisor=SupervisorAgent(supervisor_client, procedure_bindings=bindings),
            review_tool=ReviewTool(client, procedure_bindings=bindings),
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

    def cache_context() -> Mapping[str, object] | None:
        # Wiki lookup has no revision/expiry contract. Re-fetch it through the
        # graph instead of claiming that an earlier lookup remains valid.
        if support_wiki is not None:
            return None
        records = list(procedure_store.records())
        today = datetime.now(timezone.utc).date()
        if any(record.freshness(today) != "CURRENT" for record in records):
            return None
        if any(
            evidence.freshness_status != "CURRENT"
            for evidence in support_catalog.evidence_records
        ):
            return None
        return {
            "models": [fingerprint(asdict(item.config)) for item in clients],
            "registry": [
                step.model_dump(mode="json") for step in known_procedure_steps
            ],
            "procedure_bindings": {
                key: reference.model_dump(mode="json")
                for key, reference in bindings.items()
            },
            "catalog": support_catalog.model_dump(mode="json"),
            "store_version": procedure_store.snapshot_version,
            "procedure_records": [record.model_dump(mode="json") for record in records],
            "prompts": [
                factory({})
                for factory in (
                    prompts.info_messages,
                    prompts.support_messages,
                    prompts.supervisor_messages,
                    prompts.review_messages,
                )
            ],
        }

    return AgentRuntime(
        graph=graph,
        limits=resolved,
        clients=clients,
        procedure_tool=procedure_tool,
        trace_sink=trace_sink,
        decision_cache=DecisionCache() if use_decision_cache else None,
        cache_context=cache_context if use_decision_cache else None,
    )
