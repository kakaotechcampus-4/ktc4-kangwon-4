from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from app.agent import runtime as runtime_module
from app.agent.llm import (
    LLMBudgetExceededError,
    LLMCallBudget,
    LLMConfigurationError,
    ScopedCallBudget,
    call_budget_scope,
    current_call_budget,
    resolve_max_calls_per_run,
)
from app.agent.procedure_tool import (
    JsonFileProcedureStore,
    ProcedureStoreError,
    ReviewedProcedureRecord,
)
from app.agent.run_scope import (
    RunDeadline,
    RunDeadlineExceededError,
    current_deadline,
    run_deadline_scope,
)
from app.agent.runtime import RuntimeLimits, build_runtime, resolve_run_deadline_seconds
from app.agent.schemas import ProcedureLookupInput, ProcedureLookupResult
from app.agent.support_agent import ReviewedSupportCatalog
from app.agent.tracing import (
    ScopedUsageAccumulator,
    UsageAccumulator,
    usage_scope,
)


class Usage:
    def __init__(self, prompt: int, completion: int) -> None:
        self.model = "test-model"
        self.prompt_tokens = prompt
        self.completion_tokens = completion


def env(**values: str) -> dict[str, str]:
    return dict(values)


def test_call_budget_limit_comes_from_the_environment() -> None:
    assert (
        resolve_max_calls_per_run(
            env_file="/nonexistent",
            environ=env(AGENT_MAX_LLM_CALLS_PER_RUN="12"),
        )
        == 12
    )


def test_call_budget_limit_falls_back_to_forty() -> None:
    assert resolve_max_calls_per_run(env_file="/nonexistent", environ={}) == 40


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5"])
def test_call_budget_limit_rejects_a_value_that_is_not_a_positive_count(
    value: str,
) -> None:
    with pytest.raises(LLMConfigurationError):
        resolve_max_calls_per_run(
            env_file="/nonexistent",
            environ=env(AGENT_MAX_LLM_CALLS_PER_RUN=value),
        )


def test_run_deadline_comes_from_the_environment() -> None:
    assert (
        resolve_run_deadline_seconds(
            env_file="/nonexistent",
            environ=env(AGENT_RUN_DEADLINE_SECONDS="30"),
        )
        == 30.0
    )


def test_run_deadline_falls_back_to_one_minute() -> None:
    assert resolve_run_deadline_seconds(env_file="/nonexistent", environ={}) == 60.0


@pytest.mark.parametrize("value", ["0", "-5", "abc", "601"])
def test_run_deadline_rejects_an_unusable_value(value: str) -> None:
    with pytest.raises(LLMConfigurationError):
        resolve_run_deadline_seconds(
            env_file="/nonexistent",
            environ=env(AGENT_RUN_DEADLINE_SECONDS=value),
        )


@pytest.mark.parametrize(
    ("calls", "seconds"),
    [(0, 60.0), (-1, 60.0), (40, 0.0), (40, -1.0), (40, 601.0)],
)
def test_runtime_limits_reject_values_that_bound_nothing(
    calls: int,
    seconds: float,
) -> None:
    with pytest.raises(ValueError):
        RuntimeLimits(max_llm_calls_per_run=calls, run_deadline_seconds=seconds)


def test_no_budget_is_installed_outside_a_run() -> None:
    assert current_call_budget() is None
    # A client used directly, as in a script or a unit test, is not charged.
    ScopedCallBudget().consume()


def test_the_scoped_budget_charges_the_run_in_scope() -> None:
    budget = LLMCallBudget(max_calls=2)
    scoped = ScopedCallBudget()
    with call_budget_scope(budget):
        scoped.consume()
        scoped.consume()
        with pytest.raises(LLMBudgetExceededError) as caught:
            scoped.consume()

    assert caught.value.code == "LOOP_LIMIT_REACHED"
    assert budget.spent == 2
    assert current_call_budget() is None


