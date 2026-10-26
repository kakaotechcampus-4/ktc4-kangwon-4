"""Repeat planning from a frontend intake payload or AgentGraphInput and compare answers.

Run from the repository root with PYTHONPATH=backend. Every trial builds a fresh
runtime, so a repeat really calls the provider again. --validate-only never calls the provider.
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
import subprocess
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from uuid import UUID, uuid5

import httpx
from pydantic import TypeAdapter, ValidationError

import app.agent.runtime as runtime_module
from app.agent import schemas as agent_schemas
from app.agent.llm import LLMConfig, StructuredLLMClient
from app.agent.procedure_tool.cafe import CAFE_SOURCE_VERSION
from app.agent.procedure_tool.store import ReviewedProcedureSnapshot
from app.agent.schemas import (
    AgentGraphInput,
    AgentGraphOutput,
    CaseFact,
    CaseSnapshot,
    ConflictCandidate,
    ConflictConfirmedTrigger,
    EvidenceRecord,
    KnownProcedureStep,
    ProcedureProgress,
    canonical_digest,
)
from app.agent.support_agent import ReviewedSupportCatalog
from app.be.schemas.case import CaseCreateRequest

# Expected procedure coverage belongs to the test oracle, independent of whether
# the cafe feature has been merged into the Agent runtime in this checkout.
CAFE_TRACKED_CODES = frozenset({
    "CONFIRM_RESTORATION_SCOPE", "PERFORM_RESTORATION", "RETURN_PREMISES",
    "FILE_FOOD_SERVICE_CLOSURE", "FILE_TAX_BUSINESS_CLOSURE",
    "SETTLE_EMPLOYEE_PAYMENTS", "REPORT_EMPLOYEE_INSURANCE_LOSS",
    "REPORT_WORKPLACE_INSURANCE_CLOSURE",
})
ADMINISTRATIVE_PROCEDURE_CODES = frozenset({
    "FILE_TAX_BUSINESS_CLOSURE", "FILE_FOOD_SERVICE_CLOSURE",
    "REPORT_EMPLOYEE_INSURANCE_LOSS", "REPORT_WORKPLACE_INSURANCE_CLOSURE",
})


EVALUATION_ACTION_CODES = frozenset({
    "CONFIRM_RESTORATION_SCOPE", "CONFIRM_TAX_CLOSURE_REQUIREMENTS",
    "FILE_TAX_BUSINESS_CLOSURE", "CONFIRM_FOOD_SERVICE_CLOSURE_REQUIREMENTS",
    "FILE_FOOD_SERVICE_CLOSURE", "CONFIRM_WORKPLACE_INSURANCE_CLOSURE_REQUIREMENTS",
    "REPORT_WORKPLACE_INSURANCE_CLOSURE", "CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS",
    "CONFIRM_RESTORATION_REQUIREMENTS", "PERFORM_RESTORATION",
    "CONFIRM_PREMISES_RETURN_REQUIREMENTS", "RETURN_PREMISES",
    "CONFIRM_EMPLOYEE_SETTLEMENT_REQUIREMENTS", "SETTLE_EMPLOYEE_PAYMENTS",
    "CONFIRM_EMPLOYEE_INSURANCE_LOSS_REQUIREMENTS", "REPORT_EMPLOYEE_INSURANCE_LOSS",
    "CONFIRM_PROCEDURE_COMPLETION",
})


# A fixed clock keeps two runs of the same payload comparable. Reviewed sources
# carry their own review dates, so this does not make stale data look current.
FIXED_TIME = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
NAMESPACE = UUID("358ab427-27f2-4d58-98a9-5656d63904ca")

# The four intake answers every earlier recorded run used, so new numbers stay
# comparable with earlier evaluation records.
CASES = {
    "benchmark_case1": {
        "business_type": "카페", "franchise_status": False, "employee_count": 2,
        "lease_status": "LEASED_PAID", "planned_closure_date": None,
    },
    "free_lease": {
        "business_type": "카페", "franchise_status": False, "employee_count": 2,
        "lease_status": "LEASED_FREE", "planned_closure_date": None,
    },
    "optional_missing": {
        "business_type": "카페", "franchise_status": False, "employee_count": None,
        "lease_status": "LEASED_PAID", "planned_closure_date": None,
    },
    "solo_dated": {
        "business_type": "카페", "franchise_status": False, "employee_count": 0,
        "lease_status": "LEASED_PAID", "planned_closure_date": "2026-10-31",
    },
}

# What the user types on the 결과 알려주기 screen after doing a next action.
RESULT_INPUTS = {
    "demolition_only": "임대인이 철거해야 한다고 했어요.",
    "scope_and_demolition": (
        "임대인에게 확인했더니 원상복구 범위는 전체이고 철거가 필요하다고 했어요."
    ),
    # 앞 절을 뒤 절이 뒤집는 입력. 확정하지 않고 되물어야 한다.
    "scope_reversed": (
        "임대인에게 물어봤어요. 원상복구 범위는 없다고 들었는데 임대인은 전부 하라고 했어요."
    ),
    # 접속 표현은 있지만 뒤 절이 앞 절을 뒤집지 않는 입력. 되묻기가 넓어져
    # 정상 입력까지 다시 묻게 되는지 보는 반대쪽 시나리오다.
    "scope_benign_connective": (
        "임대인에게 확인했습니다. 원상복구 범위는 없다고 했는데 그대로 두면 된대요."
    ),
}

# Expected behavior, not exact generated wording. These cases deliberately reuse
# the inputs above so a regression cannot be hidden by rewriting the examples.
CORE_EXPECTATIONS = {
    "intake": {
        "result_input": None,
        "outcomes": ["REVIEWED_PLAN"],
        "decisions": ["ACTION", "NEEDS_MORE_INFO"],
        "actions": ["CONFIRM_RESTORATION_SCOPE", "CONFIRM_TAX_CLOSURE_REQUIREMENTS",
                    "CONFIRM_FOOD_SERVICE_CLOSURE_REQUIREMENTS"],
        "forbidden_fact_fields": ["restoration_scope", "demolition_required"],
    },
    "scope_reversed": {
        "result_input": "scope_reversed",
        "outcomes": ["REVIEWED_PLAN"],
        "decisions": ["ACTION", "NEEDS_MORE_INFO"],
        "forbidden_fact_fields": ["restoration_scope"],
        "required_blocker_candidates": ["missing:restoration_scope"],
    },
    "scope_benign_connective": {
        "result_input": "scope_benign_connective",
        "outcomes": ["REVIEWED_PLAN"],
        "decisions": ["ACTION", "NEEDS_MORE_INFO"],
        "required_facts": {"restoration_scope": "NOT_REQUIRED"},
    },
    "scope_and_demolition": {
        "result_input": "scope_and_demolition",
        "outcomes": ["REVIEWED_PLAN"],
        "decisions": ["ACTION", "NEEDS_MORE_INFO"],
        "required_facts": {"restoration_scope": "FULL", "demolition_required": "REQUIRED"},
    },
    "conflict_mixed": {
        "result_input": None, "request_kind": "conflict", "accepted": [True, False],
        "outcomes": ["REVIEWED_PLAN"], "decisions": ["ACTION", "NEEDS_MORE_INFO"],
        "required_facts": {"restoration_scope": "FULL", "planned_closure_date": "2026-11-02"},
        "allowed_fact_fields": ["restoration_scope", "planned_closure_date"], "no_procedure_changes": True,
    },
    "conflict_keep_all": {
        "result_input": None, "request_kind": "conflict", "accepted": [False, False],
        "outcomes": ["REVIEWED_PLAN"], "decisions": ["ACTION", "NEEDS_MORE_INFO"],
        "required_facts": {"planned_closure_date": "2026-11-02"},
        "allowed_fact_fields": ["planned_closure_date"], "no_procedure_changes": True,
    },
    "completed_scope": {
        "result_input": None, "request_kind": "completion",
        "outcomes": ["REVIEWED_PLAN"], "decisions": ["COMPLETED"],
        "allowed_fact_fields": [], "no_procedure_changes": True,
    },
    "restoration_work_completed": {
        "result_input": None, "request_kind": "procedure_progress",
        "outcomes": ["REVIEWED_PLAN"], "decisions": ["ACTION"],
        "actions": ["CONFIRM_PREMISES_RETURN_REQUIREMENTS"],
        "action_targets": {"CONFIRM_PREMISES_RETURN_REQUIREMENTS": "RETURN_PREMISES"},
        "allowed_fact_fields": ["restoration_status"],
        "procedure_expectations": {
            "PERFORM_RESTORATION": {
                "required_change": True, "statuses": ["COMPLETED"],
                "requirements_confirmed": True, "submitted": False,
            },
        },
    },
    "administrative_submitted": {
        "result_input": None, "request_kind": "procedure_progress",
        "outcomes": ["REVIEWED_PLAN"], "decisions": ["ACTION"],
        "actions": ["CONFIRM_PROCEDURE_COMPLETION"],
        "action_targets": {"CONFIRM_PROCEDURE_COMPLETION": "FILE_FOOD_SERVICE_CLOSURE"},
        "allowed_fact_fields": [],
        "procedure_expectations": {
            "FILE_FOOD_SERVICE_CLOSURE": {
                "required_change": True, "statuses": ["IN_PROGRESS"],
                "requirements_confirmed": True, "submitted": True,
            },
        },
    },
    "employee_partial_processing": {
        "result_input": None, "request_kind": "procedure_progress",
        "outcomes": ["REVIEWED_PLAN"], "decisions": ["ACTION"],
        "actions": ["REPORT_EMPLOYEE_INSURANCE_LOSS", "CONFIRM_WORKPLACE_INSURANCE_CLOSURE_REQUIREMENTS"],
        "action_targets": {
            "REPORT_EMPLOYEE_INSURANCE_LOSS": "REPORT_EMPLOYEE_INSURANCE_LOSS",
            "CONFIRM_WORKPLACE_INSURANCE_CLOSURE_REQUIREMENTS": "REPORT_WORKPLACE_INSURANCE_CLOSURE",
        },
        "allowed_fact_fields": [],
        "procedure_expectations": {
            "REPORT_EMPLOYEE_INSURANCE_LOSS": {
                "required_change": False, "statuses": ["IN_PROGRESS"],
                "requirements_confirmed": True, "submitted": False,
            },
        },
    },
}

def require_core_contract() -> None:
    """Missing feature DTOs must fail before a provider can be called."""
    required = {
        "CaseSnapshot": {"active_blocker_candidate_ids"},
        "Blocker": {"candidate_id"},
        "ActionDecisionDraft": {"blockers"},
        "ConflictConfirmedTrigger": {"conflicts", "selections", "conflict_snapshot", "pending_input"},
        "ProcedureProgress": {"requirements_confirmed", "submitted"},
        "ProcedureProgressReport": {
            "procedure_step", "status", "requirements_confirmed", "submitted",
        },
        "RedactedInput": {"procedure_reports"},
        "ProcedureProgressObservation": {"structured_report"},
        "ProcedureProgressChangeCandidate": {
            "before_requirements_confirmed", "proposed_requirements_confirmed",
            "before_submitted", "proposed_submitted",
        },
        "CompletedDecisionDraft": {"followup_guidance"},
    }
    missing = [
        f"{name}.{field}"
        for name, fields in required.items()
        for field in sorted(fields - set(getattr(getattr(agent_schemas, name, None), "model_fields", {})))
    ]
    fields = getattr(agent_schemas, "AgentFieldKey", ())
    if not {"had_employees", "pension_enrolled", "health_insurance_enrolled",
            "employment_insurance_enrolled", "industrial_accident_insurance_enrolled"}.issubset(
                {item.value for item in fields}):
        missing.append("AgentFieldKey.employee_and_insurance_history")
    if missing:
        raise SystemExit("--suite core requires the planning feature DTOs: " + ", ".join(missing))


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


def write_metadata(path: Path, value) -> None:
    """Keep a complete metadata file even when the process is interrupted."""
    pending = path.with_name(path.name + ".tmp")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)


def credentials_rejected(calls: list[dict]) -> bool:
    return any(call.get("http_status") in {401, 403} for call in calls)


def expected_model_calls(calls: list[dict]) -> bool:
    return bool(calls) and all(
        call.get("role") in ROLE_BY_PREFIX.values()
        and call.get("model") == "gpt-6.1-sol"
        and call.get("reasoning_effort") == "xhigh"
        for call in calls
    )


PRIOR_FACT_FIELDS = (
    "restoration_status", "restoration_scope", "restoration_scope_detail", "demolition_required",
)
DATASET_BRANCHES = {"REPLAN_OR_NEEDS_MORE_INFO": "REVIEWED_PLAN", "CONFLICT": "CONFLICT"}


def build_case_snapshot(
    payload: dict, prior_facts: dict | None = None
) -> tuple[CaseSnapshot, str]:
    """Map the five intake answers onto a Case read view, without a database.

    This is NOT the BE contract. BE builds a snapshot by reading a saved Case
    row, so it has a real snapshot id, case id and captured_at. Here those are
    derived from the payload so the same answers always produce the same input.
    No domain fact missing from the intake form is guessed: restoration and
    demolition stay UNKNOWN, which is exactly what the form does not ask.

    ``prior_facts`` is a dataset row's state before its result input, for the
    four restoration fields only (None = still unknown). Without it the output
    is byte-identical to earlier runs, so their recorded digests stay comparable.
    """

    request = CaseCreateRequest.model_validate(payload)
    normalized = request.model_dump(mode="json")
    text = canonical(normalized)
    prior = {name: (prior_facts or {}).get(name) for name in PRIOR_FACT_FIELDS}
    known = {name: value for name, value in prior.items() if value is not None}
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
    evidence_records = [evidence]
    # A restoration fact confirmed by an earlier result input needs its own
    # evidence; citing the intake form for it would claim the form asked it.
    prior_evidence = None
    if known:
        prior_text = canonical(known)
        prior_evidence = evidence.model_copy(update={
            "evidence_id": "synthetic-prior-result-input",
            "source_ref": "synthetic:dataset-current-facts",
            "excerpt": prior_text,
            "content_hash": hashlib.sha256(prior_text.encode()).hexdigest(),
        })
        evidence_records.append(prior_evidence)
    fields = [
        ("business_type", "STRING", request.business_type, evidence),
        ("franchise_status", "BOOLEAN", request.franchise_status, evidence),
        ("employee_count", "INTEGER", request.employee_count, evidence),
        ("lease_status", "ENUM", request.lease_status, evidence),
        # BE stores the enum UNKNOWN; the Agent models UNKNOWN as status + null.
        ("restoration_status", "ENUM", prior["restoration_status"], prior_evidence),
        ("restoration_scope", "ENUM", prior["restoration_scope"], prior_evidence),
        ("restoration_scope_detail", "STRING", prior["restoration_scope_detail"], prior_evidence),
        ("demolition_required", "ENUM", prior["demolition_required"], prior_evidence),
        ("planned_closure_date", "DATE", normalized["planned_closure_date"], evidence),
    ]
    snapshot_key = text if not known else canonical({"form": normalized, "prior": known})
    snapshot = CaseSnapshot(
        snapshot_id=uuid5(NAMESPACE, "snapshot:" + snapshot_key),
        case_id=1,
        case_status="IN_PROGRESS",
        facts=[
            CaseFact(
                field_path=name,
                value_type=kind,
                value=value,
                status="UNKNOWN" if value is None else "CONFIRMED",
                evidence_refs=[] if value is None else [source.evidence_id],
                updated_at=None if value is None else FIXED_TIME,
            )
            for name, kind, value, source in fields
        ],
        procedure_progress=[],
        evidence_records=evidence_records,
        captured_at=FIXED_TIME,
    )
    return snapshot, text


def build_graph_input(
    payload: dict, *, result_text: str | None = None, prior_facts: dict | None = None
):
    """CASE_CREATED for the intake form, RESULT_SUBMITTED for a typed result."""

    snapshot, form_text = build_case_snapshot(payload, prior_facts)
    text = form_text if result_text is None else result_text
    trigger_type = "CASE_CREATED" if result_text is None else "RESULT_SUBMITTED"
    event_id = f"synthetic-fe:{trigger_type}:" + digest(text).split(":")[1][:16]
    return AgentGraphInput(
        trigger={
            "trigger_type": trigger_type,
            "input_event_id": event_id,
            "client_event_id": None,
            "submitted_at": FIXED_TIME,
            "input": {
                "input_event_id": event_id,
                "source_type": "USER_INPUT",
                "redacted_text": text,
                "redactions": [],
                "submitted_at": FIXED_TIME,
            },
        },
        case_snapshot=snapshot,
        trace_id="evaluate-planning",
    )


def load_dataset(path: Path) -> dict[str, tuple[AgentGraphInput, dict]]:
    """One AgentGraphInput per JSONL row, keyed by its id, with the row itself.

    Each row carries its own intake answers and pre-input state, so rows run
    independently; no row's output feeds the next. Only typed results are
    supported: a conflict confirmation is a button press, not a result text.
    """

    items: dict[str, tuple[AgentGraphInput, dict]] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue

        def invalid(field: str, *, line_number: int = number) -> None:
            # Field names are fixed by this loader; never echo submitted values.
            raise SystemExit(f"line {line_number}: invalid or missing {field}")

        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            invalid("JSON")
        if not isinstance(row, dict):
            invalid("row object")
        row_id = row.get("start_set_id") or row.get("event_id")
        if not isinstance(row_id, str) or not row_id.strip():
            invalid("start_set_id/event_id")
        for field in ("difficulty", "scenario_family", "raw_input"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                invalid(field)
        if row.get("trigger_type") != "RESULT_SUBMITTED":
            invalid("trigger_type (RESULT_SUBMITTED required)")
        if not isinstance(row.get("expected_branch"), str) or row["expected_branch"] not in DATASET_BRANCHES:
            invalid("expected_branch")
        if not isinstance(row.get("must_not"), list) or any(
            not isinstance(item, str) or not item.strip() for item in row["must_not"]
        ):
            invalid("must_not")
        for field in ("current_facts", "expected_fact_changes"):
            if not isinstance(row.get(field), dict):
                invalid(field)
            for name, value in row[field].items():
                if name not in PRIOR_FACT_FIELDS:
                    invalid(field)
                try:
                    key = agent_schemas.AgentFieldKey(name)
                    agent_schemas.validate_case_field_value(
                        key, agent_schemas.CASE_FIELD_SPECS[key][0], value, allow_null=True,
                    )
                except ValueError:
                    invalid(field + "." + name)
        if not isinstance(row.get("case_create_request"), dict):
            invalid("case_create_request")
        try:
            CaseCreateRequest.model_validate_json(json.dumps(row["case_create_request"]), strict=True)
        except ValidationError:
            invalid("case_create_request")
        if row_id in items:
            invalid("duplicate start_set_id/event_id")
        try:
            request = build_graph_input(
                row["case_create_request"],
                result_text=row["raw_input"],
                prior_facts=row["current_facts"],
            )
        except ValidationError:
            invalid("case_create_request/current_facts/raw_input")
        items[row_id] = (request, row)
    if not items:
        raise SystemExit("dataset: at least one row is required")
    return items


def build_conflict_case(accepted: list[bool]) -> AgentGraphInput:
    """Restore a current conflict packet, including its nonconflicting date report."""
    values = {
        "restoration_scope": "PARTIAL", "restoration_status": "NOT_STARTED",
        "demolition_required": "NOT_REQUIRED",
    }
    snapshot, _ = build_case_snapshot(CASES["benchmark_case1"], values)
    text = "임대인에게 다시 확인하니 원상복구는 전체이고 철거가 필요하대요. 폐업 예정일은 2026-11-02입니다."
    event_id = "synthetic-stored-conflict-input"
    fingerprint = hashlib.sha256(text.encode()).hexdigest()
    evidence = EvidenceRecord(
        evidence_id=f"input:{event_id}:0:{len(text)}:{fingerprint[:12]}", source_type="USER_INPUT",
        source_ref=event_id, source_version=None, locator=f"text:0-{len(text)}",
        excerpt=text, parent_evidence_refs=[], published_at=None, retrieved_at=FIXED_TIME,
        freshness_status="CURRENT", content_hash=fingerprint,
    )
    snapshot.evidence_records.append(evidence)
    conflicts = [
        ConflictCandidate.create(
            conflict_ref="synthetic-conflict:" + field, candidate_id=uuid5(NAMESPACE, field),
            snapshot_id=snapshot.snapshot_id, field_path=field,
            committed_status="CONFIRMED", committed_value=values[field],
            proposed_operation="SET", proposed_status="CONFIRMED", proposed_value=value,
            source_evidence_refs=[evidence.evidence_id], source_call_id=uuid5(NAMESPACE, "prior-info"),
        )
        for field, value in (("restoration_scope", "FULL"), ("demolition_required", "REQUIRED"))
    ]
    pending = agent_schemas.ConflictPendingInput(
        original_input=agent_schemas.RedactedInput(
            input_event_id=event_id, source_type="USER_INPUT", redacted_text=text,
            redactions=[], submitted_at=FIXED_TIME,
        ),
        source_info_call_id=uuid5(NAMESPACE, "prior-info"),
        fact_candidates=[agent_schemas.FactCandidate(
            candidate_id=uuid5(NAMESPACE, "pending-closure-date"), operation="SET",
            field_path="planned_closure_date", value_type="DATE", value="2026-11-02",
            source_span={"input_event_id": event_id, "text": text, "start_offset": 0, "end_offset": len(text)},
            source_evidence_refs=[evidence.evidence_id], confidence_bps=10000,
            requires_confirmation=False, reason_summary="원 보고의 비충돌 폐업 예정일",
        )],
        procedure_progress_observations=[], pending_digest="sha256:" + "0" * 64,
    )
    pending.pending_digest = pending.calculate_digest(snapshot, conflicts)
    conflicts = [ConflictCandidate.create(
        **item.model_dump(exclude={"conflict_digest", "pending_input_digest"}),
        pending_input_digest=pending.pending_digest,
    ) for item in conflicts]
    return AgentGraphInput(
        trigger=ConflictConfirmedTrigger(
            trigger_type="CONFLICT_CONFIRMED", input_event_id="synthetic-confirmation",
            client_event_id=None, conflicts=conflicts,
            selections=[{"conflict_ref": item.conflict_ref, "accepted": choice}
                        for item, choice in zip(conflicts, accepted, strict=True)],
            conflict_snapshot=snapshot.model_copy(deep=True), pending_input=pending,
            confirmed_at=FIXED_TIME,
        ),
        case_snapshot=snapshot, trace_id="evaluate-conflict-batch",
    )


def build_completed_case(registry: list[KnownProcedureStep]) -> AgentGraphInput:
    """A fully reported synthetic cafe read view, including known exclusions."""
    from app.agent.procedure_tool.rules import procedure_applicability
    if {item.procedure_step.step_code for item in registry} != CAFE_TRACKED_CODES:
        raise ValueError("completed_scope requires the full cafe procedure registry")
    text = (
        "직원을 고용한 적이 없고 국민연금·건강보험·고용보험·산재보험 사업장에 가입한 적도 없습니다. "
        "원상복구와 철거는 불필요하다는 확인을 받았고 점포 반환을 마쳤습니다. "
        "영업 및 사업자 폐업신고는 기관의 처리 완료를 확인했습니다."
    )
    request = build_graph_input(CASES["benchmark_case1"] | {"employee_count": 0}, result_text=text)
    evidence = EvidenceRecord(
        evidence_id="synthetic-completed-report", source_type="USER_INPUT",
        source_ref="synthetic:prior-user-reports", source_version=None, locator=None,
        excerpt=text, parent_evidence_refs=[], published_at=None, retrieved_at=FIXED_TIME,
        freshness_status="CURRENT", content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    request.case_snapshot.evidence_records.append(evidence)
    for fact in request.case_snapshot.facts:
        if fact.field_path in {"restoration_scope", "restoration_status", "demolition_required"}:
            replacement = CaseFact(
                field_path=fact.field_path, value_type="ENUM", value="NOT_REQUIRED",
                status="CONFIRMED", evidence_refs=[evidence.evidence_id], updated_at=FIXED_TIME,
            )
            request.case_snapshot.facts[request.case_snapshot.facts.index(fact)] = replacement
    request.case_snapshot.facts.extend([
        CaseFact(field_path=field, value_type="BOOLEAN", value=False, status="CONFIRMED",
                 evidence_refs=[evidence.evidence_id], updated_at=FIXED_TIME)
        for field in (
            "had_employees", "pension_enrolled", "health_insurance_enrolled",
            "employment_insurance_enrolled", "industrial_accident_insurance_enrolled",
        )
    ])
    request.case_snapshot.procedure_progress = [
        ProcedureProgress(
            procedure_step=step.procedure_step, status="COMPLETED",
            requirements_confirmed=True,
            submitted=step.procedure_step.step_code in ADMINISTRATIVE_PROCEDURE_CODES,
            evidence_refs=[evidence.evidence_id], updated_at=FIXED_TIME,
        )
        for step in registry if procedure_applicability(step, request.case_snapshot) is True
    ]
    return AgentGraphInput.model_validate(request.model_dump(mode="python"))


def build_progress_case(case: str, registry: list[KnownProcedureStep]) -> AgentGraphInput:
    """Give each progress report a truthful prior read view and matching evidence."""
    from app.agent.procedure_tool.rules import procedure_applicability
    if {item.procedure_step.step_code for item in registry} != CAFE_TRACKED_CODES:
        raise ValueError("procedure progress cases require the full cafe registry")
    employed = case == "employee_partial_processing"
    restoration = case == "restoration_work_completed"
    text, prior, pending = {
        "restoration_work_completed": (
            "확인한 범위대로 원상복구와 철거 작업을 모두 마쳤습니다.",
            ("임대인에게 원상복구 범위는 전체이며 철거가 필요하다고 확인했고 작업 준비사항도 확인했습니다. "
             "원상복구·철거 작업과 점포 반환은 아직 시작하지 않았고 반환 준비사항도 아직 확인하지 않았습니다. "
             "식품영업 및 사업자 폐업신고는 해당 기관의 처리 완료를 확인했습니다."),
            {"PERFORM_RESTORATION": True, "RETURN_PREMISES": False},
        ),
        "administrative_submitted": (
            "식품영업 폐업신고서를 구청에 제출해 접수됐지만 기관 처리 완료는 아직 확인 못했습니다.",
            ("원상복구와 철거는 불필요하다는 확인을 받았고 점포 반환도 마쳤습니다. "
             "사업자 폐업신고는 기관의 처리 완료를 확인했습니다. "
             "식품영업 폐업신고 준비사항은 확인했지만 신고서는 아직 제출하지 않았습니다."),
            {"FILE_FOOD_SERVICE_CLOSURE": True},
        ),
        "employee_partial_processing": (
            "직원 두 명 중 한 명만 4대보험 자격상실 처리가 끝났고 다른 직원은 남아 있습니다.",
            ("직원 두 명을 고용했고 국민연금·건강보험·고용보험·산재보험 사업장에 모두 가입했습니다. "
             "직원 전체의 임금·퇴직급여 정산은 마쳤습니다. 직원 보험 자격상실 신고 준비사항은 확인했지만 "
             "직원 자격상실 신고와 사업장 탈퇴·소멸 신고는 아직 제출하지 않았습니다. "
             "사업장 탈퇴·소멸 신고의 준비사항도 아직 확인하지 않았습니다. "
             "원상복구와 철거는 불필요하다는 확인을 받았고 점포 반환도 마쳤습니다. "
             "식품영업 및 사업자 폐업신고는 기관의 처리 완료를 확인했습니다."),
            {"REPORT_EMPLOYEE_INSURANCE_LOSS": True, "REPORT_WORKPLACE_INSURANCE_CLOSURE": False},
        ),
    }[case]
    if not employed:
        prior += " 직원을 고용한 적이 없고 국민연금·건강보험·고용보험·산재보험 사업장에 가입한 적도 없습니다."
    request = build_graph_input(
        CASES["benchmark_case1"] | {"employee_count": 2 if employed else 0}, result_text=text,
    )
    report_code, report_status, report_submitted = {
        "restoration_work_completed": ("PERFORM_RESTORATION", "COMPLETED", False),
        "administrative_submitted": ("FILE_FOOD_SERVICE_CLOSURE", "IN_PROGRESS", True),
        "employee_partial_processing": ("REPORT_EMPLOYEE_INSURANCE_LOSS", "IN_PROGRESS", False),
    }[case]
    request.trigger.input.procedure_reports = [agent_schemas.ProcedureProgressReport(
        procedure_step=next(step.procedure_step for step in registry
                            if step.procedure_step.step_code == report_code),
        status=report_status, requirements_confirmed=True, submitted=report_submitted,
    )]
    evidence = EvidenceRecord(
        evidence_id="synthetic-prior-report:" + case, source_type="USER_INPUT",
        source_ref="synthetic:prior-user-reports", source_version=None, locator=None,
        excerpt=prior, parent_evidence_refs=[], published_at=None, retrieved_at=FIXED_TIME,
        freshness_status="CURRENT", content_hash=hashlib.sha256(prior.encode()).hexdigest(),
    )
    request.case_snapshot.evidence_records.append(evidence)
    values = {
        "restoration_scope": "FULL" if restoration else "NOT_REQUIRED",
        "demolition_required": "REQUIRED" if restoration else "NOT_REQUIRED",
    }
    if not restoration:
        values["restoration_status"] = "NOT_REQUIRED"
    request.case_snapshot.facts = [
        CaseFact(field_path=fact.field_path, value_type="ENUM", value=values[fact.field_path],
                 status="CONFIRMED", evidence_refs=[evidence.evidence_id], updated_at=FIXED_TIME)
        if fact.field_path in values else fact
        for fact in request.case_snapshot.facts
    ]
    request.case_snapshot.facts.extend([
        CaseFact(field_path=field, value_type="BOOLEAN", value=employed, status="CONFIRMED",
                 evidence_refs=[evidence.evidence_id], updated_at=FIXED_TIME)
        for field in (
            "had_employees", "pension_enrolled", "health_insurance_enrolled",
            "employment_insurance_enrolled", "industrial_accident_insurance_enrolled",
        )
    ])
    request.case_snapshot.procedure_progress = [
        ProcedureProgress(
            procedure_step=step.procedure_step,
            status="NOT_STARTED" if step.procedure_step.step_code in pending else "COMPLETED",
            requirements_confirmed=pending.get(step.procedure_step.step_code, True),
            submitted=step.procedure_step.step_code in ADMINISTRATIVE_PROCEDURE_CODES
            and step.procedure_step.step_code not in pending,
            evidence_refs=[evidence.evidence_id], updated_at=FIXED_TIME,
        )
        for step in registry if procedure_applicability(step, request.case_snapshot) is True
    ]
    return AgentGraphInput.model_validate_json(request.model_dump_json())


def build_core_request(case: str, registry: list[KnownProcedureStep]) -> AgentGraphInput:
    expected = CORE_EXPECTATIONS[case]
    if expected.get("request_kind") == "conflict":
        return build_conflict_case(expected["accepted"])
    if expected.get("request_kind") == "completion":
        return build_completed_case(registry)
    if expected.get("request_kind") == "procedure_progress":
        return build_progress_case(case, registry)
    text = None
    if text is None and expected["result_input"] is not None:
        text = RESULT_INPUTS[expected["result_input"]]
    return build_graph_input(CASES["benchmark_case1"], result_text=text)


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


def attach_fixture_sources(request: AgentGraphInput, store: SnapshotStore) -> AgentGraphInput:
    """Supply the reviewed Evidence a BE-built snapshot normally carries.

    Only CLI-generated fixtures use this helper. A caller-supplied --graph-input
    remains untouched, including deliberately missing or stale source records.
    """
    owned = request.model_copy(deep=True)
    for record in store.records():
        existing = [item for item in owned.case_snapshot.evidence_records
                    if item.source_type == "OFFICIAL_DOCUMENT"
                    and item.source_ref == record.canonical_url
                    and item.source_version == store.snapshot_version]
        if existing:
            continue
        owned.case_snapshot.evidence_records.append(EvidenceRecord(
            evidence_id="synthetic-reviewed:" + digest([store.snapshot_version, record.record_id])[-40:],
            source_type="OFFICIAL_DOCUMENT", source_ref=record.canonical_url,
            source_version=store.snapshot_version, locator=None, excerpt=record.excerpt,
            parent_evidence_refs=[], published_at=record.published_at,
            retrieved_at=record.retrieved_at, freshness_status=record.freshness(FIXED_TIME.date()),
            content_hash=record.content_hash,
        ))
    if isinstance(owned.trigger, ConflictConfirmedTrigger) and getattr(owned.trigger, "conflict_snapshot", None) is not None:
        trigger_data = owned.trigger.model_dump(mode="python")
        trigger_data["conflict_snapshot"] = owned.case_snapshot.model_copy(deep=True)
        if owned.trigger.pending_input is not None:
            pending = owned.trigger.pending_input
            pending.pending_digest = pending.calculate_digest(owned.case_snapshot, owned.trigger.conflicts)
            trigger_data["pending_input"] = pending
            trigger_data["conflicts"] = [ConflictCandidate.create(
                **item.model_dump(exclude={"conflict_digest", "pending_input_digest"}),
                pending_input_digest=pending.pending_digest,
            ) for item in owned.trigger.conflicts]
        owned.trigger = ConflictConfirmedTrigger.model_validate(trigger_data)
    return AgentGraphInput.model_validate(owned.model_dump(mode="python"))


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

    # The original snapshot and its text-only correction use the same master rules.
    if store.snapshot_version in {CAFE_SOURCE_VERSION, "cafe-official-sources/2026-10-18"}:
        try:
            from app.agent.procedure_tool.cafe import build_cafe_procedure_steps
        except ImportError:
            raise ValueError("this cafe source version requires the cafe procedure feature") from None
        codes = sorted({code for record in store.records() for code in record.step_codes})
        return build_cafe_procedure_steps({code: index for index, code in enumerate(codes, start=1)})
    steps: list[KnownProcedureStep] = []
    seen = set()
    for record in store.records():
        for code in record.step_codes:
            if code in seen:
                continue
            seen.add(code)
            name, aliases = _STEP_NAMES.get(code, (record.title, []))
            steps.append(
                KnownProcedureStep(
                    procedure_step={
                        "procedure_step_id": len(steps) + 1, "step_code": code
                    },
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


def code_version() -> dict:
    """Which prompts and code ran: the commit, and whether edits sat on top of it."""

    def git(*args):
        done = subprocess.run(
            ["git", *args], cwd=Path(__file__).parent, capture_output=True, text=True,
            check=False,
        )
        return done.stdout.strip() if done.returncode == 0 else None

    status = git("status", "--porcelain")
    return {"git_commit": git("rev-parse", "HEAD"), "uncommitted_changes": bool(status)}


def evaluation_code_digest() -> str:
    """Identify the exact Agent, prompts, dataset and evaluation harness bytes."""
    backend_root = Path(__file__).resolve().parents[1]
    files = sorted([
        *backend_root.joinpath("app/agent").rglob("*.py"),
        *backend_root.joinpath("scripts").rglob("*.py"),
    ])
    content = hashlib.sha256()
    for path in files:
        content.update(str(path.relative_to(backend_root)).encode())
        content.update(path.read_bytes())
    return "sha256:" + content.hexdigest()


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

    def __init__(
        self, role: str, calls: list[dict], on_update: Callable[[], None] | None = None
    ) -> None:
        self._role, self._calls = role, calls
        self._inner = httpx.AsyncHTTPTransport()
        self._on_update = on_update

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
        if schema.get("name") == "ContentSafetyDecision":
            for message in body.get("messages", []):
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if message.get("role") != "user" or not isinstance(content, str):
                    continue
                if content.startswith("INPUT_JSON="):
                    try:
                        stage = json.loads(content.removeprefix("INPUT_JSON=")).get("stage")
                    except (ValueError, AttributeError):
                        continue
                    if isinstance(stage, str) and stage in {"INPUT", "OUTPUT", "SOURCES", "SUBMISSION"}:
                        record["safety_stage"] = stage
        self._calls.append(record)
        if self._on_update is not None:
            self._on_update()
        started = perf_counter()
        try:
            response = await self._inner.handle_async_request(request)
            record["http_status"] = response.status_code
            return response
        except (Exception, asyncio.CancelledError) as exc:
            record["transport_error_type"] = type(exc).__name__
            raise
        finally:
            record["headers_latency_ms"] = round((perf_counter() - started) * 1000)
            if self._on_update is not None:
                self._on_update()

    async def aclose(self) -> None:
        await self._inner.aclose()


def recording_from_env(calls: list[dict], on_update: Callable[[], None] | None = None):
    real = StructuredLLMClient.from_env

    def from_env(*, env_prefix: str = "", **kwargs):
        return real(
            env_prefix=env_prefix,
            **kwargs,
            transport=RecordingTransport(ROLE_BY_PREFIX[env_prefix], calls, on_update),
        )

    return from_env


def recording_review(tool, reviews: list[dict], on_update: Callable[[], None] | None = None):
    """Observe the real Review result without changing it or recording prose."""
    original = tool.review

    async def review(subject):
        result = await original(subject)
        reviews.append({
            "review_attempt": subject.review_attempt,
            "verdict": as_text(result.verdict),
            "issues": [{
                "issue_code": as_text(issue.issue_code),
                "category": as_text(issue.category),
                "severity": as_text(issue.severity),
                "target_component": as_text(issue.target_component),
                "target_path": issue.target_path,
            } for issue in result.issues],
            "missing_evidence_paths": [item.claim_path for item in result.missing_evidence],
        })
        if on_update is not None:
            on_update()
        return result

    return review


def decision_summary(outcome) -> dict:
    """Record structure and digests without generated text or source quotations.

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
                {"field_path": as_text(item.field_path), "digest": item.conflict_digest}
                for item in getattr(outcome, "conflicts", [])
            ],
        }
    subject = outcome.review_subject
    decision = subject.supervisor_draft.decision
    blocker = decision.blocker
    action = decision.next_action
    target_step = None if action is None else getattr(action.target, "procedure_step", None)
    changes = subject.supervisor_draft.mutations.fact_changes
    return {
        "decision_type": as_text(decision.decision_type),
        "blocker_digest": (
            None if blocker is None else canonical_digest(blocker, exclude={"evidence_refs"})
        ),
        "blocker_count": len(getattr(decision, "blockers", [blocker] if blocker else [])),
        "blocker_candidate_ids": [
            item.candidate_id for item in getattr(decision, "blockers", [])
            if getattr(item, "candidate_id", None) is not None
        ],
        "next_action_digest": (
            None
            if action is None
            else canonical_digest(action, exclude={"evidence_refs"})
        ),
        "action_code": None if action is None else as_text(action.action_code),
        "action_target_step_code": None if target_step is None else target_step.step_code,
        "questions_for_user_count": len(decision.questions_for_user),
        "questions_for_user_digest": digest(list(decision.questions_for_user)),
        "followup_guidance_count": len(getattr(decision, "followup_guidance", [])),
        # What the 다시 계산했습니다 screen shows as 방금 반영된 내용.
        "fact_changes": [
            {
                "field_path": as_text(change.field_path),
                "before_status": as_text(change.before_status),
                "proposed_status": as_text(change.proposed_status),
                "proposed_value": (
                    digest(change.model_dump(mode="json")["proposed_value"])
                    if as_text(change.value_type) == "STRING"
                    else change.model_dump(mode="json")["proposed_value"]
                ),
                "confirmed_conflict_ref": change.confirmed_conflict_ref,
            }
            for change in changes
        ],
        "procedure_changes": [
            {"step_code": change.procedure_step.step_code,
             "before_status": as_text(change.before_status),
             "proposed_status": as_text(change.proposed_status),
             "before_requirements_confirmed": getattr(change, "before_requirements_confirmed", None),
             "proposed_requirements_confirmed": getattr(change, "proposed_requirements_confirmed", None),
             "before_submitted": getattr(change, "before_submitted", None),
             "proposed_submitted": getattr(change, "proposed_submitted", None)}
            for change in getattr(subject.supervisor_draft.mutations, "procedure_progress_changes", [])
        ],
        "support_update_count": len(getattr(
            subject.supervisor_draft.mutations, "support_match_updates", []
        )),
        # Recorded, never gated: rework bookkeeping is not user-visible text.
        "review_attempt": subject.review_attempt,
        "draft_version": decision.draft_version,
    }


