"""Reviewed support catalog — the only support data the Agent may compare against.

A discovered notice cannot become a catalog entry on its own.  The API returns
prose: "소상공인", "예산 소진시까지", "세부사업별 상이".  Turning that into a
typed eligibility rule is a judgement about who qualifies, and the team rule is
that policy data is reviewed by a person (``/CLAUDE.md``).  Code that invented
those rules would be deciding eligibility, which is exactly what this project
says it does not do.

So this module holds a snapshot whose entries may be *unreviewed*.  An entry
without a reviewer and at least one criterion is never handed to the Support
Agent -- it stays in the file waiting for someone to read the notice and fill
it in.  That is the whole design: discovery is automatic, promotion is not.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.agent.schemas import (
    AgentSchema,
    AwareDatetime,
    EvidenceRecord,
    NonEmptyStr,
    PositiveStrictInt,
    RuntimeDateTime,
    UpperSnakeCode,
)
from app.agent.support_agent.models import (
    CatalogSourcedText,
    ReviewedSupportCatalog,
    ReviewedSupportProgram,
    SupportCriterionDefinition,
    SupportRequiredDocumentDefinition,
)
from pydantic import Field, model_validator

__all__ = [
    "ReviewedSupportEntry",
    "ReviewedSupportSnapshot",
    "ReviewedSupportStore",
    "SupportStoreError",
]


class SupportStoreError(RuntimeError):
    """Raised when a catalog snapshot cannot be loaded or fails its contract."""


class ReviewedSupportEntry(AgentSchema):
    """One discovered support programme, reviewed or not.

    Everything above ``reviewed_by`` comes from the official API and is safe to
    fill in automatically.  Everything below it is a judgement and stays empty
    until a person makes it.
    """

    support_program_id: PositiveStrictInt
    wiki_uuid: UUID
    program_name: NonEmptyStr
    external_notice_id: NonEmptyStr = Field(
        description="Official notice identifier, used to merge repeat discoveries."
    )
    detail_url: NonEmptyStr
    discovered_target: NonEmptyStr | None = Field(
        description="The notice's own words about who it is for. Not a rule."
    )
    discovered_period: NonEmptyStr | None = Field(
        description="The notice's own words about when to apply. Not a date."
    )
    evidence: EvidenceRecord = Field(
        description="Official-API evidence captured when this was discovered."
    )

    reviewed_by: NonEmptyStr | None = Field(
        description="Person who read the notice and wrote the rules below."
    )
    reviewed_at: AwareDatetime | None
    related_step_codes: list[UpperSnakeCode] = Field(
        description="Procedure steps this programme belongs to."
    )
    criteria: list[SupportCriterionDefinition] = Field(
        description="Typed eligibility rules. Empty means nobody has written them."
    )
    required_documents: list[SupportRequiredDocumentDefinition]
    application_channel: CatalogSourcedText | None
    application_url: CatalogSourcedText | None
    application_period: CatalogSourcedText | None

    @model_validator(mode="after")
    def validate_entry(self) -> ReviewedSupportEntry:
        if (self.reviewed_by is None) != (self.reviewed_at is None):
            raise ValueError("reviewed_by and reviewed_at must be set together")
        if self.criteria and self.reviewed_by is None:
            raise ValueError("criteria may only exist on a reviewed entry")
        codes = [item.criterion_code for item in self.criteria]
        if len(codes) != len(set(codes)):
            raise ValueError("criterion_code must be unique within a programme")
        return self

    @property
    def is_servable(self) -> bool:
        """Whether this entry may be compared against a real Case.

        Both conditions matter. A reviewer with no criteria has read the notice
        and concluded nothing usable; criteria with no reviewer cannot happen
        because the validator above rejects it.
        """

        return self.reviewed_by is not None and bool(self.criteria)


class ReviewedSupportSnapshot(AgentSchema):
    """A whole catalog file: a version, when it was built, and its entries."""

    catalog_version: NonEmptyStr
    generated_at: RuntimeDateTime
    entries: list[ReviewedSupportEntry]

    @model_validator(mode="after")
    def validate_snapshot(self) -> ReviewedSupportSnapshot:
        for name, values in (
            ("support_program_id", [item.support_program_id for item in self.entries]),
            ("wiki_uuid", [item.wiki_uuid for item in self.entries]),
            ("external_notice_id", [item.external_notice_id for item in self.entries]),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"snapshot {name} must be unique")
        return self

    def build_catalog(
        self,
        *,
        known_steps: Sequence[object] = (),
    ) -> tuple[ReviewedSupportCatalog, int]:
        """Return the servable catalog and how many entries were held back.

        Unreviewed entries are dropped here rather than filtered somewhere
        downstream, so there is one place where "reviewed" turns into "usable".
        """

        step_refs: dict[str, object] = {}
        for step in known_steps:
            ref = getattr(step, "procedure_step", None)
            code = getattr(ref, "step_code", None)
            if code is not None:
                step_refs[code] = ref
        programs: list[ReviewedSupportProgram] = []
        evidence: list[EvidenceRecord] = []
        held_back = 0
        for entry in self.entries:
            if not entry.is_servable:
                held_back += 1
                continue
            related = tuple(
                ref
                for code in entry.related_step_codes
                if (ref := step_refs.get(code)) is not None
            )
            programs.append(
                ReviewedSupportProgram(
                    support_program={
                        "support_program_id": entry.support_program_id,
                        "wiki_uuid": entry.wiki_uuid,
                    },
                    program_name=entry.program_name,
                    related_steps=related,
                    criteria=tuple(entry.criteria),
                    required_documents=tuple(entry.required_documents),
                    application_channel=entry.application_channel,
                    application_url=entry.application_url,
                    application_period=entry.application_period,
                    source_version=self.catalog_version,
                    freshness_status=entry.evidence.freshness_status,
                    evidence_refs=(entry.evidence.evidence_id,),
                )
            )
            evidence.append(entry.evidence)
        catalog = ReviewedSupportCatalog(
            catalog_version=self.catalog_version,
            programs=tuple(programs),
            evidence_records=tuple(evidence),
        )
        return catalog, held_back


class ReviewedSupportStore(Protocol):
    """What the runtime needs from a catalog source."""

    @property
    def catalog_version(self) -> str: ...

    def snapshot(self) -> ReviewedSupportSnapshot: ...
