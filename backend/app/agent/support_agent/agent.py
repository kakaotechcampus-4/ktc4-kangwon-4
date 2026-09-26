"""Grounded support-program comparison over an injected reviewed catalog."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.agent.guardrails import GuardrailViolation, ensure_no_sensitive_text
from app.agent.prompts import support_messages
from app.agent.run_scope import RunDeadlineExceededError, current_deadline
from app.agent.schemas import (
    CASE_FIELD_SPECS,
    CaseFieldKey,
    CriterionStatus,
    EvidenceRecord,
    FactChangeCandidate,
    FactValueType,
    FreshnessStatus,
    RequiredDocument,
    SourcedText,
    SupportAgentInput,
    SupportAnalysisResult,
    SupportCheck,
    SupportCompletionStatus,
    SupportCriterionResult,
    SupportMatchStatus,
    SupportProgramRef,
    SupportSearchSummary,
    Uncertainty,
)

from .models import (
    CatalogSourcedText,
    ReviewedSupportCatalog,
    ReviewedSupportProgram,
    SupportAnalysisDraft,
    SupportCheckDraft,
    SupportCriterionDefinition,
    SupportProviderOutput,
)
from .wiki import SupportWikiStore

_OVERCONFIDENT_SUPPORT_LANGUAGE = re.compile(
    r"(?i)(?:\beligible\b|지원\s*(?:가능|대상|수령)\s*(?:확정|보장)|"
    r"수령\s*(?:확정|보장)|자격\s*(?:확정|보장))"
)
_MAX_LOCAL_GUARDRAIL_RETRIES = 2
_MAX_WIKI_LOOKUPS = 100
_CORRECTIVE_MESSAGE = {
    "role": "developer",
    "content": (
        "The previous structured response failed deterministic validation. "
        "Return one complete check for every supplied program. Copy criterion "
        "statuses exactly, use only each item's allowed evidence references, and "
        "do not add identifiers, facts, or fields."
    ),
}


class StructuredGenerator(Protocol):
    async def generate(
        self,
        response_model: type[BaseModel],
        messages: list[dict[str, str]],
        *,
        schema_name: str | None = None,
    ) -> BaseModel: ...


class SupportAgentError(RuntimeError):
    """Base error for failures at the support-analysis boundary."""


class SupportCatalogUnavailableError(SupportAgentError):
    """Raised when no reviewed catalog has been injected."""


class SupportAnalysisInputError(SupportAgentError):
    """Raised when stable references in a valid request are inconsistent."""


class SupportAnalysisGuardrailError(SupportAgentError):
    """Raised when a model draft invents or contradicts supplied data."""


@dataclass(frozen=True, slots=True)
class _ResolvedFact:
    status: str
    value: Any
    evidence_refs: tuple[str, ...]
    overlay_candidate_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class _CriterionPlan:
    definition: SupportCriterionDefinition
    fact: _ResolvedFact | None
    status: str
    allowed_evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ProgramPlan:
    program: ReviewedSupportProgram
    freshness: FreshnessStatus
    criteria: tuple[_CriterionPlan, ...]
    allowed_match_statuses: tuple[SupportMatchStatus, ...]
    allowed_evidence_refs: tuple[str, ...]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SupportAgent:
    """Compare Case facts only against an immutable reviewed catalog snapshot."""

    def __init__(
        self,
        llm: StructuredGenerator,
        catalog: ReviewedSupportCatalog | None,
        *,
        clock: Callable[[], datetime] = _utc_now,
        wiki_store: SupportWikiStore | None = None,
    ) -> None:
        self._llm = llm
        # A deep copy prevents a caller retaining the input model from mutating
        # nested shared EvidenceRecord instances after injection.
        self._catalog = catalog.model_copy(deep=True) if catalog is not None else None
        self._clock = clock
        self._wiki_store = wiki_store

    async def analyze(self, request: SupportAgentInput) -> SupportAnalysisResult:
        catalog = self._catalog
        if catalog is None:
            raise SupportCatalogUnavailableError(
                "a reviewed support catalog must be injected before analysis"
            )

        catalog, wiki_lookup, source_uncertainties = await self._resolve_wiki(
            request, catalog
        )
        # ponytail: the MVP catalog is small, so every reviewed program is
        # compared. Narrow by procedure step only if it grows.
        selected = list(catalog.programs)
        checked_at = self._checked_at()
        if not selected:
            return SupportAnalysisResult(
                completion_status="PARTIAL" if source_uncertainties else "NO_CANDIDATE",
                support_checks=[],
                no_candidate_reason_code=(
                    None if source_uncertainties else "NO_REVIEWED_CATALOG_MATCH"
                ),
                uncertainties=source_uncertainties,
                search_summary=SupportSearchSummary(
                    wiki_lookup=wiki_lookup,
                    rag_used=False,
                    official_source_checked=False,
                    checked_at=checked_at,
                ),
                evidence_records=[],
                based_on_snapshot_id=request.planning_context.case_snapshot.snapshot_id,
                based_on_candidate_ids=[],
            )

        facts = self._resolved_facts(request)
        evidence_by_id = {item.evidence_id: item for item in catalog.evidence_records}
        plans = self._build_program_plans(selected, facts, evidence_by_id)
        base_messages = support_messages(
            self._minimum_prompt_projection(request, catalog, plans)
        )

        for attempt in range(_MAX_LOCAL_GUARDRAIL_RETRIES + 1):
            messages = [dict(item) for item in base_messages]
            if attempt:
                messages.append(dict(_CORRECTIVE_MESSAGE))
            raw_draft = await self._llm.generate(
                SupportProviderOutput,
                messages,
                schema_name="support_analysis",
            )
            try:
                draft = self._validated_draft(raw_draft)
                return self._assemble_result(
                    request=request,
                    catalog=catalog,
                    plans=plans,
                    draft=draft,
                    checked_at=checked_at,
                    wiki_lookup=wiki_lookup,
                    source_uncertainties=source_uncertainties,
                )
            except SupportAnalysisGuardrailError:
                if attempt == _MAX_LOCAL_GUARDRAIL_RETRIES:
                    raise

        raise SupportAnalysisGuardrailError(
            "support model output failed deterministic validation"
        )

    async def _resolve_wiki(
        self,
        request: SupportAgentInput,
        catalog: ReviewedSupportCatalog,
    ) -> tuple[
        ReviewedSupportCatalog,
        Literal["HIT", "MISS", "NOT_REQUESTED"],
        list[Uncertainty],
    ]:
        """Resolve exact references before catalog selection can reject a new ID.

        Discovery still needs caller-supplied references; a Wiki directory is
        never searched by name or similarity. A configured miss never falls
        back to older catalog rules or pretends a RAG search occurred.
        """

        if self._wiki_store is None:
            return catalog, "NOT_REQUESTED", []
        refs = [item.support_program for item in catalog.programs]
        if not refs:
            return catalog, "NOT_REQUESTED", []
        if len(refs) > _MAX_WIKI_LOOKUPS:
            raise SupportAnalysisInputError("support Wiki lookup limit exceeded")
        if len({ref.support_program_id for ref in refs}) != len(refs) or len(
            {ref.wiki_uuid for ref in refs}
        ) != len(refs):
            raise SupportAnalysisInputError("support Wiki references must be unique")

        programs: list[ReviewedSupportProgram] = []
        evidence: dict[str, EvidenceRecord] = {}
        versions: list[str] = []
        missing: list[Uncertainty] = []
        for ref in refs:
            deadline = current_deadline()
            if deadline is None:
                resolved = await self._wiki_store.lookup(ref)
            else:
                deadline.check()
                timeout = asyncio.timeout(deadline.remaining_seconds())
                try:
                    async with timeout:
                        resolved = await self._wiki_store.lookup(ref)
                except TimeoutError:
                    if timeout.expired():
                        raise RunDeadlineExceededError() from None
                    raise
                deadline.check()
            if resolved is None:
                if not missing:
                    missing.append(
                        Uncertainty(
                            code="SOURCE_UNAVAILABLE",
                            target_path="/search_summary/wiki_lookup",
                            reason_summary=(
                                "요청한 지원사업 중 검수된 Wiki 자료와 공식 근거를 "
                                "확인할 수 없는 항목이 있습니다."
                            ),
                            evidence_refs=[],
                        )
                    )
                continue
            # Revalidate even a custom resolver's model, including closed
            # Evidence lineage, rather than trusting mutable nested objects.
            resolved = ReviewedSupportCatalog.model_validate(
                resolved.model_dump(mode="python")
            )
            if len(resolved.programs) != 1 or _program_key(
                resolved.programs[0].support_program
            ) != _program_key(ref):
                raise SupportAnalysisInputError(
                    "support Wiki result does not match the exact requested reference"
                )
            programs.append(resolved.programs[0])
            versions.append(resolved.catalog_version)
            for item in resolved.evidence_records:
                previous = evidence.get(item.evidence_id)
                if previous is not None and previous != item:
                    raise SupportAnalysisInputError(
                        "support Wiki evidence identifiers have conflicting content"
                    )
                evidence[item.evidence_id] = item
        version = hashlib.sha256("\0".join(sorted(versions)).encode()).hexdigest()
        return (
            ReviewedSupportCatalog(
                catalog_version=f"wiki:{version}",
                programs=tuple(programs),
                evidence_records=tuple(evidence.values()),
            ),
            "MISS" if missing else "HIT",
            missing,
        )

    @staticmethod
    def _validated_draft(raw_draft: Any) -> SupportAnalysisDraft:
        try:
            if isinstance(raw_draft, SupportAnalysisDraft):
                return raw_draft
            if isinstance(raw_draft, BaseModel):
                raw_draft = raw_draft.model_dump(mode="python")
            return SupportAnalysisDraft.model_validate(raw_draft)
        except (ValidationError, ValueError, TypeError):
            raise SupportAnalysisGuardrailError(
                "support model output did not satisfy the draft contract"
            ) from None

    def _assemble_result(
        self,
        *,
        request: SupportAgentInput,
        catalog: ReviewedSupportCatalog,
        plans: list[_ProgramPlan],
        draft: SupportAnalysisDraft,
        checked_at: datetime,
        wiki_lookup: Literal["HIT", "MISS", "NOT_REQUESTED"] = "NOT_REQUESTED",
        source_uncertainties: list[Uncertainty] | None = None,
    ) -> SupportAnalysisResult:
        self._validate_model_text(draft)
        self._validate_check_coverage(plans, draft)
        known_input_evidence = {
            evidence_ref
            for plan in plans
            for evidence_ref in plan.allowed_evidence_refs
        }
        self._validate_uncertainties(draft.uncertainties, known_input_evidence)

        plans_by_ref = {
            _program_key(item.program.support_program): item for item in plans
        }
        support_checks: list[SupportCheck] = []
        used_candidate_ids: list[UUID] = []
        for draft_check in draft.support_checks:
            plan = plans_by_ref.get(_program_key(draft_check.support_program))
            if plan is None:
                raise SupportAnalysisGuardrailError(
                    "model selected a support program outside the supplied catalog"
                )
            check, candidate_ids = self._build_check(
                draft_check=draft_check,
                plan=plan,
                checked_at=checked_at,
            )
            support_checks.append(check)
            for candidate_id in candidate_ids:
                if candidate_id not in used_candidate_ids:
                    used_candidate_ids.append(candidate_id)

        uncertainties = list(draft.uncertainties)
        stale_uncertainties = self._freshness_uncertainties(support_checks)
        uncertainties.extend(
            item for item in stale_uncertainties if item not in uncertainties
        )
        completion_status = draft.completion_status
        no_candidate_reason = draft.no_candidate_reason_code
        if stale_uncertainties:
            completion_status = SupportCompletionStatus.PARTIAL
            no_candidate_reason = None
        if source_uncertainties:
            uncertainties.extend(source_uncertainties)
            completion_status = SupportCompletionStatus.PARTIAL
            no_candidate_reason = None

        relevant_catalog_evidence = self._output_evidence(
            catalog,
            support_checks,
            uncertainties,
        )
        official_checked = any(
            _text(item.source_type) in {"OFFICIAL_DOCUMENT", "OFFICIAL_API"}
            for item in relevant_catalog_evidence
        )
        return SupportAnalysisResult(
            completion_status=completion_status,
            support_checks=support_checks,
            no_candidate_reason_code=no_candidate_reason,
            uncertainties=uncertainties,
            search_summary=SupportSearchSummary(
                wiki_lookup=wiki_lookup,
                rag_used=False,
                official_source_checked=official_checked,
                checked_at=checked_at,
            ),
            evidence_records=relevant_catalog_evidence,
            based_on_snapshot_id=request.planning_context.case_snapshot.snapshot_id,
            based_on_candidate_ids=used_candidate_ids,
        )

    @staticmethod
    def _resolved_facts(
        request: SupportAgentInput,
    ) -> dict[CaseFieldKey, _ResolvedFact]:
        snapshot = request.planning_context.case_snapshot
        facts = {
            fact.field_path: _ResolvedFact(
                status=_text(fact.status),
                value=fact.value,
                evidence_refs=tuple(fact.evidence_refs),
            )
            for fact in snapshot.facts
        }
        for overlay in request.planning_context.fact_overlays:
            SupportAgent._validate_overlay_before_state(
                overlay, facts.get(overlay.field_path)
            )
            facts[overlay.field_path] = _ResolvedFact(
                status=_text(overlay.proposed_status),
                value=overlay.proposed_value,
                evidence_refs=tuple(overlay.source_evidence_refs),
                overlay_candidate_id=overlay.candidate_id,
            )
        return facts

    @staticmethod
    def _build_program_plans(
        programs: list[ReviewedSupportProgram],
        facts: Mapping[CaseFieldKey, _ResolvedFact],
        evidence_by_id: Mapping[str, EvidenceRecord],
    ) -> list[_ProgramPlan]:
        plans: list[_ProgramPlan] = []
        for program in programs:
            criterion_plans: list[_CriterionPlan] = []
            allowed_check_refs = list(program.all_evidence_refs())
            for definition in program.criteria:
                fact = facts.get(definition.field_path)
                allowed_refs = list(definition.evidence_refs)
                if fact is not None:
                    allowed_refs.extend(
                        ref for ref in fact.evidence_refs if ref not in allowed_refs
                    )
                criterion_plans.append(
                    _CriterionPlan(
                        definition=definition,
                        fact=fact,
                        status=_evaluate_criterion(definition, fact),
                        allowed_evidence_refs=tuple(allowed_refs),
                    )
                )
                allowed_check_refs.extend(
                    ref for ref in allowed_refs if ref not in allowed_check_refs
                )

            freshness = _effective_freshness(program, evidence_by_id)
            plans.append(
                _ProgramPlan(
                    program=program,
                    freshness=freshness,
                    criteria=tuple(criterion_plans),
                    allowed_match_statuses=_allowed_match_statuses(
                        freshness,
                        {item.status for item in criterion_plans},
                    ),
                    allowed_evidence_refs=tuple(allowed_check_refs),
                )
            )
        return plans

    @staticmethod
    def _minimum_prompt_projection(
        request: SupportAgentInput,
        catalog: ReviewedSupportCatalog,
        plans: list[_ProgramPlan],
    ) -> dict[str, Any]:
        """Return only opaque IDs and deterministic statuses needed by the model."""

        feedback = []
        for issue in request.review_feedback:
            feedback.append(
                {
                    "issue_code": _text(issue.issue_code),
                    "category": _text(issue.category),
                    "severity": _text(issue.severity),
                    "target_component": _text(issue.target_component),
                    "target_path": issue.target_path,
                }
            )

        return {
            "catalog_version": catalog.catalog_version,
            "required_completion_status": "COMPLETE",
            "review_feedback": feedback,
            "programs": [
                {
                    "support_program": plan.program.support_program.model_dump(
                        mode="json"
                    ),
                    "freshness_status": _text(plan.freshness),
                    "allowed_match_statuses": [
                        _text(item) for item in plan.allowed_match_statuses
                    ],
                    "unknown_field_paths": [
                        item.definition.field_path.value
                        for item in plan.criteria
                        if item.status == "UNKNOWN"
                    ],
                    "criteria": [
                        {
                            "criterion_code": item.definition.criterion_code,
                            "field_path": item.definition.field_path.value,
                            "status": item.status,
                            "allowed_evidence_refs": list(item.allowed_evidence_refs),
                        }
                        for item in plan.criteria
                    ],
                    "allowed_evidence_refs": list(plan.allowed_evidence_refs),
                }
                for plan in plans
            ],
        }

    @staticmethod
    def _validate_overlay_before_state(
        overlay: FactChangeCandidate,
        fact: _ResolvedFact | None,
    ) -> None:
        if fact is None:
            if (
                _text(overlay.before_status) != "UNKNOWN"
                or overlay.before_value is not None
            ):
                raise SupportAnalysisInputError(
                    "fact overlay before state does not match the snapshot"
                )
            return
        if _text(overlay.before_status) != fact.status or not _strictly_equal(
            overlay.before_value, fact.value
        ):
            raise SupportAnalysisInputError(
                "fact overlay before state does not match the snapshot"
            )

    def _build_check(
        self,
        *,
        draft_check: SupportCheckDraft,
        plan: _ProgramPlan,
        checked_at: datetime,
    ) -> tuple[SupportCheck, list[UUID]]:
        program = plan.program
        criteria_by_code = {
            item.definition.criterion_code: item for item in plan.criteria
        }
        draft_codes = {item.criterion_code for item in draft_check.criteria}
        if draft_codes != set(criteria_by_code):
            raise SupportAnalysisGuardrailError(
                "model criteria do not match the supplied program definition"
            )

        criterion_results: list[SupportCriterionResult] = []
        used_candidate_ids: list[UUID] = []
        for draft_criterion in draft_check.criteria:
            criterion_plan = criteria_by_code[draft_criterion.criterion_code]
            definition = criterion_plan.definition
            fact = criterion_plan.fact
            status = criterion_plan.status
            if _text(draft_criterion.status) != status:
                raise SupportAnalysisGuardrailError(
                    "model criterion result contradicts supplied facts"
                )

            self._ensure_refs_allowed(
                draft_criterion.evidence_refs,
                set(criterion_plan.allowed_evidence_refs),
                label="criterion evidence",
            )

            evidence_refs = list(definition.evidence_refs)
            if fact is not None:
                evidence_refs.extend(
                    ref for ref in fact.evidence_refs if ref not in evidence_refs
                )
                if (
                    fact.overlay_candidate_id is not None
                    and fact.overlay_candidate_id not in used_candidate_ids
                ):
                    used_candidate_ids.append(fact.overlay_candidate_id)
            criterion_results.append(
                SupportCriterionResult(
                    criterion_code=definition.criterion_code,
                    case_value=(
                        fact.value
                        if fact is not None and fact.status == "CONFIRMED"
                        else None
                    ),
                    required_values=list(definition.required_values),
                    status=status,
                    reason_summary=draft_criterion.reason_summary,
                    evidence_refs=evidence_refs,
                )
            )

        expected_unknown_fields = {
            item.definition.field_path
            for item in plan.criteria
            if item.status == "UNKNOWN"
        }
        if set(draft_check.unknown_field_paths) != expected_unknown_fields:
            raise SupportAnalysisGuardrailError(
                "model unknown fields do not match unresolved criteria"
            )

        self._ensure_refs_allowed(
            draft_check.evidence_refs,
            set(plan.allowed_evidence_refs),
            label="support-check evidence",
        )

        freshness = plan.freshness
        match_status = self._validated_match_status(
            proposed=draft_check.match_status,
            freshness=freshness,
            criteria=criterion_results,
        )
        check_evidence = list(program.all_evidence_refs())
        for result in criterion_results:
            check_evidence.extend(
                ref for ref in result.evidence_refs if ref not in check_evidence
            )

        return (
            SupportCheck(
                support_program=program.support_program,
                program_name=program.program_name,
                related_steps=list(program.related_steps),
                match_status=match_status,
                criteria=criterion_results,
                unknown_field_paths=list(draft_check.unknown_field_paths),
                required_documents=[
                    RequiredDocument(
                        name=item.name,
                        submission_stage=item.submission_stage,
                        evidence_refs=list(item.evidence_refs),
                    )
                    for item in program.required_documents
                ],
                application_channel=_sourced_text(program.application_channel),
                application_url=_sourced_text(program.application_url),
                application_period=_sourced_text(program.application_period),
                source_version=program.source_version,
                freshness_status=freshness,
                checked_at=checked_at,
                reason_summary=_safe_match_reason(
                    freshness,
                    draft_check.reason_summary,
                ),
                evidence_refs=check_evidence,
            ),
            used_candidate_ids,
        )

    @staticmethod
    def _validated_match_status(
        *,
        proposed: SupportMatchStatus,
        freshness: FreshnessStatus,
        criteria: list[SupportCriterionResult],
    ) -> SupportMatchStatus:
        if freshness == FreshnessStatus.STALE:
            return SupportMatchStatus.STALE
        if freshness == FreshnessStatus.UNKNOWN:
            return SupportMatchStatus.UNVERIFIABLE

        statuses = {item.status for item in criteria}
        if CriterionStatus.NOT_MET in statuses:
            expected = SupportMatchStatus.NOT_RELEVANT
            if proposed != expected:
                raise SupportAnalysisGuardrailError(
                    "model match status contradicts a failed criterion"
                )
            return expected
        if CriterionStatus.UNKNOWN in statuses:
            expected = SupportMatchStatus.NEEDS_CONFIRMATION
            if proposed != expected:
                raise SupportAnalysisGuardrailError(
                    "model match status must preserve missing Case information"
                )
            return expected
        if proposed not in {
            SupportMatchStatus.POSSIBLY_RELEVANT,
            SupportMatchStatus.NEEDS_CONFIRMATION,
        }:
            raise SupportAnalysisGuardrailError(
                "model match status overstates or contradicts the comparison"
            )
        return proposed

    @staticmethod
    def _validate_uncertainties(
        uncertainties: list[Uncertainty],
        known_evidence: set[str],
    ) -> None:
        for uncertainty in uncertainties:
            SupportAgent._ensure_refs_allowed(
                uncertainty.evidence_refs,
                known_evidence,
                label="uncertainty evidence",
            )

    @staticmethod
    def _ensure_refs_allowed(
        refs: list[str],
        allowed: set[str],
        *,
        label: str,
    ) -> None:
        if set(refs) - allowed:
            raise SupportAnalysisGuardrailError(
                f"model returned unknown {label} references"
            )

    @staticmethod
    def _validate_model_text(draft: SupportAnalysisDraft) -> None:
        values = [item.reason_summary for item in draft.uncertainties]
        for check in draft.support_checks:
            values.append(check.reason_summary)
            values.extend(item.reason_summary for item in check.criteria)
        try:
            ensure_no_sensitive_text(values)
        except GuardrailViolation:
            raise SupportAnalysisGuardrailError(
                "support model output contains sensitive text"
            ) from None
        if any(_OVERCONFIDENT_SUPPORT_LANGUAGE.search(value) for value in values):
            raise SupportAnalysisGuardrailError(
                "support model output overstates eligibility or receipt"
            )

    @staticmethod
    def _validate_check_coverage(
        plans: list[_ProgramPlan],
        draft: SupportAnalysisDraft,
    ) -> None:
        selected_refs = {_program_key(item.program.support_program) for item in plans}
        returned_refs = {
            _program_key(item.support_program) for item in draft.support_checks
        }
        if returned_refs - selected_refs:
            raise SupportAnalysisGuardrailError(
                "model selected a support program outside the supplied catalog"
            )
        if selected_refs != returned_refs:
            raise SupportAnalysisGuardrailError(
                "support analysis must return every resolver-selected program"
            )

    @staticmethod
    def _freshness_uncertainties(
        checks: list[SupportCheck],
    ) -> list[Uncertainty]:
        uncertainties: list[Uncertainty] = []
        for index, check in enumerate(checks):
            if check.freshness_status == FreshnessStatus.CURRENT:
                continue
            is_stale = check.freshness_status == FreshnessStatus.STALE
            uncertainties.append(
                Uncertainty(
                    code="SOURCE_STALE" if is_stale else "SOURCE_UNAVAILABLE",
                    target_path=f"/support_checks/{index}/freshness_status",
                    reason_summary=(
                        "지원사업 자료가 오래되어 공식 출처에서 다시 확인해야 합니다."
                        if is_stale
                        else "지원사업 자료의 최신성을 확인할 수 없습니다."
                    ),
                    evidence_refs=list(check.evidence_refs),
                )
            )
        return uncertainties

    @staticmethod
    def _output_evidence(
        catalog: ReviewedSupportCatalog,
        checks: list[SupportCheck],
        uncertainties: list[Uncertainty],
    ) -> list[EvidenceRecord]:
        catalog_ids = {item.evidence_id for item in catalog.evidence_records}
        wanted = {
            ref for check in checks for ref in check.evidence_refs if ref in catalog_ids
        }
        wanted.update(
            ref
            for uncertainty in uncertainties
            for ref in uncertainty.evidence_refs
            if ref in catalog_ids
        )
        by_id = {item.evidence_id: item for item in catalog.evidence_records}
        pending = list(wanted)
        while pending:
            evidence = by_id[pending.pop()]
            for parent in evidence.parent_evidence_refs:
                if parent not in wanted:
                    wanted.add(parent)
                    pending.append(parent)
        return [item for item in catalog.evidence_records if item.evidence_id in wanted]

    def _checked_at(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise SupportAgentError("support Agent clock must return an aware datetime")
        return value


def _evaluate_criterion(
    definition: SupportCriterionDefinition,
    fact: _ResolvedFact | None,
) -> str:
    if fact is None or fact.status != "CONFIRMED" or fact.value is None:
        return "UNKNOWN"
    actual = fact.value
    expected_values = definition.required_values
    if CASE_FIELD_SPECS[definition.field_path][0] == FactValueType.DATE:
        actual = date.fromisoformat(actual) if isinstance(actual, str) else actual
        expected_values = tuple(
            date.fromisoformat(value) if isinstance(value, str) else value
            for value in expected_values
        )
    if definition.operator == "EQ":
        matched = _strictly_equal(actual, expected_values[0])
    elif definition.operator == "IN":
        matched = any(_strictly_equal(actual, item) for item in expected_values)
    else:
        expected = expected_values[0]
        if (
            type(actual) is not type(expected)
            or isinstance(actual, bool)
            or not isinstance(actual, (int, date))
        ):
            return "UNKNOWN"
        if definition.operator == "GT":
            matched = actual > expected
        elif definition.operator == "GTE":
            matched = actual >= expected
        elif definition.operator == "LT":
            matched = actual < expected
        else:
            matched = actual <= expected
    return "MET" if matched else "NOT_MET"


def _effective_freshness(
    program: ReviewedSupportProgram,
    evidence_by_id: Mapping[str, EvidenceRecord],
) -> FreshnessStatus:
    statuses = {_text(program.freshness_status)}
    wanted = set(program.all_evidence_refs())
    pending = list(wanted)
    while pending:
        evidence = evidence_by_id[pending.pop()]
        statuses.add(_text(evidence.freshness_status))
        for parent in evidence.parent_evidence_refs:
            if parent not in wanted:
                wanted.add(parent)
                pending.append(parent)
    if "STALE" in statuses:
        return FreshnessStatus.STALE
    if "UNKNOWN" in statuses:
        return FreshnessStatus.UNKNOWN
    return FreshnessStatus.CURRENT


def _allowed_match_statuses(
    freshness: FreshnessStatus,
    criterion_statuses: set[str],
) -> tuple[SupportMatchStatus, ...]:
    if freshness == FreshnessStatus.STALE:
        return (SupportMatchStatus.STALE,)
    if freshness == FreshnessStatus.UNKNOWN:
        return (SupportMatchStatus.UNVERIFIABLE,)
    if "NOT_MET" in criterion_statuses:
        return (SupportMatchStatus.NOT_RELEVANT,)
    if "UNKNOWN" in criterion_statuses:
        return (SupportMatchStatus.NEEDS_CONFIRMATION,)
    return (
        SupportMatchStatus.POSSIBLY_RELEVANT,
        SupportMatchStatus.NEEDS_CONFIRMATION,
    )


def _safe_match_reason(freshness: FreshnessStatus, proposed: str) -> str:
    if freshness == FreshnessStatus.STALE:
        return "지원사업 자료가 오래되어 공식 출처에서 다시 확인해야 합니다."
    if freshness == FreshnessStatus.UNKNOWN:
        return "지원사업 자료의 최신성을 확인할 수 없어 공식 출처 확인이 필요합니다."
    return proposed


def _sourced_text(value: CatalogSourcedText | None) -> SourcedText | None:
    if value is None:
        return None
    return SourcedText(text=value.text, evidence_refs=list(value.evidence_refs))


def _program_key(value: SupportProgramRef) -> tuple[int, UUID]:
    return value.support_program_id, value.wiki_uuid


def _strictly_equal(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def _text(value: object) -> str:
    return str(getattr(value, "value", value))


__all__ = [
    "StructuredGenerator",
    "SupportAgent",
    "SupportAgentError",
    "SupportAnalysisGuardrailError",
    "SupportAnalysisInputError",
    "SupportCatalogUnavailableError",
]
