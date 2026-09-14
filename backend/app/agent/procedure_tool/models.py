"""Trusted, read-only procedure-master models.

These models describe data injected by a reviewed resolver.  The lookup tool does
not fetch or persist procedure data itself.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from app.agent.schemas import (
    CASE_FIELD_SPECS,
    CaseFieldKey,
    EvidenceRecord,
    FactValueType,
    ProcedureStepRef,
    validate_case_field_value,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

NonEmptyString = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1),
]
MasterScalar = StrictStr | StrictInt | StrictBool | date
PositiveStrictInt = Annotated[StrictInt, Field(gt=0)]


class ProcedureMasterModel(BaseModel):
    """Base class that rejects accidental, unsupported master fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProcedureConditionDefinition(ProcedureMasterModel):
    """A deterministic predicate backed by reviewed procedure evidence."""

    condition_id: PositiveStrictInt
    field_path: CaseFieldKey
    operator: Literal["EQ", "IN", "GT", "GTE", "LT", "LTE"]
    expected_values: tuple[MasterScalar, ...] = Field(min_length=1)
    evidence_refs: tuple[NonEmptyString, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_operator_arity(self) -> ProcedureConditionDefinition:
        if self.operator != "IN" and len(self.expected_values) != 1:
            raise ValueError(f"{self.operator} requires exactly one expected value")

        unique_values = {(type(item), item) for item in self.expected_values}
        if len(unique_values) != len(self.expected_values):
            raise ValueError("expected_values must be unique with strict types")

        value_type, _ = CASE_FIELD_SPECS[self.field_path]
        for expected_value in self.expected_values:
            validate_case_field_value(
                self.field_path,
                value_type,
                expected_value,
                allow_null=False,
            )
        if self.operator in {"GT", "GTE", "LT", "LTE"} and value_type not in {
            FactValueType.INTEGER,
            FactValueType.DATE,
        }:
            raise ValueError(
                "ordered comparisons are supported only for INTEGER and DATE fields"
            )
        return self


class ProcedurePrerequisiteDefinition(ProcedureMasterModel):
    """A stable reference to an earlier procedure step."""

    procedure_step: ProcedureStepRef
    dependency_type: Literal["REQUIRED", "RECOMMENDED"]
    evidence_refs: tuple[NonEmptyString, ...] = Field(min_length=1)


class ProcedureStepDefinition(ProcedureMasterModel):
    """One reviewed procedure-master row and its evaluation metadata."""

    procedure_step: ProcedureStepRef
    step_name: NonEmptyString
    is_active: StrictBool
    effective_from: date | None = None
    effective_until: date | None = None
    conditions: tuple[ProcedureConditionDefinition, ...] = ()
    prerequisites: tuple[ProcedurePrerequisiteDefinition, ...] = ()
    requires_professional: StrictBool
    professional_type: NonEmptyString | None
    decision_authority: Literal[
        "USER",
        "LANDLORD",
        "OFFICIAL_AGENCY",
        "PROFESSIONAL",
        "UNKNOWN",
    ]
    evidence_refs: tuple[NonEmptyString, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_step(self) -> ProcedureStepDefinition:
        if (
            self.effective_from
            and self.effective_until
            and self.effective_from > self.effective_until
        ):
            raise ValueError("effective_from must not be after effective_until")

        if self.requires_professional != (self.professional_type is not None):
            raise ValueError(
                "professional_type must be present exactly when "
                "requires_professional is true"
            )

        condition_ids = [condition.condition_id for condition in self.conditions]
        if len(condition_ids) != len(set(condition_ids)):
            raise ValueError("condition_id must be unique within a procedure step")

        prerequisite_refs = [
            (
                item.procedure_step.procedure_step_id,
                item.procedure_step.step_code,
            )
            for item in self.prerequisites
        ]
        if len(prerequisite_refs) != len(set(prerequisite_refs)):
            raise ValueError("a prerequisite step must not be duplicated")

        own_ref = (
            self.procedure_step.procedure_step_id,
            self.procedure_step.step_code,
        )
        if own_ref in prerequisite_refs:
            raise ValueError("a procedure step cannot depend on itself")
        return self


class ProcedureMaster(ProcedureMasterModel):
    """Immutable dataset injected into :class:`ProcedureLookupTool`.

    ``freshness_status`` is supplied by the trusted resolver.  The lookup tool
    never infers freshness from the current date.
    """

    data_version: NonEmptyString
    freshness_status: Literal["CURRENT", "STALE", "UNKNOWN"]
    steps: tuple[ProcedureStepDefinition, ...]
    evidence_records: tuple[EvidenceRecord, ...]

    @model_validator(mode="after")
    def validate_dataset_integrity(self) -> ProcedureMaster:
        ids = [step.procedure_step.procedure_step_id for step in self.steps]
        codes = [step.procedure_step.step_code for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("procedure_step_id must be unique in the master")
        if len(codes) != len(set(codes)):
            raise ValueError("step_code must be unique in the master")

        evidence_by_id: dict[str, EvidenceRecord] = {}
        for evidence in self.evidence_records:
            existing = evidence_by_id.get(evidence.evidence_id)
            if existing is not None and existing != evidence:
                raise ValueError(
                    f"duplicate evidence_id has different content: "
                    f"{evidence.evidence_id}"
                )
            evidence_by_id[evidence.evidence_id] = evidence

        parent_refs = {
            parent_ref
            for evidence in self.evidence_records
            for parent_ref in evidence.parent_evidence_refs
        }
        missing_parent_refs = sorted(parent_refs - evidence_by_id.keys())
        if missing_parent_refs:
            raise ValueError(
                "procedure master evidence references unknown parents: "
                + ", ".join(missing_parent_refs)
            )

        referenced_evidence: set[str] = set()
        condition_ids: set[int] = set()
        for step in self.steps:
            referenced_evidence.update(step.evidence_refs)
            for condition in step.conditions:
                if condition.condition_id in condition_ids:
                    raise ValueError(
                        "condition_id must be unique across the procedure master"
                    )
                condition_ids.add(condition.condition_id)
                referenced_evidence.update(condition.evidence_refs)
            for prerequisite in step.prerequisites:
                referenced_evidence.update(prerequisite.evidence_refs)

        missing_evidence = sorted(referenced_evidence - evidence_by_id.keys())
        if missing_evidence:
            raise ValueError(
                "procedure master references unknown evidence: "
                + ", ".join(missing_evidence)
            )

        allowed_source_types = {
            "PROCEDURE_MASTER",
            "OFFICIAL_DOCUMENT",
            "OFFICIAL_API",
        }
        invalid_source_types: set[str] = set()
        for evidence_ref in referenced_evidence:
            source_type = evidence_by_id[evidence_ref].source_type
            source_type_text = str(getattr(source_type, "value", source_type))
            if source_type_text not in allowed_source_types:
                invalid_source_types.add(source_type_text)
        invalid_sources = sorted(invalid_source_types)
        if invalid_sources:
            raise ValueError(
                "procedure definitions require procedure-master or official evidence; "
                "found: " + ", ".join(invalid_sources)
            )

        steps_by_ref = {
            (
                step.procedure_step.procedure_step_id,
                step.procedure_step.step_code,
            ): step
            for step in self.steps
        }
        missing_prerequisites = sorted(
            {
                (
                    prerequisite.procedure_step.procedure_step_id,
                    prerequisite.procedure_step.step_code,
                )
                for step in self.steps
                for prerequisite in step.prerequisites
                if (
                    prerequisite.procedure_step.procedure_step_id,
                    prerequisite.procedure_step.step_code,
                )
                not in steps_by_ref
            },
            key=lambda item: (item[0], item[1]),
        )
        if missing_prerequisites:
            missing_codes = ", ".join(code for _, code in missing_prerequisites)
            raise ValueError(
                "procedure master references unknown prerequisite steps: "
                + missing_codes
            )

        prerequisite_graph = {
            step_ref: {
                (
                    prerequisite.procedure_step.procedure_step_id,
                    prerequisite.procedure_step.step_code,
                )
                for prerequisite in step.prerequisites
            }
            for step_ref, step in steps_by_ref.items()
        }
        _ensure_acyclic_prerequisites(prerequisite_graph)
        return self


def _ensure_acyclic_prerequisites(
    graph: dict[tuple[int, str], set[tuple[int, str]]],
) -> None:
    visiting: set[tuple[int, str]] = set()
    visited: set[tuple[int, str]] = set()

    def visit(step_ref: tuple[int, str]) -> None:
        if step_ref in visiting:
            raise ValueError("procedure prerequisite graph must not contain a cycle")
        if step_ref in visited:
            return
        visiting.add(step_ref)
        for prerequisite_ref in graph[step_ref]:
            visit(prerequisite_ref)
        visiting.remove(step_ref)
        visited.add(step_ref)

    for step_ref in graph:
        visit(step_ref)


__all__ = [
    "MasterScalar",
    "ProcedureConditionDefinition",
    "ProcedureMaster",
    "ProcedurePrerequisiteDefinition",
    "ProcedureStepDefinition",
]
