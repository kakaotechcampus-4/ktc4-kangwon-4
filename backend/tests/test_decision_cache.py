"""No network or environment files: reviewed outcomes below are synthetic fixtures."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from app.agent import decision_cache as cache_module
from app.agent import runtime as runtime_module
from app.agent.decision_cache import DecisionCache
from app.agent.llm import LLMConfig, current_call_budget
from app.agent.run_scope import RunDeadline, current_deadline, run_deadline_scope
from app.agent.runtime import AgentRuntime, RuntimeLimits
from app.agent.schemas import (
    AgentGraphInput,
    ConflictOutcome,
    EvidenceRecord,
    ProcedureLookupResult,
    ProcedureProgressChangeCandidate,
    ReviewedPlanOutcome,
    ReviewSourceResult,
    ReviewSubject,
    SafeFailureOutcome,
    SupervisorDraft,
    canonical_digest,
)
from app.agent.support_agent import ReviewedSupportCatalog

NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)


def fixture(case_id=1, freshness="CURRENT"):
    evidence = EvidenceRecord(
        evidence_id="synthetic-user",
        source_type="USER_INPUT",
        source_ref="synthetic:input",
        source_version=None,
        locator=None,
        excerpt="합성 카페 입력",
        parent_evidence_refs=[],
        published_at=None,
        retrieved_at=NOW,
        freshness_status=freshness,
        content_hash="sha256:" + "0" * 64,
    )
    facts = [
        ("business_type", "STRING", "카페"),
        ("franchise_status", "BOOLEAN", False),
        ("lease_status", "ENUM", "LEASED_PAID"),
        ("employee_count", "INTEGER", None),
    ]
    request = AgentGraphInput(
        trigger={
            "trigger_type": "CASE_CREATED",
            "input_event_id": "synthetic-event",
            "client_event_id": None,
            "submitted_at": NOW,
            "input": {
                "input_event_id": "synthetic-event",
                "source_type": "USER_INPUT",
                "redacted_text": "합성 카페 입력",
                "redactions": [],
                "submitted_at": NOW,
            },
        },
        case_snapshot={
            "snapshot_id": UUID(int=1),
            "case_id": case_id,
            "case_status": "IN_PROGRESS",
            "facts": [
                {
                    "field_path": key,
                    "value_type": kind,
                    "value": value,
                    "status": "UNKNOWN" if value is None else "CONFIRMED",
                    "evidence_refs": [] if value is None else [evidence.evidence_id],
                    "updated_at": None if value is None else NOW,
                }
                for key, kind, value in facts
            ],
            "procedure_progress": [],
            "evidence_records": [evidence],
            "captured_at": NOW,
        },
    )
    lookup = ProcedureLookupResult(
        completion_status="NO_RESULTS",
        lookup_id=UUID(int=2),
        documents=[],
        warnings=[],
        evidence_records=[],
        based_on_snapshot_id=UUID(int=1),
        as_of=NOW.date(),
    )
    source = ReviewSourceResult(
        meta={
            "schema_version": "agent-io/2.0",
            "run_id": UUID(int=3),
            "call_id": UUID(int=4),
            "parent_call_id": None,
            "case_id": case_id,
            "component": "PROCEDURE_TOOL",
            "attempt": 1,
            "requested_at": NOW,
            "trace_id": None,
        },
        output=lookup,
        output_digest=canonical_digest(lookup),
    )
    draft = SupervisorDraft(
        decision={
            "decision_type": "NEEDS_MORE_INFO",
            "draft_id": UUID(int=5),
            "draft_version": 1,
            "selection_summary": "확인이 필요합니다.",
            "requires_human": True,
            "evidence_refs": [evidence.evidence_id],
            "based_on_call_ids": [UUID(int=4)],
            "created_at": NOW,
            "blocker": {
                "description": "확인되지 않은 항목이 있습니다.",
                "evidence_refs": [evidence.evidence_id],
            },
            "next_action": None,
            "questions_for_user": ["직원 수를 알려 주세요."],
        },
        mutations={
            "fact_changes": [],
            "procedure_progress_changes": [],
            "support_match_updates": [],
        },
        grounded_claims=[],
        source_call_ids=[UUID(int=4)],
    )
    subject = ReviewSubject.create(
        schema_version="agent-io/2.0",
        review_subject_id=UUID(int=6),
        review_attempt=1,
        run_id=UUID(int=3),
        case_id=case_id,
        trigger=request.trigger,
        snapshot=request.case_snapshot,
        known_procedure_steps=[],
        source_results=[source],
        supervisor_draft=draft,
    )
    outcome = ReviewedPlanOutcome(
        outcome_type="REVIEWED_PLAN",
        review_subject=subject,
        review_proof={
            "review_call_id": UUID(int=7),
            "run_id": UUID(int=3),
            "case_id": case_id,
            "snapshot_id": UUID(int=1),
            "review_subject_id": UUID(int=6),
            "reviewed_subject_digest": subject.subject_digest,
            "verdict": "PASS",
            "reviewed_at": NOW,
        },
    )
    return request, outcome


def test_hit_preserves_original_proof_and_defends_against_returned_mutation():
    cache = DecisionCache(clock=lambda: NOW)
    request, outcome = fixture()
    key = cache.key(request, {"model": "synthetic"})
    assert cache.put(key, request, outcome)
    result = cache.get(key)
    assert result.review_proof == outcome.review_proof
    assert result is not outcome
    result.review_subject.supervisor_draft.decision.selection_summary = "외부에서 변경"
    outcome.review_subject.supervisor_draft.decision.selection_summary = "원본도 변경"
    assert (
        cache.get(key).review_subject.supervisor_draft.decision.selection_summary
        == "확인이 필요합니다."
    )
    assert cache.inspect()["hits"] == 2


@pytest.mark.parametrize(
    "changed",
    [
        "case",
        "zero",
        "false",
        "text",
        "input_source",
        "progress",
        "hash",
        "freshness",
        "snapshot",
    ],
)
def test_changed_typed_case_input_and_evidence_never_share_a_key(changed):
    cache = DecisionCache()
    request, _ = fixture()
    data = request.model_dump(mode="json")
    if changed == "case":
        data["case_snapshot"]["case_id"] = 2
    elif changed == "zero":
        data["case_snapshot"]["facts"][-1].update(
            value=0, status="CONFIRMED", evidence_refs=["synthetic-user"]
        )
    elif changed == "false":
        data["case_snapshot"]["facts"][1]["value"] = True
    elif changed == "text":
        data["trigger"]["input"]["redacted_text"] = "임대료를 내지 않습니다."
    elif changed == "input_source":
        data["trigger"]["input"]["source_type"] = "EXPERT_CONFIRMATION"
    elif changed == "progress":
        data["case_snapshot"]["procedure_progress"] = [
            {
                "procedure_step": {"procedure_step_id": 1, "step_code": "SYNTHETIC"},
                "status": "IN_PROGRESS",
                "evidence_refs": [],
                "updated_at": NOW.isoformat(),
            }
        ]
    elif changed == "hash":
        data["case_snapshot"]["evidence_records"][0]["content_hash"] = (
            "sha256:" + "1" * 64
        )
    elif changed == "freshness":
        data["case_snapshot"]["evidence_records"][0]["freshness_status"] = "STALE"
    else:
        data["case_snapshot"]["snapshot_id"] = str(UUID(int=9))
    assert cache.key(AgentGraphInput.model_validate(data), {}) != cache.key(request, {})


@pytest.mark.parametrize(
    "field", ["registry", "catalog", "store", "model", "prompt", "rules"]
)
def test_any_context_change_or_rules_version_change_invalidates(field, monkeypatch):
    request, outcome = fixture()
    cache = DecisionCache()
    key = cache.key(request, {field: "before"})
    cache.put(key, request, outcome)
    assert cache.get(cache.key(request, {field: "after"})) is None
    monkeypatch.setattr(cache_module, "RULES_VERSION", "changed")
    assert cache.get(cache.key(request, {field: "before"})) is None


def test_ttl_calendar_day_lru_case_invalidation_and_clear():
    time = [0.0]
    now = [NOW]
    cache = DecisionCache(
        max_size=2, ttl_seconds=10, clock=lambda: now[0], monotonic=lambda: time[0]
    )
    request, outcome = fixture()
    for index in range(3):
        cache.put(str(index), request, outcome)
    assert cache.inspect()["size"] == 2
    assert cache.get("0") is None
    time[0] = 10
    assert cache.get("1") is None
    cache.put("day", request, outcome)
    now[0] += timedelta(days=1)
    assert cache.get("day") is None
    other_request, other_outcome = fixture(case_id=2)
    cache.put("a", request, outcome)
    cache.put("b", other_request, other_outcome)
    cache.invalidate_case(1)
    assert cache.get("a") is None and cache.get("b") is not None
    cache.clear()
    assert cache.inspect()["size"] == 0


@pytest.mark.parametrize("freshness", ["STALE", "UNKNOWN"])
def test_noncurrent_evidence_is_never_stored(freshness):
    request, outcome = fixture(freshness=freshness)
    assert not DecisionCache().put("key", request, outcome)


def test_failures_conflicts_revised_proofs_and_mutations_are_not_stored():
    cache = DecisionCache()
    request, outcome = fixture()
    for excluded in (
        SafeFailureOutcome.model_construct(),
        ConflictOutcome.model_construct(),
    ):
        assert not cache.put("excluded", request, excluded)
    revised = outcome.model_copy(deep=True)
    revised.review_proof = revised.review_proof.model_copy(update={"verdict": "REVISE"})
    assert not cache.put("revised", request, revised)
    draft = outcome.review_subject.supervisor_draft.model_copy(deep=True)
    draft.mutations.procedure_progress_changes.append(
        ProcedureProgressChangeCandidate(
            candidate_id=UUID(int=8),
            procedure_step={"procedure_step_id": 1, "step_code": "SYNTHETIC"},
            before_status="NOT_STARTED",
            proposed_status="IN_PROGRESS",
            reason_summary="합성 실행 결과",
            execution_evidence_refs=["synthetic-user"],
            procedure_analysis_call_id=UUID(int=4),
        )
    )
    original = outcome.review_subject
    values = {
        name: getattr(original, name)
        for name in type(original).model_fields
        if name not in {"subject_digest", "supervisor_draft"}
    }
    subject = ReviewSubject.create(**values, supervisor_draft=draft)
    outcome = ReviewedPlanOutcome(
        outcome_type="REVIEWED_PLAN",
        review_subject=subject,
        review_proof=outcome.review_proof.model_copy(
            update={"reviewed_subject_digest": subject.subject_digest}
        ),
    )
    outcome.assert_integrity()
    assert not cache.put("mutations", request, outcome)


def test_corrupted_serialized_entry_is_evicted():
    request, outcome = fixture()
    cache = DecisionCache()
    cache.put("key", request, outcome)
    cache._entries["key"] = replace(cache._entries["key"], payload="{}")
    assert cache.get("key") is None
    assert cache.inspect()["size"] == 0


class GraphStub:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, 0

    async def run(self, request):
        current_deadline().check()
        current_call_budget().consume()
        self.calls += 1
        return self.outcome.model_copy(deep=True)


def test_runtime_hit_skips_graph_calls_opt_out_rechecks_and_deadline_is_respected():
    async def run():
        request, outcome = fixture()
        graph = GraphStub(outcome)
        runtime = AgentRuntime(
            graph=graph,
            limits=RuntimeLimits(1, 60),
            clients=[],
            procedure_tool=None,
            decision_cache=DecisionCache(),
            cache_context=dict,
        )
        first = await runtime.run_planning(request)
        second = await runtime.run_planning(request)
        assert graph.calls == 1 and first.review_proof == second.review_proof
        assert runtime.decision_cache.inspect()["hits"] == 1
        await runtime.run_planning(request, use_cache=False)
        assert graph.calls == 2
        with run_deadline_scope(RunDeadline.after(0.000000001)):
            with pytest.raises(Exception) as error:
                await runtime.run_planning(request)
            assert error.value.code == "RUN_DEADLINE_EXCEEDED"
        assert graph.calls == 2

    asyncio.run(run())


def test_cache_context_failure_keeps_the_graph_error_boundary():
    async def run():
        request, outcome = fixture()
        graph = GraphStub(outcome)

        def unavailable_context():
            raise RuntimeError("synthetic source lookup failure")

        runtime = AgentRuntime(
            graph=graph,
            limits=RuntimeLimits(1, 60),
            clients=[],
            procedure_tool=None,
            decision_cache=DecisionCache(),
            cache_context=unavailable_context,
        )
        assert await runtime.run_planning(request) == outcome
        assert graph.calls == 1
        assert runtime.decision_cache.inspect()["stores"] == 0

    asyncio.run(run())


def test_build_runtime_tracks_actual_config_data_prompts_and_disables_unversioned_wiki(
    monkeypatch,
):
    async def run():
        request, outcome = fixture()
        config = LLMConfig(
            base_url="https://example.org/test",
            api_token="synthetic",
            model="synthetic",
        )
        clients = []

        async def close():
            pass

        def client_factory(**kwargs):
            client = SimpleNamespace(config=config, aclose=close)
            clients.append(client)
            return client

        monkeypatch.setattr(
            runtime_module.StructuredLLMClient, "from_env", client_factory
        )
        monkeypatch.setattr(runtime_module.LangfuseTraceSink, "from_env", lambda: None)
        graph = GraphStub(outcome)
        monkeypatch.setattr(runtime_module, "AgentGraph", lambda **kwargs: graph)
        store = SimpleNamespace(snapshot_version="before", records=list)
        catalog = ReviewedSupportCatalog(
            catalog_version="synthetic", programs=(), evidence_records=()
        )
        runtime = await runtime_module.build_runtime(
            known_procedure_steps=[],
            support_catalog=catalog,
            procedure_store=store,
            limits=RuntimeLimits(1, 60),
        )
        await runtime.run_planning(request)
        await runtime.run_planning(request)
        assert graph.calls == 1
        store.snapshot_version = "after"
        await runtime.run_planning(request)
        clients[0].config = replace(config, reasoning_effort="high")
        await runtime.run_planning(request)
        monkeypatch.setattr(runtime_module.prompts, "SAFETY_RULES", "changed rules")
        await runtime.run_planning(request)
        assert graph.calls == 4
        await runtime.aclose()
        uncached = await runtime_module.build_runtime(
            known_procedure_steps=[],
            support_catalog=catalog,
            procedure_store=store,
            limits=RuntimeLimits(1, 60),
            use_decision_cache=False,
        )
        assert uncached.decision_cache is None
        await uncached.aclose()
        wiki = await runtime_module.build_runtime(
            known_procedure_steps=[],
            support_catalog=catalog,
            procedure_store=store,
            support_wiki=object(),
            limits=RuntimeLimits(1, 60),
        )
        await wiki.run_planning(request)
        await wiki.run_planning(request)
        assert wiki.decision_cache.inspect()["stores"] == 0
        await wiki.aclose()

    asyncio.run(run())
