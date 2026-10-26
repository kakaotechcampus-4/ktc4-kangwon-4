"""Supervisor decision drafting over validated, read-only component results."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import Field, StrictBool, StrictStr, model_validator

from app.agent import completion
from app.agent.action_catalog import (
    ProcedureBindings,
    build_action_candidates,
    effective_procedure_progress,
    resolve_procedure_bindings,
)
from app.agent.blocker_candidates import (
    build_blocker_candidates,
    candidate_decision_fields,
    candidate_decision_violations,
    missing_info_fields,
    resolved_blocker_candidates,
)
from app.agent.claim_safety import (
    REQUIRED_CLAIM_SOURCES,
    expand_evidence,
    high_risk_metadata,
)
from app.agent.enrichment import build_fact_overlays, evidence_records_equal
from app.agent.guardrails import (
    GuardrailViolation,
    ensure_known_refs,
    ensure_no_sensitive_text,
)
from app.agent.llm import LLMClientError
from app.agent.procedure_tool.rules import (
    procedure_constraints,
    procedure_plan_constraints,
)
from app.agent.projection import (
    ensure_projection_has_no_obvious_sensitive_text,
    to_model_projection,
)
from app.agent.prompts import supervisor_messages
from app.agent.schemas import (
    ActionCode,
    ActionDecisionDraft,
    AgentSchema,
    Blocker,
    ClaimType,
    CompletedDecisionDraft,
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
    ProcedureProgressStatus,
    ReviewSourceResult,
    SourcedText,
    SupervisorAgentInput,
    SupervisorDraft,
    SupportActionTarget,
    SupportAnalysisResult,
    SupportCheck,
    SupportMatchStatus,
)


class StructuredGenerator(Protocol):
    async def generate(
        self,
        response_model: type[AgentSchema],
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AgentSchema: ...


class SupervisorGuardrailError(GuardrailViolation):
    """Raised when a Supervisor draft references data it did not receive."""


class ProcedureBindingConfigurationError(RuntimeError):
    """Official documents are available but no procedure mapping is configured."""


class NextActionSemantic(AgentSchema):
    action_code: ActionCode
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


class SupervisorModelOutput(AgentSchema):
    """Select a verified candidate; runtime owns its text, target and evidence."""

    decision_type: DecisionType
    blocker_candidate_id: StrictStr | None = None
    action_code: ActionCode | None


class SupervisorSemanticDraft(AgentSchema):
    decision_type: DecisionType
    selection_summary: Annotated[StrictStr, Field(min_length=1)]
    requires_human: StrictBool
    evidence_refs: Annotated[
        list[Annotated[StrictStr, Field(min_length=1)]], Field(min_length=1)
    ]
    blocker: Blocker | None
    blockers: list[Blocker]
    next_action: NextActionSemantic | None
    questions_for_user: list[Annotated[StrictStr, Field(min_length=1)]]
    grounded_claims: list[GroundedClaimSemantic]
    followup_guidance: list[SourcedText] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_variant(self) -> SupervisorSemanticDraft:
        if self.decision_type == DecisionType.COMPLETED:
            if self.blocker is not None or self.blockers or self.next_action is not None or self.questions_for_user:
                raise ValueError("COMPLETED cannot contain a blocker, action or questions")
            if not self.followup_guidance:
                raise ValueError("COMPLETED requires grounded follow-up guidance")
            return self
        if self.blocker is None or self.blocker not in self.blockers:
            raise ValueError("an unfinished decision requires its primary blocker in blockers")
        if self.decision_type == DecisionType.ACTION:
            if self.next_action is None:
                raise ValueError("ACTION requires one next action")
            if self.questions_for_user:
                raise ValueError("ACTION questions_for_user must be empty")
        elif self.decision_type == DecisionType.NEEDS_MORE_INFO:
            if self.blocker is None or self.next_action is not None:
                raise ValueError("NEEDS_MORE_INFO requires blocker and no action")
            if not self.requires_human or not self.questions_for_user:
                raise ValueError("NEEDS_MORE_INFO requires a human question")
        return self


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SupervisorAgent:
    """Return every verified Blocker and preserve the model's valid priority."""

    def __init__(
        self,
        llm: StructuredGenerator,
        *,
        procedure_bindings: ProcedureBindings | None = None,
        clock: Callable[[], datetime] = _now,
        uuid_factory: Callable[[], UUID] = uuid4,
        max_local_attempts: int = 3,
    ) -> None:
        if max_local_attempts < 1 or max_local_attempts > 3:
            raise ValueError("max_local_attempts must be between 1 and 3")
        self._llm = llm
        self._procedure_bindings = (
            None if procedure_bindings is None else {
                key: reference.model_copy(deep=True)
                for key, reference in procedure_bindings.items()
            }
        )
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
        if fact_overlays is None:
            fact_overlays = [
                candidate
                for source in source_results
                if isinstance(source.output, InfoAnalysisResult)
                for candidate in build_fact_overlays(
                    request.case_snapshot,
                    source.output,
                    source.meta.call_id,
                    uuid_factory=self._uuid,
                )
            ]
        mutations = self._build_mutations(
            request, list(source_results), fact_overlays=fact_overlays
        )
        evidence_registry = self._evidence(source_results, request)
        bindings = self._bindings(request)
        completion_candidate = completion.completion_fields(
            request, mutations, evidence_registry, bindings
        )
        blocker_candidates = build_blocker_candidates(
            request.case_snapshot,
            request.known_procedure_steps,
            source_results,
            mutations,
            evidence_registry,
            bindings,
        )
        if (
            not blocker_candidates
            and not bindings
            and any(
                isinstance(source.output, ProcedureLookupResult) and source.output.documents
                for source in source_results
            )
        ):
            raise ProcedureBindingConfigurationError(
                "Reviewed documents require a configured procedure mapping"
            )
        action_candidates = [
            action
            for candidate in blocker_candidates
            for action in candidate["actions"]
        ]
        information_fields = missing_info_fields(
            request.case_snapshot, source_results, mutations, bindings,
            known_procedure_steps=request.known_procedure_steps,
        )
        information_blockers = information_fields["blockers"] if information_fields else []
        prompt_input = {
            "trigger": to_model_projection(request.trigger),
            "case_snapshot": to_model_projection(request.case_snapshot),
            "fact_overlays": to_model_projection(list(fact_overlays or [])),
            "known_procedure_steps": to_model_projection(request.known_procedure_steps),
            "procedure_constraints": [
                {
                    "procedure_step": step.procedure_step.model_dump(mode="json"),
                    "blocking_reasons": procedure_constraints(
                        step,
                        request.case_snapshot,
                        mutations.fact_changes,
                        mutations.procedure_progress_changes,
                        known_steps=request.known_procedure_steps,
                        procedure_bindings=bindings,
                    ),
                }
                for step in request.known_procedure_steps
            ],
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
                "allowed_decision_types": ["COMPLETED"] if completion_candidate is not None else ["ACTION", "NEEDS_MORE_INFO"],
                "action_count": {"ACTION": 1, "NEEDS_MORE_INFO": 0, "COMPLETED": 0},
                "primary_blocker_count": {"ACTION": 1, "NEEDS_MORE_INFO": 1, "COMPLETED": 0},
                "blocker_count": {"ACTION": {"minimum": 1}, "NEEDS_MORE_INFO": {"minimum": 1}, "COMPLETED": {"exactly": 0}},
                "completion_candidate": completion_candidate,
                "allowed_actions": action_candidates,
                "blocker_candidates": blocker_candidates,
                "information_blockers": information_blockers,
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
                            "This is a Review revision. Use previous_draft only as context. "
                            "Address blocking review_feedback by selecting a valid current "
                            "candidate and action. The runtime rebuilds all text, targets, "
                            "evidence and mutations from the selected candidate; do not "
                            "invent replacements for rejected source content."
                        ),
                    }
                )
            if attempt > 1:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "The prior selection failed contract validation. "
                            "If contract.completion_candidate is present, select COMPLETED "
                            "with blocker_candidate_id=null and action_code=null. "
                            "Otherwise COMPLETED is forbidden. For ACTION, select one "
                            "blocker_candidate_id and an action_code from that candidate's "
                            "actions. For NEEDS_MORE_INFO, select an information_blockers "
                            "candidate_id and action_code=null. Return only these three fields."
                        ),
                    }
                )
            try:
                model_output = await self._llm.generate(
                    SupervisorModelOutput,
                    messages,
                    schema_name="reborn_supervisor_draft",
                    # ponytail: no temperature=0 here -- the configured Supervisor
                    # model (see SUPERVISOR_MODEL) rejects any non-default value
                    # with HTTP 400 ("Only the default (1) value is supported"),
                    # confirmed against the real provider 2026-09-23. `seed` was
                    # tried too and does not help either -- confirmed against the
                    # real provider 2026-09-23 with an identical prompt + seed
                    # producing a different decision_type on replay. Supervisor
                    # has no sampling-level determinism guarantee. Runtime reuse
                    # separately checks the full request, evidence and configuration.
                    enum_constraints={
                        "decision_type": prompt_input["contract"]["allowed_decision_types"],
                        "action_code": [
                            action["action_code"] for action in action_candidates
                        ],
                        "blocker_candidate_id": [
                            item["candidate_id"] for item in blocker_candidates
                        ] + [item["candidate_id"] for item in information_blockers],
                    },
                )
                semantic = self._candidate_semantic(
                    model_output,
                    blocker_candidates,
                    request,
                    mutations,
                )
                return self._materialize(
                    request,
                    list(source_results),
                    semantic,
                    draft_version=draft_version,
                    mutations=mutations,
                )
            except LLMClientError:
                # The shared client already bounded provider retries. Never invent a plan.
                raise
            except (GuardrailViolation, ValueError):
                continue
        raise SupervisorGuardrailError(
            "Supervisor failed deterministic provenance checks"
        ) from None

    def _bindings(self, request: SupervisorAgentInput) -> ProcedureBindings:
        return resolve_procedure_bindings(
            request.known_procedure_steps, self._procedure_bindings
        )

    def _candidate_semantic(
        self,
        output: SupervisorModelOutput,
        candidates: list[dict[str, Any]],
        request: SupervisorAgentInput,
        mutations: MutationSet,
    ) -> SupervisorSemanticDraft:
        completed_fields = completion.completion_fields(
            request, mutations, self._evidence(request.source_results, request), self._bindings(request),
        )
        if output.decision_type == DecisionType.COMPLETED:
            if (
                completed_fields is None or output.blocker_candidate_id is not None
                or output.action_code is not None
            ):
                raise SupervisorGuardrailError(
                    "completion requires an available candidate and no blocker or action selection"
                )
            return SupervisorSemanticDraft(
                **completed_fields, grounded_claims=self._completion_claims(completed_fields),
            )
        if completed_fields is not None:
            raise SupervisorGuardrailError("select COMPLETED explicitly for the completion candidate")
        information = missing_info_fields(
            request.case_snapshot, request.source_results, mutations, self._bindings(request),
            selected_candidate_id=output.blocker_candidate_id if output.decision_type == DecisionType.NEEDS_MORE_INFO else None,
            known_procedure_steps=request.known_procedure_steps,
        )
        if output.decision_type == DecisionType.NEEDS_MORE_INFO:
            if output.action_code is not None or information is None or output.blocker_candidate_id is None and len(information["blockers"]) > 1:
                raise SupervisorGuardrailError("select one available information blocker")
            fields = information
        else:
            candidate = next((item for item in candidates if item["candidate_id"] == output.blocker_candidate_id), None)
            action = next((item for item in candidate["actions"] if item["action_code"] == output.action_code), None) if candidate else None
            if action is None:
                raise SupervisorGuardrailError("Supervisor must select an available candidate and one of its actions")
            fields = candidate_decision_fields(candidate, output.action_code, action["target"])
        fields["blockers"] = [item["blocker"] for item in candidates] + (information["blockers"] if information else [])
        return SupervisorSemanticDraft(**fields, grounded_claims=self._candidate_claims(request, fields))

    @staticmethod
    def _completion_claims(fields: dict[str, Any]) -> list[GroundedClaimSemantic]:
        base = "/supervisor_draft/decision"
        items = [(f"{base}/selection_summary", fields["selection_summary"], fields["evidence_refs"])]
        items.extend((f"{base}/followup_guidance/{index}/text", item["text"], item["evidence_refs"])
                     for index, item in enumerate(fields.get("followup_guidance", [])))
        return [GroundedClaimSemantic(claim_type=ClaimType.TAX, target_path=path,
                    text=text, assertion_level="NEEDS_CONFIRMATION", evidence_refs=refs)
                for path, text, refs in items]

    @staticmethod
    def _candidate_claims(request, fields) -> list[GroundedClaimSemantic]:
        base = "/supervisor_draft/decision"
        texts = {
            f"{base}/blockers/{index}/description": (item["description"], item["evidence_refs"])
            for index, item in enumerate(fields["blockers"])
            if item["candidate_id"].startswith("procedure:")
        }
        if fields["next_action"] is not None:
            action = fields["next_action"]
            texts.update({
                f"{base}/selection_summary": (fields["selection_summary"], fields["evidence_refs"]),
                f"{base}/blocker/description": (fields["blocker"]["description"], fields["blocker"]["evidence_refs"]),
                f"{base}/next_action/title": (action["title"], action["evidence_refs"]),
                f"{base}/next_action/reason": (action["reason"], action["evidence_refs"]),
                **{f"{base}/next_action/questions_to_ask/{index}": (text, action["evidence_refs"])
                   for index, text in enumerate(action["questions_to_ask"])},
            })
        claims = []
        for path, (text, refs) in texts.items():
            kinds, _ = high_risk_metadata(text, frozenset())
            claim_type = next(
                (kind for kind in (
                    ClaimType.ELIGIBILITY, ClaimType.TAX, ClaimType.DATE_OR_DEADLINE,
                    ClaimType.AMOUNT, ClaimType.LEGAL,
                ) if kind in kinds),
                ClaimType.PROCEDURE,
            )
            claims.append(GroundedClaimSemantic(
                claim_type=claim_type, target_path=path, text=text,
                assertion_level="NEEDS_CONFIRMATION", evidence_refs=refs,
            ))
        return claims


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
        blocker = (
            {
                "description": decision.blocker.description,
                "evidence_refs": list(decision.blocker.evidence_refs),
            }
            if decision.blocker is not None
            else None
        )
        return {
            "decision": {
                "decision_type": decision.decision_type.value,
                "selection_summary": decision.selection_summary,
                "requires_human": decision.requires_human,
                "evidence_refs": list(decision.evidence_refs),
                "blocker": blocker,
                "blockers": [item.model_dump(mode="json") for item in decision.blockers],
                "next_action": next_action,
                "questions_for_user": list(decision.questions_for_user),
                "followup_guidance": [
                    item.model_dump(mode="json")
                    for item in getattr(decision, "followup_guidance", [])
                ],
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
        mutations: MutationSet,
    ) -> SupervisorDraft:
        evidence = self._evidence(sources, request)
        known_evidence = set(evidence)
        refs = [*semantic.evidence_refs, *(ref for item in semantic.blockers for ref in item.evidence_refs)]
        if semantic.next_action is not None:
            refs.extend(semantic.next_action.evidence_refs)
        for claim in semantic.grounded_claims:
            refs.extend(claim.evidence_refs)
        refs.extend(
            ref for item in semantic.followup_guidance for ref in item.evidence_refs
        )
        ensure_known_refs(refs, known_evidence, label="evidence")

        selected_action = None
        if semantic.next_action is not None:
            action = semantic.next_action
            selected_action = next(
                (
                    candidate
                    for candidate in build_action_candidates(
                        sources,
                        evidence,
                        self._bindings(request),
                        procedure_progress=effective_procedure_progress(
                            request.case_snapshot, mutations,
                            known_steps=request.known_procedure_steps,
                            procedure_bindings=self._bindings(request),
                        ),
                    )
                    if candidate["action_code"] == action.action_code
                    and candidate["target"] == action.target.model_dump(mode="json")
                ),
                None,
            )
            if selected_action is None:
                raise SupervisorGuardrailError(
                    "action code and target are not an allowed action"
                )

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
            "blockers": semantic.blockers,
        }
        if semantic.decision_type == DecisionType.ACTION:
            assert semantic.next_action is not None
            action_values = semantic.next_action.model_dump(mode="python")
            assert selected_action is not None
            action_values["action_code"] = selected_action["action_code"]
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
        elif semantic.decision_type == DecisionType.COMPLETED:
            decision = CompletedDecisionDraft(
                decision_type=DecisionType.COMPLETED,
                blocker=None,
                next_action=None,
                questions_for_user=[],
                followup_guidance=semantic.followup_guidance,
                **common,
            )
        else:
            decision = NeedsMoreInfoDecisionDraft(
                decision_type=DecisionType.NEEDS_MORE_INFO,
                blocker=semantic.blocker,
                next_action=None,
                questions_for_user=semantic.questions_for_user,
                **common,
            )

        violations = procedure_plan_constraints(
            request.known_procedure_steps, request.case_snapshot, mutations, decision,
            procedure_bindings=self._bindings(request),
        )
        if semantic.decision_type != DecisionType.COMPLETED:
            violations.extend(
                candidate_decision_violations(
                    decision,
                    build_blocker_candidates(
                        request.case_snapshot,
                        request.known_procedure_steps,
                        sources,
                        mutations,
                        evidence,
                        self._bindings(request),
                    ),
                    missing_info_fields(
                        request.case_snapshot,
                        sources,
                        mutations,
                        self._bindings(request),
                        known_procedure_steps=request.known_procedure_steps,
                    ),
                )
            )
        if violations:
            raise SupervisorGuardrailError(
                "procedure master rules block this plan: "
                + "; ".join(reason for _, reason in violations)
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
            resolved_blocker_candidate_ids=resolved_blocker_candidates(
                request.case_snapshot, request.known_procedure_steps, mutations, self._bindings(request),
                sources=sources,
            ),
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

        for claim in draft.grounded_claims:
            expanded = expand_evidence(
                [evidence_by_id[ref] for ref in claim.evidence_refs],
                evidence_by_id,
            )
            has_non_current_evidence = any(
                item.freshness_status != "CURRENT" for item in expanded
            )
            if has_non_current_evidence and claim.assertion_level == "INFORMATION":
                raise SupervisorGuardrailError(
                    "non-current evidence cannot support an information assertion"
                )
            allowed_sources = REQUIRED_CLAIM_SOURCES
            if not any(item.source_type in allowed_sources for item in expanded):
                raise SupervisorGuardrailError(
                    "grounded claim lacks an allowed authoritative source"
                )

    def _build_mutations(
        self,
        request: SupervisorAgentInput,
        sources: list[ReviewSourceResult],
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
                    before_status = (
                        prior.status if prior else ProcedureProgressStatus.NOT_STARTED
                    )
                    if finding.current_status != before_status:
                        raise SupervisorGuardrailError(
                            "procedure finding current status differs from snapshot"
                        )
                    before_requirements = (
                        prior.requirements_confirmed if prior else False
                    )
                    before_submitted = prior.submitted if prior else False
                    proposed_requirements = (
                        before_requirements or observation.requirements_confirmed
                    )
                    proposed_submitted = before_submitted or observation.submitted
                    if (
                        before_status == observation.observed_status
                        and before_requirements == proposed_requirements
                        and before_submitted == proposed_submitted
                    ):
                        continue
                    progress_changes.append(
                        ProcedureProgressChangeCandidate(
                            candidate_id=self._uuid(),
                            procedure_step=observation.procedure_step,
                            before_status=before_status,
                            proposed_status=observation.observed_status,
                            before_requirements_confirmed=before_requirements,
                            proposed_requirements_confirmed=proposed_requirements,
                            before_submitted=before_submitted,
                            proposed_submitted=proposed_submitted,
                            reason_summary=observation.reason_summary,
                            execution_evidence_refs=observation.source_evidence_refs,
                            procedure_analysis_call_id=source.meta.call_id,
                        )
                    )

        return MutationSet(
            fact_changes=fact_changes,
            procedure_progress_changes=progress_changes,
            support_match_updates=[],
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
            if existing is not None and not evidence_records_equal(existing, record):
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
    def _free_text(draft: SupervisorDraft) -> list[str]:
        decision = draft.decision
        values = [decision.selection_summary, *(item.description for item in decision.blockers)]
        if decision.next_action is not None:
            values.extend(
                [
                    decision.next_action.title,
                    decision.next_action.reason,
                    *decision.next_action.questions_to_ask,
                ]
            )
        values.extend(decision.questions_for_user)
        values.extend(item.text for item in getattr(decision, "followup_guidance", []))
        values.extend(item.text for item in draft.grounded_claims)
        return values


    @staticmethod
    def _visible_draft_strings(draft: SupervisorDraft) -> list[tuple[str, str]]:
        decision = draft.decision
        base = "/supervisor_draft/decision"
        values = [
            (f"{base}/selection_summary", decision.selection_summary),
            *((f"{base}/blockers/{index}/description", item.description) for index, item in enumerate(decision.blockers)),
        ]
        if decision.blocker is not None:
            values.append((f"{base}/blocker/description", decision.blocker.description))
        values.extend(
            (f"{base}/followup_guidance/{index}/text", item.text)
            for index, item in enumerate(getattr(decision, "followup_guidance", []))
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
