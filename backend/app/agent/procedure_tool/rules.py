"""Evaluate the MVP subset of stored procedure rules against proposed Case state."""

from collections.abc import Mapping, Sequence
from datetime import date

from ..action_catalog import ProcedureBindings, effective_procedure_progress
from ..schemas import (
    CASE_FIELD_SPECS,
    CaseSnapshot,
    DecisionDraft,
    FactChangeCandidate,
    FactStatus,
    FactValueType,
    KnownProcedureStep,
    MutationSet,
    ProcedureProgressChangeCandidate,
    ProcedureProgressStatus,
    validate_case_field_value,
)
from ..schemas import AgentFieldKey as CaseFieldKey

# CASE.business_type holds the words the user typed ("카페"), while
# PROCEDURE_STEP.applicable_business_type holds a code ("CAFE"). Comparing them
# raw filters out every business-specific procedure, so convert first.
#
# Two known gaps, both owned outside the agent (see PR #45 review):
#   * This matches the whole typed value only.  FE takes business_type as free
#     text, so "개인 카페" or "커피숍" still miss every CAFE-only procedure.
#     Growing this dict is not the fix; FE offering a choice, or BE storing a
#     code, is.  Do not widen it here without agreeing that with FE/BE first.
#   * RESTAURANT cannot match anything yet: PROCEDURE_STEP
#     .applicable_business_type is Enum("ALL", "CAFE"), so no RESTAURANT row can
#     exist.  A 일반음식점 Case silently gets zero procedure candidates.
_BUSINESS_TYPE_CODES: dict[str, str] = {
    "카페": "CAFE",
    "휴게음식점": "CAFE",
    "식당": "RESTAURANT",
    "음식점": "RESTAURANT",
    "일반음식점": "RESTAURANT",
}


def business_type_code(value: object) -> object:
    """Return the procedure code for a Case business_type, else the value itself."""

    if type(value) is not str:
        return value
    return _BUSINESS_TYPE_CODES.get(value.strip(), value)


_INSURANCE_FIELDS = (
    CaseFieldKey.PENSION_ENROLLED,
    CaseFieldKey.HEALTH_INSURANCE_ENROLLED,
    CaseFieldKey.EMPLOYMENT_INSURANCE_ENROLLED,
    CaseFieldKey.INDUSTRIAL_ACCIDENT_INSURANCE_ENROLLED,
)


def employment_history_conflicts(values: Mapping[str, object]) -> bool:
    """A positive current staff count cannot establish no employment history."""
    count = values.get(CaseFieldKey.EMPLOYEE_COUNT)
    return (
        type(count) is int
        and count > 0
        and values.get(CaseFieldKey.HAD_EMPLOYEES) is False
    )


def procedure_applicability(
    step: KnownProcedureStep,
    snapshot: CaseSnapshot,
    fact_overlays: Sequence[FactChangeCandidate] = (),
) -> bool | None:
    """Distinguish a known exclusion from missing applicability facts."""
    return _applicability(step, snapshot, fact_overlays)[0]


