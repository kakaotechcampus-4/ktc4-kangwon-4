"""Deterministic eligibility for ending the approved cafe tracking scope."""

from collections.abc import Mapping, Sequence

from app.agent.action_catalog import (
    PROCEDURE_LABELS,
    ProcedureBindings,
    effective_procedure_progress,
)
from app.agent.blocker_candidates import missing_info_fields
from app.agent.claim_safety import expand_evidence
from app.agent.procedure_tool.rules import (
    business_type_code,
    employment_history,
    procedure_applicability,
)
from app.agent.schemas import (
    AgentFieldKey as CaseFieldKey,
)
from app.agent.schemas import (
    CaseSnapshot,
    FactStatus,
    FreshnessStatus,
    InfoAnalysisResult,
    KnownProcedureStep,
    MutationSet,
    ProcedureProgressStatus,
    SupervisorAgentInput,
)

CAFE_TRACKED_CODES = frozenset(PROCEDURE_LABELS)


def completed_scope_refs(
    snapshot: CaseSnapshot,
    known_steps: Sequence[KnownProcedureStep],
    mutations: MutationSet,
    bindings: ProcedureBindings,
) -> set[str] | None:
    """Collect state evidence only when the full applicable cafe scope is done.

    This does not approve a public completion: official tax guidance and evidence
    integrity are checked separately by ``completion_fields`` and Review.
    """
    if not CAFE_TRACKED_CODES.issubset(bindings):
        return None
    facts = {item.field_path: (item.status, item.value) for item in snapshot.facts}
    facts.update({item.field_path: (item.proposed_status, item.proposed_value)
                  for item in mutations.fact_changes})
    values = {key: value for key, (status, value) in facts.items() if status == FactStatus.CONFIRMED}
    if business_type_code(values.get(CaseFieldKey.BUSINESS_TYPE)) != "CAFE":
        return None
    if employment_history(values) is None:
        return None
    if any(key not in values for key in (
        CaseFieldKey.PENSION_ENROLLED,
        CaseFieldKey.HEALTH_INSURANCE_ENROLLED, CaseFieldKey.EMPLOYMENT_INSURANCE_ENROLLED,
        CaseFieldKey.INDUSTRIAL_ACCIDENT_INSURANCE_ENROLLED,
    )):
        return None
    try:
        effective_progress = effective_procedure_progress(
            snapshot, mutations, known_steps=known_steps, procedure_bindings=bindings,
        )
    except ValueError:
        return None
    progress = {(item.procedure_step.procedure_step_id, item.procedure_step.step_code): item.status
                for item in effective_progress}
    by_id = {step.procedure_step.procedure_step_id: step for step in known_steps}
    refs = set()
    for logical in CAFE_TRACKED_CODES:
        step = by_id.get(bindings[logical].procedure_step_id)
        if (
            step is None
            or step.procedure_step != bindings[logical]
            or step.deprecated_at is not None
            or step.registry_version == "temp"
        ):
            return None
        applicable = procedure_applicability(step, snapshot, mutations.fact_changes)
        if applicable is None:
            return None
        if not applicable:
            continue
        if logical == "CONFIRM_RESTORATION_SCOPE":
            if not all(key in values for key in (
                CaseFieldKey.RESTORATION_SCOPE, CaseFieldKey.DEMOLITION_REQUIRED
            )):
                return None
            for fact in snapshot.facts:
                if fact.field_path in {CaseFieldKey.RESTORATION_SCOPE, CaseFieldKey.DEMOLITION_REQUIRED}:
                    refs.update(fact.evidence_refs)
            for change in mutations.fact_changes:
                if change.field_path in {CaseFieldKey.RESTORATION_SCOPE, CaseFieldKey.DEMOLITION_REQUIRED}:
                    refs.update(change.source_evidence_refs)
            continue
        if progress.get((step.procedure_step.procedure_step_id, step.procedure_step.step_code)) != ProcedureProgressStatus.COMPLETED:
            return None
        for item in effective_progress:
            if item.procedure_step == step.procedure_step:
                refs.update(item.evidence_refs)
        for change in mutations.procedure_progress_changes:
            if change.procedure_step == step.procedure_step:
                refs.update(change.execution_evidence_refs)
    return refs


def completion_fields(
    request: SupervisorAgentInput,
    mutations: MutationSet,
    evidence_registry: Mapping,
    bindings: ProcedureBindings,
) -> dict | None:
    """Return a completion candidate only with full state and official guidance.

    A partial registry, an unknown eligibility fact, or a missing official tax
    follow-up can never count as completion. Proposed changes remain uncommitted.
    """
    refs = completed_scope_refs(
        request.case_snapshot, request.known_procedure_steps, mutations, bindings
    )
    if refs is None or missing_info_fields(
        request.case_snapshot, request.source_results, mutations, bindings,
        selected_candidate_id="missing:had_employees",
        known_procedure_steps=request.known_procedure_steps,
    ) is not None:
        return None
    guidance = []
    tax_ref = bindings["FILE_TAX_BUSINESS_CLOSURE"]
    for source in request.source_results:
        if not isinstance(source.output, InfoAnalysisResult):
            continue
        for finding in source.output.procedure_findings:
            if finding.procedure_step == tax_ref:
                guidance.extend(finding.followup_guidance)
    if not guidance:
        return None
    for item in guidance:
        sources = [evidence_registry.get(ref) for ref in item.evidence_refs]
        if not sources or any(source is None or source.source_type not in {
            "OFFICIAL_DOCUMENT", "OFFICIAL_API"
        } or source.freshness_status != FreshnessStatus.CURRENT for source in sources):
            return None
        expanded = expand_evidence(sources, evidence_registry)
        if any(source.freshness_status != FreshnessStatus.CURRENT or any(
            parent not in evidence_registry for parent in source.parent_evidence_refs
        ) for source in expanded):
            return None
        refs.update(item.evidence_refs)
    if not refs or not refs.issubset(evidence_registry):
        return None
    return {
        "decision_type": "COMPLETED",
        "selection_summary": "확인된 적용 대상 폐업 절차를 모두 마쳤습니다. 세금 후속 일정과 문의처를 확인해 주세요.",
        "requires_human": True,
        "evidence_refs": sorted(refs),
        "blocker": None, "blockers": [], "next_action": None,
        "questions_for_user": [],
        "followup_guidance": [item.model_dump(mode="python") for item in guidance],
    }
