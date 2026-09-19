"""Strict Agent/Tool contracts for the standalone RE:BORN runtime.

The models in this module are the executable, conservative subset of
``docs/agent-tool-io-schema.md`` needed to execute one complete planning run.
They deliberately keep BE persistence and HTTP response DTOs out of the Agent
package.

Values described as runtime-injected are never trusted when proposed by an
LLM.  Callers must construct them after validating the semantic LLM payload.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Annotated, Any, Generic, Literal, TypeAlias, TypeVar
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)


class AgentSchema(BaseModel):
    """Base contract: unknown fields and assignment-time corruption are errors."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        validate_default=True,
    )


NonEmptyStr = Annotated[StrictStr, Field(min_length=1)]
UpperSnakeCode = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$", min_length=1),
]
JsonPointer = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^(?:/(?:[^~/]|~[01])*)*$"),
]
Digest = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
]
PositiveStrictInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeStrictInt = Annotated[StrictInt, Field(ge=0)]
ConfidenceBps = Annotated[StrictInt, Field(ge=0, le=10_000)]
RuntimeUUID = Annotated[
    UUID,
    Field(
        description="Trusted runtime-generated value; an LLM must not generate it.",
        json_schema_extra={"x-runtime-injected": True},
    ),
]
RuntimeDateTime = Annotated[
    AwareDatetime,
    Field(
        description="Trusted runtime/resolver timestamp; an LLM must not generate it.",
        json_schema_extra={"x-runtime-injected": True},
    ),
]

StrictScalar: TypeAlias = StrictStr | StrictInt | StrictBool | date | None
NonNullStrictScalar: TypeAlias = StrictStr | StrictInt | StrictBool | date


class StrEnum(str, Enum):
    """String enum whose value is stable in JSON and prompts."""


class Component(StrEnum):
    SUPERVISOR = "SUPERVISOR"
    INFO_AGENT = "INFO_AGENT"
    SUPPORT_AGENT = "SUPPORT_AGENT"
    PROCEDURE_TOOL = "PROCEDURE_TOOL"
    REVIEW_TOOL = "REVIEW_TOOL"


class FreshnessStatus(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class CaseFieldKey(StrEnum):
    BUSINESS_TYPE = "business_type"
    FRANCHISE_STATUS = "franchise_status"
    EMPLOYEE_COUNT = "employee_count"
    LEASE_STATUS = "lease_status"
    ENTITY_TYPE = "entity_type"
    BUILDING_USE_TYPE = "building_use_type"
    PREVIOUS_SUPPORT_HISTORY = "previous_support_history"
    RESTORATION_STATUS = "restoration_status"
    RESTORATION_SCOPE = "restoration_scope"
    RESTORATION_SCOPE_DETAIL = "restoration_scope_detail"
    DEMOLITION_REQUIRED = "demolition_required"
    PLANNED_CLOSURE_DATE = "planned_closure_date"


class FactValueType(StrEnum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    ENUM = "ENUM"


class FactStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    UNKNOWN = "UNKNOWN"


class FactOperation(StrEnum):
    SET = "SET"
    CLEAR = "CLEAR"


class CaseStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ProcedureProgressStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class SupportMatchStatus(StrEnum):
    POSSIBLY_RELEVANT = "POSSIBLY_RELEVANT"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    NOT_RELEVANT = "NOT_RELEVANT"
    STALE = "STALE"
    UNVERIFIABLE = "UNVERIFIABLE"


class EvidenceSourceType(StrEnum):
    USER_INPUT = "USER_INPUT"
    EXPERT_CONFIRMATION = "EXPERT_CONFIRMATION"
    REVIEWED_WIKI = "REVIEWED_WIKI"
    OFFICIAL_DOCUMENT = "OFFICIAL_DOCUMENT"
    OFFICIAL_API = "OFFICIAL_API"
    CALCULATION_RESULT = "CALCULATION_RESULT"
    SYSTEM_RECORD = "SYSTEM_RECORD"


# This catalog is intentionally local to the standalone Agent.  The unresolved
# BE/API enum mismatch remains a boundary decision.  Expanding these values must
# be an explicit contract change; free-form text never passes an ENUM field.
CASE_FIELD_SPECS: dict[CaseFieldKey, tuple[FactValueType, frozenset[str] | None]] = {
    CaseFieldKey.BUSINESS_TYPE: (FactValueType.STRING, None),
    CaseFieldKey.FRANCHISE_STATUS: (FactValueType.BOOLEAN, None),
    CaseFieldKey.EMPLOYEE_COUNT: (FactValueType.INTEGER, None),
    CaseFieldKey.LEASE_STATUS: (
        FactValueType.ENUM,
        frozenset({"ACTIVE", "TERMINATION_NOTIFIED", "TERMINATED", "OWNED"}),
    ),
    CaseFieldKey.ENTITY_TYPE: (
        FactValueType.ENUM,
        frozenset({"SOLE_PROPRIETOR", "CORPORATION"}),
    ),
    CaseFieldKey.BUILDING_USE_TYPE: (
        FactValueType.ENUM,
        frozenset({"NEIGHBORHOOD_LIVING", "OTHER"}),
    ),
    CaseFieldKey.PREVIOUS_SUPPORT_HISTORY: (
        FactValueType.ENUM,
        frozenset({"NONE", "RECEIVED"}),
    ),
    CaseFieldKey.RESTORATION_STATUS: (
        FactValueType.ENUM,
        frozenset({"NOT_STARTED", "IN_PROGRESS", "COMPLETED"}),
    ),
    CaseFieldKey.RESTORATION_SCOPE: (
        FactValueType.ENUM,
        frozenset(
            {
                "AGREEMENT_REQUIRED",
                "TENANT_ALL",
                "LANDLORD_ALL",
                "SHARED",
                "NOT_REQUIRED",
            }
        ),
    ),
    CaseFieldKey.RESTORATION_SCOPE_DETAIL: (FactValueType.STRING, None),
    CaseFieldKey.DEMOLITION_REQUIRED: (
        FactValueType.ENUM,
        frozenset({"REQUIRED", "NOT_REQUIRED"}),
    ),
    CaseFieldKey.PLANNED_CLOSURE_DATE: (FactValueType.DATE, None),
}

SIMULATION_CONFLICT_REF_PREFIX = "standalone:"


def validate_case_field_value(
    field_path: CaseFieldKey,
    value_type: FactValueType,
    value: StrictScalar,
    *,
    allow_null: bool,
) -> None:
    """Validate a fact against the standalone canonical field registry.

    ``UNKNOWN`` is represented by the surrounding status and a null value.  It
    is never accepted as a confirmed enum value.
    """

    expected_type, allowed_values = CASE_FIELD_SPECS[field_path]
    if value_type != expected_type:
        raise ValueError(
            f"{field_path.value} requires value_type={expected_type.value}"
        )
    if value is None:
        if allow_null:
            return
        raise ValueError(f"{field_path.value} requires a non-null value")

    if expected_type == FactValueType.BOOLEAN:
        valid = type(value) is bool
    elif expected_type == FactValueType.INTEGER:
        valid = type(value) is int and value >= 0
    elif expected_type == FactValueType.DATE:
        valid = (type(value) is date) or (
            type(value) is str
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None
            and _is_iso_date(value)
        )
    else:
        valid = type(value) is str and bool(value.strip())

    if not valid:
        raise ValueError(
            f"{field_path.value} value does not match {expected_type.value}"
        )
    if allowed_values is not None and value not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(f"{field_path.value} must be one of: {allowed}")


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _ensure_unique(values: list[Any], key: Any, label: str) -> None:
    seen: set[Any] = set()
    for value in values:
        item_key = key(value)
        if item_key in seen:
            raise ValueError(f"duplicate {label}: {item_key}")
        seen.add(item_key)


class InvocationMeta(AgentSchema):
    schema_version: Literal["agent-io/2.0"]
    run_id: RuntimeUUID
    call_id: RuntimeUUID
    parent_call_id: RuntimeUUID | None
    case_id: PositiveStrictInt
    component: Component
    attempt: PositiveStrictInt
    requested_at: RuntimeDateTime
    trace_id: NonEmptyStr | None


T = TypeVar("T")


class ComponentRequest(AgentSchema, Generic[T]):
    meta: InvocationMeta
    input: T


class ComponentWarning(AgentSchema):
    code: UpperSnakeCode
    message: NonEmptyStr
    target_path: JsonPointer | None


class ComponentErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    SNAPSHOT_UNAVAILABLE = "SNAPSHOT_UNAVAILABLE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    LOOP_LIMIT_REACHED = "LOOP_LIMIT_REACHED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ComponentError(AgentSchema):
    code: ComponentErrorCode
    message_code: UpperSnakeCode
    retryable: StrictBool
    failed_dependency: NonEmptyStr | None
    retry_after_ms: NonNegativeStrictInt | None


class ComponentSuccess(AgentSchema, Generic[T]):
    execution_status: Literal["SUCCESS"]
    meta: InvocationMeta
    output: T
    warnings: list[ComponentWarning]


class ComponentFailure(AgentSchema):
    execution_status: Literal["ERROR"]
    meta: InvocationMeta
    error: ComponentError


class EvidenceRecord(AgentSchema):
    evidence_id: NonEmptyStr
    source_type: EvidenceSourceType
    source_ref: NonEmptyStr
    source_version: NonEmptyStr | None
    locator: NonEmptyStr
    excerpt: NonEmptyStr
    parent_evidence_refs: list[NonEmptyStr]
    published_at: AwareDatetime | None
    retrieved_at: RuntimeDateTime
    freshness_status: FreshnessStatus
    content_hash: Digest | None

    @model_validator(mode="after")
    def validate_lineage(self) -> EvidenceRecord:
        if self.evidence_id in self.parent_evidence_refs:
            raise ValueError("evidence cannot be its own parent")
        if len(set(self.parent_evidence_refs)) != len(self.parent_evidence_refs):
            raise ValueError("parent_evidence_refs must be unique")
        return self


class ProcedureStepRef(AgentSchema):
    procedure_step_id: PositiveStrictInt
    step_code: UpperSnakeCode


class SupportProgramRef(AgentSchema):
    support_program_id: PositiveStrictInt
    wiki_uuid: UUID


class CaseFact(AgentSchema):
    field_path: CaseFieldKey
    value_type: FactValueType
    value: StrictScalar
    status: FactStatus
    evidence_refs: list[NonEmptyStr]
    updated_at: AwareDatetime | None

    @model_validator(mode="after")
    def validate_fact_state(self) -> CaseFact:
        if self.status == FactStatus.UNKNOWN:
            if self.value is not None:
                raise ValueError("UNKNOWN fact must have value=null")
            if self.evidence_refs:
                raise ValueError("UNKNOWN fact must not claim confirming evidence")
        else:
            if self.value is None:
                raise ValueError("CONFIRMED fact requires a value")
            if not self.evidence_refs:
                raise ValueError("CONFIRMED fact requires evidence")
        validate_case_field_value(
            self.field_path,
            self.value_type,
            self.value,
            allow_null=self.status == FactStatus.UNKNOWN,
        )
        return self


class ProcedureProgress(AgentSchema):
    procedure_step: ProcedureStepRef
    status: ProcedureProgressStatus
    evidence_refs: list[NonEmptyStr]
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def completed_requires_evidence(self) -> ProcedureProgress:
        if self.status == ProcedureProgressStatus.COMPLETED and not self.evidence_refs:
            raise ValueError("COMPLETED procedure progress requires evidence")
        return self


class CaseSnapshot(AgentSchema):
    snapshot_id: RuntimeUUID
    case_id: PositiveStrictInt
    case_version: PositiveStrictInt | None
    case_status: CaseStatus
    facts: list[CaseFact]
    procedure_progress: list[ProcedureProgress]
    evidence_records: list[EvidenceRecord]
    captured_at: RuntimeDateTime

    @model_validator(mode="after")
    def validate_snapshot_integrity(self) -> CaseSnapshot:
        _ensure_unique(self.facts, lambda item: item.field_path, "fact field_path")
        _ensure_unique(
            self.procedure_progress,
            lambda item: item.procedure_step.procedure_step_id,
            "procedure_step_id",
        )
        _ensure_unique(
            self.evidence_records, lambda item: item.evidence_id, "evidence_id"
        )
        known_evidence = {item.evidence_id for item in self.evidence_records}
        referenced = {
            evidence_ref for fact in self.facts for evidence_ref in fact.evidence_refs
        } | {
            evidence_ref
            for progress in self.procedure_progress
            for evidence_ref in progress.evidence_refs
        }
        missing = referenced - known_evidence
        if missing:
            raise ValueError(
                "snapshot contains unresolved evidence refs: "
                + ", ".join(sorted(missing))
            )
        return self


class RedactionType(StrEnum):
    ADDRESS = "ADDRESS"
    NATIONAL_ID = "NATIONAL_ID"
    ACCOUNT = "ACCOUNT"
    TOKEN = "TOKEN"
    OTHER = "OTHER"


class Redaction(AgentSchema):
    type: RedactionType
    placeholder: NonEmptyStr
    start_offset: NonNegativeStrictInt
    end_offset: PositiveStrictInt

    @model_validator(mode="after")
    def validate_offsets(self) -> Redaction:
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        return self


class InputSourceType(StrEnum):
    USER_INPUT = "USER_INPUT"
    EXPERT_CONFIRMATION = "EXPERT_CONFIRMATION"


class RedactedInput(AgentSchema):
    input_event_id: NonEmptyStr
    source_type: InputSourceType
    redacted_text: NonEmptyStr
    redactions: list[Redaction]
    submitted_at: AwareDatetime

    @model_validator(mode="after")
    def validate_redactions(self) -> RedactedInput:
        text_length = len(self.redacted_text)
        previous_end = 0
        for redaction in sorted(self.redactions, key=lambda item: item.start_offset):
            if redaction.start_offset < previous_end:
                raise ValueError("redaction spans must not overlap")
            if redaction.end_offset > text_length:
                raise ValueError("redaction span is outside redacted_text")
            if (
                self.redacted_text[redaction.start_offset : redaction.end_offset]
                != redaction.placeholder
            ):
                raise ValueError("redaction placeholder must match redacted_text span")
            previous_end = redaction.end_offset
        return self


class VerifiedTextSpan(AgentSchema):
    input_event_id: NonEmptyStr
    text: NonEmptyStr
    start_offset: NonNegativeStrictInt
    end_offset: PositiveStrictInt

    @model_validator(mode="after")
    def validate_offsets(self) -> VerifiedTextSpan:
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        if self.end_offset - self.start_offset != len(self.text):
            raise ValueError("span offsets must match text length")
        return self


class FactCandidate(AgentSchema):
    candidate_id: RuntimeUUID
    operation: FactOperation
    field_path: CaseFieldKey
    value_type: FactValueType
    value: StrictScalar
    source_span: VerifiedTextSpan
    source_evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]
    confidence_bps: ConfidenceBps
    requires_confirmation: StrictBool
    reason_summary: NonEmptyStr

    @model_validator(mode="after")
    def validate_candidate(self) -> FactCandidate:
        is_clear = self.operation == FactOperation.CLEAR
        if is_clear and self.value is not None:
            raise ValueError("CLEAR fact candidate must have value=null")
        if not is_clear and self.value is None:
            raise ValueError("SET fact candidate requires a value")
        validate_case_field_value(
            self.field_path,
            self.value_type,
            self.value,
            allow_null=is_clear,
        )
        return self


class FactChangeSourceType(StrEnum):
    INFO_ANALYSIS = "INFO_ANALYSIS"
    CONFIRMED_CONFLICT = "CONFIRMED_CONFLICT"


class FactChangeCandidate(AgentSchema):
    candidate_id: RuntimeUUID
    operation: FactOperation
    source_fact_candidate_id: RuntimeUUID
    source_type: FactChangeSourceType
    field_path: CaseFieldKey
    value_type: FactValueType
    before_status: FactStatus
    before_value: StrictScalar
    proposed_status: FactStatus
    proposed_value: StrictScalar
    candidate_status: Literal["READY_FOR_REVIEW"]
    reason_summary: NonEmptyStr
    source_evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]
    source_call_id: RuntimeUUID | None
    confirmed_conflict_ref: NonEmptyStr | None

    @model_validator(mode="after")
    def validate_change(self) -> FactChangeCandidate:
        if self.before_status == FactStatus.UNKNOWN and self.before_value is not None:
            raise ValueError("UNKNOWN before state must have value=null")
        if self.before_status == FactStatus.CONFIRMED and self.before_value is None:
            raise ValueError("CONFIRMED before state requires a value")
        validate_case_field_value(
            self.field_path,
            self.value_type,
            self.before_value,
            allow_null=self.before_status == FactStatus.UNKNOWN,
        )

        if self.operation == FactOperation.SET:
            if self.proposed_status != FactStatus.CONFIRMED:
                raise ValueError("SET must propose CONFIRMED")
            if self.proposed_value is None:
                raise ValueError("SET requires a proposed value")
        else:
            if self.proposed_status != FactStatus.UNKNOWN:
                raise ValueError("CLEAR must propose UNKNOWN")
            if self.proposed_value is not None:
                raise ValueError("CLEAR must propose value=null")
        validate_case_field_value(
            self.field_path,
            self.value_type,
            self.proposed_value,
            allow_null=self.operation == FactOperation.CLEAR,
        )

        if self.source_type == FactChangeSourceType.INFO_ANALYSIS:
            if self.source_call_id is None or self.confirmed_conflict_ref is not None:
                raise ValueError("INFO_ANALYSIS requires source_call_id only")
        elif self.source_call_id is not None or self.confirmed_conflict_ref is None:
            raise ValueError("CONFIRMED_CONFLICT requires confirmed_conflict_ref only")
        return self