def _applicability(
    step: KnownProcedureStep,
    snapshot: CaseSnapshot,
    fact_overlays: Sequence[FactChangeCandidate],
) -> tuple[bool | None, list[str]]:
    facts = {fact.field_path: (fact.status, fact.value) for fact in snapshot.facts}
    facts.update(
        (change.field_path, (change.proposed_status, change.proposed_value))
        for change in fact_overlays
    )
    values = {
        key: value
        for key, (status, value) in facts.items()
        if status == FactStatus.CONFIRMED
    }
    excluded = step.deprecated_at is not None
    unknown = False
    reasons = ["procedure is deprecated"] if excluded else []
    if step.applicable_business_type != "ALL":
        business = values.get(CaseFieldKey.BUSINESS_TYPE)
        if business is None:
            unknown = True
        elif business_type_code(business) != step.applicable_business_type:
            excluded = True
        if (
            business is None
            or business_type_code(business) != step.applicable_business_type
        ):
            reasons.append("applicable_business_type is not confirmed for this Case")
    for condition in step.eligibility_conditions:
        key, raw = condition.condition_key, condition.condition_value
        try:
            if key == "has_employee":
                expected = _boolean(raw)
                count = values.get(CaseFieldKey.EMPLOYEE_COUNT)
                actual = None if count is None else count > 0
            elif key == "has_workplace_insurance":
                expected = _boolean(raw)
                insured = [values.get(field) for field in _INSURANCE_FIELDS]
                actual = (
                    True
                    if any(value is True for value in insured)
                    else (False if all(value is False for value in insured) else None)
                )
            elif key == "is_leased":
                expected = _boolean(raw)
                lease = values.get(CaseFieldKey.LEASE_STATUS)
                actual = (
                    None if lease is None else lease in {"LEASED_PAID", "LEASED_FREE"}
                )
            elif key == "restoration_required":
                expected = _boolean(raw)
                scope = values.get(CaseFieldKey.RESTORATION_SCOPE)
                demolition = values.get(CaseFieldKey.DEMOLITION_REQUIRED)
                actual = (
                    True
                    if scope in {"PARTIAL", "FULL"} or demolition == "REQUIRED"
                    else False
                    if scope == "NOT_REQUIRED" and demolition == "NOT_REQUIRED"
                    else None
                )
            else:
                field = CaseFieldKey(key)
                value_type, _ = CASE_FIELD_SPECS[field]
                expected = (
                    _boolean(raw)
                    if value_type == FactValueType.BOOLEAN
                    else int(raw)
                    if value_type == FactValueType.INTEGER
                    else raw
                )
                validate_case_field_value(field, value_type, expected, allow_null=False)
                actual = values.get(field)
                if field == CaseFieldKey.HAD_EMPLOYEES and employment_history_conflicts(values):
                    actual = None
                if type(actual) is date:
                    actual = actual.isoformat()
        except ValueError:
            unknown = True
            reasons.append(f"unsupported or invalid eligibility condition: {key}")
            continue
        if actual is None:
            unknown = True
            reasons.append(f"eligibility fact is not confirmed: {key}")
        elif type(actual) is not type(expected) or actual != expected:
            excluded = True
            reasons.append(f"eligibility condition is not met: {key}")
    return (False if excluded else None if unknown else True), reasons


def procedure_constraints(
    step: KnownProcedureStep,
    snapshot: CaseSnapshot,
    fact_overlays: Sequence[FactChangeCandidate] = (),
    progress_changes: Sequence[ProcedureProgressChangeCandidate] = (),
    *,
    known_steps: Sequence[KnownProcedureStep] = (),
    procedure_bindings: ProcedureBindings | None = None,
) -> list[str]:
    """Return unmet master rules; an empty result does not establish source quality."""

    registry = {item.procedure_step.procedure_step_id: item for item in known_steps}
    progress = {
        item.procedure_step.procedure_step_id: item.status
        for item in effective_procedure_progress(
            snapshot, MutationSet(fact_changes=list(fact_overlays),
                                  procedure_progress_changes=list(progress_changes), support_match_updates=[]),
            known_steps=known_steps, procedure_bindings=procedure_bindings,
        )
        if item.procedure_step.procedure_step_id not in registry
        or item.procedure_step == registry[item.procedure_step.procedure_step_id].procedure_step
    }
    _, reasons = _applicability(step, snapshot, fact_overlays)
    for dependency in step.dependencies:
        if dependency.dependency_type != "SEQUENTIAL":
            reasons.append("unsupported dependency_type")
            continue
        prerequisite = registry.get(dependency.prerequisite_procedure_step_id)
        if (
            prerequisite is not None
            and procedure_applicability(
                prerequisite,
                snapshot,
                fact_overlays,
            )
            is False
        ):
            continue
        if (
            prerequisite is not None
            and prerequisite.procedure_step.step_code == "CONFIRM_RESTORATION_SCOPE"
        ):
            confirmed = {
                fact.field_path
                for fact in snapshot.facts
                if fact.status == FactStatus.CONFIRMED
            }
            for change in fact_overlays:
                if change.proposed_status == FactStatus.CONFIRMED:
                    confirmed.add(change.field_path)
                else:
                    confirmed.discard(change.field_path)
            if {
                CaseFieldKey.RESTORATION_SCOPE,
                CaseFieldKey.DEMOLITION_REQUIRED,
            }.issubset(confirmed):
                continue
            reasons.append("restoration scope and demolition need confirmed facts")
        elif (
            progress.get(dependency.prerequisite_procedure_step_id)
            != ProcedureProgressStatus.COMPLETED
        ):
            reasons.append(
                f"prerequisite procedure {dependency.prerequisite_procedure_step_id} is not completed"
            )
    return reasons