def test_two_concurrent_runs_do_not_spend_each_others_budget() -> None:
    """The reason this module exists.

    A single shared counter was fine while only a CLI ran one thing at a time.
    Served from a route, two overlapping requests would spend one counter and
    neither reading would be right -- one user could exhaust another's budget.
    """

    scoped = ScopedCallBudget()
    budgets: dict[str, LLMCallBudget] = {}

    async def run(name: str, calls: int) -> None:
        budget = LLMCallBudget(max_calls=10)
        budgets[name] = budget
        with call_budget_scope(budget):
            for _ in range(calls):
                scoped.consume()
                await asyncio.sleep(0)

    async def both() -> None:
        await asyncio.gather(run("a", 3), run("b", 5))

    asyncio.run(both())

    assert budgets["a"].spent == 3
    assert budgets["b"].spent == 5


def test_two_concurrent_runs_do_not_mix_token_counts() -> None:
    scoped = ScopedUsageAccumulator()
    totals: dict[str, Any] = {}

    async def run(name: str, tokens: int) -> None:
        accumulator = UsageAccumulator()
        with usage_scope(accumulator):
            scoped.record(Usage(tokens, tokens))
            await asyncio.sleep(0)
            totals[name] = scoped.drain()

    async def both() -> None:
        await asyncio.gather(run("a", 10), run("b", 500))

    asyncio.run(both())

    assert totals["a"] == ("test-model", 10, 10)
    assert totals["b"] == ("test-model", 500, 500)


def test_usage_recorded_outside_a_run_is_dropped_rather_than_leaking() -> None:
    scoped = ScopedUsageAccumulator()
    scoped.record(Usage(7, 7))

    assert scoped.drain() == (None, None, None)


def test_no_deadline_is_installed_outside_a_run() -> None:
    assert current_deadline() is None


def test_a_deadline_reports_the_time_it_has_left() -> None:
    deadline = RunDeadline.after(5)

    assert 0 < deadline.remaining_seconds() <= 5
    assert not deadline.is_expired()
    deadline.check()


def test_an_expired_deadline_refuses_further_work() -> None:
    deadline = RunDeadline(expires_at=time.monotonic() - 1)

    assert deadline.is_expired()
    with pytest.raises(RunDeadlineExceededError) as caught:
        deadline.check()
    assert caught.value.code == "RUN_DEADLINE_EXCEEDED"
    assert caught.value.retryable is False


@pytest.mark.parametrize("seconds", [0, -1])
def test_a_deadline_must_bound_something(seconds: float) -> None:
    with pytest.raises(ValueError):
        RunDeadline.after(seconds)


def test_two_concurrent_runs_keep_their_own_deadline() -> None:
    seen: dict[str, float] = {}

    async def run(name: str, seconds: float) -> None:
        with run_deadline_scope(RunDeadline.after(seconds)):
            await asyncio.sleep(0)
            deadline = current_deadline()
            assert deadline is not None
            seen[name] = deadline.remaining_seconds()

    async def both() -> None:
        await asyncio.gather(run("short", 1), run("long", 100))

    asyncio.run(both())

    assert seen["short"] < seen["long"]
    assert current_deadline() is None


@pytest.fixture
def runtime_clients(monkeypatch: pytest.MonkeyPatch) -> list[Mock]:
    clients = [Mock(aclose=AsyncMock()), Mock(aclose=AsyncMock())]
    monkeypatch.setattr(
        runtime_module.StructuredLLMClient, "from_env", Mock(side_effect=clients)
    )
    monkeypatch.setattr(
        runtime_module.LangfuseTraceSink, "from_env", Mock(return_value=None)
    )
    return clients


@pytest.fixture
def runtime_options() -> dict[str, Any]:
    return {
        "known_procedure_steps": [],
        "support_catalog": ReviewedSupportCatalog(
            catalog_version="test/1", programs=(), evidence_records=()
        ),
        "limits": RuntimeLimits(max_llm_calls_per_run=10, run_deadline_seconds=30),
    }


class PreloadedProcedureStore:
    snapshot_version = "be-preloaded/test"

    def __init__(self, records: tuple[ReviewedProcedureRecord, ...]) -> None:
        self._records = records

    def records(self) -> tuple[ReviewedProcedureRecord, ...]:
        return self._records

    def __bool__(self) -> bool:
        # Adapter truthiness must never select a different data source.
        return False