async def trial(
    case: str, request: AgentGraphInput, store, registry, catalog,
    *, calls_path: Path | None = None,
) -> dict:
    calls: list[dict] = []
    reviews: list[dict] = []
    result = {
        "case": case,
        "trigger": as_text(request.trigger.trigger_type),
        "graph_input_digest": canonical_digest(request),
        "status": "ERROR",
        "calls": calls,
        "review_results": reviews,
    }
    on_update = (
        lambda: write_metadata(calls_path, {"case": case, "calls": calls, "review_results": reviews})
    ) if calls_path is not None else None
    runtime = None
    started = perf_counter()
    try:
        with patch.object(
            runtime_module.StructuredLLMClient, "from_env", recording_from_env(
                calls, on_update,
            )
        ):
            runtime = await runtime_module.build_runtime(
                known_procedure_steps=registry,
                procedure_store=store,
            )
        result["limits"] = asdict(runtime.limits)
        tool = runtime._graph._review_tool
        with patch.object(tool, "review", recording_review(tool, reviews, on_update)):
            outcome = await runtime.run_planning(request)
        outcome = TypeAdapter(AgentGraphOutput).validate_python(outcome)
        if outcome.outcome_type == "REVIEWED_PLAN":
            outcome.assert_integrity()
            result["review_proof_valid"] = True
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
        result["input_unchanged"] = canonical_digest(request) == result["graph_input_digest"]
    return result


