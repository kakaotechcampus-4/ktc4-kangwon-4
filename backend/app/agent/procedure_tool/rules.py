"""Evaluate the MVP subset of stored procedure rules against proposed Case state."""

from collections.abc import Sequence
from datetime import date

from ..schemas import (
    CASE_FIELD_SPECS,
    CaseFieldKey,
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


def procedure_constraints(
    step: KnownProcedureStep,
    snapshot: CaseSnapshot,
    fact_overlays: Sequence[FactChangeCandidate] = (),
    progress_changes: Sequence[ProcedureProgressChangeCandidate] = (),
) -> list[str]:
    """Return unmet master rules; an empty result does not establish source quality."""

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
    progress = {
        item.procedure_step.procedure_step_id: item.status
        for item in snapshot.procedure_progress
    }
    progress.update(
        (change.procedure_step.procedure_step_id, change.proposed_status)
        for change in progress_changes
    )
    reasons = []
    if step.deprecated_at is not None:
        reasons.append("procedure is deprecated")
    if (
        step.applicable_business_type != "ALL"
        and values.get(CaseFieldKey.BUSINESS_TYPE) != step.applicable_business_type
    ):
        reasons.append("applicable_business_type is not confirmed for this Case")
    for dependency in step.dependencies:
        if dependency.dependency_type != "SEQUENTIAL":
            reasons.append("unsupported dependency_type")
        elif (
            progress.get(dependency.prerequisite_procedure_step_id)
            != ProcedureProgressStatus.COMPLETED
        ):
            reasons.append(
                f"prerequisite procedure {dependency.prerequisite_procedure_step_id} is not completed"
            )
    # ponytail: support equality and has_employee only; add operators for concrete master rules.
    for condition in step.eligibility_conditions:
        key, raw = condition.condition_key, condition.condition_value
        try:
            if key == "has_employee":
                expected = _boolean(raw)
                count = values.get(CaseFieldKey.EMPLOYEE_COUNT)
                actual = None if count is None else count > 0
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
                if type(actual) is date:
                    actual = actual.isoformat()
        except ValueError:
            reasons.append(f"unsupported or invalid eligibility condition: {key}")
            continue
        if actual is None:
            reasons.append(f"eligibility fact is not confirmed: {key}")
        elif type(actual) is not type(expected) or actual != expected:
            reasons.append(f"eligibility condition is not met: {key}")
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
        for item in snapshot.procedure_progress
    }
    progress.update(
        (item.procedure_step.procedure_step_id, item.proposed_status)
        for item in mutations.procedure_progress_changes
    )
    violations = []
    for reference, path, is_action in targets:
        step = registry.get(reference.procedure_step_id)
        if step is None or step.procedure_step != reference:
            violations.append(
                (path, "procedure reference does not match the supplied registry")
            )
            continue
        reasons = procedure_constraints(
            step, snapshot, mutations.fact_changes, mutations.procedure_progress_changes
        )
        if (
            is_action
            and progress.get(reference.procedure_step_id)
            == ProcedureProgressStatus.COMPLETED
        ):
            reasons.append("next action targets an already completed procedure")
        if reasons:
            violations.append((path, "; ".join(reasons)))
    return violations
