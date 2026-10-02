"""The BE-callable entry points, which BE wires a Case into.

These are the functions BE calls; nothing else in the suite covers them, so a
signature change here would otherwise only surface once BE is wired up. No
database, no provider: BE rows are built in memory and the runtime is replaced.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.agent.action_catalog import resolve_procedure_bindings
from app.agent.guardrails import GuardrailViolation
from app.agent.schemas import ProcedureStepRef
from app.agent.support_agent import ReviewedSupportCatalog
from app.be.models.procedure_step import ProcedureStep, StepDependency
from app.common.agent_data import (
    InMemoryReviewedProcedureStore,
    build_known_procedure_steps,
)
from app.common.agent_dto import CaseSnapshot, RedactedInput
from app.common.agent_service import build_planning_input, run_case_planning

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)
REF = "synthetic-document"


def row(step_id, step_code, **changes):
    return ProcedureStep(
        id=step_id,
        step_code=step_code,
        step_name="합성 절차",
        registry_version="synthetic/1",
        **changes,
    )


def known(*steps, dependencies=(), db_timezone=SEOUL):
    return build_known_procedure_steps(
        list(steps), list(dependencies), [], db_timezone=db_timezone
    )


def redacted_input(**changes):
    return RedactedInput.model_validate({
        "input_event_id": "evt-1",
        "source_type": "USER_INPUT",
        "redacted_text": "가게를 정리하려고 합니다.",
        "redactions": [],
        "submitted_at": NOW,
        **changes,
    })


def case_snapshot():
    return CaseSnapshot.model_validate({
        "snapshot_id": UUID(int=1),
        "case_id": 1,
        "case_status": "IN_PROGRESS",
        "facts": [
            {
                "field_path": name,
                "value_type": kind,
                "value": value,
                "status": "CONFIRMED",
                "evidence_refs": [REF],
                "updated_at": NOW,
            }
            for name, kind, value in (
                ("business_type", "STRING", "카페"),
                ("franchise_status", "BOOLEAN", False),
                ("lease_status", "ENUM", "LEASED_PAID"),
            )
        ],
        "procedure_progress": [],
        "evidence_records": [
            {
                "evidence_id": REF,
                "source_type": "OFFICIAL_DOCUMENT",
                "source_ref": "https://example.org/synthetic",
                "source_version": None,
                "locator": None,
                "excerpt": "합성 발췌",
                "published_at": None,
                "retrieved_at": NOW,
                "freshness_status": "CURRENT",
                "content_hash": None,
                "parent_evidence_refs": [],
            }
        ],
        "captured_at": NOW,
    })


# 1. Bindings. BE's step_code is its own ("BUSINESS_CLOSURE_REPORT"), so the
# mapping is supplied, never guessed from a name or alias.
def test_bindings_reject_one_step_bound_twice():
    steps = known(row(11, "TAX_CLOSE_V2"))
    ref = ProcedureStepRef(procedure_step_id=11, step_code="TAX_CLOSE_V2")

    with pytest.raises(ValueError, match="multiple logical bindings"):
        resolve_procedure_bindings(
            steps,
            {"FILE_TAX_BUSINESS_CLOSURE": ref, "FILE_FOOD_SERVICE_CLOSURE": ref},
        )


def test_bindings_reject_a_logical_code_the_agent_does_not_define():
    steps = known(row(11, "TAX_CLOSE_V2"))
    ref = ProcedureStepRef(procedure_step_id=11, step_code="TAX_CLOSE_V2")

    with pytest.raises(ValueError, match="unknown logical procedure binding codes"):
        resolve_procedure_bindings(steps, {"FILE_TAX_BUSINES_CLOSURE": ref})


def test_bindings_reject_a_step_that_was_not_loaded():
    steps = known(row(11, "TAX_CLOSE_V2"))

    with pytest.raises(ValueError, match="unknown id\\+code"):
        resolve_procedure_bindings(
            steps,
            {
                "FILE_TAX_BUSINESS_CLOSURE": ProcedureStepRef(
                    procedure_step_id=12, step_code="TAX_CLOSE_V2"
                )
            },
        )


# 2. Registry adapter. The columns return naive datetimes, so the caller states
# the timezone and this must not guess UTC or the host zone.
def test_naive_deprecated_at_takes_the_declared_db_timezone():
    naive = datetime(2026, 9, 29, 10, 0)  # noqa: DTZ001 — 컬럼이 돌려주는 모양

    steps = known(row(11, "TAX_CLOSE_V2", deprecated_at=naive))

    assert steps[0].deprecated_at == naive.replace(tzinfo=SEOUL)
    assert steps[0].deprecated_at.utcoffset().total_seconds() == 9 * 3600


def test_db_timezone_must_be_a_tzinfo_not_its_name():
    with pytest.raises(TypeError, match="explicit datetime.tzinfo"):
        known(row(11, "TAX_CLOSE_V2"), db_timezone="Asia/Seoul")


def test_dependency_pointing_at_an_unloaded_step_is_rejected():
    dependency = StepDependency(
        procedure_step_id=11,
        prerequisite_procedure_step_id=99,
        dependency_type="REQUIRES",
    )

    with pytest.raises(ValueError, match="references unloaded procedure step 99"):
        known(row(11, "TAX_CLOSE_V2"), dependencies=[dependency])


# 3. Input assembly. Reject what MySQL would reject, while a retry is possible.
def test_planning_input_rejects_a_trace_id_longer_than_its_column():
    with pytest.raises(ValidationError):
        build_planning_input(
            trigger_type="CASE_CREATED",
            case_snapshot=case_snapshot(),
            user_input=redacted_input(),
            trace_id="t" * 101,
        )


def test_planning_input_rejects_an_unredacted_phone_number():
    with pytest.raises(GuardrailViolation, match="PHONE_NUMBER"):
        build_planning_input(
            trigger_type="CASE_CREATED",
            case_snapshot=case_snapshot(),
            user_input=redacted_input(
                redacted_text="임대인(010-1234-5678)에게 물어봤습니다."
            ),
        )


def test_planning_input_rejects_an_unknown_trigger():
    with pytest.raises(ValueError, match="CASE_CREATED or RESULT_SUBMITTED"):
        build_planning_input(
            trigger_type="CASE_CLOSED",
            case_snapshot=case_snapshot(),
            user_input=redacted_input(),
        )


# 4. The run itself. The real runtime opens provider clients and a trace sink,
# so it is replaced here; what matters is that the outcome is checked and the
# runtime is always closed, including on the failure path.
class FakeOutcome:
    def __init__(self, outcome_type):
        self.outcome_type = outcome_type
        self.integrity_checked = False

    def assert_integrity(self):
        self.integrity_checked = True


class FakeRuntime:
    def __init__(self, outcome=None, error=None):
        self.outcome = outcome
        self.error = error
        self.closed = False
        self.flushed = False

    async def run_planning(self, request, use_cache=False):
        if self.error is not None:
            raise self.error
        return self.outcome

    async def aclose(self):
        self.closed = True

    def flush(self):
        self.flushed = True


def plan_with(runtime):
    request = build_planning_input(
        trigger_type="CASE_CREATED",
        case_snapshot=case_snapshot(),
        user_input=redacted_input(),
    )

    async def run():
        with patch(
            "app.common.agent_service.build_runtime",
            new=AsyncMock(return_value=runtime),
        ):
            return await run_case_planning(
                request,
                known_procedure_steps=known(row(11, "FILE_TAX_BUSINESS_CLOSURE")),
                procedure_bindings={},
                procedure_store=InMemoryReviewedProcedureStore("synthetic/1", ()),
                support_catalog=ReviewedSupportCatalog.model_validate(
                    {
                        "programs": [],
                        "evidence_records": [],
                        "catalog_version": "synthetic/1",
                    }
                ),
            )

    return asyncio.run(run())


def test_a_reviewed_plan_is_integrity_checked_before_it_is_returned():
    outcome = FakeOutcome("REVIEWED_PLAN")
    runtime = FakeRuntime(outcome=outcome)

    assert plan_with(runtime) is outcome
    assert outcome.integrity_checked
    assert runtime.closed and runtime.flushed


def test_a_safe_failure_is_returned_without_the_reviewed_plan_check():
    outcome = FakeOutcome("SAFE_FAILURE")

    assert plan_with(FakeRuntime(outcome=outcome)) is outcome
    assert not outcome.integrity_checked


def test_the_runtime_is_closed_and_flushed_when_planning_raises():
    runtime = FakeRuntime(error=RuntimeError("provider down"))

    with pytest.raises(RuntimeError, match="provider down"):
        plan_with(runtime)

    assert runtime.closed and runtime.flushed