def expectation_checks(row: dict, expected: dict) -> dict[str, bool]:
    """Assess actual domain behavior separately from prose repeatability."""
    changes = {item["field_path"]: item for item in row.get("fact_changes", [])}
    procedure_changes = {item["step_code"]: item for item in row.get("procedure_changes", [])}
    action = row.get("action_code")
    successful_schemas = {
        call.get("schema_name") for call in row.get("calls", [])
        if call.get("http_status") == 200
    }
    reviewed = row.get("status") == "REVIEWED_PLAN"
    return {
        "expected_outcome": row.get("status") in expected["outcomes"],
        "review_proof_valid": not reviewed or row.get("review_proof_valid") is True,
        "input_preserved": row.get("input_unchanged", True),
        "expected_models_called": expected_model_calls(row.get("calls", [])),
        "expected_decision": not reviewed or row.get("decision_type") in expected.get(
            "decisions", ["ACTION", "NEEDS_MORE_INFO"]
        ),
        "expected_action": action is None or action in expected.get("actions", [action]),
        "expected_action_target": "action_targets" not in expected or (
            action in expected["action_targets"]
            and row.get("action_target_step_code") == expected["action_targets"][action]
        ),
        "valid_action": (
            action in EVALUATION_ACTION_CODES if row.get("decision_type") == "ACTION" else action is None
        ),
        "question_when_needed": row.get("decision_type") != "NEEDS_MORE_INFO"
        or row.get("questions_for_user_count", 0) > 0,
        "no_forbidden_changes": not set(changes).intersection(expected.get("forbidden_fact_fields", [])),
        "required_blockers": set(expected.get("required_blocker_candidates", [])).issubset(
            row.get("blocker_candidate_ids", [])
        ),
        "only_allowed_changes": "allowed_fact_fields" not in expected
        or set(changes).issubset(expected["allowed_fact_fields"]),
        "no_unapproved_procedure_changes": not expected.get("no_procedure_changes")
        or not row.get("procedure_changes"),
        "only_expected_procedure_changes": "procedure_expectations" not in expected
        or set(procedure_changes).issubset(expected["procedure_expectations"]),
        "expected_procedure_states": all(
            (not state["required_change"] if code not in procedure_changes else (
                procedure_changes[code].get("proposed_status") in state["statuses"]
                and procedure_changes[code].get("proposed_submitted") is state["submitted"]
                and procedure_changes[code].get("proposed_requirements_confirmed")
                is state["requirements_confirmed"]
            ))
            for code, state in expected.get("procedure_expectations", {}).items()
        ),
        "required_facts": all(
            changes.get(field, {}).get("proposed_status") == "CONFIRMED"
            and changes.get(field, {}).get("proposed_value") == value
            for field, value in expected.get("required_facts", {}).items()
        ),
        "no_support_mutations": row.get("support_update_count", 0) == 0,
        "completed_has_no_fake_action": row.get("decision_type") != "COMPLETED" or (
            action is None and row.get("blocker_count") == 0
            and row.get("questions_for_user_count") == 0
            and row.get("followup_guidance_count", 0) > 0
        ),
        "required_components_called": not reviewed or {
            "ContentSafetyDecision", "reborn_info_analysis", "reborn_supervisor_draft",
            "reborn_review_output",
        }.issubset(successful_schemas),
    }