def _boolean(value: str) -> bool:
    if value not in {"true", "false"}:
        raise ValueError("boolean condition must be true or false")
    return value == "true"


def procedure_plan_constraints(
    steps: Sequence[KnownProcedureStep],
    snapshot: CaseSnapshot,
    mutations: MutationSet,
    decision: DecisionDraft,
    *,
    procedure_bindings: ProcedureBindings | None = None,
) -> list[tuple[str, str]]:
    """Bind procedure targets to the supplied registry and their final Case state."""

    targets = [
        (change.procedure_step, f"/mutations/procedure_progress_changes/{index}", False)
        for index, change in enumerate(mutations.procedure_progress_changes)
    ]
    action = decision.next_action
    if action is not None and action.target.target_kind == "PROCEDURE":
        targets.insert(
            0, (action.target.procedure_step, "/decision/next_action/target", True)
        )
    registry = {step.procedure_step.procedure_step_id: step for step in steps}
    progress = {
        item.procedure_step.procedure_step_id: item.status
        for item in effective_procedure_progress(
            snapshot, mutations, known_steps=steps, procedure_bindings=procedure_bindings,
        )
        if item.procedure_step.procedure_step_id in registry
        and item.procedure_step == registry[item.procedure_step.procedure_step_id].procedure_step
    }
    confirmed = {item.field_path for item in snapshot.facts if item.status == FactStatus.CONFIRMED}
    for item in mutations.fact_changes:
        if item.proposed_status == FactStatus.CONFIRMED:
            confirmed.add(item.field_path)
        else:
            confirmed.discard(item.field_path)
    unknown_insurance_steps = {
        step_id for step_id, step in registry.items()
        if not set(_INSURANCE_FIELDS).issubset(confirmed)
        and any(condition.condition_key == "has_workplace_insurance"
                for condition in step.eligibility_conditions)
    }
    insurance_history_error = (
        "aggregate insurance submission/completion requires all four enrollment histories"
    )
    violations = []
    for index, change in enumerate(mutations.procedure_progress_changes):
        if change.procedure_step.procedure_step_id in unknown_insurance_steps and (
            change.proposed_submitted or change.proposed_status == ProcedureProgressStatus.COMPLETED
        ):
            violations.append((
                f"/mutations/procedure_progress_changes/{index}",
                insurance_history_error,
            ))
    for reference, path, is_action in targets:
        step = registry.get(reference.procedure_step_id)
        if step is None or step.procedure_step != reference:
            violations.append(
                (path, "procedure reference does not match the supplied registry")
            )
            continue
        reasons = procedure_constraints(
            step,
            snapshot,
            mutations.fact_changes,
            mutations.procedure_progress_changes,
            known_steps=steps,
            procedure_bindings=procedure_bindings,
        )
        if (
            is_action
            and action.action_code in {
                "REPORT_WORKPLACE_INSURANCE_CLOSURE", "REPORT_EMPLOYEE_INSURANCE_LOSS",
            }
            and reference.procedure_step_id in unknown_insurance_steps
        ):
            reasons.append(insurance_history_error)
        if (
            is_action
            and progress.get(reference.procedure_step_id)
            == ProcedureProgressStatus.COMPLETED
        ):
            reasons.append("next action targets an already completed procedure")
        if reasons:
            violations.append((path, "; ".join(reasons)))
    return violations