class PlanningContext(AgentSchema):
    case_snapshot: CaseSnapshot
    fact_overlays: list[FactChangeCandidate]

    @model_validator(mode="after")
    def validate_overlays(self) -> PlanningContext:
        _ensure_unique(
            self.fact_overlays, lambda item: item.candidate_id, "candidate_id"
        )
        _ensure_unique(
            self.fact_overlays, lambda item: item.field_path, "overlay field_path"
        )
        return self


class KnownProcedureStep(AgentSchema):
    procedure_step: ProcedureStepRef
    step_name: NonEmptyStr
    utterance_aliases: list[NonEmptyStr]


class InfoCompletionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    PARTIAL = "PARTIAL"


class MissingFieldBlock(StrEnum):
    PROCEDURE_LOOKUP = "PROCEDURE_LOOKUP"
    SUPPORT_ANALYSIS = "SUPPORT_ANALYSIS"
    SUPERVISOR_DECISION = "SUPERVISOR_DECISION"


class MissingField(AgentSchema):
    field_path: CaseFieldKey
    reason_summary: NonEmptyStr
    blocks: Annotated[list[MissingFieldBlock], Field(min_length=1)]
    question_candidate_id: RuntimeUUID | None


class UncertaintyCode(StrEnum):
    AMBIGUOUS_INPUT = "AMBIGUOUS_INPUT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    CONTEXT_MISSING = "CONTEXT_MISSING"
    SOURCE_STALE = "SOURCE_STALE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class Uncertainty(AgentSchema):
    code: UncertaintyCode
    target_path: JsonPointer
    reason_summary: NonEmptyStr
    evidence_refs: list[NonEmptyStr]


class QuestionCandidate(AgentSchema):
    question_id: RuntimeUUID
    text: NonEmptyStr
    resolves_field_paths: Annotated[list[CaseFieldKey], Field(min_length=1)]
    reason_summary: NonEmptyStr


class ProcedureProgressObservation(AgentSchema):
    observation_id: RuntimeUUID
    procedure_step: ProcedureStepRef
    observed_status: Literal[
        ProcedureProgressStatus.IN_PROGRESS,
        ProcedureProgressStatus.COMPLETED,
    ]
    source_span: VerifiedTextSpan
    source_evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]
    requires_confirmation: StrictBool
    reason_summary: NonEmptyStr


