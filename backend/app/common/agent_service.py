"""BE-callable planning entry point; database reads and writes stay with BE.

Pass a BE-built CaseSnapshot and reviewed reference data. This module does not
query SQL, manufacture evidence from a Case row, or claim an outcome was saved.
BE remains responsible for loading the snapshot and persisting the outcome.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from app.agent.action_catalog import ProcedureBindings
from app.agent.guardrails import ensure_no_sensitive_text
from app.agent.procedure_tool.store import ReviewedProcedureStore
from app.agent.runtime import RuntimeLimits, build_runtime
from app.agent.schemas import KnownProcedureStep
from app.agent.support_agent import ReviewedSupportCatalog
from app.common.agent_dto import (
    AgentGraphInput,
    AgentGraphOutput,
    CaseCreatedTrigger,
    CaseSnapshot,
    ConflictCandidate,
    ConflictConfirmedTrigger,
    RedactedInput,
    ResultSubmittedTrigger,
)

__all__ = [
    "build_conflict_input",
    "build_planning_input",
    "run_case_planning",
]


def build_planning_input(
    *,
    trigger_type: Literal["CASE_CREATED", "RESULT_SUBMITTED"],
    case_snapshot: CaseSnapshot,
    user_input: RedactedInput,
    client_event_id: str | None = None,
    trace_id: str | None = None,
) -> AgentGraphInput:
    """Use the persisted input event's ID/time, not invented run-time values.

    BE must authorize the Case and redact the submitted text before calling.
    The guardrail here is a last resort, not the redaction step: it rejects only
    a national ID, business registration number, mobile number or credential
    string.  Email, address, name and bank account are not checked, so BE must
    still redact them before calling.
    """
    if trigger_type not in {"CASE_CREATED", "RESULT_SUBMITTED"}:
        raise ValueError("input trigger must be CASE_CREATED or RESULT_SUBMITTED")
    ensure_no_sensitive_text([user_input.redacted_text])
    trigger_model = (
        CaseCreatedTrigger if trigger_type == "CASE_CREATED" else ResultSubmittedTrigger
    )
    return AgentGraphInput.model_validate({
        "trigger": trigger_model(
            trigger_type=trigger_type,
            input_event_id=user_input.input_event_id,
            client_event_id=client_event_id,
            input=user_input,
            submitted_at=user_input.submitted_at,
        ).model_dump(mode="python"),
        "case_snapshot": case_snapshot.model_dump(mode="python"),
        "trace_id": trace_id,
    })


def build_conflict_input(
    *,
    case_snapshot: CaseSnapshot,
    confirmed_conflict: ConflictCandidate,
    input_event_id: str,
    confirmed_at: datetime,
    client_event_id: str | None = None,
    trace_id: str | None = None,
) -> AgentGraphInput:
    """Accept the original candidate restored by BE, never a client field/value.

    BE checks ownership, expiry and single use before restoring this candidate.
    The Agent checks its digest/current Case values and reviews the new plan.
    """
    return AgentGraphInput.model_validate({
        "trigger": ConflictConfirmedTrigger(
            trigger_type="CONFLICT_CONFIRMED",
            input_event_id=input_event_id,
            client_event_id=client_event_id,
            confirmed_conflict=ConflictCandidate.model_validate(
                confirmed_conflict.model_dump(mode="python")
            ),
            confirmed_at=confirmed_at,
        ).model_dump(mode="python"),
        "case_snapshot": case_snapshot.model_dump(mode="python"),
        "trace_id": trace_id,
    })


async def run_case_planning(
    request: AgentGraphInput,
    *,
    known_procedure_steps: Sequence[KnownProcedureStep],
    procedure_bindings: ProcedureBindings,
    procedure_store: ReviewedProcedureStore,
    support_catalog: ReviewedSupportCatalog,
    limits: RuntimeLimits | None = None,
) -> AgentGraphOutput:
    """Build, invoke and close the real Agent using BE-supplied data.

    Explicit bindings map the AI's existing logical procedure codes to BE's
    actual id+step_code pairs. An empty mapping means no bound procedure;
    no label or TEMP_* name is interpreted as a mapping.

    REVIEWED_PLAN carries a PASS proof and uncommitted mutations. CONFLICT
    carries candidates for BE to retain. SAFE_FAILURE carries recovery fields.
    The BE caller rechecks the current Case and persists the reviewed outcome;
    returning this result does not report database persistence.
    """
    owned_request = AgentGraphInput.model_validate(request.model_dump(mode="python"))
    if isinstance(owned_request.trigger, (CaseCreatedTrigger, ResultSubmittedTrigger)):
        ensure_no_sensitive_text([owned_request.trigger.input.redacted_text])
    registry = [
        KnownProcedureStep.model_validate(step.model_dump(mode="python"))
        for step in known_procedure_steps
    ]
    catalog = ReviewedSupportCatalog.model_validate(support_catalog.model_dump())
    runtime = await build_runtime(
        known_procedure_steps=registry,
        procedure_bindings=procedure_bindings,
        procedure_store=procedure_store,
        support_catalog=catalog,
        limits=limits,
        use_decision_cache=False,
    )
    try:
        outcome = await runtime.run_planning(owned_request, use_cache=False)
        if outcome.outcome_type == "REVIEWED_PLAN":
            outcome.assert_integrity()
        return outcome
    finally:
        try:
            await runtime.aclose()
        finally:
            runtime.flush()
