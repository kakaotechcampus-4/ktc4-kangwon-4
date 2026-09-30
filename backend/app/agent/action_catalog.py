"""Fixed action kinds; the separate target identifies the procedure or program."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.agent.claim_safety import REQUIRED_CLAIM_SOURCES, expand_evidence
from app.agent.schemas import (
    EvidenceRecord,
    FreshnessStatus,
    InfoAnalysisResult,
    KnownProcedureStep,
    ProcedureRelevance,
    ProcedureStepRef,
    ReviewSourceResult,
    SupportAnalysisResult,
    SupportMatchStatus,
)


@dataclass(frozen=True)
class ActionDefinition:
    description: str
    procedure_logical_code: str | None
    confirmation_only: bool


ProcedureBindings = Mapping[str, ProcedureStepRef]

_PROCEDURE_LOGICAL_CODES = frozenset(
    {
        "CONFIRM_RESTORATION_SCOPE",
        "FILE_TAX_BUSINESS_CLOSURE",
        "FILE_FOOD_SERVICE_CLOSURE",
        "REPORT_WORKPLACE_INSURANCE_CLOSURE",
    }
)


ACTION_DEFINITIONS: dict[str, ActionDefinition] = {
    "CONFIRM_RESTORATION_SCOPE": ActionDefinition(
        "임대인에게 원상복구 범위와 철거 필요 여부를 확인한다.",
        "CONFIRM_RESTORATION_SCOPE",
        True,
    ),
    "CONFIRM_TAX_CLOSURE_REQUIREMENTS": ActionDefinition(
        "세무서 등 공식 창구에 사업자 폐업신고 방법과 필요한 서류를 확인한다. 신고 제출과 구분한다.",
        "FILE_TAX_BUSINESS_CLOSURE",
        True,
    ),
    "FILE_TAX_BUSINESS_CLOSURE": ActionDefinition(
        "공식 근거와 확인한 요건에 따라 사업자 폐업신고를 제출한다. 방법을 묻는 행동과 구분한다.",
        "FILE_TAX_BUSINESS_CLOSURE",
        False,
    ),
    "CONFIRM_FOOD_SERVICE_CLOSURE_REQUIREMENTS": ActionDefinition(
        "관할 기관에 식품영업 폐업신고 방법과 필요한 서류를 확인한다. 신고 제출과 구분한다.",
        "FILE_FOOD_SERVICE_CLOSURE",
        True,
    ),
    "FILE_FOOD_SERVICE_CLOSURE": ActionDefinition(
        "공식 근거와 확인한 요건에 따라 식품영업 폐업신고를 제출한다. 방법을 묻는 행동과 구분한다.",
        "FILE_FOOD_SERVICE_CLOSURE",
        False,
    ),
    "CONFIRM_WORKPLACE_INSURANCE_CLOSURE_REQUIREMENTS": ActionDefinition(
        "담당 보험기관에 사업장 탈퇴 신고 방법과 필요한 서류를 확인한다. 신고 제출과 구분한다.",
        "REPORT_WORKPLACE_INSURANCE_CLOSURE",
        True,
    ),
    "REPORT_WORKPLACE_INSURANCE_CLOSURE": ActionDefinition(
        "공식 근거와 확인한 요건에 따라 사업장 탈퇴 신고를 제출한다. 방법을 묻는 행동과 구분한다.",
        "REPORT_WORKPLACE_INSURANCE_CLOSURE",
        False,
    ),
    "CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS": ActionDefinition(
        "해당 지원사업의 공식 창구에 현재 조건과 신청 전 필요한 증빙을 확인한다. 신청이나 자격 확정이 아니다.",
        None,
        True,
    ),
}


def _step_key(step: ProcedureStepRef) -> tuple[int, str]:
    return step.procedure_step_id, step.step_code


def resolve_procedure_bindings(
    known_steps: Sequence[KnownProcedureStep],
    bindings: Mapping[str, ProcedureStepRef] | None = None,
) -> ProcedureBindings:
    """Validate and freeze caller-supplied logical-to-physical step bindings.

    ``None`` keeps legacy callers working only when the registry already uses an
    exact logical code. An explicit empty mapping stays empty. Names and aliases
    are deliberately ignored because they cannot disambiguate similar closure
    procedures.
    """

    known_by_ref = {
        _step_key(item.procedure_step): item.procedure_step for item in known_steps
    }
    supplied = (
        {
            item.procedure_step.step_code: item.procedure_step
            for item in known_steps
            if item.procedure_step.step_code in _PROCEDURE_LOGICAL_CODES
        }
        if bindings is None
        else dict(bindings)
    )
    unknown = set(supplied) - _PROCEDURE_LOGICAL_CODES
    if unknown:
        raise ValueError(
            "unknown logical procedure binding codes: " + ", ".join(sorted(unknown))
        )

    resolved: dict[str, ProcedureStepRef] = {}
    used_refs: set[tuple[int, str]] = set()
    for logical_code, supplied_ref in supplied.items():
        if not isinstance(supplied_ref, ProcedureStepRef):
            raise TypeError("procedure binding values must be ProcedureStepRef")
        ref_key = _step_key(supplied_ref)
        if ref_key not in known_by_ref:
            raise ValueError(
                f"procedure binding {logical_code} references an unknown id+code"
            )
        if ref_key in used_refs:
            raise ValueError("one procedure step cannot have multiple logical bindings")
        used_refs.add(ref_key)
        resolved[logical_code] = ProcedureStepRef.model_validate(
            known_by_ref[ref_key].model_dump(mode="python")
        )
    return MappingProxyType(resolved)


def _evidence(
    refs: Sequence[str],
    evidence_by_id: Mapping[str, EvidenceRecord],
) -> tuple[EvidenceRecord, ...]:
    if not refs or any(ref not in evidence_by_id for ref in refs):
        return ()
    expanded = expand_evidence([evidence_by_id[ref] for ref in refs], evidence_by_id)
    if any(
        parent not in evidence_by_id
        for item in expanded
        for parent in item.parent_evidence_refs
    ):
        return ()
    return (
        expanded
        if any(item.source_type in REQUIRED_CLAIM_SOURCES for item in expanded)
        else ()
    )


def _source_procedure_bindings(
    sources: Sequence[ReviewSourceResult],
    bindings: ProcedureBindings | None,
) -> ProcedureBindings:
    if bindings is not None:
        return bindings
    derived: dict[str, ProcedureStepRef] = {}
    for source in sources:
        if not isinstance(source.output, InfoAnalysisResult):
            continue
        for finding in source.output.procedure_findings:
            ref = finding.procedure_step
            if ref.step_code not in _PROCEDURE_LOGICAL_CODES:
                continue
            previous = derived.get(ref.step_code)
            if previous is not None and _step_key(previous) != _step_key(ref):
                raise ValueError("canonical procedure code resolves to multiple steps")
            derived[ref.step_code] = ref
    return MappingProxyType(derived)


def build_action_candidates(
    sources: Sequence[ReviewSourceResult],
    evidence_by_id: Mapping[str, EvidenceRecord],
    procedure_bindings: ProcedureBindings | None = None,
) -> list[dict[str, Any]]:
    """List grounded action kinds; existing plan guards check Case constraints."""

    resolved_bindings = _source_procedure_bindings(sources, procedure_bindings)
    candidates: list[dict[str, Any]] = []

    def append(code: str, target: dict[str, Any]) -> None:
        definition = ACTION_DEFINITIONS[code]
        candidates.append(
            {
                "action_code": code,
                "target": target,
                "description": definition.description,
                "confirmation_only": definition.confirmation_only,
            }
        )

    for source in sources:
        output = source.output
        if isinstance(output, InfoAnalysisResult):
            for finding in output.procedure_findings:
                evidence = _evidence(finding.evidence_refs, evidence_by_id)
                if not evidence:
                    continue
                executable = (
                    finding.relevance == ProcedureRelevance.RELEVANT
                    and bool(finding.required_actions)
                    and all(
                        _evidence(action.evidence_refs, evidence_by_id)
                        for action in finding.required_actions
                    )
                    and all(
                        item.freshness_status == FreshnessStatus.CURRENT
                        for item in evidence
                    )
                )
                for code, definition in ACTION_DEFINITIONS.items():
                    bound_step = (
                        resolved_bindings.get(definition.procedure_logical_code)
                        if definition.procedure_logical_code is not None
                        else None
                    )
                    if (
                        bound_step is not None
                        and _step_key(bound_step) == _step_key(finding.procedure_step)
                        and (definition.confirmation_only or executable)
                    ):
                        append(
                            code,
                            {
                                "target_kind": "PROCEDURE",
                                "procedure_step": finding.procedure_step.model_dump(
                                    mode="json"
                                ),
                            },
                        )
        elif isinstance(output, SupportAnalysisResult):
            for check in output.support_checks:
                if check.match_status != SupportMatchStatus.NOT_RELEVANT and _evidence(
                    check.evidence_refs, evidence_by_id
                ):
                    append(
                        "CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS",
                        {
                            "target_kind": "SUPPORT_PROGRAM",
                            "support_program": check.support_program.model_dump(
                                mode="json"
                            ),
                        },
                    )
    return candidates