class ConflictCandidate(AgentSchema):
    conflict_ref: Annotated[
        NonEmptyStr,
        Field(
            description=(
                "BE-issued conflict reference. Values beginning with 'standalone:' "
                "are simulation-only and must never be persisted or accepted by a "
                "production confirmation endpoint."
            )
        ),
    ]
    conflict_digest: Digest
    candidate_id: RuntimeUUID
    snapshot_id: RuntimeUUID
    case_version: PositiveStrictInt | None
    field_path: CaseFieldKey
    committed_status: Literal[FactStatus.CONFIRMED]
    committed_value: NonNullStrictScalar
    proposed_operation: FactOperation
    proposed_status: FactStatus
    proposed_value: StrictScalar
    source_evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]
    source_call_id: RuntimeUUID

    @model_validator(mode="after")
    def validate_proposal(self) -> ConflictCandidate:
        validate_case_field_value(
            self.field_path,
            CASE_FIELD_SPECS[self.field_path][0],
            self.committed_value,
            allow_null=False,
        )
        if self.proposed_operation == FactOperation.SET:
            if (
                self.proposed_status != FactStatus.CONFIRMED
                or self.proposed_value is None
            ):
                raise ValueError("SET conflict must propose a confirmed value")
        elif (
            self.proposed_status != FactStatus.UNKNOWN
            or self.proposed_value is not None
        ):
            raise ValueError("CLEAR conflict must propose UNKNOWN/null")
        validate_case_field_value(
            self.field_path,
            CASE_FIELD_SPECS[self.field_path][0],
            self.proposed_value,
            allow_null=self.proposed_operation == FactOperation.CLEAR,
        )
        if self.conflict_ref.startswith(
            SIMULATION_CONFLICT_REF_PREFIX
        ) and not re.fullmatch(
            rf"{re.escape(SIMULATION_CONFLICT_REF_PREFIX)}[0-9a-f]{{24}}",
            self.conflict_ref,
        ):
            raise ValueError(
                "standalone conflict_ref must contain a 24-hex digest suffix"
            )
        self.assert_integrity()
        return self

    def calculate_digest(self) -> str:
        """Digest all conflict content except the server/simulation reference."""

        return canonical_digest(
            self,
            exclude={"conflict_ref", "conflict_digest"},
        )

    @property
    def is_simulation_only(self) -> bool:
        return self.conflict_ref.startswith(SIMULATION_CONFLICT_REF_PREFIX)

    @classmethod
    def create(cls, *, conflict_ref: str, **values: Any) -> ConflictCandidate:
        """Bind trusted conflict fields and a resolver-issued reference to a digest."""

        provisional = cls.model_construct(
            conflict_ref=conflict_ref,
            conflict_digest="sha256:" + "0" * 64,
            **values,
        )
        digest = provisional.calculate_digest()
        return cls.model_validate(
            {
                **values,
                "conflict_ref": conflict_ref,
                "conflict_digest": digest,
            }
        )

    @classmethod
    def create_standalone(cls, **values: Any) -> ConflictCandidate:
        """Build a digest-bound conflict with an explicitly non-production ref."""

        provisional = cls.model_construct(
            conflict_ref=SIMULATION_CONFLICT_REF_PREFIX + "0" * 24,
            conflict_digest="sha256:" + "0" * 64,
            **values,
        )
        digest = provisional.calculate_digest()
        return cls.create(
            conflict_ref=(
                SIMULATION_CONFLICT_REF_PREFIX + digest.removeprefix("sha256:")[:24]
            ),
            **values,
        )

    def assert_integrity(self) -> None:
        if self.conflict_digest != self.calculate_digest():
            raise ValueError("conflict_digest does not match conflict candidate")

    @model_serializer(mode="wrap")
    def serialize_with_integrity(self, handler: Any) -> Any:
        self.assert_integrity()
        return handler(self)


class InfoAnalysisInput(AgentSchema):
    """Complete request schema accepted by ``InfoAnalysisAgent.analyze``."""

    input: RedactedInput = Field(
        description="Redacted user or expert text to interpret in this call."
    )
    case_snapshot: CaseSnapshot = Field(
        description="Immutable Case read view used as the analysis baseline."
    )
    allowed_field_paths: Annotated[
        list[CaseFieldKey],
        Field(
            min_length=1,
            description="Canonical Case fields that this call may propose changing.",
        ),
    ]
    known_procedure_steps: list[KnownProcedureStep] = Field(
        description="Canonical procedure steps to which source text may be linked."
    )
    source_call_id: RuntimeUUID = Field(
        description="Invocation call ID assigned to this Info Agent result."
    )
    procedure_lookup_call_id: RuntimeUUID = Field(
        description="Call ID of the Procedure Lookup result supplied below."
    )
    procedure_lookup_result: ProcedureLookupResult = Field(
        description="Fetched official procedure documents to analyze."
    )
    review_feedback: list[ReviewIssue] = Field(
        description="Blocking review issues supplied when this call is a rework."
    )

    @model_validator(mode="after")
    def validate_input(self) -> InfoAnalysisInput:
        if len(set(self.allowed_field_paths)) != len(self.allowed_field_paths):
            raise ValueError("allowed_field_paths must be unique")
        _ensure_unique(
            self.known_procedure_steps,
            lambda item: item.procedure_step.procedure_step_id,
            "known procedure_step_id",
        )
        _ensure_unique(
            self.known_procedure_steps,
            lambda item: item.procedure_step.step_code,
            "known procedure step_code",
        )
        _ensure_unique(
            self.known_procedure_steps,
            lambda item: item.step_name.casefold().strip(),
            "known procedure step_name",
        )
        phrases: list[str] = []
        for item in self.known_procedure_steps:
            phrases.append(item.step_name.casefold().strip())
            phrases.extend(alias.casefold().strip() for alias in item.utterance_aliases)
        if len(set(phrases)) != len(phrases):
            raise ValueError("known procedure names and aliases must be unique")
        if (
            self.procedure_lookup_result.based_on_snapshot_id
            != self.case_snapshot.snapshot_id
        ):
            raise ValueError("procedure lookup snapshot must match Info snapshot")
        return self


class InfoAnalysisResult(AgentSchema):
    """Complete success schema returned by ``InfoAnalysisAgent.analyze``."""

    completion_status: InfoCompletionStatus = Field(
        description="Whether analysis completed or needs more input."
    )
    fact_candidates: list[FactCandidate] = Field(
        description="Evidence-linked Case fact changes proposed for later review."
    )
    procedure_progress_observations: list[ProcedureProgressObservation] = Field(
        description="User-evidenced observations of real procedure progress."
    )
    procedure_findings: list[ProcedureFinding] = Field(
        description="Official procedure content linked to canonical Case steps."
    )
    conflicts: list[ConflictCandidate] = Field(
        description="New statements that conflict with confirmed Case facts."
    )
    missing_fields: list[MissingField] = Field(
        description="Unknown canonical facts that block a downstream decision."
    )
    uncertainties: list[Uncertainty] = Field(
        description="Analysis limitations that must remain visible downstream."
    )
    question_candidates: list[QuestionCandidate] = Field(
        description="Candidate user questions that resolve missing Case facts."
    )
    evidence_records: list[EvidenceRecord] = Field(
        description="Evidence records that close all fact and progress references."
    )
    parser_version: Annotated[
        NonEmptyStr,
        Field(
            description="Version of the deterministic Info parser and guardrails.",
            json_schema_extra={"x-runtime-injected": True},
        ),
    ]
    based_on_snapshot_id: RuntimeUUID = Field(
        description="Snapshot ID against which this result was produced."
    )
    based_on_procedure_lookup_call_id: RuntimeUUID = Field(
        description="Procedure Tool call ID used as this result's source."
    )
    based_on_procedure_lookup_digest: Digest = Field(
        description="Canonical digest of the Procedure Tool result that was analyzed."
    )

    @model_validator(mode="after")
    def validate_result(self) -> InfoAnalysisResult:
        candidates: list[Any] = [*self.fact_candidates, *self.conflicts]
        _ensure_unique(candidates, lambda item: item.candidate_id, "candidate_id")
        _ensure_unique(
            self.procedure_progress_observations,
            lambda item: item.observation_id,
            "observation_id",
        )
        _ensure_unique(
            self.procedure_findings,
            lambda item: item.procedure_step.procedure_step_id,
            "procedure finding procedure_step_id",
        )
        _ensure_unique(
            self.procedure_findings,
            lambda item: item.finding_id,
            "procedure finding_id",
        )
        _ensure_unique(
            self.question_candidates, lambda item: item.question_id, "question_id"
        )
        _ensure_unique(
            self.missing_fields,
            lambda item: item.field_path,
            "missing field_path",
        )
        _ensure_unique(
            self.evidence_records, lambda item: item.evidence_id, "evidence_id"
        )
        if self.completion_status == InfoCompletionStatus.NEEDS_USER_INPUT and (
            not self.missing_fields or not self.question_candidates
        ):
            raise ValueError(
                "NEEDS_USER_INPUT requires missing_fields and question_candidates"
            )
        known_evidence = {item.evidence_id for item in self.evidence_records}
        referenced = {
            evidence_ref
            for candidate in self.fact_candidates
            for evidence_ref in candidate.source_evidence_refs
        } | {
            evidence_ref
            for observation in self.procedure_progress_observations
            for evidence_ref in observation.source_evidence_refs
        }
        missing = referenced - known_evidence
        if missing:
            raise ValueError(
                "info result contains unresolved evidence refs: "
                + ", ".join(sorted(missing))
            )
        return self


class SupportLookupGoal(StrEnum):
    DISCOVER_RELEVANT = "DISCOVER_RELEVANT"
    CHECK_SPECIFIC = "CHECK_SPECIFIC"
    REFRESH_STALE = "REFRESH_STALE"


class DiscoverSupportInput(AgentSchema):
    """Support Agent request for all reviewed programs relevant to the Case."""

    lookup_goal: Literal[SupportLookupGoal.DISCOVER_RELEVANT] = Field(
        description="Select reviewed programs relevant to the supplied Case context."
    )
    planning_context: PlanningContext = Field(
        description="Immutable Case snapshot plus reviewable fact overlays."
    )
    related_steps: list[ProcedureStepRef] = Field(
        description="Canonical procedure steps used to narrow program selection."
    )
    as_of: date = Field(
        description="Decision date carried as provenance for this comparison."
    )
    review_feedback: list[ReviewIssue] = Field(
        description="Blocking review issues supplied when this call is a rework."
    )


class CheckSpecificSupportInput(AgentSchema):
    """Support Agent request for an explicit set of reviewed programs."""

    lookup_goal: Literal[SupportLookupGoal.CHECK_SPECIFIC] = Field(
        description="Compare only the explicitly requested reviewed programs."
    )
    planning_context: PlanningContext = Field(
        description="Immutable Case snapshot plus reviewable fact overlays."
    )
    related_steps: list[ProcedureStepRef] = Field(
        description="Canonical procedure steps used to validate program relevance."
    )
    as_of: date = Field(
        description="Decision date carried as provenance for this comparison."
    )
    review_feedback: list[ReviewIssue] = Field(
        description="Blocking review issues supplied when this call is a rework."
    )
    support_programs: Annotated[
        list[SupportProgramRef],
        Field(
            min_length=1,
            description="Stable identifiers of reviewed programs to compare.",
        ),
    ]


