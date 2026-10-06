"""Repeat planning from a frontend intake payload or AgentGraphInput and compare answers.

Run from the repository root with PYTHONPATH=backend. Every trial builds a fresh
runtime with the decision cache off, so a repeat really calls the provider again
instead of replaying an earlier answer. --validate-only never calls the provider.
Reports record model names, timings and digests -- never tokens, URLs, prompts or
user text.

Reviewed procedure and support data are supplied by the caller, the same way
``build_runtime`` expects. Nothing is fetched from the internet during a run.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from uuid import UUID, uuid5

import httpx

import app.agent.runtime as runtime_module
from app.agent.llm import LLMConfig, StructuredLLMClient
from app.agent.procedure_tool.store import ReviewedProcedureSnapshot
from app.agent.schemas import (
    AgentGraphInput,
    CaseFact,
    CaseSnapshot,
    EvidenceRecord,
    KnownProcedureStep,
    canonical_digest,
)
from app.agent.support_agent import ReviewedSupportCatalog
from app.be.schemas.case import CaseCreateRequest

# A fixed clock keeps two runs of the same payload comparable. Reviewed sources
# carry their own review dates, so this does not make stale data look current.
FIXED_TIME = datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)
NAMESPACE = UUID("358ab427-27f2-4d58-98a9-5656d63904ca")

# The four intake answers every earlier recorded run used, so new numbers stay
# comparable with the ones in docs/agent/handoof.md.
CASES = {
    "benchmark_case1": dict(
        business_type="카페", franchise_status=False, employee_count=2,
        lease_status="LEASED_PAID", planned_closure_date=None,
    ),
    "free_lease": dict(
        business_type="카페", franchise_status=False, employee_count=2,
        lease_status="LEASED_FREE", planned_closure_date=None,
    ),
    "optional_missing": dict(
        business_type="카페", franchise_status=False, employee_count=None,
        lease_status="LEASED_PAID", planned_closure_date=None,
    ),
    "solo_dated": dict(
        business_type="카페", franchise_status=False, employee_count=0,
        lease_status="LEASED_PAID", planned_closure_date="2026-10-31",
    ),
}

# What the user types on the 결과 알려주기 screen after doing a next action.
RESULT_INPUTS = {
    "demolition_only": "임대인이 철거해야 한다고 했어요.",
    "scope_and_demolition": (
        "임대인에게 확인했더니 원상복구 범위는 전체이고 철거가 필요하다고 했어요."
    ),
}

# build_runtime creates one client per env prefix; giving each its own transport
# attributes every request without wrapping any Agent.
ROLE_BY_PREFIX = {"": "shared", "SUPERVISOR_": "supervisor", "INFO_": "info"}


def as_text(value):
    """Plain Enums str() as ``DecisionType.ACTION``; records want the value."""
    return value.value if isinstance(value, Enum) else value


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value) -> str:
    return "sha256:" + hashlib.sha256(canonical(value).encode()).hexdigest()


def build_case_snapshot(payload: dict) -> tuple[CaseSnapshot, str]:
    """Map the five intake answers onto a Case read view, without a database.

    This is NOT the BE contract. BE builds a snapshot by reading a saved Case
    row, so it has a real snapshot id, case id and captured_at. Here those are
    derived from the payload so the same answers always produce the same input.
    No domain fact missing from the intake form is guessed: restoration and
    demolition stay UNKNOWN, which is exactly what the form does not ask.
    """

    request = CaseCreateRequest.model_validate(payload)
    normalized = request.model_dump(mode="json")
    text = canonical(normalized)
    evidence = EvidenceRecord(
        evidence_id="synthetic-fe-case-input",
        source_type="USER_INPUT",
        source_ref="synthetic:CaseCreateRequest",
        source_version="fixture/1",
        locator=None,
        excerpt=text,
        parent_evidence_refs=[],
        published_at=None,
        retrieved_at=FIXED_TIME,
        freshness_status="CURRENT",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    fields = [
        ("business_type", "STRING", request.business_type),
        ("franchise_status", "BOOLEAN", request.franchise_status),
        ("employee_count", "INTEGER", request.employee_count),
        ("lease_status", "ENUM", request.lease_status),
        # BE stores the enum UNKNOWN; the Agent models UNKNOWN as status + null.
        ("restoration_status", "ENUM", None),
        ("restoration_scope", "ENUM", None),
        ("restoration_scope_detail", "STRING", None),
        ("demolition_required", "ENUM", None),
        ("planned_closure_date", "DATE", normalized["planned_closure_date"]),
    ]
    snapshot = CaseSnapshot(
        snapshot_id=uuid5(NAMESPACE, "snapshot:" + text),
        case_id=1,
        case_status="IN_PROGRESS",
        facts=[
            CaseFact(
                field_path=name,
                value_type=kind,
                value=value,
                status="UNKNOWN" if value is None else "CONFIRMED",
                evidence_refs=[] if value is None else [evidence.evidence_id],
                updated_at=None if value is None else FIXED_TIME,
            )
            for name, kind, value in fields
        ],
        procedure_progress=[],
        evidence_records=[evidence],
        captured_at=FIXED_TIME,
    )
    return snapshot, text


def build_graph_input(payload: dict, *, result_text: str | None = None):
    """CASE_CREATED for the intake form, RESULT_SUBMITTED for a typed result."""

    snapshot, form_text = build_case_snapshot(payload)
    text = form_text if result_text is None else result_text
    trigger_type = "CASE_CREATED" if result_text is None else "RESULT_SUBMITTED"
    event_id = f"synthetic-fe:{trigger_type}:" + digest(text).split(":")[1][:16]
    return AgentGraphInput(
        trigger=dict(
            trigger_type=trigger_type,
            input_event_id=event_id,
            client_event_id=None,
            submitted_at=FIXED_TIME,
            input=dict(
                input_event_id=event_id,
                source_type="USER_INPUT",
                redacted_text=text,
                redactions=[],
                submitted_at=FIXED_TIME,
            ),
        ),
        case_snapshot=snapshot,
        trace_id="evaluate-planning",
    )


class SnapshotStore:
    """Reviewed procedure documents the caller supplies; no lookup fetches them."""

    def __init__(self, path: Path) -> None:
        self.raw = path.read_bytes()
        self.snapshot = ReviewedProcedureSnapshot.model_validate_json(self.raw)
        self._records = tuple(self.snapshot.records)

    @property
    def snapshot_version(self) -> str:
        return self.snapshot.snapshot_version

    def records(self):
        return self._records


# A step's name and aliases are how the Agent recognises "I already did that"
# in the user's own words. Using the scraped document title instead made
# "원상복구 범위를 확인했다" unrecognisable, and Info burned every retry on a
# progress observation the guard could not accept. BE owns the real names;
# these mirror the labels the Agent itself already uses.
_STEP_NAMES = {
    "CONFIRM_RESTORATION_SCOPE": ("임대차 원상복구 범위 확인", ["원상복구", "철거"]),
    "FILE_TAX_BUSINESS_CLOSURE": ("사업자 폐업신고", ["폐업신고", "사업자"]),
    "FILE_FOOD_SERVICE_CLOSURE": ("식품영업 폐업신고", ["식품영업", "영업신고"]),
    "REPORT_WORKPLACE_INSURANCE_CLOSURE": ("사업장 탈퇴 신고", ["사업장", "4대보험"]),
}


def build_registry(store: SnapshotStore) -> list[KnownProcedureStep]:
    """One registry entry per step_code the reviewed documents cover.

    The IDs are local to this run. BE owns the real PROCEDURE_STEP rows, so the
    registry_version says so rather than pretending these were persisted.
    """

    steps: list[KnownProcedureStep] = []
    for record in store.records():
        for code in record.step_codes:
            name, aliases = _STEP_NAMES.get(code, (record.title, []))
            steps.append(
                KnownProcedureStep(
                    procedure_step=dict(
                        procedure_step_id=len(steps) + 1, step_code=code
                    ),
                    step_name=name,
                    utterance_aliases=list(aliases),
                    registry_version="LOCAL_TEST_IDS_NOT_PERSISTED",
                    applicable_business_type="ALL",
                    deprecated_at=None,
                    dependencies=[],
                    eligibility_conditions=[],
                )
            )
    return steps


def load_catalog(path: Path | None) -> ReviewedSupportCatalog:
    if path is None:
        return ReviewedSupportCatalog(
            catalog_version="evaluate-planning/no-reviewed-support-data",
            programs=(),
            evidence_records=(),
        )
    return ReviewedSupportCatalog.model_validate_json(path.read_bytes())


def source_manifest(store, registry, catalog, catalog_path: Path | None) -> dict:
    """Prove which reviewed bytes were used, so a rerun can show it used the same."""

    return {
        "procedure_snapshot_version": store.snapshot_version,
        "procedure_file_sha256": "sha256:" + hashlib.sha256(store.raw).hexdigest(),
        "procedure_records": [
            {
                "record_id": record.record_id,
                "reviewed_by": record.reviewed_by,
                "reviewed_at": (
                    record.reviewed_at.isoformat() if record.reviewed_at else None
                ),
                "freshness": record.freshness(FIXED_TIME.date()),
                "step_codes": list(record.step_codes),
            }
            for record in store.records()
        ],
        "procedure_registry_count": len(registry),
        "support_catalog_version": catalog.catalog_version,
        "support_catalog_file": None if catalog_path is None else str(catalog_path),
        "support_program_count": len(catalog.programs),
        # freshness_status here is a human's claim, not a computed value. It
        # changes what the answer means, so it is recorded explicitly.
        "support_freshness": sorted(
            {str(as_text(program.freshness_status)) for program in catalog.programs}
        ),
    }


class RecordingTransport(httpx.AsyncBaseTransport):
    """Record what each role actually sent. Never a header, token, URL or body."""

    def __init__(self, role: str, calls: list[dict]) -> None:
        self._role, self._calls = role, calls
        self._inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        body = json.loads(await request.aread())
        schema = (body.get("response_format") or {}).get("json_schema") or {}
        record = {
            "role": self._role,
            "model": body.get("model"),
            "schema_name": schema.get("name"),
            "reasoning_effort": body.get("reasoning_effort"),
            "max_completion_tokens": body.get("max_completion_tokens"),
            "stream": body.get("stream", False),
            "request_without_model_digest": hashlib.sha256(
                canonical(
                    {key: value for key, value in body.items() if key != "model"}
                ).encode()
            ).hexdigest(),
        }
        self._calls.append(record)
        started = perf_counter()
        try:
            response = await self._inner.handle_async_request(request)
            record["http_status"] = response.status_code
            return response
        finally:
            record["headers_latency_ms"] = round((perf_counter() - started) * 1000)

    async def aclose(self) -> None:
        await self._inner.aclose()


def recording_from_env(calls: list[dict]):
    real = StructuredLLMClient.from_env

    def from_env(*, env_prefix: str = "", **kwargs):
        return real(
            env_prefix=env_prefix,
            **kwargs,
            transport=RecordingTransport(ROLE_BY_PREFIX[env_prefix], calls),
        )

    return from_env


def decision_summary(outcome) -> dict:
    """The Blocker and Next Action a user would see, plus digests to compare.

    Compare the user-facing decision separately from its provenance. Official
    evidence keeps its DB ID; other derived evidence may have per-run IDs.
    """

    if outcome.outcome_type != "REVIEWED_PLAN":
        # Why it stopped is the whole value of a failed trial, so keep every
        # field the outcome carries rather than just the code.
        return {
            "failure_code": getattr(outcome, "failure_code", None),
            "failed_component": as_text(getattr(outcome, "failed_component", None)),
            "message_code": as_text(getattr(outcome, "message_code", None)),
            "recovery_action_code": as_text(
                getattr(outcome, "recovery_action_code", None)
            ),
            "requested_field_paths": [
                as_text(item) for item in getattr(outcome, "requested_field_paths", [])
            ],
            "retryable": getattr(outcome, "retryable", None),
            "conflicts": [
                item.model_dump(mode="json")
                for item in getattr(outcome, "conflicts", [])
            ],
        }
    subject = outcome.review_subject
    decision = subject.supervisor_draft.decision
    blocker = decision.blocker
    action = decision.next_action
    changes = subject.supervisor_draft.mutations.fact_changes
    return {
        "decision_type": as_text(decision.decision_type),
        "blocker_digest": canonical_digest(blocker, exclude={"evidence_refs"}),
        "next_action_digest": (
            None
            if action is None
            else canonical_digest(action, exclude={"evidence_refs"})
        ),
        # Read by a person; the digests above already gate the comparison.
        "blocker": blocker.description,
        "action_code": None if action is None else as_text(action.action_code),
        "next_action": None if action is None else action.model_dump(mode="json"),
        "questions_for_user": list(decision.questions_for_user),
        # What the 다시 계산했습니다 screen shows as 방금 반영된 내용.
        "fact_changes": [
            change.model_dump(
                mode="json",
                include={
                    "field_path", "before_status", "before_value",
                    "proposed_status", "proposed_value",
                },
            )
            for change in changes
        ],
        # Recorded, never gated: rework bookkeeping is not user-visible text.
        "review_attempt": subject.review_attempt,
        "draft_version": decision.draft_version,
    }


async def trial(case: str, request: AgentGraphInput, store, registry, catalog) -> dict:
    calls: list[dict] = []
    result = {
        "case": case,
        "trigger": as_text(request.trigger.trigger_type),
        "graph_input_digest": canonical_digest(request),
        "status": "ERROR",
        "calls": calls,
    }
    runtime = None
    started = perf_counter()
    try:
        with patch.object(
            runtime_module.StructuredLLMClient, "from_env", recording_from_env(calls)
        ):
            runtime = await runtime_module.build_runtime(
                known_procedure_steps=registry,
                procedure_store=store,
                support_catalog=catalog,
                # A repeat must really re-run. A cached answer would return with
                # zero provider calls and make every repeat trivially identical.
                use_decision_cache=False,
            )
        result["decision_cache_disabled"] = runtime.decision_cache is None
        result["limits"] = asdict(runtime.limits)
        outcome = await runtime.run_planning(request)
        result["status"] = as_text(outcome.outcome_type)
        result.update(decision_summary(outcome))
    except Exception as exc:  # noqa: BLE001 - provider messages may carry bodies
        result["status"] = "ERROR"
        result["error"] = {
            "type": type(exc).__name__,
            "code": getattr(exc, "code", None),
            "status_code": getattr(exc, "status_code", None),
        }
    finally:
        if runtime is not None:
            await runtime.aclose()
        result["elapsed_ms"] = round((perf_counter() - started) * 1000)
        result["calls_by_role"] = dict(Counter(call["role"] for call in calls))
    return result


def verdict(rows: list[dict]) -> dict:
    """Did every repeat of one case produce the same Blocker and Next Action?

    Two different questions are reported separately, because a provider outage
    and a model changing its mind are not the same problem:
      reliability -- did every repeat produce a reviewed plan at all
      consistency -- did the repeats that DID produce one agree with each other
    Mixing them would let one HTTP 503 read as "the answer was unstable".
    """

    planned = [
        row for row in rows
        if row["status"] == "REVIEWED_PLAN" and "error" not in row
    ]

    def same(key: str) -> bool:
        return len({canonical(row.get(key)) for row in planned}) <= 1

    checks = {
        "no_errors": all("error" not in row for row in rows),
        "all_reviewed_plan": len(planned) == len(rows),
        "same_graph_input": len({row["graph_input_digest"] for row in rows}) == 1,
        "same_decision_type": same("decision_type"),
        "same_blocker": same("blocker_digest"),
        "same_next_action": same("next_action_digest"),
        "same_fact_changes": same("fact_changes"),
        # Observable proof no repeat replayed an earlier answer: a cache hit
        # returns with zero provider calls. Which roles are called depends on
        # the configuration and on whether reviewed support data was supplied,
        # so requiring a specific set of roles would be wrong.
        "provider_called_every_repeat": all(
            sum(row["calls_by_role"].values()) > 0 for row in rows
        ),
    }
    consistency = [
        key for key in checks if key.startswith("same_") or key == "decision_type"
    ]
    return {
        "repeats": len(rows),
        "reviewed_plans": len(planned),
        # What the repeats that succeeded agreed on.
        "consistency": "PASS" if all(checks[key] for key in consistency) else "FAIL",
        # Whether every repeat got that far at all.
        "reliability": "PASS" if checks["all_reviewed_plan"] else "FAIL",
        "verdict": "PASS" if all(checks.values()) else "FAIL",
        **checks,
    }


async def run(args) -> None:
    graph_input_path = getattr(args, "graph_input", None)
    if graph_input_path is not None and (args.case or args.result_input is not None):
        raise SystemExit("--graph-input cannot be combined with --case or --result-input")

    store = SnapshotStore(args.procedure_snapshot)
    registry = build_registry(store)
    catalog = load_catalog(args.support_catalog)
    expected = dict(pair.split("=", 1) for pair in args.expect)
    # Read exactly what build_runtime will read: the process environment on
    # top of .env. Passing environ={} would check the file while the run used
    # an override, so the guard could pass for the wrong models.
    configured = {
        role: LLMConfig.from_env(env_prefix=prefix).model
        for prefix, role in ROLE_BY_PREFIX.items()
    }
    mismatched = {
        role: {"expected": model, "configured": configured.get(role)}
        for role, model in expected.items()
        if configured.get(role) != model
    }

    if graph_input_path is not None:
        case = graph_input_path.stem
        cases = [case]
        requests = {
            case: AgentGraphInput.model_validate_json(graph_input_path.read_bytes())
        }
        # Report the source and digest, never the supplied snapshot or user input.
        case_inputs = {case: {"graph_input_file": str(graph_input_path)}}
    else:
        cases = args.case or sorted(CASES)
        result_text = None if args.result_input is None else RESULT_INPUTS[args.result_input]
        requests = {
            case: build_graph_input(CASES[case], result_text=result_text) for case in cases
        }
        case_inputs = {case: CASES[case] for case in cases}
    manifest = {
        "trigger": as_text(requests[cases[0]].trigger.trigger_type),
        "result_input": args.result_input,
        "repeats": args.repeats,
        "cases": case_inputs,
        "graph_input_digests": {
            case: canonical_digest(request) for case, request in requests.items()
        },
        "configured_models": configured,
        "expected_models": expected,
        "model_mismatch": mismatched,
        "decision_cache_enabled": False,
        "sources": source_manifest(store, registry, catalog, args.support_catalog),
        "scope": (
            "지정한 Agent 입력으로 전체 판단 경로를 반복 실행한다. "
            "FE HTTP·로그인·DB 저장은 포함하지 않는다."
        ),
    }

    if args.validate_only:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    if mismatched:
        raise SystemExit(f"configured models differ from --expect: {mismatched}")

    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    rows: list[dict] = []
    # Sequential on purpose: the from_env patch is process-wide, so concurrent
    # trials would hand a transport to the wrong client.
    for repeat in range(1, args.repeats + 1):
        for case in cases:
            row = await trial(case, requests[case], store, registry, catalog)
            row["repeat"] = repeat
            rows.append(row)
            (args.output / f"trial-{len(rows):03d}.json").write_text(
                json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {key: row.get(key) for key in
                     ("case", "repeat", "status", "action_code", "elapsed_ms")},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            (args.output / "results.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if (row.get("error") or {}).get("status_code") in (401, 403):
                raise SystemExit("Provider rejected credentials; remaining trials stopped.")

    per_case = {
        case: verdict([row for row in rows if row["case"] == case]) for case in cases
    }
    summary = {
        "verdict": "PASS" if all(v["verdict"] == "PASS" for v in per_case.values()) else "FAIL",
        "per_case": per_case,
        # If every different intake converges on one action, the run shows
        # consistency, not that the model picks well among several candidates.
        "distinct_next_action_digests": len(
            {row.get("next_action_digest") for row in rows}
        ),
        "trials": rows,
    }
    (args.output / "results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in ("verdict", "distinct_next_action_digests")},
                     ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--procedure-snapshot", type=Path, required=True)
    parser.add_argument("--support-catalog", type=Path)
    parser.add_argument(
        "--graph-input", type=Path,
        help="AgentGraphInput JSON; cannot be combined with --case or --result-input",
    )
    parser.add_argument("--case", action="append", choices=sorted(CASES))
    parser.add_argument("--result-input", choices=sorted(RESULT_INPUTS))
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--expect", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    asyncio.run(run(parser.parse_args()))
