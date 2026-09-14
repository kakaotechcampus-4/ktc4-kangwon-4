"""Deterministic lookup and evaluation over an injected procedure master."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from app.agent.schemas import (
    CaseFact,
    EvidenceRecord,
    ProcedureConditionResult,
    ProcedureLookupInput,
    ProcedureLookupResult,
    ProcedurePrerequisiteResult,
    ProcedureStepEvaluation,
    ProcedureUnavailableReason,
)

from .models import (
    MasterScalar,
    ProcedureConditionDefinition,
    ProcedureMaster,
    ProcedureStepDefinition,
)


class ProcedureLookupError(RuntimeError):
    """Base class for deterministic procedure lookup failures."""


class ProcedureMasterUnavailableError(ProcedureLookupError):
    """Raised when no reviewed procedure master was injected."""


class ProcedureLookupInputError(ProcedureLookupError):
    """Raised when cross-object references in otherwise valid input conflict."""


@dataclass(frozen=True, slots=True)
class _ResolvedFact:
    status: str
    value: Any
    evidence_refs: tuple[str, ...]


def _text(value: Any) -> str:
    """Return a Literal/Enum value without relying on permissive coercion."""

    enum_value = getattr(value, "value", value)
    return str(enum_value)


def _strictly_equal(left: MasterScalar, right: MasterScalar) -> bool:
    """Compare values without Python's ``True == 1`` coercion."""

    return type(left) is type(right) and left == right