@pytest.mark.parametrize(
    ("reviewed_at", "freshness", "warning"),
    [
        (datetime(2026, 9, 19, tzinfo=timezone.utc), "CURRENT", None),
        (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            "STALE",
            "STALE_PROCEDURE_REVIEW",
        ),
        (None, "UNKNOWN", "UNREVIEWED_PROCEDURE_SOURCE"),
    ],
)
def test_runtime_injected_store_preserves_evidence_and_review_state(
    monkeypatch: pytest.MonkeyPatch,
    runtime_clients: list[Mock],
    runtime_options: dict[str, Any],
    reviewed_at: datetime | None,
    freshness: str,
    warning: str | None,
) -> None:
    loader = Mock(side_effect=AssertionError("injected store must bypass JSON"))
    monkeypatch.setattr(JsonFileProcedureStore, "from_env", loader)
    record = ReviewedProcedureRecord(
        record_id="TAX_BUSINESS_CLOSURE",
        title="폐업 신고 안내",
        authority_name="국세청",
        canonical_url="https://www.nts.go.kr/test/closure",
        source_domain="www.nts.go.kr",
        excerpt="폐업 신고에 관한 검수 대상 문서",
        content_hash="sha256:" + "a" * 64,
        published_at=None,
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reviewed_by="test-reviewer" if reviewed_at is not None else None,
        reviewed_at=reviewed_at,
        review_valid_days=30,
        step_codes=["FILE_TAX_BUSINESS_CLOSURE"],
        required_terms=["폐업"],
        any_terms=[],
    )
    store = PreloadedProcedureStore((record,))
    request = ProcedureLookupInput(
        lookup_goal="BUSINESS_CLOSURE",
        search_queries=["폐업 신고"],
        as_of=date(2026, 9, 20),
        locale="ko-KR",
        source_policy="OFFICIAL_ONLY",
        max_results_per_query=5,
        based_on_snapshot_id=UUID("00000000-0000-4000-8000-000000000001"),
        review_feedback=[],
    )

    async def run() -> ProcedureLookupResult:
        runtime = await build_runtime(procedure_store=store, **runtime_options)
        try:
            return await runtime._procedure_tool.lookup(request)
        finally:
            await runtime.aclose()

    result = asyncio.run(run())

    loader.assert_not_called()
    document = result.documents[0]
    evidence = result.evidence_records[0]
    assert document.evidence_ref == evidence.evidence_id
    assert document.canonical_url == evidence.source_ref == record.canonical_url
    assert document.content_hash == evidence.content_hash == record.content_hash
    assert document.excerpt == evidence.excerpt == record.excerpt
    assert document.retrieved_at == evidence.retrieved_at == record.retrieved_at
    assert evidence.source_version == store.snapshot_version
    assert (
        document.freshness_status.value == evidence.freshness_status.value == freshness
    )
    assert {item.code for item in result.warnings} == ({warning} if warning else set())
    for client in runtime_clients:
        client.aclose.assert_awaited_once()


def test_runtime_without_injected_store_loads_the_configured_json(
    monkeypatch: pytest.MonkeyPatch,
    runtime_clients: list[Mock],
    runtime_options: dict[str, Any],
) -> None:
    store = PreloadedProcedureStore(())
    loader = Mock(return_value=store)
    monkeypatch.setattr(JsonFileProcedureStore, "from_env", loader)

    async def run() -> None:
        runtime = await build_runtime(**runtime_options)
        try:
            assert runtime._procedure_tool._store is store
        finally:
            await runtime.aclose()

    asyncio.run(run())

    loader.assert_called_once_with()


def test_runtime_store_load_failure_closes_clients_and_is_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
    runtime_clients: list[Mock],
    runtime_options: dict[str, Any],
) -> None:
    loader = Mock(side_effect=ProcedureStoreError("snapshot unavailable"))
    monkeypatch.setattr(JsonFileProcedureStore, "from_env", loader)

    with pytest.raises(ProcedureStoreError, match="snapshot unavailable"):
        asyncio.run(build_runtime(**runtime_options))

    loader.assert_called_once_with()
    for client in runtime_clients:
        client.aclose.assert_awaited_once()
