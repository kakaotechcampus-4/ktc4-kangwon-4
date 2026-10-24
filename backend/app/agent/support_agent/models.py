"""Immutable reviewed support-catalog contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.schemas import (
    CASE_FIELD_SPECS,
    CaseFieldKey,
    EvidenceRecord,
    FactValueType,
    FreshnessStatus,
    NonEmptyStr,
    NonNullStrictScalar,
    ProcedureStepRef,
    SupportProgramRef,
    UpperSnakeCode,
    Varchar50,
    validate_case_field_value,
)


class SupportCatalogModel(BaseModel):
    """Strict and shallow-immutable base for reviewed resolver data."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )


class CatalogSourcedText(SupportCatalogModel):
    text: NonEmptyStr
    evidence_refs: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class SupportRequiredDocumentDefinition(SupportCatalogModel):
    name: NonEmptyStr
    submission_stage: NonEmptyStr | None
    evidence_refs: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class SupportCriterionDefinition(SupportCatalogModel):
    criterion_code: UpperSnakeCode
    field_path: CaseFieldKey
    operator: Literal["EQ", "IN", "GT", "GTE", "LT", "LTE"]
    required_values: Annotated[
        tuple[NonNullStrictScalar, ...],
        Field(min_length=1),
    ]
    evidence_refs: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_definition(self) -> SupportCriterionDefinition:
        if self.operator != "IN" and len(self.required_values) != 1:
            raise ValueError(f"{self.operator} requires exactly one required value")
        value_type = CASE_FIELD_SPECS[self.field_path][0]
        if self.operator not in {"EQ", "IN"} and value_type not in {
            FactValueType.INTEGER,
            FactValueType.DATE,
        }:
            raise ValueError(
                "ordered support criteria require an integer or date field"
            )
        for value in self.required_values:
            validate_case_field_value(
                self.field_path, value_type, value, allow_null=False
            )
        return self


class ReviewedSupportProgram(SupportCatalogModel):
    support_program: SupportProgramRef
    program_name: NonEmptyStr
    related_steps: tuple[ProcedureStepRef, ...]
    criteria: Annotated[
        tuple[SupportCriterionDefinition, ...],
        Field(min_length=1),
    ]
    required_documents: tuple[SupportRequiredDocumentDefinition, ...]
    application_channel: CatalogSourcedText | None
    application_url: CatalogSourcedText | None
    application_period: CatalogSourcedText | None
    source_version: NonEmptyStr | None
    freshness_status: FreshnessStatus
    evidence_refs: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_program(self) -> ReviewedSupportProgram:
        criterion_codes = [item.criterion_code for item in self.criteria]
        if len(criterion_codes) != len(set(criterion_codes)):
            raise ValueError("criterion_code must be unique within a support program")

        step_refs = [
            (item.procedure_step_id, item.step_code) for item in self.related_steps
        ]
        if len(step_refs) != len(set(step_refs)):
            raise ValueError("related procedure steps must be unique")
        return self

    def all_evidence_refs(self) -> tuple[str, ...]:
        refs: list[str] = list(self.evidence_refs)
        for criterion in self.criteria:
            refs.extend(ref for ref in criterion.evidence_refs if ref not in refs)
        for document in self.required_documents:
            refs.extend(ref for ref in document.evidence_refs if ref not in refs)
        for sourced in (
            self.application_channel,
            self.application_url,
            self.application_period,
        ):
            if sourced is not None:
                refs.extend(ref for ref in sourced.evidence_refs if ref not in refs)
        return tuple(refs)


class ReviewedSupportCatalog(SupportCatalogModel):
    """Complete immutable snapshot supplied by a trusted, read-only resolver."""

    catalog_version: Varchar50  # SUPPORT_ITEM/SUPPORT_MATCH.catalog_version
    programs: tuple[ReviewedSupportProgram, ...]
    evidence_records: tuple[EvidenceRecord, ...]

    @model_validator(mode="after")
    def validate_catalog_integrity(self) -> ReviewedSupportCatalog:
        ids = [item.support_program.support_program_id for item in self.programs]
        wiki_ids = [item.support_program.wiki_uuid for item in self.programs]
        if len(ids) != len(set(ids)):
            raise ValueError("support_program_id must be unique in the catalog")
        if len(wiki_ids) != len(set(wiki_ids)):
            raise ValueError("wiki_uuid must be unique in the catalog")

        evidence_by_id: dict[str, EvidenceRecord] = {}
        for evidence in self.evidence_records:
            existing = evidence_by_id.get(evidence.evidence_id)
            if existing is not None and existing != evidence:
                raise ValueError("duplicate evidence_id has different content")
            evidence_by_id[evidence.evidence_id] = evidence

        for evidence in self.evidence_records:
            unknown_parents = set(evidence.parent_evidence_refs) - evidence_by_id.keys()
            if unknown_parents:
                raise ValueError("support evidence has unresolved parent references")

        referenced = {
            evidence_ref
            for program in self.programs
            for evidence_ref in program.all_evidence_refs()
        }
        missing = referenced - evidence_by_id.keys()
        if missing:
            raise ValueError(
                "support catalog references unknown evidence: "
                + ", ".join(sorted(missing))
            )

        allowed_source_types = {
            "REVIEWED_WIKI",
            "OFFICIAL_DOCUMENT",
            "OFFICIAL_API",
        }
        for evidence_ref in referenced:
            evidence = evidence_by_id[evidence_ref]
            source_type = _text(evidence.source_type)
            if source_type not in allowed_source_types:
                raise ValueError(
                    "support catalog claims require reviewed or official evidence"
                )
            if source_type == "REVIEWED_WIKI":
                official_parent = any(
                    _text(evidence_by_id[parent].source_type)
                    in {"OFFICIAL_DOCUMENT", "OFFICIAL_API"}
                    for parent in evidence.parent_evidence_refs
                )
                if not official_parent:
                    raise ValueError(
                        "reviewed wiki evidence requires a direct official parent"
                    )
        return self


def _text(value: object) -> str:
    return str(getattr(value, "value", value))


__all__ = [
    "CatalogSourcedText",
    "ReviewedSupportCatalog",
    "ReviewedSupportProgram",
    "SupportCriterionDefinition",
    "SupportRequiredDocumentDefinition",
]