def verdict(rows: list[dict], expected: dict | None = None) -> dict:
    """Did every repeat of one case produce the same Blocker and Next Action?

    Two different questions are reported separately, because a provider outage
    and a model changing its mind are not the same problem:
      reliability -- did every repeat produce a reviewed plan at all
                     (or a conflict outcome when grading a dataset)
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
    behavior = [expectation_checks(row, expected) for row in rows] if expected else []
    reliable = bool(rows) and checks["no_errors"] and checks["provider_called_every_repeat"] and (
        all(item["expected_outcome"] for item in behavior)
        if expected else checks["all_reviewed_plan"]
    )
    passed = all(all(item.values()) for item in behavior) if expected else all(checks.values())
    passed = passed and bool(rows) and all(checks[key] for key in (
        "no_errors", "same_graph_input", "provider_called_every_repeat",
    ))
    if expected is None and any("score" in row for row in rows):
        # A correctly predicted CONFLICT is a successful dataset result too.
        reliable = bool(rows) and checks["no_errors"] and checks["provider_called_every_repeat"] and all(
            row["status"] in DATASET_BRANCHES.values() for row in rows
        )
        passed = reliable and all(checks[key] for key in consistency) and all(
            row.get("score", {}).get("result") == "PASS" for row in rows
        )
    return {
        "repeats": len(rows),
        "reviewed_plans": len(planned),
        # What the repeats that succeeded agreed on.
        "consistency": "PASS" if all(checks[key] for key in consistency) else "FAIL",
        # Whether every repeat got that far at all.
        "reliability": "PASS" if reliable else "FAIL",
        "verdict": "PASS" if passed else "FAIL",
        "expected_behavior": behavior,
        **checks,
    }


# Enum fields a dataset row fixes; any change outside the expected ones is wrong.
# restoration_scope_detail is free text, so it is recorded but never scored.
SCORED_FIELDS = ("demolition_required", "restoration_scope", "restoration_status")
# must_not items decidable from the outcome's state. The rest need a person to
# read the Blocker and Next Action text, so they are listed, never auto-passed.
STATE_CHECKS = {
    "PLANNED_CLOSURE_DATE_CHANGED": lambda r: any(
        c["field_path"] == "planned_closure_date" for c in r.get("fact_changes", [])
    ),
    "TAX_FILING_COMPLETED_WITHOUT_PROOF": lambda r: any(
        c["step_code"] == "FILE_TAX_BUSINESS_CLOSURE" and c["proposed_status"] == "COMPLETED"
        for c in r.get("procedure_changes", [])
    ),
}
# Both mean "a scored field changed when it should not have"; the change
# comparison in score() already fails that, so nobody needs to read for them.
SCORED_BY_COMPARISON = {"SILENT_FACT_OVERWRITE", "UNCONFIRMED_DEMOLITION_VALUE"}


def score(row: dict, result: dict) -> dict:
    """PASS / WRONG / RUN_FAILED for one dataset row against one trial.

    A provider outage or safe failure is RUN_FAILED, not WRONG: it says nothing
    about whether the model understood the owner's sentence.
    """

    status = result["status"]
    if status not in ("REVIEWED_PLAN", "CONFLICT"):
        reason = result.get("failure_code") or (result.get("error") or {}).get("type")
        return {"result": "RUN_FAILED", "reasons": [f"{status}: {reason}"]}

    reasons = []
    expected_status = DATASET_BRANCHES[row["expected_branch"]]
    if status != expected_status:
        reasons.append(f"expected {expected_status}, got {status}")
    elif status == "REVIEWED_PLAN":
        changed = {
            c["field_path"]: c["proposed_value"]
            for c in result["fact_changes"] if c["field_path"] in SCORED_FIELDS
        }
        expected = {
            k: v for k, v in row["expected_fact_changes"].items() if k in SCORED_FIELDS
        }
        if changed != expected:
            reasons.append(f"changes {changed} != expected {expected}")
    for item in row["must_not"]:
        if item in STATE_CHECKS and STATE_CHECKS[item](result):
            reasons.append(f"must_not {item}")
    return {
        "result": "WRONG" if reasons else "PASS",
        "reasons": reasons,
        "human_check": [
            item for item in row["must_not"]
            if item not in STATE_CHECKS and item not in SCORED_BY_COMPARISON
        ],
        "detail_changed": any(
            c["field_path"] == "restoration_scope_detail" for c in result.get("fact_changes", [])
        ),
    }


def dataset_summary(rows: list[dict]) -> dict:
    """Counts a person reads first; per-row reasons stay in each trial file."""

    def passed_by(key):
        groups: dict[str, list[str]] = {}
        for row in rows:
            groups.setdefault(row[key], []).append(row["score"]["result"])
        return {k: f"{v.count('PASS')}/{len(v)}" for k, v in sorted(groups.items())}

    return {
        "results": dict(Counter(row["score"]["result"] for row in rows)),
        "pass_by_difficulty": passed_by("difficulty"),
        "pass_by_family": passed_by("scenario_family"),
        # RUN_FAILED is shown with its codes, never folded into PASS or hidden.
        "not_passed": [
            {"case": row["case"], "repeat": row["repeat"], **row["score"]}
            for row in rows if row["score"]["result"] != "PASS"
        ],
        "human_check_cases": sorted({
            row["case"] for row in rows if row["score"].get("human_check")
        }),
    }


def overall_verdict(per_case: dict, dataset_rows: list[dict] | None) -> str:
    """A wrong or failed dataset row fails the run even when every repeat agreed."""
    if any(v["verdict"] != "PASS" for v in per_case.values()):
        return "FAIL"
    if dataset_rows is not None and any(
        row["score"]["result"] != "PASS" for row in dataset_rows
    ):
        return "FAIL"
    return "PASS"


async def run(args) -> None:
    graph_input_path = getattr(args, "graph_input", None)
    dataset_path = getattr(args, "dataset", None)
    core = getattr(args, "suite", None) == "core"
    fixed_suite = core
    if core:
        require_core_contract()
    if getattr(args, "core_case", None) and not core:
        raise SystemExit("--core-case requires --suite core")
    if fixed_suite and (dataset_path is not None or graph_input_path is not None or args.case or args.result_input is not None):
        raise SystemExit("a fixed suite cannot be combined with another input selector")
    if graph_input_path is not None and (args.case or args.result_input is not None):
        raise SystemExit("--graph-input cannot be combined with --case or --result-input")
    if dataset_path is not None and (
        graph_input_path is not None or args.case or args.result_input is not None
    ):
        raise SystemExit("--dataset cannot be combined with --graph-input, --case or --result-input")

    store = SnapshotStore(args.procedure_snapshot)
    registry = build_registry(store)
    catalog = load_catalog(args.support_catalog)
    expected = dict(pair.split("=", 1) for pair in args.expect)
    # Read exactly what build_runtime will read: the process environment on
    # top of .env. Passing environ={} would check the file while the run used
    # an override, so the guard could pass for the wrong models.
    configs = {
        role: LLMConfig.from_env(env_prefix=prefix)
        for prefix, role in ROLE_BY_PREFIX.items()
    }
    configured = {role: config.model for role, config in configs.items()}
    if fixed_suite:
        expected.update({role: "gpt-6.1-sol" for role in ROLE_BY_PREFIX.values()})
    mismatched = {
        role: {"expected": model, "configured": configured.get(role)}
        for role, model in expected.items()
        if configured.get(role) != model
    }

    if fixed_suite and any(config.reasoning_effort != "xhigh" for config in configs.values()):
        raise SystemExit("The fixed suites require xhigh for every configured role")

    if fixed_suite:
        cases = getattr(args, "core_case", None) or list(CORE_EXPECTATIONS)
        requests = {case: build_core_request(case, registry) for case in cases}
        case_inputs = {case: {"expectations": CORE_EXPECTATIONS[case]} for case in cases}
    elif dataset_path is not None:
        loaded = load_dataset(dataset_path)
        cases = list(loaded)
        requests = {case: request for case, (request, _row) in loaded.items()}
        # The file digest proves which dataset ran; the rows' text is not copied.
        case_inputs = {
            "dataset_file": str(dataset_path),
            "dataset_sha256": "sha256:" + hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
            "rows": len(cases),
        }
    elif graph_input_path is not None:
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
        case_inputs = {case: {"intake_digest": digest(CASES[case])} for case in cases}
    stores = {case: store for case in cases}
    registries = {case: registry for case in cases}
    if graph_input_path is None:
        requests = {case: attach_fixture_sources(request, stores[case])
                    for case, request in requests.items()}
    triggers = {case: as_text(request.trigger.trigger_type) for case, request in requests.items()}
    code_digest = evaluation_code_digest()
    manifest = {
        "code_digest": code_digest,
        "trigger": next(iter(triggers.values())) if len(set(triggers.values())) == 1 else "MIXED",
        "triggers": triggers,
        "result_input": args.result_input,
        "repeats": args.repeats,
        "cases": case_inputs,
        "graph_input_digests": {
            case: canonical_digest(request) for case, request in requests.items()
        },
        "code_version": code_version(),
        "configured_models": configured,
        "configured_efforts": {role: config.reasoning_effort for role, config in configs.items()},
        "expected_models": expected,
        "model_mismatch": mismatched,
        "sources": source_manifest(store, registry, catalog, args.support_catalog),
        "scope": (
            "지정한 Agent 입력으로 전체 판단 경로를 반복 실행한다. "
            "FE HTTP·로그인·DB 저장은 포함하지 않는다."
        ),
    }

    if args.validate_only:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        if mismatched:
            raise SystemExit(1)
        return
    if mismatched:
        raise SystemExit(f"configured models differ from --expect: {mismatched}")

    args.output.mkdir(parents=True, exist_ok=False)
    write_metadata(args.output / "manifest.json", manifest)

    rows: list[dict] = []
    # Sequential on purpose: the from_env patch is process-wide, so concurrent
    # trials would hand a transport to the wrong client.
    for repeat in range(1, args.repeats + 1):
        for case in cases:
            row = await trial(
                case, requests[case], stores[case], registries[case], catalog,
                calls_path=args.output / f"calls-{len(rows) + 1:03d}.json",
            )
            row["repeat"] = repeat
            if dataset_path is not None:
                expected_row = loaded[case][1]
                row["difficulty"] = expected_row["difficulty"]
                row["scenario_family"] = expected_row["scenario_family"]
                row["score"] = score(expected_row, row)
            rows.append(row)
            write_metadata(args.output / f"trial-{len(rows):03d}.json", row)
            print(
                json.dumps(
                    {**{key: row.get(key) for key in
                        ("case", "repeat", "status", "action_code", "elapsed_ms")},
                     "score": (row.get("score") or {}).get("result")},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            write_metadata(args.output / "results.json", rows)
            if credentials_rejected(row.get("calls", [])) or (
                row.get("error") or {}
            ).get("status_code") in (401, 403):
                raise SystemExit("Provider rejected credentials; remaining trials stopped.")

    per_case = {
        case: verdict(
            [row for row in rows if row["case"] == case],
            CORE_EXPECTATIONS[case] if fixed_suite else None,
        ) for case in cases
    }
    code_unchanged = evaluation_code_digest() == code_digest
    summary = {
        "code_unchanged": code_unchanged,
        "verdict": overall_verdict(per_case, rows if dataset_path is not None else None) if code_unchanged else "FAIL",
        "per_case": per_case,
        # If every different intake converges on one action, the run shows
        # consistency, not that the model picks well among several candidates.
        "distinct_next_action_digests": len(
            {row.get("next_action_digest") for row in rows}
        ),
        "trials": rows,
    }
    if dataset_path is not None:
        summary["dataset_score"] = dataset_summary(rows)
    write_metadata(args.output / "results.json", summary)
    print(json.dumps({k: summary[k] for k in ("verdict", "distinct_next_action_digests")},
                     ensure_ascii=False))
    if dataset_path is not None:
        print(json.dumps(summary["dataset_score"]["results"], ensure_ascii=False))
    if summary["verdict"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--procedure-snapshot", type=Path, required=True)
    parser.add_argument("--support-catalog", type=Path)
    parser.add_argument(
        "--graph-input", type=Path,
        help="AgentGraphInput JSON; cannot be combined with --case or --result-input",
    )
    parser.add_argument(
        "--dataset", type=Path,
        help="JSONL rows with case_create_request, current_facts and raw_input; "
        "cannot be combined with --graph-input, --case or --result-input",
    )
    parser.add_argument("--case", action="append", choices=sorted(CASES))
    parser.add_argument("--result-input", choices=sorted(RESULT_INPUTS))
    parser.add_argument("--suite", choices=["core"])
    parser.add_argument("--core-case", action="append", choices=sorted(CORE_EXPECTATIONS))
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--expect", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    try:
        asyncio.run(run(parser.parse_args()))
    except Exception as exc:  # noqa: BLE001 - validation errors may include submitted text
        print(json.dumps({"verdict": "ERROR", "error_type": type(exc).__name__,
                          "error_code": getattr(exc, "code", None)}))
        raise SystemExit(1) from None