def _strictly_equal_nullable(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    return _strictly_equal(left, right)


def _evaluate_condition(
    condition: ProcedureConditionDefinition,
    actual_value: MasterScalar | None,
) -> bool | None:
    """Return True/False, or None when a comparison cannot be verified."""

    if actual_value is None:
        return None

    expected_values = condition.expected_values
    if condition.operator == "EQ":
        return _strictly_equal(actual_value, expected_values[0])
    if condition.operator == "IN":
        return any(
            _strictly_equal(actual_value, expected) for expected in expected_values
        )

    expected = expected_values[0]
    if type(actual_value) is not type(expected):
        return None
    if isinstance(actual_value, bool) or not isinstance(actual_value, (int, date)):
        return None

    if condition.operator == "GT":
        return actual_value > expected
    if condition.operator == "GTE":
        return actual_value >= expected
    if condition.operator == "LT":
        return actual_value < expected
    if condition.operator == "LTE":
        return actual_value <= expected
    return None


class ProcedureLookupTool:
    """Evaluate procedure facts without selecting a blocker or next action.

    The tool is intentionally synchronous and side-effect free.  Its master is
    immutable, and Case data is supplied entirely through ``ProcedureLookupInput``.
    """

    def __init__(self, master: ProcedureMaster | None) -> None:
        self._master = master.model_copy(deep=True) if master is not None else None

    def lookup(self, request: ProcedureLookupInput) -> ProcedureLookupResult:
        master = self._master
        if master is None:
            raise ProcedureMasterUnavailableError(
                "a reviewed procedure master must be injected before lookup"
            )

        selected_steps, has_missing_codes = self._select_steps(request)
        facts, used_candidate_ids = self._resolve_facts(request, selected_steps)
        progress = self._resolve_progress(request)
        evidence_by_id = {
            evidence.evidence_id: evidence for evidence in master.evidence_records
        }

        evaluations: list[ProcedureStepEvaluation] = []
        selected_evidence_refs: set[str] = set()
        dataset_is_current = master.freshness_status == "CURRENT"
        all_selected_sources_current = dataset_is_current

        for step in selected_steps:
            step_refs = self._step_evidence_refs(step)
            step_lineage_refs = self._evidence_lineage_refs(
                step_refs,
                evidence_by_id,
            )
            selected_evidence_refs.update(step_lineage_refs)
            step_source_is_current = dataset_is_current and all(
                _text(evidence_by_id[evidence_ref].freshness_status) == "CURRENT"
                for evidence_ref in step_lineage_refs
            )
            if not step_source_is_current:
                all_selected_sources_current = False

            evaluations.append(
                self._evaluate_step(
                    step=step,
                    as_of=request.as_of,
                    facts=facts,
                    progress=progress,
                    source_is_current=step_source_is_current,
                )
            )

        output_evidence = []
        emitted_evidence_ids: set[str] = set()
        for evidence in master.evidence_records:
            if (
                evidence.evidence_id in selected_evidence_refs
                and evidence.evidence_id not in emitted_evidence_ids
            ):
                output_evidence.append(evidence)
                emitted_evidence_ids.add(evidence.evidence_id)
        is_complete = (
            bool(selected_steps)
            and not has_missing_codes
            and all_selected_sources_current
        )

        return ProcedureLookupResult(
            completion_status="COMPLETE" if is_complete else "PARTIAL",
            procedure_data_version=master.data_version,
            step_evaluations=evaluations,
            evidence_records=output_evidence,
            based_on_snapshot_id=request.planning_context.case_snapshot.snapshot_id,
            based_on_candidate_ids=used_candidate_ids,
        )

    def _select_steps(
        self,
        request: ProcedureLookupInput,
    ) -> tuple[list[ProcedureStepDefinition], bool]:
        assert self._master is not None
        if request.lookup_scope == "ALL_STEPS":
            return list(self._master.steps), False

        requested_codes = list(dict.fromkeys(request.step_codes))
        steps_by_code = {
            step.procedure_step.step_code: step for step in self._master.steps
        }
        selected = [
            steps_by_code[code] for code in requested_codes if code in steps_by_code
        ]
        return selected, len(selected) != len(requested_codes)

    def _resolve_facts(
        self,
        request: ProcedureLookupInput,
        selected_steps: list[ProcedureStepDefinition],
    ) -> tuple[dict[str, _ResolvedFact], list[UUID]]:
        snapshot = request.planning_context.case_snapshot
        facts: dict[str, _ResolvedFact] = {}
        for fact in snapshot.facts:
            field_path = _text(fact.field_path)
            if field_path in facts:
                raise ProcedureLookupInputError(
                    f"snapshot has duplicate fact field_path: {field_path}"
                )
            facts[field_path] = self._resolved_snapshot_fact(fact)

        relevant_fields = {
            _text(condition.field_path)
            for step in selected_steps
            for condition in step.conditions
        }
        used_candidate_ids: list[UUID] = []
        applied_fields: set[str] = set()
        for candidate in request.planning_context.fact_overlays:
            field_path = _text(candidate.field_path)
            if field_path not in relevant_fields:
                continue
            if field_path in applied_fields:
                raise ProcedureLookupInputError(
                    f"fact overlay has duplicate field_path: {field_path}"
                )
            applied_fields.add(field_path)
            snapshot_fact = facts.get(
                field_path,
                _ResolvedFact(status="UNKNOWN", value=None, evidence_refs=()),
            )
            if _text(
                candidate.before_status
            ) != snapshot_fact.status or not _strictly_equal_nullable(
                candidate.before_value, snapshot_fact.value
            ):
                raise ProcedureLookupInputError(
                    f"fact overlay before state does not match snapshot: {field_path}"
                )
            facts[field_path] = _ResolvedFact(
                status=_text(candidate.proposed_status),
                value=candidate.proposed_value,
                evidence_refs=tuple(candidate.source_evidence_refs),
            )
            used_candidate_ids.append(candidate.candidate_id)
        return facts, used_candidate_ids

    @staticmethod
    def _resolved_snapshot_fact(fact: CaseFact) -> _ResolvedFact:
        return _ResolvedFact(
            status=_text(fact.status),
            value=fact.value,
            evidence_refs=tuple(fact.evidence_refs),
        )

    def _resolve_progress(
        self, request: ProcedureLookupInput
    ) -> dict[tuple[int, str], str]:
        assert self._master is not None
        progress_by_ref: dict[tuple[int, str], str] = {}
        ids_to_codes: dict[int, str] = {}
        codes_to_ids: dict[str, int] = {}
        master_ids_to_codes = {
            int(step.procedure_step.procedure_step_id): _text(
                step.procedure_step.step_code
            )
            for step in self._master.steps
        }
        master_codes_to_ids = {
            _text(step.procedure_step.step_code): int(
                step.procedure_step.procedure_step_id
            )
            for step in self._master.steps
        }
        for progress in request.planning_context.case_snapshot.procedure_progress:
            step_ref = progress.procedure_step
            step_id = int(step_ref.procedure_step_id)
            step_code = _text(step_ref.step_code)

            previous_code = ids_to_codes.setdefault(step_id, step_code)
            previous_id = codes_to_ids.setdefault(step_code, step_id)
            if previous_code != step_code or previous_id != step_id:
                raise ProcedureLookupInputError(
                    "procedure progress contains inconsistent stable references"
                )
            if (
                step_id in master_ids_to_codes
                and master_ids_to_codes[step_id] != step_code
            ) or (
                step_code in master_codes_to_ids
                and master_codes_to_ids[step_code] != step_id
            ):
                raise ProcedureLookupInputError(
                    "procedure progress reference conflicts with the procedure master"
                )

            key = (step_id, step_code)
            if key in progress_by_ref:
                raise ProcedureLookupInputError(
                    f"duplicate procedure progress for {step_code}"
                )
            progress_by_ref[key] = _text(progress.status)
        return progress_by_ref

    def _evaluate_step(
        self,
        *,
        step: ProcedureStepDefinition,
        as_of: date,
        facts: dict[str, _ResolvedFact],
        progress: dict[tuple[int, str], str],
        source_is_current: bool,
    ) -> ProcedureStepEvaluation:
        step_key = (
            int(step.procedure_step.procedure_step_id),
            _text(step.procedure_step.step_code),
        )
        current_status = progress.get(step_key)
        is_active = self._is_active_on(step, as_of)

        condition_results = [
            self._condition_result(
                condition,
                facts.get(_text(condition.field_path)),
                source_is_current=source_is_current,
            )
            for condition in step.conditions
        ]
        prerequisite_results = [
            self._prerequisite_result(prerequisite, progress)
            for prerequisite in step.prerequisites
        ]
        unavailable_reasons: list[ProcedureUnavailableReason] = []

        if not is_active:
            applicability = "NOT_APPLICABLE"
            readiness = "BLOCKED"
            unavailable_reasons.append(
                ProcedureUnavailableReason(
                    code="STEP_INACTIVE",
                    message="기준일에 사용할 수 없는 절차입니다.",
                    evidence_refs=list(step.evidence_refs),
                )
            )
        elif not source_is_current:
            applicability = "UNDETERMINED"
            readiness = "UNDETERMINED"
            unavailable_reasons.append(
                ProcedureUnavailableReason(
                    code="CONDITION_UNKNOWN",
                    message="절차 자료가 최신인지 공식 출처에서 확인해야 합니다.",
                    evidence_refs=list(self._step_evidence_refs(step)),
                )
            )
        elif any(result.status == "NOT_MET" for result in condition_results):
            applicability = "NOT_APPLICABLE"
            readiness = "BLOCKED"
            not_met_refs = self._condition_refs_with_status(
                condition_results, "NOT_MET"
            )
            unavailable_reasons.append(
                ProcedureUnavailableReason(
                    code="CONDITION_NOT_MET",
                    message="현재 확인된 정보가 이 절차의 조건과 맞지 않습니다.",
                    evidence_refs=not_met_refs,
                )
            )
        elif any(result.status == "UNKNOWN" for result in condition_results):
            applicability = "UNDETERMINED"
            readiness = "UNDETERMINED"
            unknown_refs = self._condition_refs_with_status(
                condition_results, "UNKNOWN"
            )
            unavailable_reasons.append(
                ProcedureUnavailableReason(
                    code="CONDITION_UNKNOWN",
                    message="절차 적용 여부를 판단할 정보가 더 필요합니다.",
                    evidence_refs=unknown_refs,
                )
            )
        else:
            applicability = "APPLICABLE"
            required = [
                result
                for result in prerequisite_results
                if result.dependency_type == "REQUIRED"
            ]
            if any(result.satisfaction == "NOT_SATISFIED" for result in required):
                readiness = "BLOCKED"
            elif any(result.satisfaction == "UNKNOWN" for result in required):
                readiness = "UNDETERMINED"
            else:
                readiness = "READY"

        for prerequisite, result in zip(
            step.prerequisites, prerequisite_results, strict=True
        ):
            if result.satisfaction == "SATISFIED":
                continue
            dependency_label = (
                "필수" if result.dependency_type == "REQUIRED" else "권고"
            )
            unavailable_reasons.append(
                ProcedureUnavailableReason(
                    code="PREREQUISITE_INCOMPLETE",
                    message=f"{dependency_label} 선행 절차의 완료 여부를 확인해야 합니다.",
                    evidence_refs=list(prerequisite.evidence_refs),
                )
            )

        return ProcedureStepEvaluation(
            procedure_step=step.procedure_step,
            step_name=step.step_name,
            is_active=is_active,
            applicability=applicability,
            readiness=readiness,
            current_status=current_status,
            conditions=condition_results,
            prerequisites=prerequisite_results,
            unavailable_reasons=unavailable_reasons,
            requires_professional=step.requires_professional,
            professional_type=step.professional_type,
            decision_authority=step.decision_authority,
            evidence_refs=list(self._step_evidence_refs(step)),
        )

    @staticmethod
    def _is_active_on(step: ProcedureStepDefinition, as_of: date) -> bool:
        if not step.is_active:
            return False
        if step.effective_from is not None and as_of < step.effective_from:
            return False
        return step.effective_until is None or as_of <= step.effective_until

    @staticmethod
    def _condition_result(
        condition: ProcedureConditionDefinition,
        fact: _ResolvedFact | None,
        *,
        source_is_current: bool,
    ) -> ProcedureConditionResult:
        actual_value: MasterScalar | None = None
        if source_is_current and fact is not None and fact.status == "CONFIRMED":
            actual_value = fact.value

        evaluated = (
            _evaluate_condition(condition, actual_value) if source_is_current else None
        )
        status = "UNKNOWN" if evaluated is None else "MET" if evaluated else "NOT_MET"
        evidence_refs = list(condition.evidence_refs)
        if fact is not None:
            evidence_refs.extend(
                evidence_ref
                for evidence_ref in fact.evidence_refs
                if evidence_ref not in evidence_refs
            )
        return ProcedureConditionResult(
            condition_id=condition.condition_id,
            field_path=condition.field_path,
            operator=condition.operator,
            expected_values=list(condition.expected_values),
            actual_value=actual_value,
            status=status,
            evidence_refs=evidence_refs,
        )

    @staticmethod
    def _prerequisite_result(
        prerequisite: Any,
        progress: dict[tuple[int, str], str],
    ) -> ProcedurePrerequisiteResult:
        step_ref = prerequisite.procedure_step
        key = (int(step_ref.procedure_step_id), _text(step_ref.step_code))
        current_status = progress.get(key)
        if current_status == "COMPLETED":
            satisfaction = "SATISFIED"
            reason = "선행 절차의 완료 기록이 확인되었습니다."
        elif current_status in {"NOT_STARTED", "IN_PROGRESS"}:
            satisfaction = "NOT_SATISFIED"
            reason = "선행 절차가 아직 완료되지 않았습니다."
        else:
            satisfaction = "UNKNOWN"
            reason = "선행 절차의 진행 기록을 확인할 수 없습니다."
        return ProcedurePrerequisiteResult(
            procedure_step=step_ref,
            dependency_type=prerequisite.dependency_type,
            current_status=current_status,
            satisfaction=satisfaction,
            reason_summary=reason,
        )

    @staticmethod
    def _step_evidence_refs(step: ProcedureStepDefinition) -> tuple[str, ...]:
        refs: list[str] = list(step.evidence_refs)
        for condition in step.conditions:
            refs.extend(ref for ref in condition.evidence_refs if ref not in refs)
        for prerequisite in step.prerequisites:
            refs.extend(ref for ref in prerequisite.evidence_refs if ref not in refs)
        return tuple(refs)

    @staticmethod
    def _evidence_lineage_refs(
        evidence_refs: tuple[str, ...],
        evidence_by_id: dict[str, EvidenceRecord],
    ) -> tuple[str, ...]:
        """Return direct evidence and every transitive parent exactly once."""

        lineage: list[str] = []
        seen: set[str] = set()
        pending = list(evidence_refs)
        while pending:
            evidence_ref = pending.pop()
            if evidence_ref in seen:
                continue
            seen.add(evidence_ref)
            lineage.append(evidence_ref)
            pending.extend(evidence_by_id[evidence_ref].parent_evidence_refs)
        return tuple(lineage)

    @staticmethod
    def _condition_refs_with_status(
        condition_results: list[ProcedureConditionResult],
        status: str,
    ) -> list[str]:
        refs: list[str] = []
        for result in condition_results:
            if result.status != status:
                continue
            refs.extend(ref for ref in result.evidence_refs if ref not in refs)
        return refs


__all__ = [
    "ProcedureLookupError",
    "ProcedureLookupInputError",
    "ProcedureLookupTool",
    "ProcedureMasterUnavailableError",
]