class RefreshSupportInput(AgentSchema):
    """Support Agent request to re-evaluate programs in the injected catalog."""

    lookup_goal: Literal[SupportLookupGoal.REFRESH_STALE] = Field(
        description="Re-evaluate named programs from the already injected catalog."
    )
    planning_context: PlanningContext = Field(
        description="Immutable Case snapshot plus reviewable fact overlays."
    )
    related_steps: list[ProcedureStepRef] = Field(
        description="Canonical procedure steps used to validate program relevance."
    )
    as_of: date = Field(
        description="Decision date carried as provenance for this comparison."
    )
    review_feedback: list[ReviewIssue] = Field(
        description="Blocking review issues supplied when this call is a rework."
    )
    support_programs: Annotated[
        list[SupportProgramRef],
        Field(
            min_length=1,
            description="Stable identifiers of injected programs to re-evaluate.",
        ),
    ]


SupportAgentInput: TypeAlias = Annotated[
    DiscoverSupportInput | CheckSpecificSupportInput | RefreshSupportInput,
    Field(
        title="SupportAgentInput",
        discriminator="lookup_goal",
        description=(
            "Complete Support Agent input; lookup_goal selects exactly one request "
            "schema."
        ),
    ),
]


class CriterionStatus(StrEnum):
    MET = "MET"
    NOT_MET = "NOT_MET"
    UNKNOWN = "UNKNOWN"


class SupportCriterionResult(AgentSchema):
    criterion_code: UpperSnakeCode
    case_value: StrictScalar
    required_values: Annotated[list[NonNullStrictScalar], Field(min_length=1)]
    status: CriterionStatus
    reason_summary: NonEmptyStr
    evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_unknown(self) -> SupportCriterionResult:
        if (self.case_value is None) != (self.status == CriterionStatus.UNKNOWN):
            raise ValueError("case_value is null iff criterion status is UNKNOWN")
        return self


class SourcedText(AgentSchema):
    text: NonEmptyStr
    evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]


class RequiredDocument(AgentSchema):
    name: NonEmptyStr
    submission_stage: NonEmptyStr | None
    evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]


class SupportCheck(AgentSchema):
    support_program: SupportProgramRef
    program_name: NonEmptyStr
    related_steps: list[ProcedureStepRef]
    match_status: SupportMatchStatus
    criteria: list[SupportCriterionResult]
    unknown_field_paths: list[CaseFieldKey]
    required_documents: list[RequiredDocument]
    application_channel: SourcedText | None
    application_url: SourcedText | None
    application_period: SourcedText | None
    source_version: NonEmptyStr | None
    freshness_status: FreshnessStatus
    checked_at: RuntimeDateTime
    reason_summary: NonEmptyStr
    evidence_refs: list[NonEmptyStr]

    @model_validator(mode="after")
    def validate_safety(self) -> SupportCheck:
        if self.freshness_status == FreshnessStatus.STALE:
            if self.match_status != SupportMatchStatus.STALE:
                raise ValueError("STALE evidence must produce STALE match status")
        elif self.match_status == SupportMatchStatus.STALE:
            raise ValueError("STALE match status requires STALE evidence")

        if (
            self.freshness_status == FreshnessStatus.UNKNOWN
            and self.match_status != SupportMatchStatus.UNVERIFIABLE
        ):
            raise ValueError("UNKNOWN freshness must produce UNVERIFIABLE match status")

        positive = {
            SupportMatchStatus.POSSIBLY_RELEVANT,
            SupportMatchStatus.NEEDS_CONFIRMATION,
        }
        if self.match_status in positive:
            if self.freshness_status != FreshnessStatus.CURRENT:
                raise ValueError(
                    "positive support comparison requires CURRENT evidence"
                )
            if not self.evidence_refs:
                raise ValueError("positive support comparison requires evidence")

        if self.match_status == SupportMatchStatus.NOT_RELEVANT:
            if self.freshness_status != FreshnessStatus.CURRENT:
                raise ValueError("NOT_RELEVANT requires CURRENT evidence")
            if not any(
                item.status == CriterionStatus.NOT_MET for item in self.criteria
            ):
                raise ValueError("NOT_RELEVANT requires a NOT_MET criterion")

        if len(set(self.unknown_field_paths)) != len(self.unknown_field_paths):
            raise ValueError("unknown_field_paths must be unique")
        return self


class SupportSearchSummary(AgentSchema):
    wiki_lookup: Literal["HIT", "MISS", "NOT_REQUESTED"]
    rag_used: StrictBool
    official_source_checked: StrictBool
    checked_at: RuntimeDateTime


class SupportCompletionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    NO_CANDIDATE = "NO_CANDIDATE"
    PARTIAL = "PARTIAL"


class SupportAnalysisResult(AgentSchema):
    """Complete success schema returned by ``SupportAgent.analyze``."""

    completion_status: SupportCompletionStatus = Field(
        description="Whether reviewed-program comparison completed or was partial."
    )
    support_checks: list[SupportCheck] = Field(
        description="Per-program, evidence-linked comparison results."
    )
    no_candidate_reason_code: UpperSnakeCode | None = Field(
        description="Machine code explaining an empty reviewed candidate set."
    )
    uncertainties: list[Uncertainty] = Field(
        description="Unknown inputs or source limits preserved for downstream review."
    )
    search_summary: SupportSearchSummary = Field(
        description="What reviewed lookup sources this call actually used."
    )
    evidence_records: list[EvidenceRecord] = Field(
        description="Closed Evidence set referenced by support checks."
    )
    based_on_snapshot_id: RuntimeUUID = Field(
        description="Case snapshot ID used for the comparison."
    )
    based_on_candidate_ids: list[RuntimeUUID] = Field(
        description="Fact overlay candidate IDs used in addition to the snapshot."
    )

    @model_validator(mode="after")
    def validate_completion(self) -> SupportAnalysisResult:
        if self.completion_status == SupportCompletionStatus.NO_CANDIDATE:
            if self.support_checks or self.no_candidate_reason_code is None:
                raise ValueError("NO_CANDIDATE requires no checks and a reason code")
        elif self.completion_status == SupportCompletionStatus.COMPLETE:
            if not self.support_checks or self.no_candidate_reason_code is not None:
                raise ValueError("COMPLETE requires checks and no no-candidate reason")
        else:
            if not self.uncertainties or self.no_candidate_reason_code is not None:
                raise ValueError("PARTIAL requires uncertainty and no reason code")
        _ensure_unique(
            self.support_checks,
            lambda item: item.support_program.support_program_id,
            "support_program_id",
        )
        if len(set(self.based_on_candidate_ids)) != len(self.based_on_candidate_ids):
            raise ValueError("based_on_candidate_ids must be unique")
        return self


class DecisionAuthority(StrEnum):
    USER = "USER"
    LANDLORD = "LANDLORD"
    OFFICIAL_AGENCY = "OFFICIAL_AGENCY"
    PROFESSIONAL = "PROFESSIONAL"
    UNKNOWN = "UNKNOWN"


class ProcedureCompletionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NO_RESULTS = "NO_RESULTS"


class ProcedureLookupGoal(StrEnum):
    BUSINESS_CLOSURE = "BUSINESS_CLOSURE"


class ProcedureSourcePolicy(StrEnum):
    OFFICIAL_ONLY = "OFFICIAL_ONLY"


class ProcedureSearchProvider(StrEnum):
    OFFICIAL_SOURCE_REGISTRY = "OFFICIAL_SOURCE_REGISTRY"
    GOOGLE_AGENT_SEARCH = "GOOGLE_AGENT_SEARCH"
    KAKAO_DAUM_WEB = "KAKAO_DAUM_WEB"


