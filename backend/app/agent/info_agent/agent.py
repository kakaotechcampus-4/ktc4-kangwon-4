"""Grounded extraction of closure-case facts from one redacted input."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID, uuid4

from app.agent.guardrails import (
    GuardrailViolation,
    ensure_no_sensitive_text,
    exact_span,
)
from app.agent.projection import ensure_projection_has_no_obvious_sensitive_text
from app.agent.prompts import info_messages
from app.agent.schemas import (
    CASE_FIELD_SPECS,
    AgentSchema,
    CaseFieldKey,
    ConflictCandidate,
    EvidenceRecord,
    FactCandidate,
    FactOperation,
    FactStatus,
    FactValueType,
    InfoAnalysisInput,
    InfoAnalysisResult,
    InfoCompletionStatus,
    MissingField,
    MissingFieldBlock,
    NonNullStrictScalar,
    ProcedureProgressObservation,
    ProcedureProgressStatus,
    QuestionCandidate,
    StrictScalar,
    Uncertainty,
    VerifiedTextSpan,
    validate_case_field_value,
)
from pydantic import (
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)


class StructuredGenerator(Protocol):
    async def generate(
        self,
        response_model: type[AgentSchema],
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AgentSchema: ...


class InfoAnalysisGuardrailError(GuardrailViolation):
    """Raised when a syntactically valid model result is not grounded."""


class ExtractedFactDraft(AgentSchema):
    operation: FactOperation
    field_path: CaseFieldKey
    value_type: FactValueType
    value: StrictScalar
    source_text: Annotated[StrictStr, Field(min_length=1)]
    confidence_bps: Annotated[StrictInt, Field(ge=0, le=10_000)]
    requires_confirmation: StrictBool
    reason_summary: Annotated[StrictStr, Field(min_length=1)]

    @model_validator(mode="after")
    def validate_value(self) -> ExtractedFactDraft:
        validate_case_field_value(
            self.field_path,
            self.value_type,
            self.value,
            allow_null=self.operation == FactOperation.CLEAR,
        )
        if (self.operation == FactOperation.CLEAR) != (self.value is None):
            raise ValueError("CLEAR requires null and SET requires a value")
        return self


class ExtractedFactModelOutput(AgentSchema):
    """Provider-facing fact shape without canonical field/value validation.

    The structured-output provider can guarantee these individual field types,
    while :class:`ExtractedFactDraft` applies the operation/value and canonical
    Case-field relationships inside the Agent's bounded retry loop.
    """

    operation: FactOperation
    field_path: CaseFieldKey
    value_type: FactValueType
    value: StrictScalar
    source_text: Annotated[StrictStr, Field(min_length=1)]
    confidence_bps: Annotated[StrictInt, Field(ge=0, le=10_000)]
    requires_confirmation: StrictBool
    reason_summary: Annotated[StrictStr, Field(min_length=1)]


class ProcedureObservationDraft(AgentSchema):
    step_code: Annotated[StrictStr, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]
    observed_status: Literal[
        ProcedureProgressStatus.IN_PROGRESS,
        ProcedureProgressStatus.COMPLETED,
    ]
    source_text: Annotated[StrictStr, Field(min_length=1)]
    requires_confirmation: StrictBool
    reason_summary: Annotated[StrictStr, Field(min_length=1)]


class MissingFieldDraft(AgentSchema):
    field_path: CaseFieldKey
    reason_summary: Annotated[StrictStr, Field(min_length=1)]
    blocks: Annotated[list[MissingFieldBlock], Field(min_length=1)]
    question: Annotated[StrictStr, Field(min_length=1)]


class InfoAnalysisDraft(AgentSchema):
    completion_status: InfoCompletionStatus
    facts: list[ExtractedFactDraft]
    procedure_observations: list[ProcedureObservationDraft]
    missing_fields: list[MissingFieldDraft]
    uncertainties: list[Uncertainty]

    @model_validator(mode="after")
    def validate_completion(self) -> InfoAnalysisDraft:
        if (
            self.completion_status == InfoCompletionStatus.NEEDS_USER_INPUT
            and not self.missing_fields
        ):
            raise ValueError("NEEDS_USER_INPUT requires a missing field")
        return self


class InfoProviderOutput(AgentSchema):
    """Typed provider shape whose semantic invariants are checked locally.

    In particular, this model deliberately does not enforce the relationship
    between ``completion_status`` and ``missing_fields``, or the canonical
    relationships within an extracted fact.  That validation belongs to
    :class:`InfoAnalysisDraft`, after the provider call has returned, so a bad
    semantic response receives the Agent's bounded corrective retry.
    """

    completion_status: InfoCompletionStatus
    facts: list[ExtractedFactModelOutput]
    procedure_observations: list[ProcedureObservationDraft]
    missing_fields: list[MissingFieldDraft]
    uncertainties: list[Uncertainty]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InfoAnalysisAgent:
    """A bounded LLM extraction call followed by deterministic provenance checks."""

    def __init__(
        self,
        llm: StructuredGenerator,
        *,
        clock: Callable[[], datetime] = _now,
        uuid_factory: Callable[[], UUID] = uuid4,
        parser_version: str = "info-agent/1.0",
        max_local_attempts: int = 2,
    ) -> None:
        if max_local_attempts < 1 or max_local_attempts > 3:
            raise ValueError("max_local_attempts must be between 1 and 3")
        self._llm = llm
        self._clock = clock
        self._uuid = uuid_factory
        self._parser_version = parser_version
        self._max_local_attempts = max_local_attempts

    async def analyze(
        self,
        request: InfoAnalysisInput,
        *,
        source_call_id: UUID | None = None,
    ) -> InfoAnalysisResult:
        prompt_input = self._prompt_input(request)
        try:
            ensure_projection_has_no_obvious_sensitive_text(prompt_input)
        except GuardrailViolation:
            raise InfoAnalysisGuardrailError(
                "information-analysis input failed sensitive-data preflight"
            ) from None
        for attempt in range(1, self._max_local_attempts + 1):
            messages = info_messages(prompt_input)
            if attempt > 1:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "The prior structured result failed deterministic semantic "
                            "or grounding validation. Match every fact's operation, value, "
                            "value_type, and allowed enum value to canonical_field_registry; "
                            "CLEAR requires null and SET requires a non-null value. "
                            "NEEDS_USER_INPUT requires at least one missing field. Use only "
                            "allowed fields and known procedure steps, and copy source_text "
                            "as an exact input substring. Return a more conservative result; "
                            "omit any uncertain fact."
                        ),
                    }
                )
            provider_output = await self._llm.generate(
                InfoProviderOutput,
                messages,
                schema_name="reborn_info_analysis",
            )
            try:
                draft = self._validated_draft(provider_output)
                return self._materialize(
                    request,
                    draft,
                    source_call_id=source_call_id,
                )
            except (GuardrailViolation, ValueError):
                continue
        raise InfoAnalysisGuardrailError(
            "information analysis failed deterministic semantic or grounding checks"
        ) from None

    @staticmethod
    def _validated_draft(raw_output: Any) -> InfoAnalysisDraft:
        """Apply the authoritative semantic schema inside the local retry."""

        try:
            if isinstance(raw_output, InfoAnalysisDraft):
                return raw_output
            if isinstance(raw_output, AgentSchema):
                raw_output = raw_output.model_dump(mode="python")
            return InfoAnalysisDraft.model_validate(raw_output)
        except (ValidationError, TypeError, ValueError):
            raise InfoAnalysisGuardrailError(
                "information-analysis output violated the semantic contract"
            ) from None

    @staticmethod
    def _prompt_input(request: InfoAnalysisInput) -> dict[str, Any]:
        allowed = set(request.allowed_field_paths)
        return {
            "input": request.input.model_dump(mode="json"),
            "snapshot_facts": [
                fact.model_dump(mode="json")
                for fact in request.case_snapshot.facts
                if fact.field_path in allowed
            ],
            "allowed_field_paths": [item.value for item in request.allowed_field_paths],
            "canonical_field_registry": {
                key.value: {
                    "value_type": spec[0].value,
                    "allowed_values": sorted(spec[1]) if spec[1] is not None else None,
                }
                for key, spec in CASE_FIELD_SPECS.items()
                if key in allowed
            },
            "known_procedure_steps": [
                item.model_dump(mode="json") for item in request.known_procedure_steps
            ],
            "review_feedback": [
                item.model_dump(mode="json") for item in request.review_feedback
            ],
        }

    def _materialize(
        self,
        request: InfoAnalysisInput,
        draft: InfoAnalysisDraft,
        *,
        source_call_id: UUID | None,
    ) -> InfoAnalysisResult:
        allowed = set(request.allowed_field_paths)
        known_steps = {
            item.procedure_step.step_code: item.procedure_step
            for item in request.known_procedure_steps
        }
        committed = {fact.field_path: fact for fact in request.case_snapshot.facts}
        evidence_by_span: dict[tuple[int, int], EvidenceRecord] = {}
        fact_candidates: list[FactCandidate] = []
        conflicts: list[ConflictCandidate] = []

        proposed_fields = [item.field_path for item in draft.facts]
        if len(set(proposed_fields)) != len(proposed_fields):
            raise InfoAnalysisGuardrailError("model returned duplicate fact fields")

        for semantic in draft.facts:
            if semantic.field_path not in allowed:
                raise InfoAnalysisGuardrailError(
                    "model returned a field outside allowlist"
                )
            span, evidence = self._ground_text(request, semantic.source_text)
            evidence_by_span[(span.start_offset, span.end_offset)] = evidence
            current = committed.get(semantic.field_path)
            if current is not None and current.status == FactStatus.CONFIRMED:
                if semantic.operation == FactOperation.SET and self._same_value(
                    current.value, semantic.value
                ):
                    continue
                conflicts.append(
                    self._conflict(
                        request,
                        semantic,
                        current.value,
                        evidence.evidence_id,
                        source_call_id=source_call_id or self._uuid(),
                    )
                )
                continue
            candidate = FactCandidate(
                candidate_id=self._uuid(),
                operation=semantic.operation,
                field_path=semantic.field_path,
                value_type=semantic.value_type,
                value=semantic.value,
                source_span=span,
                source_evidence_refs=[evidence.evidence_id],
                confidence_bps=semantic.confidence_bps,
                requires_confirmation=semantic.requires_confirmation,
                reason_summary=semantic.reason_summary,
            )
            fact_candidates.append(candidate)

        observations: list[ProcedureProgressObservation] = []
        for semantic in draft.procedure_observations:
            step = known_steps.get(semantic.step_code)
            if step is None:
                raise InfoAnalysisGuardrailError(
                    "model returned an unknown procedure step"
                )
            span, evidence = self._ground_text(request, semantic.source_text)
            evidence_by_span[(span.start_offset, span.end_offset)] = evidence
            observations.append(
                ProcedureProgressObservation(
                    observation_id=self._uuid(),
                    procedure_step=step,
                    observed_status=semantic.observed_status,
                    source_span=span,
                    source_evidence_refs=[evidence.evidence_id],
                    requires_confirmation=semantic.requires_confirmation,
                    reason_summary=semantic.reason_summary,
                )
            )

        missing_fields: list[MissingField] = []
        questions: list[QuestionCandidate] = []
        for missing in draft.missing_fields:
            if missing.field_path not in allowed:
                raise InfoAnalysisGuardrailError("missing field is outside allowlist")
            question_id = self._uuid()
            questions.append(
                QuestionCandidate(
                    question_id=question_id,
                    text=missing.question,
                    resolves_field_paths=[missing.field_path],
                    reason_summary=missing.reason_summary,
                )
            )
            missing_fields.append(
                MissingField(
                    field_path=missing.field_path,
                    reason_summary=missing.reason_summary,
                    blocks=missing.blocks,
                    question_candidate_id=question_id,
                )
            )

        free_text = [
            *(item.reason_summary for item in fact_candidates),
            *(item.reason_summary for item in observations),
            *(item.text for item in questions),
            *(item.reason_summary for item in questions),
            *(item.reason_summary for item in draft.uncertainties),
        ]
        ensure_no_sensitive_text(free_text)

        status = draft.completion_status
        if conflicts:
            status = InfoCompletionStatus.NEEDS_USER_INPUT
            if not missing_fields:
                # Conflicts are returned structurally.  A BE confirmation adapter
                # will provide the fixed UI copy; the LLM does not invent it.
                field_path = conflicts[0].field_path
                question_id = self._uuid()
                questions.append(
                    QuestionCandidate(
                        question_id=question_id,
                        text="기존 정보와 새 입력 중 어떤 내용이 맞는지 확인해 주세요.",
                        resolves_field_paths=[field_path],
                        reason_summary="확정된 Case 정보와 새 입력이 다릅니다.",
                    )
                )
                missing_fields.append(
                    MissingField(
                        field_path=field_path,
                        reason_summary="충돌 확인 전에는 값을 변경할 수 없습니다.",
                        blocks=[MissingFieldBlock.SUPERVISOR_DECISION],
                        question_candidate_id=question_id,
                    )
                )
        elif missing_fields:
            status = InfoCompletionStatus.NEEDS_USER_INPUT

        known_evidence = {
            item.evidence_id for item in request.case_snapshot.evidence_records
        } | {item.evidence_id for item in evidence_by_span.values()}
        for uncertainty in draft.uncertainties:
            unknown_refs = set(uncertainty.evidence_refs) - known_evidence
            if unknown_refs:
                raise InfoAnalysisGuardrailError(
                    "uncertainty references unknown evidence"
                )

        return InfoAnalysisResult(
            completion_status=status,
            fact_candidates=fact_candidates,
            procedure_progress_observations=observations,
            conflicts=conflicts,
            missing_fields=missing_fields,
            uncertainties=draft.uncertainties,
            question_candidates=questions,
            evidence_records=list(evidence_by_span.values()),
            parser_version=self._parser_version,
            based_on_snapshot_id=request.case_snapshot.snapshot_id,
        )

    def _ground_text(
        self,
        request: InfoAnalysisInput,
        source_text: str,
    ) -> tuple[VerifiedTextSpan, EvidenceRecord]:
        start, end = exact_span(request.input.redacted_text, source_text)
        span = VerifiedTextSpan(
            input_event_id=request.input.input_event_id,
            text=source_text,
            start_offset=start,
            end_offset=end,
        )
        fingerprint = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        evidence = EvidenceRecord(
            evidence_id=(
                f"input:{request.input.input_event_id}:{start}:{end}:{fingerprint[:12]}"
            ),
            source_type=request.input.source_type.value,
            source_ref=request.input.input_event_id,
            source_version=None,
            locator=f"text:{start}-{end}",
            excerpt=source_text,
            parent_evidence_refs=[],
            published_at=None,
            retrieved_at=self._clock(),
            freshness_status="CURRENT",
            content_hash="sha256:" + fingerprint,
        )
        return span, evidence

    def _conflict(
        self,
        request: InfoAnalysisInput,
        semantic: ExtractedFactDraft,
        committed_value: NonNullStrictScalar,
        evidence_id: str,
        *,
        source_call_id: UUID,
    ) -> ConflictCandidate:
        candidate_id = self._uuid()
        return ConflictCandidate.create_standalone(
            candidate_id=candidate_id,
            snapshot_id=request.case_snapshot.snapshot_id,
            case_version=request.case_snapshot.case_version,
            field_path=semantic.field_path,
            committed_status=FactStatus.CONFIRMED,
            committed_value=committed_value,
            proposed_operation=semantic.operation,
            proposed_status=(
                FactStatus.UNKNOWN
                if semantic.operation == FactOperation.CLEAR
                else FactStatus.CONFIRMED
            ),
            proposed_value=semantic.value,
            source_evidence_refs=[evidence_id],
            source_call_id=source_call_id,
        )

    @staticmethod
    def _same_value(left: StrictScalar, right: StrictScalar) -> bool:
        return type(left) is type(right) and left == right


__all__ = [
    "ExtractedFactDraft",
    "ExtractedFactModelOutput",
    "InfoAnalysisAgent",
    "InfoAnalysisDraft",
    "InfoAnalysisGuardrailError",
    "InfoProviderOutput",
    "MissingFieldDraft",
    "ProcedureObservationDraft",
]
