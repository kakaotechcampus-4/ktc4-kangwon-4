"""Independent LLM review wrapped in deterministic integrity and safety checks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.agent.claim_safety import (
    expand_evidence,
    has_confirmation_caveat,
    has_explicit_eligibility_language,
    has_procedure_language,
    has_support_action_language,
    high_risk_metadata,
    is_overconfident,
    references_other_known_label,
    required_sources_for_claim,
)
from app.agent.guardrails import GuardrailViolation, ensure_no_sensitive_text
from app.agent.projection import ensure_projection_has_no_obvious_sensitive_text
from app.agent.prompts import review_messages
from app.agent.schemas import (
    ClaimType,
    Component,
    DecisionType,
    EvidenceRecord,
    FactChangeSourceType,
    FactOperation,
    FactStatus,
    FreshnessStatus,
    InfoAnalysisResult,
    MissingEvidence,
    ProcedureActionTarget,
    ProcedureFinding,
    ProcedureLookupResult,
    ReviewIssue,
    ReviewIssueCode,
    ReviewResult,
    ReviewSubject,
    ReviewVerdict,
    SupportActionTarget,
    SupportAnalysisResult,
    SupportCheck,
    SupportMatchStatus,
    canonical_digest,
)
from pydantic import BaseModel, ValidationError

from .models import ReviewModelOutput, ReviewProviderOutput


class ReviewToolError(RuntimeError):
    """Base class for local Review Tool failures."""


class ReviewIntegrityError(ReviewToolError):
    """The immutable review package failed deterministic integrity checks."""


class ReviewOutputViolation(ReviewToolError):
    """The model output used references outside the supplied review package."""


class StructuredReviewClient(Protocol):
    async def generate(
        self,
        response_model: type[BaseModel],
        messages: Sequence[Mapping[str, Any]],
        *,
        schema_name: str | None = None,
        max_retries: int | None = None,
        temperature: float | None = None,
    ) -> BaseModel: ...


@dataclass(frozen=True, slots=True)
class _ReviewContext:
    evidence_by_id: dict[str, EvidenceRecord]
    calls_by_id: dict[UUID, Component]
    sources_by_call_id: dict[UUID, Any]
    procedure_findings: tuple[tuple[UUID, ProcedureFinding], ...]
    support_checks: tuple[tuple[UUID, SupportCheck], ...]
    support_program_names: frozenset[str]


@dataclass(frozen=True, slots=True)
class _SafetyFindings:
    issues: tuple[ReviewIssue, ...]
    missing_evidence: tuple[MissingEvidence, ...]


class ReviewTool:
    """Review one immutable subject and inject trusted runtime identity.

    Cross-reference failures in the subject are rejected before any model call.
    Semantically unsafe but structurally intact drafts still receive the required
    independent model review; deterministic findings are then merged and cannot
    be overridden by a model ``PASS``.
    """

    def __init__(
        self,
        client: StructuredReviewClient,
        *,
        max_output_attempts: int = 2,
        provider_max_retries: int = 1,
    ) -> None:
        if not 1 <= max_output_attempts <= 3:
            raise ValueError("max_output_attempts must be between 1 and 3")
        if not 0 <= provider_max_retries <= 2:
            raise ValueError("provider_max_retries must be between 0 and 2")
        self._client = client
        self._max_output_attempts = max_output_attempts
        self._provider_max_retries = provider_max_retries

    async def review(self, subject: ReviewSubject) -> ReviewResult:
        context = _validate_integrity(subject)
        deterministic = _deterministic_safety_review(subject, context)

        model_input = _review_prompt_projection(subject, context)
        try:
            ensure_projection_has_no_obvious_sensitive_text(model_input)
        except GuardrailViolation:
            raise ReviewIntegrityError(
                "review input failed sensitive-data preflight"
            ) from None
        base_messages = review_messages(model_input)
        base_messages[0]["content"] += (
            "\n- Every issue.target_path and missing_evidence.claim_path must be an "
            "exact canonical JSON Pointer into the projected ReviewSubject in "
            "INPUT_JSON. Do not target omitted fields or null evidence placeholders. "
            "Every missing_evidence.claim_path must be a non-null path below "
            "/supervisor_draft/ because missing-evidence rework is owned by the "
            "Supervisor; never use a /source_results/ path for missing_evidence."
            "\n- PASS must have no blocking issue, missing evidence, or rework target. "
            "REVISE must have at least one BLOCKING issue or missing-evidence item. "
            "Warning-only findings must use PASS with no rework target. The runtime "
            "derives final rework targets; do not use that list to change severity. "
            "UNSUPPORTED_CLAIM, MISSING_EVIDENCE, STALE_EVIDENCE, "
            "PROCEDURE_CONFLICT, and CONTRACT_VIOLATION issues must be BLOCKING."
            " A question that only asks the user to supply an explicitly unknown "
            "field is not a factual claim and must not receive MISSING_EVIDENCE. "
            "Only flag a question when its own wording asserts an unsupported fact."
        )
        last_violation: ReviewOutputViolation | None = None

        for attempt in range(1, self._max_output_attempts + 1):
            messages = list(base_messages)
            if attempt > 1:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "The previous review output violated the response contract. "
                            "Use only call IDs, evidence IDs, and JSON Pointer paths "
                            "present in the canonical ReviewSubject projection in "
                            "INPUT_JSON. Do not target omitted fields or null evidence "
                            "placeholders. Every missing_evidence.claim_path must be a "
                            "non-null path below /supervisor_draft/; never use a "
                            "/source_results/ path for missing_evidence. PASS must have "
                            "no blocking issue, missing "
                            "evidence, or rework target. REVISE must have at least one "
                            "BLOCKING issue or missing-evidence item. Warning-only "
                            "findings must use PASS with no rework target. The runtime "
                            "derives final rework targets. UNSUPPORTED_CLAIM, "
                            "MISSING_EVIDENCE, STALE_EVIDENCE, PROCEDURE_CONFLICT, and "
                            "CONTRACT_VIOLATION issues must be BLOCKING. A question "
                            "that only requests an explicitly unknown field is not a "
                            "claim and must not receive MISSING_EVIDENCE. Do not output "
                            "subject IDs or digests."
                        ),
                    }
                )
            raw_output = await self._client.generate(
                ReviewProviderOutput,
                messages,
                schema_name="reborn_review_output",
                max_retries=self._provider_max_retries,
                temperature=0,
            )
            try:
                model_output = _coerce_model_output(raw_output, subject)
                _validate_model_output(
                    model_output,
                    subject,
                    context,
                    projected_subject=model_input,
                )
            except ReviewOutputViolation as exc:
                last_violation = exc
                if attempt < self._max_output_attempts:
                    continue
                raise

            return _finalize_result(subject, model_output, deterministic)

        raise last_violation or ReviewOutputViolation(
            "review output failed bounded validation"
        )


def _coerce_model_output(
    value: BaseModel | Mapping[str, Any],
    subject: ReviewSubject,
) -> ReviewModelOutput:
    try:
        if isinstance(value, ReviewModelOutput):
            return value
        if isinstance(value, ReviewProviderOutput):
            payload = value.model_dump(mode="python")
            # Asking for an explicitly unknown value is not itself a factual
            # claim.  Provider reviewers repeatedly classified these question
            # strings as unsupported claims even though deterministic review
            # separately catches factual assertions embedded in questions.
            original_issue_count = len(payload["issues"])
            original_missing_count = len(payload["missing_evidence"])
            payload["issues"] = [
                issue
                for issue in payload["issues"]
                if not (
                    issue["issue_code"] == ReviewIssueCode.MISSING_EVIDENCE
                    and _is_unassertive_information_question(
                        subject, issue["target_path"]
                    )
                )
            ]
            payload["missing_evidence"] = [
                item
                for item in payload["missing_evidence"]
                if not _is_unassertive_information_question(subject, item["claim_path"])
            ]
            dropped_question_finding = (
                len(payload["issues"]) != original_issue_count
                or len(payload["missing_evidence"]) != original_missing_count
            )
            derived_targets: set[Component] = set()
            for issue in payload["issues"]:
                owner_component, owner_call_id = _issue_owner_for_path(
                    subject, issue["target_path"]
                )
                # Component/call ownership is a deterministic property of the
                # canonical JSON Pointer.  Provider-authored copies are redundant
                # and frequently confuse a run UUID with a call UUID, so the
                # runtime replaces them with the authoritative values.
                issue["target_component"] = owner_component
                issue["target_call_id"] = owner_call_id
                if issue["severity"] == "BLOCKING":
                    derived_targets.add(owner_component)
            if payload["missing_evidence"]:
                derived_targets.add(Component.SUPERVISOR)
            payload["recommended_rework_targets"] = [
                component
                for component in (
                    Component.INFO_AGENT,
                    Component.PROCEDURE_TOOL,
                    Component.SUPPORT_AGENT,
                    Component.SUPERVISOR,
                )
                if component in derived_targets
            ]
            if (
                dropped_question_finding
                and not any(
                    issue["severity"] == "BLOCKING" for issue in payload["issues"]
                )
                and not payload["missing_evidence"]
            ):
                payload["verdict"] = ReviewVerdict.PASS
            return ReviewModelOutput.model_validate(payload)
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="python")
        return ReviewModelOutput.model_validate(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ReviewOutputViolation("review model output violates its schema") from exc


def _is_question_path(path: str) -> bool:
    tokens = _json_pointer_tokens(path)
    return (
        (
            len(tokens) == 3
            and tokens == ["supervisor_draft", "decision", "questions_for_user"]
        )
        or (
            len(tokens) == 4
            and tokens[:3] == ["supervisor_draft", "decision", "questions_for_user"]
            and tokens[3].isdigit()
        )
        or (
            len(tokens) == 4
            and tokens
            == [
                "supervisor_draft",
                "decision",
                "next_action",
                "questions_to_ask",
            ]
        )
        or (
            len(tokens) == 5
            and tokens[:4]
            == [
                "supervisor_draft",
                "decision",
                "next_action",
                "questions_to_ask",
            ]
            and tokens[4].isdigit()
        )
    )


_ASSUMPTIVE_QUESTION_PATTERN = re.compile(
    r"(?:이미|벌써|당연|확실|분명|받으셨죠|하셨죠|했죠|됐죠|맞죠|"
    r"완료했(?:다고|으니)|완료됐(?:다고|으니))",
    re.IGNORECASE,
)
_INFORMATION_QUESTION_PATTERN = re.compile(
    r"(?:무엇|어떤|언제|어디|어떻게|왜|누구|몇|얼마|여부|내용|상태|범위|사항|"
    r"확인|알려|입력|제공|필요|"
    r"what|which|when|where|how|who)",
    re.IGNORECASE,
)
_INFORMATION_REQUEST_ENDING_PATTERN = re.compile(
    r"(?:알려|입력해|제공해|답변해|확인해)\s*(?:주(?:세요|십시오|시겠습니까)|달라)\s*[.!]?$",
    re.IGNORECASE,
)
_QUESTION_WITH_OPTIONAL_EXAMPLE_PATTERN = re.compile(
    r"\?(?:\s*예(?:시)?\)?\s*[:.)]?\s*[^?]{0,200})?$",
    re.IGNORECASE,
)


def _is_unassertive_information_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return (
        (
            _QUESTION_WITH_OPTIONAL_EXAMPLE_PATTERN.search(text) is not None
            or _INFORMATION_REQUEST_ENDING_PATTERN.search(text) is not None
        )
        and _INFORMATION_QUESTION_PATTERN.search(text) is not None
        and _ASSUMPTIVE_QUESTION_PATTERN.search(text) is None
        and not is_overconfident(text)
    )


def _is_unassertive_information_question(
    subject: ReviewSubject,
    path: str,
) -> bool:
    """Recognize only plainly interrogative, non-presuppositional questions."""

    if not _is_question_path(path):
        return False
    try:
        value = _resolve_json_pointer(subject, path)
    except ReviewOutputViolation:
        return False
    if isinstance(value, list):
        return bool(value) and all(
            _is_unassertive_information_text(item) for item in value
        )
    return _is_unassertive_information_text(value)


def _validate_integrity(subject: ReviewSubject) -> _ReviewContext:
    try:
        calculated_digest = subject.calculate_digest()
    except (TypeError, ValueError, AttributeError) as exc:
        raise ReviewIntegrityError("review subject cannot be digested") from exc
    if subject.subject_digest != calculated_digest:
        raise ReviewIntegrityError("review subject digest does not match its contents")

    call_ids = [source.meta.call_id for source in subject.source_results]
    if len(set(call_ids)) != len(call_ids):
        raise ReviewIntegrityError("review source call IDs must be unique")
    if set(call_ids) != set(subject.supervisor_draft.source_call_ids):
        raise ReviewIntegrityError(
            "review sources do not match the Supervisor source call set"
        )

    calls_by_id: dict[UUID, Component] = {}
    sources_by_call_id: dict[UUID, Any] = {}
    procedure_findings: list[tuple[UUID, ProcedureFinding]] = []
    support_checks: list[tuple[UUID, SupportCheck]] = []
    support_program_names: set[str] = set()
    for source in subject.source_results:
        if source.output_digest != canonical_digest(source.output):
            raise ReviewIntegrityError("review source output digest is invalid")
        if (
            source.meta.run_id != subject.run_id
            or source.meta.case_id != subject.case_id
        ):
            raise ReviewIntegrityError("review source run/case does not match")
        if source.output.based_on_snapshot_id != subject.snapshot.snapshot_id:
            raise ReviewIntegrityError("review source snapshot does not match")
        calls_by_id[source.meta.call_id] = source.meta.component
        sources_by_call_id[source.meta.call_id] = source
        if source.meta.component == Component.INFO_AGENT:
            procedure_findings.extend(
                (source.meta.call_id, finding)
                for finding in source.output.procedure_findings
            )
        if source.meta.component == Component.SUPPORT_AGENT:
            support_checks.extend(
                (source.meta.call_id, check) for check in source.output.support_checks
            )
            support_program_names.update(
                check.program_name for check in source.output.support_checks
            )

    evidence_by_id: dict[str, EvidenceRecord] = {}
    for evidence in _walk_evidence_records(subject):
        existing = evidence_by_id.get(evidence.evidence_id)
        if existing is not None and existing != evidence:
            raise ReviewIntegrityError(
                "the same evidence ID has conflicting content in the review package"
            )
        evidence_by_id[evidence.evidence_id] = evidence

    unknown_evidence = sorted(
        set(_walk_named_evidence_refs(subject)) - evidence_by_id.keys()
    )
    if unknown_evidence:
        raise ReviewIntegrityError(
            "review subject contains unresolved evidence references: "
            + ", ".join(unknown_evidence)
        )

    _validate_procedure_analysis_provenance(sources_by_call_id)
    _validate_mutation_provenance(subject, sources_by_call_id)
    _validate_action_shape(subject, sources_by_call_id)
    return _ReviewContext(
        evidence_by_id=evidence_by_id,
        calls_by_id=calls_by_id,
        sources_by_call_id=sources_by_call_id,
        procedure_findings=tuple(procedure_findings),
        support_checks=tuple(support_checks),
        support_program_names=frozenset(support_program_names),
    )


def _validate_mutation_provenance(
    subject: ReviewSubject,
    sources_by_call_id: dict[UUID, Any],
) -> None:
    mutations = subject.supervisor_draft.mutations
    snapshot_facts = {fact.field_path: fact for fact in subject.snapshot.facts}
    for candidate in mutations.fact_changes:
        if candidate.source_type != FactChangeSourceType.INFO_ANALYSIS:
            raise ReviewIntegrityError(
                "confirmed-conflict fact mutation lacks a verifiable standalone trigger"
            )
        if candidate.source_call_id is None:
            raise ReviewIntegrityError("fact mutation is missing its Info source call")
        source = _require_source_output(
            candidate.source_call_id,
            InfoAnalysisResult,
            sources_by_call_id,
            "fact mutation",
        )
        fact_candidates = [
            fact
            for fact in source.output.fact_candidates
            if fact.candidate_id == candidate.source_fact_candidate_id
        ]
        if len(fact_candidates) != 1:
            raise ReviewIntegrityError(
                "fact mutation does not resolve to exactly one Info fact candidate"
            )
        fact_candidate = fact_candidates[0]
        if fact_candidate.requires_confirmation:
            raise ReviewIntegrityError(
                "fact mutation cannot use a candidate that requires confirmation"
            )
        expected_status = (
            FactStatus.UNKNOWN
            if fact_candidate.operation == FactOperation.CLEAR
            else FactStatus.CONFIRMED
        )
        if not (
            candidate.operation == fact_candidate.operation
            and candidate.field_path == fact_candidate.field_path
            and candidate.value_type == fact_candidate.value_type
            and candidate.proposed_status == expected_status
            and _strictly_equal_nullable(candidate.proposed_value, fact_candidate.value)
            and candidate.reason_summary == fact_candidate.reason_summary
            and candidate.source_evidence_refs == fact_candidate.source_evidence_refs
        ):
            raise ReviewIntegrityError(
                "fact mutation differs from its Info fact candidate"
            )

        before = snapshot_facts.get(candidate.field_path)
        before_status = before.status if before is not None else FactStatus.UNKNOWN
        before_value = before.value if before is not None else None
        if candidate.before_status != before_status or not _strictly_equal_nullable(
            candidate.before_value, before_value
        ):
            raise ReviewIntegrityError(
                "fact mutation before state differs from the review snapshot"
            )

    for candidate in mutations.procedure_progress_changes:
        source = _require_source_output(
            candidate.procedure_analysis_call_id,
            InfoAnalysisResult,
            sources_by_call_id,
            "procedure mutation",
        )
        findings = [
            finding
            for finding in source.output.procedure_findings
            if finding.procedure_step == candidate.procedure_step
        ]
        if len(findings) != 1:
            raise ReviewIntegrityError(
                "procedure mutation does not resolve to one Info procedure finding"
            )
        finding = findings[0]
        snapshot_progress = next(
            (
                progress
                for progress in subject.snapshot.procedure_progress
                if progress.procedure_step == candidate.procedure_step
            ),
            None,
        )
        before_status = snapshot_progress.status if snapshot_progress else None
        if (
            candidate.before_status != before_status
            or finding.current_status != before_status
        ):
            raise ReviewIntegrityError(
                "procedure mutation before state differs from snapshot/finding"
            )

        matching_observations = [
            observation
            for observation in source.output.procedure_progress_observations
            if (
                observation.procedure_step == candidate.procedure_step
                and observation.observed_status == candidate.proposed_status
                and observation.source_evidence_refs
                == candidate.execution_evidence_refs
                and observation.reason_summary == candidate.reason_summary
            )
        ]
        if len(matching_observations) != 1:
            raise ReviewIntegrityError(
                "procedure mutation does not resolve to one Info observation"
            )
        if matching_observations[0].requires_confirmation:
            raise ReviewIntegrityError(
                "procedure mutation cannot use an observation requiring confirmation"
            )

    for candidate in mutations.support_match_updates:
        source = _require_source_output(
            candidate.source_call_id,
            SupportAnalysisResult,
            sources_by_call_id,
            "support mutation",
        )
        source_checks = [
            support_check
            for support_check in source.output.support_checks
            if support_check.support_program.support_program_id
            == candidate.support_check.support_program.support_program_id
        ]
        if len(source_checks) != 1 or source_checks[0] != candidate.support_check:
            raise ReviewIntegrityError(
                "support mutation differs from its source SupportCheck"
            )


def _validate_procedure_analysis_provenance(
    sources_by_call_id: dict[UUID, Any],
) -> None:
    """Verify that Info procedure findings only interpret supplied raw lookup data."""

    for source in sources_by_call_id.values():
        if not isinstance(source.output, InfoAnalysisResult):
            continue
        info = source.output
        lookup_source = _require_source_output(
            info.based_on_procedure_lookup_call_id,
            ProcedureLookupResult,
            sources_by_call_id,
            "Info procedure analysis",
        )
        if info.based_on_procedure_lookup_digest != lookup_source.output_digest:
            raise ReviewIntegrityError(
                "Info procedure analysis digest does not match its raw lookup"
            )

        lookup_evidence = {
            record.evidence_id: record
            for record in lookup_source.output.evidence_records
        }
        for finding in info.procedure_findings:
            for evidence_ref in finding.evidence_refs:
                if evidence_ref not in lookup_evidence:
                    raise ReviewIntegrityError(
                        "Info procedure finding evidence is not from its raw lookup"
                    )


def _require_source_output(
    call_id: UUID,
    expected_type: type[Any],
    sources_by_call_id: dict[UUID, Any],
    label: str,
) -> Any:
    source = sources_by_call_id.get(call_id)
    if source is None or not isinstance(source.output, expected_type):
        raise ReviewIntegrityError(f"{label} references an unknown or wrong component")
    return source


def _strictly_equal_nullable(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    return type(left) is type(right) and left == right


_PROMPT_EXCLUDED_KEYS = {
    "application_id",
    "candidate_id",
    "captured_at",
    "case_id",
    "case_version",
    "checked_at",
    "claim_id",
    "client_event_id",
    "confirmed_at",
    "conflict_digest",
    "conflict_ref",
    "content_hash",
    "created_at",
    "document_id",
    "draft_id",
    "finding_id",
    "history_id",
    "input_event_id",
    "locator",
    "lookup_id",
    "observation_id",
    "parent_call_id",
    "published_at",
    "question_id",
    "requested_at",
    "retrieved_at",
    "review_subject_id",
    "run_id",
    "schema_version",
    "snapshot_id",
    "source_fact_candidate_id",
    "source_ref",
    "searched_at",
    "submitted_at",
    "trace_id",
    "updated_at",
}


def _review_prompt_projection(
    subject: ReviewSubject,
    context: _ReviewContext,
) -> dict[str, Any]:
    """Build a minimal projection whose paths remain canonical ReviewSubject paths."""

    snapshot_payload = subject.snapshot.model_dump(
        mode="json", exclude={"evidence_records"}
    )
    snapshot_payload = _minimize_prompt_value(snapshot_payload)
    source_output_payloads = [
        _minimize_prompt_value(
            source.output.model_dump(mode="json", exclude={"evidence_records"})
        )
        for source in subject.source_results
    ]
    supervisor_payload = subject.supervisor_draft.model_dump(mode="json")

    directly_used_refs = set(
        _walk_named_evidence_refs(snapshot_payload)
        + [
            evidence_ref
            for source in subject.source_results
            for evidence_ref in _walk_named_evidence_refs(
                source.output.model_dump(mode="python", exclude={"evidence_records"})
            )
        ]
        + _walk_named_evidence_refs(supervisor_payload)
    )
    used_refs = set(directly_used_refs)
    pending = list(directly_used_refs)
    while pending:
        evidence_ref = pending.pop()
        evidence = context.evidence_by_id[evidence_ref]
        for parent_ref in evidence.parent_evidence_refs:
            if parent_ref not in used_refs:
                used_refs.add(parent_ref)
                pending.append(parent_ref)

    snapshot_payload["evidence_records"] = [
        _prompt_evidence_record(evidence) if evidence.evidence_id in used_refs else None
        for evidence in subject.snapshot.evidence_records
    ]
    source_payloads: list[dict[str, Any]] = []
    for source, output_payload in zip(
        subject.source_results, source_output_payloads, strict=True
    ):
        output_payload["evidence_records"] = [
            _prompt_evidence_record(evidence)
            if evidence.evidence_id in used_refs
            else None
            for evidence in source.output.evidence_records
        ]
        source_payloads.append(
            {
                "meta": {
                    "component": source.meta.component.value,
                    "call_id": str(source.meta.call_id),
                },
                "output": output_payload,
            }
        )

    trigger: dict[str, Any] = {
        "trigger_type": subject.trigger.trigger_type,
    }
    redacted_input = getattr(subject.trigger, "input", None)
    if redacted_input is not None:
        trigger["input"] = {
            "source_type": redacted_input.source_type.value,
            "redacted_text": redacted_input.redacted_text,
        }
    support_programs = getattr(subject.trigger, "support_programs", None)
    if support_programs is not None:
        trigger["support_programs"] = [
            item.model_dump(mode="json") for item in support_programs
        ]
    as_of = getattr(subject.trigger, "as_of", None)
    if as_of is not None:
        trigger["as_of"] = as_of.isoformat()

    return {
        "review_attempt": subject.review_attempt,
        "trigger": trigger,
        "snapshot": snapshot_payload,
        "source_results": source_payloads,
        "supervisor_draft": _minimize_prompt_value(supervisor_payload),
    }


def _prompt_evidence_record(evidence: EvidenceRecord) -> dict[str, Any]:
    return _minimize_prompt_value(evidence.model_dump(mode="json"))


def _minimize_prompt_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _minimize_prompt_value(item)
            for key, item in value.items()
            if str(key) not in _PROMPT_EXCLUDED_KEYS
        }
    if isinstance(value, list):
        return [_minimize_prompt_value(item) for item in value]
    return value


def _validate_action_shape(
    subject: ReviewSubject,
    sources_by_call_id: dict[UUID, Any],
) -> None:
    decision = subject.supervisor_draft.decision
    if decision.decision_type == DecisionType.ACTION:
        if decision.blocker is None or decision.next_action is None:
            raise ReviewIntegrityError("ACTION requires exactly one blocker and action")
        if decision.questions_for_user:
            raise ReviewIntegrityError("ACTION cannot also be a user-question branch")
    elif decision.decision_type == DecisionType.NEEDS_MORE_INFO:
        if decision.blocker is None or decision.next_action is not None:
            raise ReviewIntegrityError("NEEDS_MORE_INFO shape is invalid")
    else:
        if decision.blocker is not None or decision.next_action is not None:
            raise ReviewIntegrityError("CASE_COMPLETE cannot contain blocker/action")
        raise ReviewIntegrityError(
            "CASE_COMPLETE is unavailable without authoritative procedure coverage"
        )


def _deterministic_safety_review(
    subject: ReviewSubject,
    context: _ReviewContext,
) -> _SafetyFindings:
    issues: list[ReviewIssue] = []
    missing: list[MissingEvidence] = []
    draft = subject.supervisor_draft
    visible_strings = dict(_visible_draft_strings(subject))

    for index, claim in enumerate(draft.grounded_claims):
        claim_path = f"/supervisor_draft/grounded_claims/{index}"
        target = visible_strings.get(claim.target_path)
        if target != claim.text:
            issues.append(
                _issue(
                    code="CONTRACT_VIOLATION",
                    category="CONTRACT",
                    path=f"{claim_path}/target_path",
                    reason="근거 주장의 경로가 실제 사용자 노출 문장과 일치하지 않습니다.",
                    evidence_refs=claim.evidence_refs,
                )
            )

        claim_evidence = [
            context.evidence_by_id[evidence_ref] for evidence_ref in claim.evidence_refs
        ]
        expanded_claim_evidence = expand_evidence(
            claim_evidence, context.evidence_by_id
        )
        has_non_current_evidence = any(
            evidence.freshness_status != FreshnessStatus.CURRENT
            for evidence in expanded_claim_evidence
        )
        if has_non_current_evidence:
            if claim.assertion_level == "INFORMATION":
                issues.append(
                    _issue(
                        code="STALE_EVIDENCE",
                        category="EVIDENCE",
                        path=claim_path,
                        reason="최신성이 확인되지 않은 근거로 확정형 정보를 제시했습니다.",
                        evidence_refs=claim.evidence_refs,
                    )
                )
            elif not has_confirmation_caveat(claim.text):
                issues.append(
                    _issue(
                        code="STALE_EVIDENCE",
                        category="EVIDENCE",
                        path=claim.target_path,
                        reason=(
                            "최신성이 확인되지 않은 근거의 주장이 사용자 문장에 "
                            "확인 필요 또는 불확실성을 명시하지 않았습니다."
                        ),
                        evidence_refs=claim.evidence_refs,
                    )
                )

        required_sources = required_sources_for_claim(claim.claim_type)
        has_required_source = any(
            evidence.source_type in required_sources
            for evidence in expanded_claim_evidence
        )
        if not has_required_source:
            issues.append(
                _issue(
                    code="MISSING_EVIDENCE",
                    category="EVIDENCE",
                    path=claim_path,
                    reason="고위험 주장을 뒷받침할 검증된 공식 근거가 없습니다.",
                    evidence_refs=claim.evidence_refs,
                )
            )
            missing.append(
                MissingEvidence(
                    claim_path=claim.target_path,
                    required_source_types=sorted(required_sources),
                    reason_summary="고위험 주장은 공식 문서 또는 공식 API 근거가 필요합니다.",
                )
            )

        if is_overconfident(claim.text):
            issues.append(
                _issue(
                    code="OVERCONFIDENT_LANGUAGE",
                    category="SAFETY",
                    path=claim.target_path,
                    reason="기관·전문가 확인 전 확정적으로 읽히는 표현이 포함되어 있습니다.",
                    evidence_refs=claim.evidence_refs,
                )
            )

    claim_keys = {
        (claim.target_path, claim.text, claim.claim_type)
        for claim in draft.grounded_claims
    }
    for path, text in visible_strings.items():
        if is_overconfident(text):
            issues.append(
                _issue(
                    code="OVERCONFIDENT_LANGUAGE",
                    category="SAFETY",
                    path=path,
                    reason="기관·전문가 확인 전 확정적으로 읽히는 표현이 포함되어 있습니다.",
                    evidence_refs=[],
                )
            )
        risk_types, required_sources = high_risk_metadata(
            text, context.support_program_names
        )
        if not risk_types:
            continue
        matching_claims = [
            claim
            for claim in draft.grounded_claims
            if claim.target_path == path and claim.text == text
        ]
        explicit_eligibility_is_grounded = not has_explicit_eligibility_language(
            text
        ) or any(
            claim.claim_type == ClaimType.ELIGIBILITY
            and claim.assertion_level == "NEEDS_CONFIRMATION"
            for claim in matching_claims
        )
        has_matching_risk_claim = any(
            (path, text, claim_type) in claim_keys for claim_type in risk_types
        )
        if not explicit_eligibility_is_grounded or not has_matching_risk_claim:
            issues.append(
                _issue(
                    code="UNSUPPORTED_CLAIM",
                    category="EVIDENCE",
                    path=path,
                    reason="고위험 사용자 노출 문장이 GroundedClaim으로 연결되지 않았습니다.",
                    evidence_refs=[],
                )
            )
            missing.append(
                MissingEvidence(
                    claim_path=path,
                    required_source_types=sorted(required_sources),
                    reason_summary="해당 문장을 직접 뒷받침하는 공식 근거가 필요합니다.",
                )
            )

    issues.extend(_action_target_findings(subject, context))
    return _SafetyFindings(
        issues=tuple(_deduplicate_models(issues)),
        missing_evidence=tuple(_deduplicate_models(missing)),
    )


def _action_target_findings(
    subject: ReviewSubject,
    context: _ReviewContext,
) -> list[ReviewIssue]:
    decision = subject.supervisor_draft.decision
    if decision.decision_type != DecisionType.ACTION:
        return []
    action = decision.next_action
    action_path = "/supervisor_draft/decision/next_action"
    if isinstance(action.target, SupportActionTarget):
        target = action.target.support_program
        matches = [
            (call_id, check)
            for call_id, check in context.support_checks
            if check.support_program == target
        ]
        if not matches:
            return [
                _issue(
                    code="CONTRACT_VIOLATION",
                    category="CONTRACT",
                    path=f"{action_path}/target",
                    reason="Next Action의 지원사업 target이 지원금 분석 결과에 없습니다.",
                    evidence_refs=action.evidence_refs,
                )
            ]

        if len(matches) != 1:
            return [
                _issue(
                    code="CONTRACT_VIOLATION",
                    category="CONTRACT",
                    path=f"{action_path}/target",
                    reason="Next Action의 지원사업 target은 정확히 한 분석 결과와 연결되어야 합니다.",
                    evidence_refs=action.evidence_refs,
                )
            ]

        _, check = matches[0]
        findings: list[ReviewIssue] = []
        if check.match_status == SupportMatchStatus.NOT_RELEVANT:
            findings.append(
                _issue(
                    code="INFEASIBLE_ACTION",
                    category="ACTIONABILITY",
                    path=action_path,
                    reason="관련 없음으로 확인된 지원사업을 다음 행동으로 선택했습니다.",
                    evidence_refs=action.evidence_refs,
                )
            )
        check_refs = set(check.evidence_refs)
        if not check_refs or not set(action.evidence_refs).intersection(check_refs):
            findings.append(
                _issue(
                    code="MISSING_EVIDENCE",
                    category="EVIDENCE",
                    path=f"{action_path}/evidence_refs",
                    reason="Next Action 근거가 대상 지원사업 분석 결과와 연결되지 않습니다.",
                    evidence_refs=action.evidence_refs,
                )
            )

        cleaned_values = [
            value.replace(check.program_name, " ")
            for value in (
                action.action_code,
                action.title,
                action.reason,
                *action.questions_to_ask,
            )
        ]
        support_names = {other.program_name for _, other in context.support_checks}
        procedure_labels = {
            label
            for _, procedure_finding in context.procedure_findings
            for label in (
                procedure_finding.step_name,
                procedure_finding.procedure_step.step_code,
            )
        }
        cleaned_text = " ".join(cleaned_values)
        if (
            has_procedure_language(*cleaned_values)
            or references_other_known_label(
                " ".join(
                    (
                        action.action_code,
                        action.title,
                        action.reason,
                        *action.questions_to_ask,
                    )
                ),
                selected_labels={check.program_name},
                known_labels=support_names,
            )
            or any(label in cleaned_text for label in procedure_labels)
        ):
            findings.append(
                _issue(
                    code="PROCEDURE_CONFLICT",
                    category="PROCEDURE",
                    path=f"{action_path}/target",
                    reason="하나의 Next Action이 여러 canonical 대상을 함께 지시합니다.",
                    evidence_refs=action.evidence_refs,
                )
            )
        if not decision.requires_human or not action.questions_to_ask:
            findings.append(
                _issue(
                    code="HUMAN_CONFIRMATION_OMITTED",
                    category="SAFETY",
                    path=action_path,
                    reason="지원사업 행동에 기관 확인 질문이 포함되지 않았습니다.",
                    evidence_refs=action.evidence_refs,
                )
            )
        return findings

    if not isinstance(action.target, ProcedureActionTarget):
        return [
            _issue(
                code="CONTRACT_VIOLATION",
                category="CONTRACT",
                path=f"{action_path}/target",
                reason="알 수 없는 Next Action target 종류입니다.",
                evidence_refs=action.evidence_refs,
            )
        ]

    procedure_target = action.target.procedure_step
    target = (
        procedure_target.procedure_step_id,
        procedure_target.step_code,
    )
    matches = [
        (call_id, finding)
        for call_id, finding in context.procedure_findings
        if (
            finding.procedure_step.procedure_step_id,
            finding.procedure_step.step_code,
        )
        == target
    ]
    if not matches:
        return [
            _issue(
                code="PROCEDURE_CONFLICT",
                category="PROCEDURE",
                path=f"{action_path}/target",
                reason="Next Action의 대상 절차가 정보분석 결과에 없습니다.",
                evidence_refs=action.evidence_refs,
            )
        ]

    if len(matches) != 1:
        return [
            _issue(
                code="CONTRACT_VIOLATION",
                category="CONTRACT",
                path=f"{action_path}/target",
                reason="Next Action의 절차 target은 정확히 한 정보분석 결과와 연결되어야 합니다.",
                evidence_refs=action.evidence_refs,
            )
        ]

    _, finding = matches[0]
    findings: list[ReviewIssue] = []

    finding_refs = set(finding.evidence_refs)
    if not set(action.evidence_refs).intersection(finding_refs):
        findings.append(
            _issue(
                code="MISSING_EVIDENCE",
                category="EVIDENCE",
                path=f"{action_path}/evidence_refs",
                reason="Next Action 근거가 대상 절차 정보분석 결과와 연결되지 않습니다.",
                evidence_refs=action.evidence_refs,
            )
        )

    combined = " ".join(
        [action.action_code, action.title, action.reason, *action.questions_to_ask]
    )
    procedure_labels = {
        label
        for _, other in context.procedure_findings
        for label in (other.step_name, other.procedure_step.step_code)
    }
    if (
        any(name in combined for name in context.support_program_names)
        or has_support_action_language(combined)
        or references_other_known_label(
            combined,
            selected_labels={finding.step_name, finding.procedure_step.step_code},
            known_labels=procedure_labels,
        )
    ):
        findings.append(
            _issue(
                code="CONTRACT_VIOLATION",
                category="CONTRACT",
                path=f"{action_path}/target",
                reason="하나의 Next Action이 여러 canonical 대상을 함께 지시합니다.",
                evidence_refs=action.evidence_refs,
            )
        )

    action_and_finding_refs = set(action.evidence_refs) | finding_refs
    unverified_evidence = [
        context.evidence_by_id[evidence_ref]
        for evidence_ref in action_and_finding_refs
        if context.evidence_by_id[evidence_ref].freshness_status
        != FreshnessStatus.CURRENT
    ]
    confirmation_only_action = (
        finding.requires_confirmation
        and decision.requires_human
        and bool(action.questions_to_ask)
    )
    if unverified_evidence and not confirmation_only_action:
        findings.append(
            _issue(
                code="STALE_EVIDENCE",
                category="EVIDENCE",
                path=action_path,
                reason="최신성이 확인되지 않은 절차 근거로 실행 행동을 제시했습니다.",
                evidence_refs=[
                    evidence.evidence_id for evidence in unverified_evidence
                ],
            )
        )

    if finding.requires_confirmation and (
        not decision.requires_human or not action.questions_to_ask
    ):
        findings.append(
            _issue(
                code="HUMAN_CONFIRMATION_OMITTED",
                category="SAFETY",
                path=action_path,
                reason="미확인 절차를 제시하면서 사람·공식기관 확인 질문을 포함하지 않았습니다.",
                evidence_refs=action.evidence_refs,
            )
        )
    return findings


def _validate_model_output(
    output: ReviewModelOutput,
    subject: ReviewSubject,
    context: _ReviewContext,
    *,
    projected_subject: Mapping[str, Any],
) -> None:
    if len(set(output.recommended_rework_targets)) != len(
        output.recommended_rework_targets
    ):
        raise ReviewOutputViolation("review rework targets must be unique")

    authored_text = [output.resolution_reason]
    for issue in output.issues:
        authored_text.append(issue.reason_summary)
        target_value = _resolve_json_pointer(projected_subject, issue.target_path)
        if target_value is None:
            raise ReviewOutputViolation(
                "review issue cannot target an omitted or null projected value"
            )
        if issue.target_component == Component.SUPERVISOR:
            if issue.target_call_id is not None:
                raise ReviewOutputViolation(
                    "Supervisor review issue must not invent a target call ID"
                )
        else:
            if issue.target_call_id is None:
                raise ReviewOutputViolation(
                    "component review issue requires its supplied target call ID"
                )
            if context.calls_by_id.get(issue.target_call_id) != issue.target_component:
                raise ReviewOutputViolation(
                    "review issue references an unknown or wrong component call"
                )
        owner_component, owner_call_id = _issue_owner_for_path(
            subject, issue.target_path
        )
        if (
            issue.target_component != owner_component
            or issue.target_call_id != owner_call_id
        ):
            raise ReviewOutputViolation(
                "review issue target component/call does not own its target path"
            )
        unknown = set(issue.evidence_refs) - context.evidence_by_id.keys()
        if unknown:
            raise ReviewOutputViolation("review issue invented an evidence reference")

    for item in output.missing_evidence:
        authored_text.append(item.reason_summary)
        target_value = _resolve_json_pointer(projected_subject, item.claim_path)
        if target_value is None:
            raise ReviewOutputViolation(
                "missing evidence cannot target an omitted or null projected value"
            )
        if not item.claim_path.startswith("/supervisor_draft/"):
            raise ReviewOutputViolation(
                "missing evidence must target a Supervisor draft path"
            )
        owner_component, owner_call_id = _issue_owner_for_path(subject, item.claim_path)
        if owner_component != Component.SUPERVISOR or owner_call_id is not None:
            raise ReviewOutputViolation(
                "missing evidence must be owned by the Supervisor draft"
            )
        if len(set(item.required_source_types)) != len(item.required_source_types):
            raise ReviewOutputViolation("missing-evidence source types must be unique")

    try:
        ensure_no_sensitive_text(authored_text)
    except GuardrailViolation as exc:
        raise ReviewOutputViolation("review output contains sensitive text") from exc


def _finalize_result(
    subject: ReviewSubject,
    model_output: ReviewModelOutput,
    deterministic: _SafetyFindings,
) -> ReviewResult:
    issues = _deduplicate_models([*model_output.issues, *deterministic.issues])
    missing = _deduplicate_models(
        [*model_output.missing_evidence, *deterministic.missing_evidence]
    )
    has_blocking = any(issue.severity == "BLOCKING" for issue in issues)
    force_revise = has_blocking or bool(missing)
    verdict = ReviewVerdict.REVISE if force_revise else ReviewVerdict.PASS

    derived_targets = {
        issue.target_component for issue in issues if issue.severity == "BLOCKING"
    }
    if missing:
        derived_targets.add(Component.SUPERVISOR)
    targets = [
        component
        for component in (
            Component.INFO_AGENT,
            Component.PROCEDURE_TOOL,
            Component.SUPPORT_AGENT,
            Component.SUPERVISOR,
        )
        if component in derived_targets
    ]

    resolution_reason = model_output.resolution_reason
    if force_revise and model_output.verdict == ReviewVerdict.PASS:
        resolution_reason = "결정적 안전 검증에서 수정이 필요한 항목을 확인했습니다."

    return ReviewResult(
        reviewed_subject_id=subject.review_subject_id,
        reviewed_subject_digest=subject.subject_digest,
        verdict=verdict,
        issues=issues,
        missing_evidence=missing,
        recommended_rework_targets=targets,
        resolution_reason=resolution_reason,
    )


def _issue_owner_for_path(
    subject: ReviewSubject,
    target_path: str,
) -> tuple[Component, UUID | None]:
    tokens = _json_pointer_tokens(target_path)
    if tokens and tokens[0] == "supervisor_draft":
        return Component.SUPERVISOR, None
    if len(tokens) >= 2 and tokens[0] == "source_results":
        index_token = tokens[1]
        if index_token.isdigit():
            index = int(index_token)
            if index < len(subject.source_results):
                source = subject.source_results[index]
                return source.meta.component, source.meta.call_id
    raise ReviewOutputViolation(
        "review issue target path has no unambiguous component owner"
    )


def _visible_draft_strings(subject: ReviewSubject) -> list[tuple[str, str]]:
    decision = subject.supervisor_draft.decision
    base = "/supervisor_draft/decision"
    values: list[tuple[str, str]] = [
        (f"{base}/selection_summary", decision.selection_summary)
    ]
    if decision.blocker is not None:
        values.extend(
            [
                (f"{base}/blocker/title", decision.blocker.title),
                (f"{base}/blocker/description", decision.blocker.description),
            ]
        )
    if decision.next_action is not None:
        action_base = f"{base}/next_action"
        values.extend(
            [
                (f"{action_base}/title", decision.next_action.title),
                (f"{action_base}/reason", decision.next_action.reason),
            ]
        )
        values.extend(
            (f"{action_base}/questions_to_ask/{index}", text)
            for index, text in enumerate(decision.next_action.questions_to_ask)
        )
    values.extend(
        (f"{base}/questions_for_user/{index}", text)
        for index, text in enumerate(decision.questions_for_user)
    )
    return values


def _issue(
    *,
    code: str,
    category: str,
    path: str,
    reason: str,
    evidence_refs: list[str],
    target_component: str = "SUPERVISOR",
    target_call_id: UUID | None = None,
) -> ReviewIssue:
    return ReviewIssue(
        issue_code=code,
        category=category,
        severity="BLOCKING",
        target_component=target_component,
        target_call_id=target_call_id,
        target_path=path,
        reason_summary=reason,
        evidence_refs=evidence_refs,
    )


def _walk_evidence_records(value: Any) -> list[EvidenceRecord]:
    found: list[EvidenceRecord] = []

    def walk(item: Any) -> None:
        if isinstance(item, EvidenceRecord):
            found.append(item)
            return
        if isinstance(item, BaseModel):
            for field_name in type(item).model_fields:
                walk(getattr(item, field_name))
            return
        if isinstance(item, Mapping):
            for child in item.values():
                walk(child)
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                walk(child)

    walk(value)
    return found


def _walk_named_evidence_refs(value: Any) -> list[str]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    refs: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if str(key).endswith("evidence_refs"):
                    if isinstance(child, (list, tuple)):
                        refs.extend(str(ref) for ref in child)
                    continue
                if str(key) == "evidence_ref" and isinstance(child, str):
                    refs.append(child)
                    continue
                walk(child)
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                walk(child)

    walk(value)
    return refs


def _resolve_json_pointer(root: Any, pointer: str) -> Any:
    if pointer == "":
        return root
    current = root
    for token in _json_pointer_tokens(pointer):
        if isinstance(current, BaseModel):
            if token not in type(current).model_fields:
                raise ReviewOutputViolation(
                    "review output uses an unknown JSON Pointer"
                )
            current = getattr(current, token)
        elif isinstance(current, Mapping):
            if token not in current:
                raise ReviewOutputViolation(
                    "review output uses an unknown JSON Pointer"
                )
            current = current[token]
        elif isinstance(current, (list, tuple)):
            if not token.isdigit() or int(token) >= len(current):
                raise ReviewOutputViolation(
                    "review output uses an unknown JSON Pointer"
                )
            current = current[int(token)]
        else:
            raise ReviewOutputViolation("review output uses an unknown JSON Pointer")
    return current


def _json_pointer_tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    return [
        raw_token.replace("~1", "/").replace("~0", "~")
        for raw_token in pointer[1:].split("/")
    ]


def _deduplicate_models(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    unique: list[Any] = []
    for value in values:
        digest = canonical_digest(value)
        if digest not in seen:
            seen.add(digest)
            unique.append(value)
    return unique


__all__ = [
    "ReviewIntegrityError",
    "ReviewOutputViolation",
    "ReviewTool",
    "ReviewToolError",
    "StructuredReviewClient",
]