class ProcedureLookupInput(AgentSchema):
    """Complete request schema accepted by ``ProcedureLookupTool.lookup``."""

    lookup_goal: Literal[ProcedureLookupGoal.BUSINESS_CLOSURE] = Field(
        description="Fixed lookup goal for business-closure procedures."
    )
    search_queries: Annotated[
        list[NonEmptyStr],
        Field(
            min_length=1,
            max_length=4,
            description="Bounded, deduplicated queries selected by trusted Graph code.",
        ),
    ]
    as_of: date = Field(
        description="Lookup date copied into the result as request provenance."
    )
    locale: Literal["ko-KR"] = Field(
        description="Locale of the requested Korean official sources."
    )
    source_policy: Literal[ProcedureSourcePolicy.OFFICIAL_ONLY] = Field(
        description="Policy that permits only verified official source domains."
    )
    max_results_per_query: Annotated[
        StrictInt,
        Field(
            ge=1,
            le=10,
            description="Maximum provider candidates retained for each query.",
        ),
    ]
    based_on_snapshot_id: RuntimeUUID = Field(
        description="Case snapshot ID for which the procedure lookup was requested."
    )
    review_feedback: list[ReviewIssue] = Field(
        description="Blocking review issues supplied when this lookup is a rework."
    )

    @field_validator("search_queries")
    @classmethod
    def unique_search_queries(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("search queries must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("search_queries must be unique")
        return normalized


class ProcedureLookupWarning(AgentSchema):
    code: UpperSnakeCode
    message: NonEmptyStr


class ProcedureSourceDocument(AgentSchema):
    document_id: RuntimeUUID
    title: NonEmptyStr
    authority_name: NonEmptyStr
    canonical_url: NonEmptyStr
    source_domain: NonEmptyStr
    excerpt: Annotated[StrictStr, Field(min_length=1, max_length=6000)]
    published_at: AwareDatetime | None
    retrieved_at: RuntimeDateTime
    freshness_status: FreshnessStatus
    content_hash: Digest
    evidence_ref: NonEmptyStr
    search_query: NonEmptyStr
    discovery_provider: ProcedureSearchProvider

    @model_validator(mode="after")
    def validate_source_identity(self) -> ProcedureSourceDocument:
        parsed = urlsplit(self.canonical_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("procedure document URL must be absolute HTTPS")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError(
                "procedure document URL must not contain credentials or fragment"
            )
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("procedure document URL has an invalid port") from exc
        if port is not None:
            raise ValueError("canonical procedure document URL must omit its port")
        try:
            hostname = (
                parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
            )
        except UnicodeError as exc:
            raise ValueError("procedure document hostname is invalid") from exc
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise ValueError("procedure document URL must not use an IP literal")
        if (
            self.source_domain != hostname
            or parsed.netloc != hostname
            or not parsed.path
        ):
            raise ValueError(
                "source_domain and canonical URL must use one lowercase canonical host"
            )
        return self


class ProcedureProviderSearchSummary(AgentSchema):
    provider: ProcedureSearchProvider
    attempted_query_count: NonNegativeStrictInt
    successful_query_count: NonNegativeStrictInt
    failed_query_count: NonNegativeStrictInt
    provider_result_count: NonNegativeStrictInt

    @model_validator(mode="after")
    def validate_counts(self) -> ProcedureProviderSearchSummary:
        if self.successful_query_count + self.failed_query_count != (
            self.attempted_query_count
        ):
            raise ValueError("provider query outcomes must cover provider attempts")
        if self.successful_query_count == 0 and self.provider_result_count != 0:
            raise ValueError("provider results require a successful provider response")
        return self


class ProcedureSearchSummary(AgentSchema):
    provider_order: Annotated[
        list[ProcedureSearchProvider], Field(min_length=1, max_length=3)
    ]
    provider_summaries: Annotated[
        list[ProcedureProviderSearchSummary], Field(min_length=1, max_length=3)
    ]
    fallback_query_count: NonNegativeStrictInt
    requested_query_count: PositiveStrictInt
    successful_query_count: NonNegativeStrictInt
    failed_query_count: NonNegativeStrictInt
    provider_result_count: NonNegativeStrictInt
    official_candidate_count: NonNegativeStrictInt
    fetched_document_count: NonNegativeStrictInt
    rejected_result_count: NonNegativeStrictInt
    fetch_failure_count: NonNegativeStrictInt
    searched_at: RuntimeDateTime

    @model_validator(mode="after")
    def validate_counts(self) -> ProcedureSearchSummary:
        if len(set(self.provider_order)) != len(self.provider_order):
            raise ValueError("provider_order must be unique")
        allowed_orders = {
            (ProcedureSearchProvider.OFFICIAL_SOURCE_REGISTRY,),
            (
                ProcedureSearchProvider.OFFICIAL_SOURCE_REGISTRY,
                ProcedureSearchProvider.KAKAO_DAUM_WEB,
            ),
            (
                ProcedureSearchProvider.OFFICIAL_SOURCE_REGISTRY,
                ProcedureSearchProvider.GOOGLE_AGENT_SEARCH,
            ),
            (
                ProcedureSearchProvider.OFFICIAL_SOURCE_REGISTRY,
                ProcedureSearchProvider.KAKAO_DAUM_WEB,
                ProcedureSearchProvider.GOOGLE_AGENT_SEARCH,
            ),
            (ProcedureSearchProvider.GOOGLE_AGENT_SEARCH,),
            (ProcedureSearchProvider.KAKAO_DAUM_WEB,),
            (
                ProcedureSearchProvider.KAKAO_DAUM_WEB,
                ProcedureSearchProvider.GOOGLE_AGENT_SEARCH,
            ),
        }
        if tuple(self.provider_order) not in allowed_orders:
            raise ValueError(
                "provider_order must preserve official-registry, Kakao, Google policy"
            )
        summary_providers = [item.provider for item in self.provider_summaries]
        if summary_providers != self.provider_order:
            raise ValueError(
                "provider_summaries must match provider_order exactly and in order"
            )
        if (
            self.successful_query_count + self.failed_query_count
            != self.requested_query_count
        ):
            raise ValueError("query outcome counts must match requested_query_count")
        if self.fetched_document_count > self.official_candidate_count:
            raise ValueError("fetched documents cannot exceed official candidates")
        if not any(item.successful_query_count for item in self.provider_summaries):
            raise ValueError(
                "a procedure result requires at least one successful provider response"
            )
        if any(
            item.attempted_query_count > self.requested_query_count
            for item in self.provider_summaries
        ):
            raise ValueError("provider attempts cannot exceed requested queries")
        first = self.provider_summaries[0]
        if first.attempted_query_count != self.requested_query_count:
            raise ValueError("the first source provider must attempt every query")
        for previous, current in zip(
            self.provider_summaries,
            self.provider_summaries[1:],
            strict=False,
        ):
            if current.attempted_query_count > previous.attempted_query_count:
                raise ValueError(
                    "a fallback provider cannot attempt more queries than its predecessor"
                )
        expected_fallbacks = (
            self.provider_summaries[1].attempted_query_count
            if len(self.provider_summaries) > 1
            else 0
        )
        if self.fallback_query_count != expected_fallbacks:
            raise ValueError(
                "fallback count must match queries passed beyond the first provider"
            )
        if self.provider_result_count != sum(
            item.provider_result_count for item in self.provider_summaries
        ):
            raise ValueError("aggregate provider results must match provider summaries")
        if (
            self.official_candidate_count + self.rejected_result_count
            != self.provider_result_count
        ):
            raise ValueError(
                "official and rejected result counts must cover provider results"
            )
        if (
            self.fetched_document_count + self.fetch_failure_count
            > self.official_candidate_count
        ):
            raise ValueError("fetch outcomes cannot exceed official candidate count")
        return self


class ProcedureLookupResult(AgentSchema):
    """Complete success schema returned by ``ProcedureLookupTool.lookup``."""

    completion_status: ProcedureCompletionStatus = Field(
        description="Whether official source retrieval completed, was partial, or empty."
    )
    lookup_id: RuntimeUUID = Field(
        description="Unique runtime ID for this lookup result."
    )
    documents: list[ProcedureSourceDocument] = Field(
        description="Fetched and verified official procedure source documents."
    )
    search_summary: ProcedureSearchSummary = Field(
        description="Provider attempts, fallback use, and source filtering counts."
    )
    warnings: list[ProcedureLookupWarning] = Field(
        description="Non-fatal source retrieval warnings."
    )
    evidence_records: list[EvidenceRecord] = Field(
        description="One official-document Evidence record for every returned document."
    )
    based_on_snapshot_id: RuntimeUUID = Field(
        description="Case snapshot ID copied from the lookup request."
    )
    as_of: date = Field(description="Lookup date copied from the request.")

    @model_validator(mode="after")
    def validate_result(self) -> ProcedureLookupResult:
        _ensure_unique(self.documents, lambda item: item.document_id, "document_id")
        _ensure_unique(self.documents, lambda item: item.canonical_url, "canonical_url")
        _ensure_unique(
            self.evidence_records, lambda item: item.evidence_id, "evidence_id"
        )
        if self.search_summary.fetched_document_count != len(self.documents):
            raise ValueError("fetched_document_count must match documents")
        if len(self.documents) != len(self.evidence_records):
            raise ValueError("each document must have exactly one evidence record")
        evidence_by_id = {item.evidence_id: item for item in self.evidence_records}
        provider_summaries = {
            item.provider: item for item in self.search_summary.provider_summaries
        }
        document_counts: dict[ProcedureSearchProvider, int] = {}
        for document in self.documents:
            provider_summary = provider_summaries.get(document.discovery_provider)
            if (
                provider_summary is None
                or provider_summary.successful_query_count == 0
                or provider_summary.provider_result_count == 0
            ):
                raise ValueError(
                    "procedure document provider must have a successful search result"
                )
            document_counts[document.discovery_provider] = (
                document_counts.get(document.discovery_provider, 0) + 1
            )
            evidence = evidence_by_id.get(document.evidence_ref)
            if evidence is None:
                raise ValueError("procedure document has unresolved evidence_ref")
            if (
                evidence.source_type != EvidenceSourceType.OFFICIAL_DOCUMENT
                or evidence.source_ref != document.canonical_url
                or evidence.excerpt != document.excerpt
                or evidence.published_at != document.published_at
                or evidence.retrieved_at != document.retrieved_at
                or evidence.freshness_status != document.freshness_status
                or evidence.content_hash != document.content_hash
            ):
                raise ValueError(
                    "procedure document and evidence must describe one source"
                )
        for provider, document_count in document_counts.items():
            if document_count > provider_summaries[provider].provider_result_count:
                raise ValueError(
                    "procedure documents cannot exceed their provider result count"
                )
        failures = (
            self.search_summary.failed_query_count
            + self.search_summary.fetch_failure_count
        )
        if self.completion_status == ProcedureCompletionStatus.COMPLETE:
            if not self.documents or failures:
                raise ValueError("COMPLETE requires documents and no request failures")
        elif self.completion_status == ProcedureCompletionStatus.NO_RESULTS:
            if (
                self.documents
                or failures
                or self.search_summary.official_candidate_count != 0
            ):
                raise ValueError(
                    "NO_RESULTS requires successful lookup with no official candidates"
                )
        elif failures == 0:
            raise ValueError("PARTIAL requires at least one query or fetch failure")
        return self


class ProcedureRelevance(StrEnum):
    RELEVANT = "RELEVANT"
    POSSIBLY_RELEVANT = "POSSIBLY_RELEVANT"
    UNDETERMINED = "UNDETERMINED"


class ProcedureFinding(AgentSchema):
    finding_id: RuntimeUUID
    procedure_step: ProcedureStepRef
    step_name: NonEmptyStr
    summary: SourcedText
    relevance: ProcedureRelevance
    current_status: ProcedureProgressStatus | None
    decision_authority: DecisionAuthority
    requires_confirmation: Literal[True]
    required_actions: list[SourcedText]
    required_documents: list[RequiredDocument]
    application_channel: SourcedText | None
    application_url: SourcedText | None
    deadline: SourcedText | None
    evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_evidence_refs(self) -> ProcedureFinding:
        refs = [*self.summary.evidence_refs]
        refs.extend(ref for item in self.required_actions for ref in item.evidence_refs)
        refs.extend(
            ref for item in self.required_documents for ref in item.evidence_refs
        )
        for item in (self.application_channel, self.application_url, self.deadline):
            if item is not None:
                refs.extend(item.evidence_refs)
        if set(refs) != set(self.evidence_refs):
            raise ValueError(
                "procedure finding evidence_refs must equal its detail evidence union"
            )
        return self


class Blocker(AgentSchema):
    blocker_code: UpperSnakeCode
    title: NonEmptyStr
    description: NonEmptyStr
    evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]


BlockerDraft = Blocker


class ProcedureActionTarget(AgentSchema):
    target_kind: Literal["PROCEDURE"]
    procedure_step: ProcedureStepRef


class SupportActionTarget(AgentSchema):
    target_kind: Literal["SUPPORT_PROGRAM"]
    support_program: SupportProgramRef


NextActionTarget: TypeAlias = Annotated[
    ProcedureActionTarget | SupportActionTarget,
    Field(discriminator="target_kind"),
]


class NextAction(AgentSchema):
    action_code: UpperSnakeCode
    sequence: PositiveStrictInt
    title: NonEmptyStr
    reason: NonEmptyStr
    questions_to_ask: list[NonEmptyStr]
    target: NextActionTarget
    evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]


NextActionDraft = NextAction


class DecisionType(StrEnum):
    ACTION = "ACTION"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"
    CASE_COMPLETE = "CASE_COMPLETE"


class ActionDecisionDraft(AgentSchema):
    decision_type: Literal[DecisionType.ACTION]
    draft_id: RuntimeUUID
    draft_version: PositiveStrictInt
    selection_summary: NonEmptyStr
    requires_human: StrictBool
    evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]
    based_on_call_ids: Annotated[list[RuntimeUUID], Field(min_length=1)]
    created_at: RuntimeDateTime
    blocker: Blocker
    next_action: NextAction
    questions_for_user: list[NonEmptyStr]

    @field_validator("questions_for_user")
    @classmethod
    def action_has_no_user_question_branch(cls, value: list[str]) -> list[str]:
        if value:
            raise ValueError("ACTION questions_for_user must be []")
        return value


