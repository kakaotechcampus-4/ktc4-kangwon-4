"""Supervisor decision drafting over validated, read-only component results."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID, uuid4

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
from app.agent.enrichment import build_fact_overlays
from app.agent.guardrails import (
    GuardrailViolation,
    ensure_known_refs,
    ensure_no_sensitive_text,
)
from app.agent.projection import (
    ensure_projection_has_no_obvious_sensitive_text,
    to_model_projection,
)
from app.agent.prompts import supervisor_messages
from app.agent.schemas import (
    ActionDecisionDraft,
    AgentSchema,
    Blocker,
    CaseCompleteDecisionDraft,
    CaseStatus,
    CaseStatusChangeCandidate,
    ClaimType,
    DecisionType,
    EvidenceRecord,
    FactChangeCandidate,
    GroundedClaim,
    InfoAnalysisResult,
    MutationSet,
    NeedsMoreInfoDecisionDraft,
    NextAction,
    NextActionTarget,
    ProcedureActionTarget,
    ProcedureFinding,
    ProcedureLookupResult,
    ProcedureProgressChangeCandidate,
    ReviewSourceResult,
    SupervisorAgentInput,
    SupervisorDraft,
    SupportActionTarget,
    SupportAnalysisResult,
    SupportCheck,
    SupportMatchStatus,
    SupportMatchUpdateCandidate,
)
from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator


class StructuredGenerator(Protocol):
    async def generate(
        self,
        response_model: type[AgentSchema],
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AgentSchema: ...


class SupervisorGuardrailError(GuardrailViolation):
    """Raised when a Supervisor draft references data it did not receive."""


class NextActionSemantic(AgentSchema):
    action_code: Annotated[StrictStr, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]
    title: Annotated[StrictStr, Field(min_length=1)]
    reason: Annotated[StrictStr, Field(min_length=1)]
    questions_to_ask: list[Annotated[StrictStr, Field(min_length=1)]]
    target: NextActionTarget
    evidence_refs: Annotated[
        list[Annotated[StrictStr, Field(min_length=1)]], Field(min_length=1)
    ]


class GroundedClaimSemantic(AgentSchema):
    claim_type: ClaimType
    target_path: Annotated[
        StrictStr, Field(pattern=r"^/supervisor_draft/(?:[^~/]|~[01]|/)+$")
    ]
    text: Annotated[StrictStr, Field(min_length=1)]
    assertion_level: Literal["INFORMATION", "NEEDS_CONFIRMATION"]
    evidence_refs: Annotated[
        list[Annotated[StrictStr, Field(min_length=1)]], Field(min_length=1)
    ]

    @model_validator(mode="after")
    def eligibility_is_never_final(self) -> GroundedClaimSemantic:
        if (
            self.claim_type == ClaimType.ELIGIBILITY
            and self.assertion_level != "NEEDS_CONFIRMATION"
        ):
            raise ValueError("eligibility claims require confirmation")
        return self


class GroundedClaimModelOutput(AgentSchema):
    """Provider selects a visible field; runtime injects its path and exact text."""

    claim_type: ClaimType
    target_kind: Literal[
        "SELECTION_SUMMARY",
        "BLOCKER_TITLE",
        "BLOCKER_DESCRIPTION",
        "NEXT_ACTION_TITLE",
        "NEXT_ACTION_REASON",
        "NEXT_ACTION_QUESTION",
        "USER_QUESTION",
    ]
    target_index: Annotated[StrictInt, Field(ge=0)] | None
    assertion_level: Literal["INFORMATION", "NEEDS_CONFIRMATION"]
    evidence_refs: Annotated[
        list[Annotated[StrictStr, Field(min_length=1)]], Field(min_length=1)
    ]


class SupervisorModelOutput(AgentSchema):
    """Provider-facing shape; runtime applies conditional invariants next."""

    decision_type: DecisionType
    selection_summary: Annotated[StrictStr, Field(min_length=1)]
    requires_human: StrictBool
    evidence_refs: Annotated[
        list[Annotated[StrictStr, Field(min_length=1)]], Field(min_length=1)
    ]
    blocker: Blocker | None
    next_action: NextActionSemantic | None
    questions_for_user: list[Annotated[StrictStr, Field(min_length=1)]]
    grounded_claims: list[GroundedClaimModelOutput]


class SupervisorSemanticDraft(AgentSchema):
    decision_type: DecisionType
    selection_summary: Annotated[StrictStr, Field(min_length=1)]
    requires_human: StrictBool
    evidence_refs: Annotated[
        list[Annotated[StrictStr, Field(min_length=1)]], Field(min_length=1)
    ]
    blocker: Blocker | None
    next_action: NextActionSemantic | None
    questions_for_user: list[Annotated[StrictStr, Field(min_length=1)]]
    grounded_claims: list[GroundedClaimSemantic]

    @model_validator(mode="after")
    def validate_variant(self) -> SupervisorSemanticDraft:
        if self.decision_type == DecisionType.ACTION:
            if self.blocker is None or self.next_action is None:
                raise ValueError("ACTION requires one blocker and one next action")
            if self.questions_for_user:
                raise ValueError("ACTION questions_for_user must be empty")
        elif self.decision_type == DecisionType.NEEDS_MORE_INFO:
            if self.blocker is None or self.next_action is not None:
                raise ValueError("NEEDS_MORE_INFO requires blocker and no action")
            if not self.requires_human or not self.questions_for_user:
                raise ValueError("NEEDS_MORE_INFO requires a human question")
        else:
            if self.blocker is not None or self.next_action is not None:
                raise ValueError("CASE_COMPLETE has no blocker or action")
            if self.requires_human or self.questions_for_user:
                raise ValueError("CASE_COMPLETE has no human question")
        return self


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SupervisorAgent:
    """Create the sole Blocker/Next Action draft and deterministic mutations."""

    def __init__(
        self,
        llm: StructuredGenerator,
        *,
        clock: Callable[[], datetime] = _now,
        uuid_factory: Callable[[], UUID] = uuid4,
        max_local_attempts: int = 3,
    ) -> None:
        if max_local_attempts < 1 or max_local_attempts > 3:
            raise ValueError("max_local_attempts must be between 1 and 3")
        self._llm = llm
        self._clock = clock
        self._uuid = uuid_factory
        self._max_local_attempts = max_local_attempts

    async def draft(self, request: SupervisorAgentInput) -> SupervisorDraft:
        source_results = request.source_results
        draft_version = request.draft_version
        review_feedback = request.review_feedback
        fact_overlays = request.fact_overlays
        previous_draft = request.previous_draft
        if not source_results:
            raise SupervisorGuardrailError("Supervisor requires component results")
        call_ids = [item.meta.call_id for item in source_results]
        if len(set(call_ids)) != len(call_ids):
            raise SupervisorGuardrailError("component call IDs must be unique")
        for source in source_results:
            if source.meta.case_id != request.case_snapshot.case_id:
                raise SupervisorGuardrailError("component case does not match snapshot")
            if source.output.based_on_snapshot_id != request.case_snapshot.snapshot_id:
                raise SupervisorGuardrailError(
                    "component result does not match the Supervisor snapshot"
                )
        self._validate_procedure_analysis_sources(source_results)
        evidence_registry = self._evidence(source_results, request)

        prompt_input = {
            "trigger": to_model_projection(request.trigger),
            "case_snapshot": to_model_projection(request.case_snapshot),
            "component_results": [
                {
                    "component": item.meta.component.value,
                    "call_id": str(item.meta.call_id),
                    "output": to_model_projection(item.output),
                }
                for item in source_results
            ],
            "review_feedback": to_model_projection(list(review_feedback)),
            "previous_draft": (
                self._previous_draft_projection(previous_draft)
                if previous_draft is not None
                else None
            ),
            "contract": {
                "action_count": 1,
                "blocker_count": 1,
                "action_questions_for_user": [],
                "needs_more_info_requires_human": True,
                "eligibility_assertion_level": "NEEDS_CONFIRMATION",
                "claim_target_kinds": [
                    "SELECTION_SUMMARY",
                    "BLOCKER_TITLE",
                    "BLOCKER_DESCRIPTION",
                    "NEXT_ACTION_TITLE",
                    "NEXT_ACTION_REASON",
                    "NEXT_ACTION_QUESTION",
                    "USER_QUESTION",
                ],
                "claim_text_and_path_are_runtime_injected": True,
                "support_eligibility_is_final": False,
                "case_complete_is_allowed": False,
                "action_target_kinds": ["PROCEDURE", "SUPPORT_PROGRAM"],
                "action_requires_exactly_one_target": True,
                "high_risk_visible_text_requires_exact_grounded_claim": [
                    "support program",
                    "amount",
                    "date or deadline",
                    "eligibility",
                    "legal",
                    "tax",
                ],
                "claim_source_rules": {
                    "procedure_or_date": ["OFFICIAL_DOCUMENT", "OFFICIAL_API"],
                    "all_other_high_risk_claims": [
                        "OFFICIAL_DOCUMENT",
                        "OFFICIAL_API",
                    ],
                    "transitive_parent_evidence_counts": True,
                },
                "allowed_evidence_refs": [
                    {
                        "evidence_ref": evidence.evidence_id,
                        "source_type": evidence.source_type.value,
                        "freshness_status": evidence.freshness_status.value,
                    }
                    for evidence in evidence_registry.values()
                ],
                "overconfident_language_is_forbidden": True,
                "runtime_injects_ids_and_timestamps": True,
                "revision": {
                    "previous_draft_is_context_only": True,
                    "address_every_blocking_review_issue": True,
                    "change_content_identified_as_defective": True,
                    "select_provenance_from_current_component_results": True,
                    "runtime_rebuilds_ids_mutations_and_call_provenance": True,
                },
            },
        }
        ensure_projection_has_no_obvious_sensitive_text(prompt_input)

        for attempt in range(1, self._max_local_attempts + 1):
            messages = supervisor_messages(prompt_input)
            if previous_draft is not None:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "This is a Review revision. Treat previous_draft only as "
                            "context: materially change or otherwise address every BLOCKING "
                            "item in review_feedback, especially each targeted field. Rebuild "
                            "the semantic draft from the current component_results and select "
                            "only their evidence IDs. Do not preserve or invent runtime IDs, "
                            "timestamps, mutations, or source call IDs; the runtime rebuilds "
                            "those and validates all selected evidence provenance."
                        ),
                    }
                )
            if attempt > 1:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "The prior draft failed deterministic contract validation. "
                            "For ACTION, return one blocker, one next_action, and an empty "
                            "questions_for_user list. For NEEDS_MORE_INFO, return a blocker, "
                            "no next_action, requires_human=true, and at least one question. "
                            "Do not return CASE_COMPLETE: bounded internet lookup cannot prove "
                            "complete procedure coverage. "
                            "Every ACTION must select exactly one canonical target. Use "
                            "target_kind=PROCEDURE with a procedure_step from an Info finding, "
                            "or target_kind=SUPPORT_PROGRAM with a support_program from a "
                            "Support check. Never mix both kinds in one action. "
                            "Every ELIGIBILITY claim must use NEEDS_CONFIRMATION. Select only "
                            "evidence_ref values listed in contract.allowed_evidence_refs; never "
                            "use a call, candidate, finding, document, or question UUID as evidence. "
                            "Select only an available grounded-claim target_kind and use a zero-based "
                            "target_index only for an existing question. For NEEDS_MORE_INFO about "
                            "missing Case facts, reuse Info question candidates, avoid eligibility "
                            "wording, and omit grounded claims that lack official evidence. Every "
                            "visible support-program name, amount, "
                            "date/deadline, eligibility, legal, or tax statement needs an exact "
                            "GroundedClaim selector backed by an allowed official document or "
                            "official API source. Never use "
                            "overconfident wording such as guaranteed or unconditional outcomes. "
                            "Use only IDs, facts, procedure references and evidence in INPUT_JSON."
                        ),
                    }
                )
            model_output = await self._llm.generate(
                SupervisorModelOutput,
                messages,
                schema_name="reborn_supervisor_draft",
            )
            try:
                semantic_payload = model_output.model_dump(mode="python")
                semantic_payload["grounded_claims"] = [
                    self._materialize_model_claim(model_output, claim)
                    for claim in model_output.grounded_claims
                ]
                semantic = SupervisorSemanticDraft.model_validate(semantic_payload)
                return self._materialize(
                    request,
                    list(source_results),
                    semantic,
                    draft_version=draft_version,
                    fact_overlays=fact_overlays,
                )
            except (GuardrailViolation, ValueError):
                continue
        fallback = self._missing_info_fallback(source_results, evidence_registry)
        if fallback is not None:
            return self._materialize(
                request,
                list(source_results),
                fallback,
                draft_version=draft_version,
                fact_overlays=fact_overlays,
            )
        raise SupervisorGuardrailError(
            "Supervisor failed deterministic provenance checks"
        ) from None

    @staticmethod
    def _missing_info_fallback(
        sources: Sequence[ReviewSourceResult],
        evidence_by_id: dict[str, EvidenceRecord],
    ) -> SupervisorSemanticDraft | None:
        """Build a conservative question-only draft after bounded model failure."""

        questions: list[str] = []
        missing_paths: set[str] = set()
        for source in sources:
            if not isinstance(source.output, InfoAnalysisResult):
                continue
            missing_paths.update(
                item.field_path.value for item in source.output.missing_fields
            )
            questions.extend(item.text for item in source.output.question_candidates)
        questions = list(dict.fromkeys(questions))
        if not questions:
            return None

        preferred_refs = [
            evidence.evidence_id
            for evidence in evidence_by_id.values()
            if evidence.source_type.value
            in {
                "USER_INPUT",
                "EXPERT_CONFIRMATION",
                "SYSTEM_RECORD",
            }
            and any(path in evidence.excerpt for path in missing_paths)
        ]
        if not preferred_refs:
            preferred_refs = [
                evidence.evidence_id
                for evidence in evidence_by_id.values()
                if evidence.source_type.value
                in {
                    "USER_INPUT",
                    "EXPERT_CONFIRMATION",
                    "SYSTEM_RECORD",
                }
            ]
        if not preferred_refs:
            return None
        evidence_refs = list(dict.fromkeys(preferred_refs))
        return SupervisorSemanticDraft(
            decision_type="NEEDS_MORE_INFO",
            selection_summary="누락된 정보를 먼저 확인해 주세요.",
            requires_human=True,
            evidence_refs=evidence_refs,
            blocker=Blocker(
                blocker_code="MISSING_CASE_INFORMATION",
                title="확인할 정보가 있습니다",
                description="입력에서 확인되지 않은 항목이 있어 다음 판단을 보류합니다.",
                evidence_refs=evidence_refs,
            ),
            next_action=None,
            questions_for_user=questions,
            grounded_claims=[],
        )

    @staticmethod
    def _previous_draft_projection(draft: SupervisorDraft) -> dict[str, Any]:
        """Expose only revision-relevant semantics, never runtime-owned fields."""

        decision = draft.decision
        next_action = None
        if decision.next_action is not None:
            next_action = {
                "action_code": decision.next_action.action_code,
                "title": decision.next_action.title,
                "reason": decision.next_action.reason,
                "questions_to_ask": list(decision.next_action.questions_to_ask),
                "target": to_model_projection(decision.next_action.target),
                "evidence_refs": list(decision.next_action.evidence_refs),
            }
        blocker = None
        if decision.blocker is not None:
            blocker = {
                "blocker_code": decision.blocker.blocker_code,
                "title": decision.blocker.title,
                "description": decision.blocker.description,
                "evidence_refs": list(decision.blocker.evidence_refs),
            }
        return {
            "decision": {
                "decision_type": decision.decision_type.value,
                "selection_summary": decision.selection_summary,
                "requires_human": decision.requires_human,
                "evidence_refs": list(decision.evidence_refs),
                "blocker": blocker,
                "next_action": next_action,
                "questions_for_user": list(decision.questions_for_user),
            },
            "grounded_claims": [
                {
                    "claim_type": claim.claim_type.value,
                    "target_path": claim.target_path,
                    "text": claim.text,
                    "assertion_level": claim.assertion_level,
                    "evidence_refs": list(claim.evidence_refs),
                }
                for claim in draft.grounded_claims
            ],
        }

    def _materialize(
        self,
        request: SupervisorAgentInput,
        sources: list[ReviewSourceResult],
        semantic: SupervisorSemanticDraft,
        *,
        draft_version: int,
        fact_overlays: Sequence[FactChangeCandidate] | None,
    ) -> SupervisorDraft:
        evidence = self._evidence(sources, request)
        known_evidence = set(evidence)
        refs = [*semantic.evidence_refs]
        if semantic.blocker is not None:
            refs.extend(semantic.blocker.evidence_refs)
        if semantic.next_action is not None:
            refs.extend(semantic.next_action.evidence_refs)
        for claim in semantic.grounded_claims:
            refs.extend(claim.evidence_refs)
        ensure_known_refs(refs, known_evidence, label="evidence")

        findings_by_step: dict[
            tuple[int, str], list[tuple[UUID, ProcedureFinding]]
        ] = {}
        for source in sources:
            if not isinstance(source.output, InfoAnalysisResult):
                continue
            for finding in source.output.procedure_findings:
                key = (
                    finding.procedure_step.procedure_step_id,
                    finding.procedure_step.step_code,
                )
                findings_by_step.setdefault(key, []).append(
                    (source.meta.call_id, finding)
                )

        target_finding: ProcedureFinding | None = None
        target_support_check: SupportCheck | None = None
        if semantic.next_action is not None:
            action = semantic.next_action
            if isinstance(action.target, ProcedureActionTarget):
                target = action.target.procedure_step
                matches = findings_by_step.get(
                    (target.procedure_step_id, target.step_code), []
                )
                if len(matches) != 1:
                    raise SupervisorGuardrailError("unknown target procedure")
                _, target_finding = matches[0]
                if target_finding.requires_confirmation and (
                    not semantic.requires_human or not action.questions_to_ask
                ):
                    raise SupervisorGuardrailError(
                        "procedure action requires an explicit confirmation question"
                    )

                support_names = {
                    check.program_name
                    for source in sources
                    if isinstance(source.output, SupportAnalysisResult)
                    for check in source.output.support_checks
                }
                combined = " ".join(
                    [
                        action.action_code,
                        action.title,
                        action.reason,
                        *action.questions_to_ask,
                    ]
                )
                procedure_labels = {
                    label
                    for matches_for_step in findings_by_step.values()
                    for _, finding in matches_for_step
                    for label in (finding.step_name, finding.procedure_step.step_code)
                }
                if (
                    any(name in combined for name in support_names)
                    or has_support_action_language(combined)
                    or references_other_known_label(
                        combined,
                        selected_labels={
                            target_finding.step_name,
                            target_finding.procedure_step.step_code,
                        },
                        known_labels=procedure_labels,
                    )
                ):
                    raise SupervisorGuardrailError(
                        "one action cannot mix multiple canonical targets"
                    )
            elif isinstance(action.target, SupportActionTarget):
                target = action.target.support_program
                matches = [
                    check
                    for source in sources
                    if isinstance(source.output, SupportAnalysisResult)
                    for check in source.output.support_checks
                    if check.support_program == target
                ]
                if len(matches) != 1:
                    raise SupervisorGuardrailError("unknown target support program")
                target_support_check = matches[0]
                if target_support_check.match_status == SupportMatchStatus.NOT_RELEVANT:
                    raise SupervisorGuardrailError(
                        "a not-relevant support program cannot be the next action target"
                    )
                if not target_support_check.evidence_refs:
                    raise SupervisorGuardrailError(
                        "support action target requires source evidence"
                    )
                if not semantic.requires_human or not action.questions_to_ask:
                    raise SupervisorGuardrailError(
                        "support action requires an explicit confirmation question"
                    )
                cleaned_values = [
                    value.replace(target_support_check.program_name, " ")
                    for value in (
                        action.action_code,
                        action.title,
                        action.reason,
                        *action.questions_to_ask,
                    )
                ]
                support_names = {
                    check.program_name
                    for source in sources
                    if isinstance(source.output, SupportAnalysisResult)
                    for check in source.output.support_checks
                }
                procedure_labels = {
                    label
                    for matches_for_step in findings_by_step.values()
                    for _, finding in matches_for_step
                    for label in (finding.step_name, finding.procedure_step.step_code)
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
                        selected_labels={target_support_check.program_name},
                        known_labels=support_names,
                    )
                    or any(label in cleaned_text for label in procedure_labels)
                ):
                    raise SupervisorGuardrailError(
                        "one action cannot mix multiple canonical targets"
                    )
            else:  # pragma: no cover - discriminated schema makes this unreachable
                raise SupervisorGuardrailError("unknown next-action target kind")

        now = self._clock()
        call_ids = [item.meta.call_id for item in sources]
        common = {
            "draft_id": self._uuid(),
            "draft_version": draft_version,
            "selection_summary": semantic.selection_summary,
            "requires_human": semantic.requires_human,
            "evidence_refs": semantic.evidence_refs,
            "based_on_call_ids": call_ids,
            "created_at": now,
        }
        if semantic.decision_type == DecisionType.ACTION:
            assert semantic.blocker is not None and semantic.next_action is not None
            action_values = semantic.next_action.model_dump(mode="python")
            target_evidence_refs: list[str] = []
            if target_finding is not None:
                target_evidence_refs.extend(target_finding.evidence_refs)
            if target_support_check is not None:
                target_evidence_refs.extend(target_support_check.evidence_refs)
            if target_evidence_refs:
                action_values["evidence_refs"] = list(
                    dict.fromkeys(
                        [
                            *action_values["evidence_refs"],
                            *target_evidence_refs,
                        ]
                    )
                )
            action = NextAction(
                sequence=1,
                **action_values,
            )
            decision = ActionDecisionDraft(
                decision_type=DecisionType.ACTION,
                blocker=semantic.blocker,
                next_action=action,
                questions_for_user=[],
                **common,
            )
        elif semantic.decision_type == DecisionType.NEEDS_MORE_INFO:
            assert semantic.blocker is not None
            decision = NeedsMoreInfoDecisionDraft(
                decision_type=DecisionType.NEEDS_MORE_INFO,
                blocker=semantic.blocker,
                next_action=None,
                questions_for_user=semantic.questions_for_user,
                **common,
            )
        else:
            self._ensure_complete_is_supported(request, sources)
            decision = CaseCompleteDecisionDraft(
                decision_type=DecisionType.CASE_COMPLETE,
                blocker=None,
                next_action=None,
                questions_for_user=[],
                **common,
            )

        mutations = self._build_mutations(
            request,
            sources,
            decision,
            fact_overlays=fact_overlays,
        )
        grounded_claims = [
            GroundedClaim(claim_id=self._uuid(), **item.model_dump(mode="python"))
            for item in semantic.grounded_claims
        ]
        draft = SupervisorDraft(
            decision=decision,
            mutations=mutations,
            grounded_claims=grounded_claims,
            source_call_ids=call_ids,
        )
        self._validate_claim_targets(draft)
        self._validate_pre_review_claim_safety(draft, evidence, sources)
        ensure_no_sensitive_text(self._free_text(draft))
        return draft

    @staticmethod
    def _validate_pre_review_claim_safety(
        draft: SupervisorDraft,
        evidence_by_id: dict[str, EvidenceRecord],
        sources: Sequence[ReviewSourceResult],
    ) -> None:
        """Reject drafts that deterministic Review would block for claim safety."""

        support_program_names = frozenset(
            check.program_name
            for source in sources
            if isinstance(source.output, SupportAnalysisResult)
            for check in source.output.support_checks
        )
        visible_strings = dict(SupervisorAgent._visible_draft_strings(draft))

        for text in visible_strings.values():
            if is_overconfident(text):
                raise SupervisorGuardrailError(
                    "overconfident language is not allowed in a Supervisor draft"
                )

        for claim in draft.grounded_claims:
            expanded = expand_evidence(
                [evidence_by_id[ref] for ref in claim.evidence_refs],
                evidence_by_id,
            )
            has_non_current_evidence = any(
                item.freshness_status != "CURRENT" for item in expanded
            )
            if has_non_current_evidence:
                if claim.assertion_level == "INFORMATION":
                    raise SupervisorGuardrailError(
                        "non-current evidence cannot support an information assertion"
                    )
                if not has_confirmation_caveat(claim.text):
                    raise SupervisorGuardrailError(
                        "non-current evidence requires an explicit confirmation caveat"
                    )
            allowed_sources = required_sources_for_claim(claim.claim_type)
            if not any(item.source_type in allowed_sources for item in expanded):
                raise SupervisorGuardrailError(
                    "grounded claim lacks an allowed authoritative source"
                )

        claim_keys = {
            (claim.target_path, claim.text, claim.claim_type)
            for claim in draft.grounded_claims
        }
        for path, text in visible_strings.items():
            risk_types, _ = high_risk_metadata(text, support_program_names)
            matching_claims = [
                claim
                for claim in draft.grounded_claims
                if claim.target_path == path and claim.text == text
            ]
            if has_explicit_eligibility_language(text) and not any(
                claim.claim_type == ClaimType.ELIGIBILITY
                and claim.assertion_level == "NEEDS_CONFIRMATION"
                for claim in matching_claims
            ):
                raise SupervisorGuardrailError(
                    "explicit eligibility language requires a confirmation-only "
                    "ELIGIBILITY claim"
                )
            if risk_types and not any(
                (path, text, claim_type) in claim_keys for claim_type in risk_types
            ):
                raise SupervisorGuardrailError(
                    "high-risk visible text requires an exact grounded claim"
                )

    def _build_mutations(
        self,
        request: SupervisorAgentInput,
        sources: list[ReviewSourceResult],
        decision: ActionDecisionDraft
        | NeedsMoreInfoDecisionDraft
        | CaseCompleteDecisionDraft,
        *,
        fact_overlays: Sequence[FactChangeCandidate] | None,
    ) -> MutationSet:
        snapshot = request.case_snapshot
        progress = {
            (
                item.procedure_step.procedure_step_id,
                item.procedure_step.step_code,
            ): item
            for item in snapshot.procedure_progress
        }
        fact_changes: list[FactChangeCandidate] = list(fact_overlays or [])
        progress_changes: list[ProcedureProgressChangeCandidate] = []
        support_updates: list[SupportMatchUpdateCandidate] = []
        for source in sources:
            output = source.output
            if isinstance(output, InfoAnalysisResult):
                if fact_overlays is None:
                    fact_changes.extend(
                        build_fact_overlays(
                            snapshot,
                            output,
                            source.meta.call_id,
                            uuid_factory=self._uuid,
                        )
                    )
                findings = {
                    (
                        finding.procedure_step.procedure_step_id,
                        finding.procedure_step.step_code,
                    ): finding
                    for finding in output.procedure_findings
                }
                for observation in output.procedure_progress_observations:
                    key = (
                        observation.procedure_step.procedure_step_id,
                        observation.procedure_step.step_code,
                    )
                    finding = findings.get(key)
                    if observation.requires_confirmation or finding is None:
                        continue
                    prior = progress.get(key)
                    before_status = prior.status if prior else None
                    if finding.current_status != before_status:
                        raise SupervisorGuardrailError(
                            "procedure finding current status differs from snapshot"
                        )
                    if before_status == observation.observed_status:
                        continue
                    progress_changes.append(
                        ProcedureProgressChangeCandidate(
                            candidate_id=self._uuid(),
                            procedure_step=observation.procedure_step,
                            before_status=before_status,
                            proposed_status=observation.observed_status,
                            reason_summary=observation.reason_summary,
                            execution_evidence_refs=observation.source_evidence_refs,
                            procedure_analysis_call_id=source.meta.call_id,
                        )
                    )
            elif isinstance(output, SupportAnalysisResult):
                support_updates.extend(
                    SupportMatchUpdateCandidate(
                        candidate_id=self._uuid(),
                        support_check=check,
                        source_call_id=source.meta.call_id,
                    )
                    for check in output.support_checks
                )

        status_change = None
        if decision.decision_type == DecisionType.CASE_COMPLETE:
            status_change = CaseStatusChangeCandidate(
                candidate_id=self._uuid(),
                before_status=CaseStatus.IN_PROGRESS,
                proposed_status=CaseStatus.COMPLETED,
                reason_summary=decision.selection_summary,
                evidence_refs=decision.evidence_refs,
            )
        return MutationSet(
            fact_changes=fact_changes,
            procedure_progress_changes=progress_changes,
            support_match_updates=support_updates,
            case_status_change=status_change,
        )

    @staticmethod
    def _evidence(
        sources: Sequence[ReviewSourceResult],
        request: SupervisorAgentInput,
    ) -> dict[str, EvidenceRecord]:
        records = [*request.case_snapshot.evidence_records]
        for source in sources:
            records.extend(source.output.evidence_records)
        result: dict[str, EvidenceRecord] = {}
        for record in records:
            existing = result.get(record.evidence_id)
            if existing is not None and existing != record:
                raise SupervisorGuardrailError("evidence ID collision")
            result[record.evidence_id] = record
        return result

    @staticmethod
    def _validate_procedure_analysis_sources(
        sources: Sequence[ReviewSourceResult],
    ) -> None:
        """Bind every Info procedure interpretation to one raw lookup result."""

        sources_by_call_id = {source.meta.call_id: source for source in sources}
        for source in sources:
            if not isinstance(source.output, InfoAnalysisResult):
                continue
            info = source.output
            lookup_source = sources_by_call_id.get(
                info.based_on_procedure_lookup_call_id
            )
            if lookup_source is None or not isinstance(
                lookup_source.output, ProcedureLookupResult
            ):
                raise SupervisorGuardrailError(
                    "Info result references an unknown procedure lookup"
                )
            if info.based_on_procedure_lookup_digest != lookup_source.output_digest:
                raise SupervisorGuardrailError(
                    "Info result procedure lookup digest does not match"
                )

            lookup_evidence = {
                record.evidence_id: record
                for record in lookup_source.output.evidence_records
            }
            for finding in info.procedure_findings:
                for evidence_ref in finding.evidence_refs:
                    if evidence_ref not in lookup_evidence:
                        raise SupervisorGuardrailError(
                            "procedure finding evidence is not from its raw lookup"
                        )

    @staticmethod
    def _ensure_complete_is_supported(
        request: SupervisorAgentInput,
        sources: Sequence[ReviewSourceResult],
    ) -> None:
        del request, sources
        raise SupervisorGuardrailError(
            "CASE_COMPLETE is unavailable without authoritative procedure coverage"
        )

    @staticmethod
    def _validate_claim_targets(draft: SupervisorDraft) -> None:
        root = {"supervisor_draft": draft.model_dump(mode="json")}
        for claim in draft.grounded_claims:
            current: Any = root
            for raw_token in claim.target_path.lstrip("/").split("/"):
                token = raw_token.replace("~1", "/").replace("~0", "~")
                if isinstance(current, dict) and token in current:
                    current = current[token]
                elif (
                    isinstance(current, list)
                    and token.isdigit()
                    and int(token) < len(current)
                ):
                    current = current[int(token)]
                else:
                    raise SupervisorGuardrailError(
                        "grounded claim target does not exist"
                    )
            if not isinstance(current, str) or current != claim.text:
                raise SupervisorGuardrailError(
                    "grounded claim text must exactly match its target"
                )

    @staticmethod
    def _materialize_model_claim(
        output: SupervisorModelOutput,
        claim: GroundedClaimModelOutput,
    ) -> dict[str, Any]:
        """Resolve a constrained selector to a runtime-owned path and exact text."""

        base = "/supervisor_draft/decision"
        scalar_targets: dict[str, tuple[str, str] | None] = {
            "SELECTION_SUMMARY": (
                f"{base}/selection_summary",
                output.selection_summary,
            ),
            "BLOCKER_TITLE": (
                (f"{base}/blocker/title", output.blocker.title)
                if output.blocker is not None
                else None
            ),
            "BLOCKER_DESCRIPTION": (
                (f"{base}/blocker/description", output.blocker.description)
                if output.blocker is not None
                else None
            ),
            "NEXT_ACTION_TITLE": (
                (f"{base}/next_action/title", output.next_action.title)
                if output.next_action is not None
                else None
            ),
            "NEXT_ACTION_REASON": (
                (f"{base}/next_action/reason", output.next_action.reason)
                if output.next_action is not None
                else None
            ),
        }
        resolved = scalar_targets.get(claim.target_kind)
        if resolved is not None:
            if claim.target_index is not None:
                raise SupervisorGuardrailError(
                    "scalar grounded-claim target must not include an index"
                )
            target_path, text = resolved
        else:
            if claim.target_kind == "NEXT_ACTION_QUESTION":
                questions = (
                    output.next_action.questions_to_ask
                    if output.next_action is not None
                    else []
                )
                path_prefix = f"{base}/next_action/questions_to_ask"
            elif claim.target_kind == "USER_QUESTION":
                questions = output.questions_for_user
                path_prefix = f"{base}/questions_for_user"
            else:
                raise SupervisorGuardrailError("grounded-claim target is unavailable")
            if claim.target_index is None or claim.target_index >= len(questions):
                raise SupervisorGuardrailError(
                    "grounded-claim question index is unavailable"
                )
            target_path = f"{path_prefix}/{claim.target_index}"
            text = questions[claim.target_index]
        return {
            "claim_type": claim.claim_type,
            "target_path": target_path,
            "text": text,
            "assertion_level": claim.assertion_level,
            "evidence_refs": claim.evidence_refs,
        }

    @staticmethod
    def _free_text(draft: SupervisorDraft) -> list[str]:
        decision = draft.decision
        values = [decision.selection_summary]
        if decision.blocker is not None:
            values.extend([decision.blocker.title, decision.blocker.description])
        if decision.next_action is not None:
            values.extend(
                [
                    decision.next_action.title,
                    decision.next_action.reason,
                    *decision.next_action.questions_to_ask,
                ]
            )
        values.extend(decision.questions_for_user)
        values.extend(item.text for item in draft.grounded_claims)
        return values

    @staticmethod
    def _visible_draft_strings(draft: SupervisorDraft) -> list[tuple[str, str]]:
        decision = draft.decision
        base = "/supervisor_draft/decision"
        values = [(f"{base}/selection_summary", decision.selection_summary)]
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


__all__ = [
    "GroundedClaimSemantic",
    "NextActionSemantic",
    "SupervisorAgent",
    "SupervisorGuardrailError",
    "SupervisorModelOutput",
    "SupervisorSemanticDraft",
]