class NeedsMoreInfoDecisionDraft(AgentSchema):
    decision_type: Literal[DecisionType.NEEDS_MORE_INFO]
    draft_id: RuntimeUUID
    draft_version: PositiveStrictInt
    selection_summary: NonEmptyStr
    requires_human: Literal[True]
    evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]
    based_on_call_ids: Annotated[list[RuntimeUUID], Field(min_length=1)]
    created_at: RuntimeDateTime
    blocker: Blocker
    next_action: None
    questions_for_user: Annotated[list[NonEmptyStr], Field(min_length=1)]


class CaseCompleteDecisionDraft(AgentSchema):
    decision_type: Literal[DecisionType.CASE_COMPLETE]
    draft_id: RuntimeUUID
    draft_version: PositiveStrictInt
    selection_summary: NonEmptyStr
    requires_human: Literal[False]
    evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]
    based_on_call_ids: Annotated[list[RuntimeUUID], Field(min_length=1)]
    created_at: RuntimeDateTime
    blocker: None
    next_action: None
    questions_for_user: list[NonEmptyStr]

    @field_validator("questions_for_user")
    @classmethod
    def complete_has_no_questions(cls, value: list[str]) -> list[str]:
        if value:
            raise ValueError("CASE_COMPLETE questions_for_user must be []")
        return value


DecisionDraft: TypeAlias = Annotated[
    ActionDecisionDraft | NeedsMoreInfoDecisionDraft | CaseCompleteDecisionDraft,
    Field(discriminator="decision_type"),
]


class ProcedureProgressChangeCandidate(AgentSchema):
    candidate_id: RuntimeUUID
    procedure_step: ProcedureStepRef
    before_status: ProcedureProgressStatus | None
    proposed_status: ProcedureProgressStatus
    reason_summary: NonEmptyStr
    execution_evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]
    procedure_analysis_call_id: RuntimeUUID

    @model_validator(mode="after")
    def validate_forward_transition(self) -> ProcedureProgressChangeCandidate:
        order = {
            None: -1,
            ProcedureProgressStatus.NOT_STARTED: 0,
            ProcedureProgressStatus.IN_PROGRESS: 1,
            ProcedureProgressStatus.COMPLETED: 2,
        }
        if order[self.proposed_status] <= order[self.before_status]:
            raise ValueError("procedure progress change must move forward")
        return self


class SupportMatchUpdateCandidate(AgentSchema):
    candidate_id: RuntimeUUID
    support_check: SupportCheck
    source_call_id: RuntimeUUID


class CaseStatusChangeCandidate(AgentSchema):
    candidate_id: RuntimeUUID
    before_status: Literal[CaseStatus.IN_PROGRESS]
    proposed_status: Literal[CaseStatus.COMPLETED]
    reason_summary: NonEmptyStr
    evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]


class MutationSet(AgentSchema):
    fact_changes: list[FactChangeCandidate]
    procedure_progress_changes: list[ProcedureProgressChangeCandidate]
    support_match_updates: list[SupportMatchUpdateCandidate]
    case_status_change: CaseStatusChangeCandidate | None

    @model_validator(mode="after")
    def validate_uniqueness(self) -> MutationSet:
        all_candidates: list[Any] = [
            *self.fact_changes,
            *self.procedure_progress_changes,
            *self.support_match_updates,
        ]
        if self.case_status_change is not None:
            all_candidates.append(self.case_status_change)
        _ensure_unique(all_candidates, lambda item: item.candidate_id, "candidate_id")
        _ensure_unique(
            self.fact_changes, lambda item: item.field_path, "fact field_path"
        )
        _ensure_unique(
            self.procedure_progress_changes,
            lambda item: item.procedure_step.procedure_step_id,
            "procedure_step_id",
        )
        _ensure_unique(
            self.support_match_updates,
            lambda item: item.support_check.support_program.support_program_id,
            "support_program_id",
        )
        return self


class ClaimType(StrEnum):
    SUPPORT_PROGRAM = "SUPPORT_PROGRAM"
    AMOUNT = "AMOUNT"
    DATE_OR_DEADLINE = "DATE_OR_DEADLINE"
    ELIGIBILITY = "ELIGIBILITY"
    LEGAL = "LEGAL"
    TAX = "TAX"
    PROCEDURE = "PROCEDURE"


class GroundedClaim(AgentSchema):
    claim_id: RuntimeUUID
    claim_type: ClaimType
    target_path: JsonPointer
    text: NonEmptyStr
    assertion_level: Literal["INFORMATION", "NEEDS_CONFIRMATION"]
    evidence_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]

    @model_validator(mode="after")
    def eligibility_needs_confirmation(self) -> GroundedClaim:
        if (
            self.claim_type == ClaimType.ELIGIBILITY
            and self.assertion_level != "NEEDS_CONFIRMATION"
        ):
            raise ValueError("eligibility claims always need confirmation")
        return self


class SupervisorDraft(AgentSchema):
    """Complete success schema returned by ``SupervisorAgent.draft``."""

    decision: DecisionDraft = Field(
        description="Exactly one Blocker/Next Action or needs-more-information decision."
    )
    mutations: MutationSet = Field(
        description="Uncommitted Case changes that require a matching Review PASS."
    )
    grounded_claims: list[GroundedClaim] = Field(
        description="Visible high-risk claims bound to exact Evidence records."
    )
    source_call_ids: Annotated[
        list[RuntimeUUID],
        Field(
            min_length=1,
            description="Exact lower-component calls used to build this draft.",
        ),
    ]

    @model_validator(mode="after")
    def validate_decision_and_sources(self) -> SupervisorDraft:
        if len(set(self.source_call_ids)) != len(self.source_call_ids):
            raise ValueError("source_call_ids must be unique")
        if set(self.source_call_ids) != set(self.decision.based_on_call_ids):
            raise ValueError(
                "source_call_ids must exactly match decision.based_on_call_ids"
            )
        if self.decision.decision_type == DecisionType.CASE_COMPLETE:
            if self.mutations.case_status_change is None:
                raise ValueError("CASE_COMPLETE requires a case status change")
        elif self.mutations.case_status_change is not None:
            raise ValueError("only CASE_COMPLETE may include a case status change")
        return self

    @property
    def blocker(self) -> Blocker | None:
        return self.decision.blocker

    @property
    def next_action(self) -> NextAction | None:
        return self.decision.next_action


class CaseCreatedTrigger(AgentSchema):
    trigger_type: Literal["CASE_CREATED"]
    input_event_id: NonEmptyStr
    client_event_id: NonEmptyStr | None
    input: RedactedInput
    submitted_at: AwareDatetime

    @model_validator(mode="after")
    def validate_event(self) -> CaseCreatedTrigger:
        if self.input.input_event_id != self.input_event_id:
            raise ValueError("trigger and input event IDs must match")
        return self


class ResultSubmittedTrigger(AgentSchema):
    trigger_type: Literal["RESULT_SUBMITTED"]
    input_event_id: NonEmptyStr
    client_event_id: NonEmptyStr | None
    input: RedactedInput
    submitted_at: AwareDatetime

    @model_validator(mode="after")
    def validate_event(self) -> ResultSubmittedTrigger:
        if self.input.input_event_id != self.input_event_id:
            raise ValueError("trigger and input event IDs must match")
        return self


class SupportRefreshTrigger(AgentSchema):
    trigger_type: Literal["SUPPORT_REFRESH"]
    input_event_id: NonEmptyStr
    client_event_id: NonEmptyStr | None
    support_programs: Annotated[list[SupportProgramRef], Field(min_length=1)]
    as_of: date


RunTrigger: TypeAlias = Annotated[
    CaseCreatedTrigger | ResultSubmittedTrigger | SupportRefreshTrigger,
    Field(discriminator="trigger_type"),
]


class AgentGraphInput(AgentSchema):
    """Complete public request schema accepted by ``AgentGraph.run``."""

    trigger: RunTrigger = Field(
        description="Event that starts a first plan, replanning, or support refresh."
    )
    case_snapshot: CaseSnapshot = Field(
        description="Immutable Case read view used throughout this Graph run."
    )
    trace_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Optional caller correlation identifier propagated to invocation metadata; "
            "it is not a planning-decision input."
        ),
    )


class ReviewIssueCode(StrEnum):
    CASE_MISMATCH = "CASE_MISMATCH"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    OVERCONFIDENT_LANGUAGE = "OVERCONFIDENT_LANGUAGE"
    INFEASIBLE_ACTION = "INFEASIBLE_ACTION"
    HUMAN_CONFIRMATION_OMITTED = "HUMAN_CONFIRMATION_OMITTED"
    AMBIGUOUS_LANGUAGE = "AMBIGUOUS_LANGUAGE"
    PROCEDURE_CONFLICT = "PROCEDURE_CONFLICT"
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"


class ReviewIssue(AgentSchema):
    issue_code: ReviewIssueCode
    category: Literal[
        "FACTUALITY",
        "EVIDENCE",
        "PROCEDURE",
        "SAFETY",
        "ACTIONABILITY",
        "LANGUAGE",
        "CONTRACT",
    ]
    severity: Literal["BLOCKING", "WARNING"]
    target_component: Literal[
        Component.SUPERVISOR,
        Component.INFO_AGENT,
        Component.SUPPORT_AGENT,
        Component.PROCEDURE_TOOL,
    ]
    target_call_id: RuntimeUUID | None
    target_path: JsonPointer
    reason_summary: NonEmptyStr
    evidence_refs: list[NonEmptyStr]

    @model_validator(mode="after")
    def dangerous_issues_are_blocking(self) -> ReviewIssue:
        always_blocking = {
            ReviewIssueCode.UNSUPPORTED_CLAIM,
            ReviewIssueCode.MISSING_EVIDENCE,
            ReviewIssueCode.STALE_EVIDENCE,
            ReviewIssueCode.PROCEDURE_CONFLICT,
            ReviewIssueCode.CONTRACT_VIOLATION,
        }
        if self.issue_code in always_blocking and self.severity != "BLOCKING":
            raise ValueError(f"{self.issue_code.value} must be BLOCKING")
        return self


class MissingEvidence(AgentSchema):
    claim_path: JsonPointer
    required_source_types: Annotated[list[EvidenceSourceType], Field(min_length=1)]
    reason_summary: NonEmptyStr


ReviewSourceOutput: TypeAlias = (
    InfoAnalysisResult | SupportAnalysisResult | ProcedureLookupResult
)


class ReviewSourceResult(AgentSchema):
    meta: InvocationMeta
    output_digest: Digest
    output: ReviewSourceOutput

    @model_validator(mode="after")
    def component_matches_output(self) -> ReviewSourceResult:
        expected_type: dict[Component, type[AgentSchema]] = {
            Component.INFO_AGENT: InfoAnalysisResult,
            Component.SUPPORT_AGENT: SupportAnalysisResult,
            Component.PROCEDURE_TOOL: ProcedureLookupResult,
        }
        expected = expected_type.get(self.meta.component)
        if expected is None or not isinstance(self.output, expected):
            raise ValueError("source result component does not match output type")
        if self.output_digest != canonical_digest(self.output):
            raise ValueError("source output_digest does not match output")
        return self


class SupervisorAgentInput(AgentSchema):
    """Complete request schema accepted by ``SupervisorAgent.draft``."""

    trigger: RunTrigger = Field(
        description="Graph trigger whose planning decision is being drafted."
    )
    case_snapshot: CaseSnapshot = Field(
        description="Immutable Case read view shared by every supplied source result."
    )
    source_results: Annotated[
        list[ReviewSourceResult],
        Field(
            min_length=1,
            description="Digest-bound outputs from the required lower components.",
        ),
    ]
    draft_version: PositiveStrictInt = Field(
        default=1,
        description="One-based Supervisor draft attempt within this Graph run.",
    )
    review_feedback: list[ReviewIssue] = Field(
        default_factory=list,
        description="Blocking issues from the prior Review Tool attempt.",
    )
    fact_overlays: list[FactChangeCandidate] | None = Field(
        default=None,
        description=(
            "Graph-built uncommitted Info fact changes, or null when the Supervisor "
            "must derive them from source results for a direct call."
        ),
    )
    previous_draft: SupervisorDraft | None = Field(
        default=None,
        description="Prior rejected draft supplied only for bounded review rework.",
    )

    @model_validator(mode="after")
    def validate_sources(self) -> SupervisorAgentInput:
        call_ids = [item.meta.call_id for item in self.source_results]
        if len(set(call_ids)) != len(call_ids):
            raise ValueError("Supervisor source call IDs must be unique")
        run_ids = {item.meta.run_id for item in self.source_results}
        if len(run_ids) != 1:
            raise ValueError("Supervisor source results must belong to one run")
        for source in self.source_results:
            if source.meta.case_id != self.case_snapshot.case_id:
                raise ValueError("Supervisor source case must match its snapshot")
            if source.output.based_on_snapshot_id != self.case_snapshot.snapshot_id:
                raise ValueError("Supervisor source snapshot must match its snapshot")
        if self.fact_overlays is not None:
            _ensure_unique(
                self.fact_overlays,
                lambda item: item.candidate_id,
                "Supervisor fact overlay candidate_id",
            )
            _ensure_unique(
                self.fact_overlays,
                lambda item: item.field_path,
                "Supervisor fact overlay field_path",
            )
        return self


class ReviewSubject(AgentSchema):
    """Complete request schema accepted by ``ReviewTool.review``."""

    schema_version: Literal["agent-io/2.0"] = Field(
        description="Version of the Agent/Tool contract represented by this subject."
    )
    review_subject_id: RuntimeUUID = Field(
        description="Unique runtime identifier for this immutable review package."
    )
    review_attempt: Annotated[
        StrictInt,
        Field(
            ge=1,
            le=3,
            description="One-based Review Tool attempt within the Graph run.",
        ),
    ]
    run_id: RuntimeUUID = Field(
        description="Graph run identifier shared by all source invocations."
    )
    case_id: PositiveStrictInt = Field(
        description="Case identifier that must match the embedded snapshot."
    )
    trigger: RunTrigger = Field(
        description="Event that initiated the plan under review."
    )
    snapshot: CaseSnapshot = Field(
        description="Immutable Case baseline used by every reviewed component."
    )
    source_results: Annotated[
        list[ReviewSourceResult],
        Field(
            min_length=1,
            description="Digest-bound lower component outputs used by the draft.",
        ),
    ]
    supervisor_draft: SupervisorDraft = Field(
        description="Supervisor output being independently reviewed."
    )
    subject_digest: Digest = Field(
        description="Canonical digest binding the entire review package."
    )

    @model_validator(mode="after")
    def validate_subject(self) -> ReviewSubject:
        self.assert_integrity()
        return self

    def assert_integrity(self) -> None:
        """Reject any structural or nested change made after subject creation."""

        if self.case_id != self.snapshot.case_id:
            raise ValueError("review case_id must match snapshot")
        call_ids = [item.meta.call_id for item in self.source_results]
        if len(set(call_ids)) != len(call_ids):
            raise ValueError("source result call IDs must be unique")
        if set(call_ids) != set(self.supervisor_draft.source_call_ids):
            raise ValueError("source results must exactly match supervisor sources")
        for result in self.source_results:
            if result.meta.run_id != self.run_id or result.meta.case_id != self.case_id:
                raise ValueError("source result run/case does not match review subject")
            based_on_snapshot_id = getattr(result.output, "based_on_snapshot_id", None)
            if based_on_snapshot_id != self.snapshot.snapshot_id:
                raise ValueError("source result snapshot does not match review subject")
            if result.output_digest != canonical_digest(result.output):
                raise ValueError(
                    "source output changed after its digest was calculated"
                )
        if self.subject_digest != self.calculate_digest():
            raise ValueError("subject_digest does not match review subject")

    @model_serializer(mode="wrap")
    def serialize_with_integrity(self, handler: Any) -> Any:
        self.assert_integrity()
        return handler(self)

    def calculate_digest(self) -> str:
        return canonical_digest(self, exclude={"subject_digest"})

    @classmethod
    def create(cls, **values: Any) -> ReviewSubject:
        """Construct a subject and inject its digest after all other IDs exist."""

        draft = cls.model_construct(
            **values,
            subject_digest="sha256:" + "0" * 64,
        )
        values["subject_digest"] = draft.calculate_digest()
        return cls.model_validate(values)


class ReviewVerdict(StrEnum):
    PASS = "PASS"
    REVISE = "REVISE"


class ReviewResult(AgentSchema):
    """Complete success schema returned by ``ReviewTool.review``."""

    reviewed_subject_id: RuntimeUUID = Field(
        description="Identifier of the exact ReviewSubject that was checked."
    )
    reviewed_subject_digest: Digest = Field(
        description="Digest of the exact immutable ReviewSubject that was checked."
    )
    verdict: ReviewVerdict = Field(
        description="PASS for release or REVISE for bounded component rework."
    )
    issues: list[ReviewIssue] = Field(
        description="Review findings with severity, owner, path, reason, and evidence."
    )
    missing_evidence: list[MissingEvidence] = Field(
        description="Supervisor claim paths that require additional evidence."
    )
    recommended_rework_targets: list[
        Literal[
            Component.SUPERVISOR,
            Component.INFO_AGENT,
            Component.SUPPORT_AGENT,
            Component.PROCEDURE_TOOL,
        ]
    ] = Field(description="Components that must be re-executed before another review.")
    resolution_reason: NonEmptyStr = Field(
        description="Human-readable reason for the PASS or REVISE verdict."
    )

    @model_validator(mode="after")
    def enforce_review_gate(self) -> ReviewResult:
        blocking = any(issue.severity == "BLOCKING" for issue in self.issues)
        if self.verdict == ReviewVerdict.PASS:
            if blocking or self.missing_evidence or self.recommended_rework_targets:
                raise ValueError(
                    "PASS cannot contain blocking issues, missing evidence, or rework"
                )
        elif not blocking and not self.missing_evidence:
            raise ValueError("REVISE requires a blocking issue or missing evidence")
        return self


class ReviewProof(AgentSchema):
    review_call_id: RuntimeUUID
    run_id: RuntimeUUID
    case_id: PositiveStrictInt
    snapshot_id: RuntimeUUID
    case_version: PositiveStrictInt | None
    review_subject_id: RuntimeUUID
    reviewed_subject_digest: Digest
    verdict: Literal[ReviewVerdict.PASS]
    reviewed_at: RuntimeDateTime

    @classmethod
    def from_passed_review(
        cls,
        *,
        subject: ReviewSubject,
        result: ReviewResult,
        review_meta: InvocationMeta,
        reviewed_at: datetime,
    ) -> ReviewProof:
        """Issue proof only for a matching, successful Review Tool response."""

        subject.assert_integrity()
        if review_meta.component != Component.REVIEW_TOOL:
            raise ValueError("review proof requires REVIEW_TOOL invocation metadata")
        if (
            review_meta.run_id != subject.run_id
            or review_meta.case_id != subject.case_id
        ):
            raise ValueError("review invocation does not match review subject")
        if result.verdict != ReviewVerdict.PASS:
            raise ValueError("review proof can only be issued for PASS")
        if (
            result.reviewed_subject_id != subject.review_subject_id
            or result.reviewed_subject_digest != subject.subject_digest
        ):
            raise ValueError("review result does not match review subject")
        return cls(
            review_call_id=review_meta.call_id,
            run_id=subject.run_id,
            case_id=subject.case_id,
            snapshot_id=subject.snapshot.snapshot_id,
            case_version=subject.snapshot.case_version,
            review_subject_id=subject.review_subject_id,
            reviewed_subject_digest=subject.subject_digest,
            verdict=ReviewVerdict.PASS,
            reviewed_at=reviewed_at,
        )


class ReviewedPlanOutcome(AgentSchema):
    """AgentGraph result released only after a matching Review Tool PASS."""

    outcome_type: Literal["REVIEWED_PLAN"] = Field(
        description="Discriminator for a plan that passed independent review."
    )
    review_subject: ReviewSubject = Field(
        description="Exact immutable package that was supplied to the Review Tool."
    )
    review_proof: ReviewProof = Field(
        description="Runtime proof binding the matching PASS to this review subject."
    )

    @model_validator(mode="after")
    def validate_proof(self) -> ReviewedPlanOutcome:
        self.assert_integrity()
        return self

    def assert_integrity(self) -> None:
        """Recheck the reviewed payload and proof immediately before release."""

        subject = self.review_subject
        proof = self.review_proof
        subject.assert_integrity()
        expected = (
            subject.run_id,
            subject.case_id,
            subject.snapshot.snapshot_id,
            subject.snapshot.case_version,
            subject.review_subject_id,
            subject.subject_digest,
        )
        actual = (
            proof.run_id,
            proof.case_id,
            proof.snapshot_id,
            proof.case_version,
            proof.review_subject_id,
            proof.reviewed_subject_digest,
        )
        if actual != expected:
            raise ValueError("review proof does not match review subject")

    @model_serializer(mode="wrap")
    def serialize_with_integrity(self, handler: Any) -> Any:
        self.assert_integrity()
        return handler(self)


class ConflictOutcome(AgentSchema):
    """AgentGraph result that pauses only the current run for user confirmation."""

    outcome_type: Literal["CONFLICT"] = Field(
        description="Discriminator for confirmed-Case fact conflicts."
    )
    run_id: RuntimeUUID = Field(
        description="Graph run identifier that produced these conflicts."
    )
    case_id: PositiveStrictInt = Field(
        description="Case identifier copied from the input snapshot."
    )
    trigger: RunTrigger = Field(
        description="Event that exposed the conflicting statements."
    )
    snapshot_id: RuntimeUUID = Field(
        description="Immutable snapshot identifier against which conflicts were found."
    )
    case_version: PositiveStrictInt | None = Field(
        description="Optional Case version copied from the input snapshot."
    )
    conflicts: Annotated[
        list[ConflictCandidate],
        Field(
            min_length=1,
            description="User statements that conflict with confirmed snapshot facts.",
        ),
    ]
    message_code: Literal["CONFIRM_CONFLICT"] = Field(
        description="Caller instruction to request explicit user confirmation."
    )

    @model_validator(mode="after")
    def validate_conflicts(self) -> ConflictOutcome:
        _ensure_unique(self.conflicts, lambda item: item.conflict_ref, "conflict_ref")
        _ensure_unique(self.conflicts, lambda item: item.candidate_id, "candidate_id")
        for conflict in self.conflicts:
            if (
                conflict.snapshot_id != self.snapshot_id
                or conflict.case_version != self.case_version
            ):
                raise ValueError("conflict does not match outcome snapshot/version")
        return self


class SafeFailureOutcome(AgentSchema):
    """Fail-closed AgentGraph result that never exposes an unreviewed draft."""

    outcome_type: Literal["SAFE_FAILURE"] = Field(
        description="Discriminator for a fail-closed Graph result."
    )
    run_id: RuntimeUUID = Field(
        description="Graph run identifier in which the failure occurred."
    )
    case_id: PositiveStrictInt = Field(
        description="Case identifier copied from the input snapshot."
    )
    trigger: RunTrigger = Field(
        description="Event whose processing ended in this safe failure."
    )
    snapshot_id: RuntimeUUID = Field(
        description="Immutable snapshot identifier used by the failed run."
    )
    case_version: PositiveStrictInt | None = Field(
        description="Optional Case version copied from the input snapshot."
    )
    failure_code: Literal[
        "REVIEW_RETRY_EXHAUSTED",
        "COMPONENT_UNAVAILABLE",
        "STRUCTURED_OUTPUT_FAILED",
        "LOOP_LIMIT_REACHED",
    ] = Field(description="Bounded machine classification of the Graph failure.")
    message_code: UpperSnakeCode = Field(
        description="Safe caller-facing machine message code."
    )
    recovery_action_code: Literal[
        "RETRY", "RESUBMIT_INPUT", "CONTACT_SUPPORT", "NONE"
    ] = Field(description="Permitted caller recovery action for this failure.")
    requested_field_paths: list[CaseFieldKey] = Field(
        description="Canonical Case fields requested for a future resubmission."
    )
    retryable: StrictBool = Field(
        description="Whether retrying the same operation may succeed."
    )
    failed_component: Component | None = Field(
        description="Component that failed, or null for a Graph-level failure."
    )
    trace_id: NonEmptyStr | None = Field(
        description="Optional caller trace identifier copied from AgentGraphInput."
    )


AgentRunOutcome: TypeAlias = Annotated[
    ReviewedPlanOutcome | ConflictOutcome | SafeFailureOutcome,
    Field(discriminator="outcome_type"),
]

# Public Graph output name.  The discriminated union preserves the existing
# wire shape while making the Graph input/output pair explicit to callers.
AgentGraphOutput: TypeAlias = Annotated[
    AgentRunOutcome,
    Field(
        title="AgentGraphOutput",
        description=(
            "Complete AgentGraph result: a reviewed plan, a user-confirmable "
            "conflict, or a fail-closed safe failure."
        ),
    ),
]


def _canonical_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical_value(_model_field_values(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float):
        raise TypeError("floats are not allowed in canonical Agent contract digests")
    return value


def _model_field_values(
    value: BaseModel,
    *,
    exclude: set[str] | None = None,
) -> dict[str, Any]:
    """Read declared fields without invoking serialization integrity hooks."""

    excluded = exclude or set()
    return {
        field_name: getattr(value, field_name)
        for field_name in type(value).model_fields
        if field_name not in excluded
    }


def canonical_digest(value: BaseModel, *, exclude: set[str] | None = None) -> str:
    """Return the deterministic digest used by ReviewSource/ReviewSubject."""

    payload = _model_field_values(value, exclude=exclude)
    canonical = json.dumps(
        _canonical_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


# Resolve feedback/result forward references after ReviewIssue exists.
InfoAnalysisInput.model_rebuild()
InfoAnalysisResult.model_rebuild()
ProcedureLookupInput.model_rebuild()
DiscoverSupportInput.model_rebuild()
CheckSpecificSupportInput.model_rebuild()
RefreshSupportInput.model_rebuild()


__all__ = [
    "CASE_FIELD_SPECS",
    "SIMULATION_CONFLICT_REF_PREFIX",
    "ActionDecisionDraft",
    "AgentGraphInput",
    "AgentGraphOutput",
    "AgentRunOutcome",
    "AgentSchema",
    "Blocker",
    "BlockerDraft",
    "CaseCompleteDecisionDraft",
    "CaseCreatedTrigger",
    "CaseFact",
    "CaseFieldKey",
    "CaseSnapshot",
    "CaseStatus",
    "CaseStatusChangeCandidate",
    "CheckSpecificSupportInput",
    "ClaimType",
    "Component",
    "ComponentError",
    "ComponentErrorCode",
    "ComponentFailure",
    "ComponentRequest",
    "ComponentSuccess",
    "ComponentWarning",
    "ConflictCandidate",
    "ConflictOutcome",
    "CriterionStatus",
    "DecisionAuthority",
    "DecisionDraft",
    "DecisionType",
    "Digest",
    "DiscoverSupportInput",
    "EvidenceRecord",
    "EvidenceSourceType",
    "FactCandidate",
    "FactChangeCandidate",
    "FactChangeSourceType",
    "FactOperation",
    "FactStatus",
    "FactValueType",
    "FreshnessStatus",
    "GroundedClaim",
    "InfoAnalysisInput",
    "InfoAnalysisResult",
    "InfoCompletionStatus",
    "InputSourceType",
    "InvocationMeta",
    "JsonPointer",
    "KnownProcedureStep",
    "MissingEvidence",
    "MissingField",
    "MissingFieldBlock",
    "MutationSet",
    "NeedsMoreInfoDecisionDraft",
    "NextAction",
    "NextActionDraft",
    "NextActionTarget",
    "NonNullStrictScalar",
    "PlanningContext",
    "ProcedureActionTarget",
    "ProcedureCompletionStatus",
    "ProcedureFinding",
    "ProcedureLookupGoal",
    "ProcedureLookupInput",
    "ProcedureLookupResult",
    "ProcedureLookupWarning",
    "ProcedureProgress",
    "ProcedureProgressChangeCandidate",
    "ProcedureProgressObservation",
    "ProcedureProgressStatus",
    "ProcedureProviderSearchSummary",
    "ProcedureRelevance",
    "ProcedureSearchProvider",
    "ProcedureSearchSummary",
    "ProcedureSourceDocument",
    "ProcedureSourcePolicy",
    "ProcedureStepRef",
    "QuestionCandidate",
    "RedactedInput",
    "Redaction",
    "RedactionType",
    "RefreshSupportInput",
    "RequiredDocument",
    "ResultSubmittedTrigger",
    "ReviewIssue",
    "ReviewIssueCode",
    "ReviewProof",
    "ReviewResult",
    "ReviewSourceOutput",
    "ReviewSourceResult",
    "ReviewSubject",
    "ReviewVerdict",
    "ReviewedPlanOutcome",
    "RunTrigger",
    "RuntimeDateTime",
    "RuntimeUUID",
    "SafeFailureOutcome",
    "SourcedText",
    "StrictScalar",
    "SupervisorAgentInput",
    "SupervisorDraft",
    "SupportActionTarget",
    "SupportAgentInput",
    "SupportAnalysisResult",
    "SupportCheck",
    "SupportCompletionStatus",
    "SupportCriterionResult",
    "SupportLookupGoal",
    "SupportMatchStatus",
    "SupportMatchUpdateCandidate",
    "SupportProgramRef",
    "SupportSearchSummary",
    "Uncertainty",
    "UpperSnakeCode",
    "VerifiedTextSpan",
    "canonical_digest",
    "validate_case_field_value",
]
