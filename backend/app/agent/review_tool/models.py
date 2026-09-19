"""LLM-authored portion of an independent review result."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from app.agent.schemas import (
    Component,
    EvidenceSourceType,
    JsonPointer,
    MissingEvidence,
    NonEmptyStr,
    ReviewIssue,
    ReviewIssueCode,
    ReviewVerdict,
)
from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator


class ReviewIssueModelOutput(BaseModel):
    """Provider-facing issue shape without semantic cross-field validation."""

    model_config = ConfigDict(extra="forbid")

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
    target_call_id: UUID | None
    target_path: JsonPointer
    reason_summary: NonEmptyStr
    evidence_refs: list[NonEmptyStr]


class MissingEvidenceModelOutput(BaseModel):
    """Provider-facing missing-evidence shape; references are checked locally."""

    model_config = ConfigDict(extra="forbid")

    claim_path: JsonPointer
    required_source_types: Annotated[list[EvidenceSourceType], Field(min_length=1)]
    reason_summary: NonEmptyStr


class ReviewProviderOutput(BaseModel):
    """Typed provider shape that deliberately omits semantic gate validators.

    Strict structured output can guarantee this shape, but conditional relations
    between verdicts, severities, findings, and rework targets are validated by
    :class:`ReviewModelOutput` inside ``ReviewTool``.  This lets the tool issue a
    bounded corrective retry instead of failing inside the shared LLM client.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: ReviewVerdict
    issues: list[ReviewIssueModelOutput]
    missing_evidence: list[MissingEvidenceModelOutput]
    recommended_rework_targets: list[
        Literal[
            Component.SUPERVISOR,
            Component.INFO_AGENT,
            Component.SUPPORT_AGENT,
            Component.PROCEDURE_TOOL,
        ]
    ]
    resolution_reason: StrictStr = Field(min_length=1)


class ReviewModelOutput(BaseModel):
    """Semantic fields the model may author.

    The reviewed subject ID and digest are deliberately absent.  ``ReviewTool``
    injects those trusted values only after local validation succeeds.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: ReviewVerdict
    issues: list[ReviewIssue]
    missing_evidence: list[MissingEvidence]
    recommended_rework_targets: list[
        Literal[
            Component.SUPERVISOR,
            Component.INFO_AGENT,
            Component.SUPPORT_AGENT,
            Component.PROCEDURE_TOOL,
        ]
    ]
    resolution_reason: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def enforce_review_gate(self) -> ReviewModelOutput:
        blocking = any(issue.severity == "BLOCKING" for issue in self.issues)
        if self.verdict == ReviewVerdict.PASS:
            if blocking or self.missing_evidence or self.recommended_rework_targets:
                raise ValueError(
                    "PASS cannot contain blocking issues, missing evidence, or rework"
                )
        elif not blocking and not self.missing_evidence:
            raise ValueError(
                "REVISE requires a BLOCKING issue or missing evidence; "
                "warning-only findings must PASS"
            )
        return self


__all__ = [
    "MissingEvidenceModelOutput",
    "ReviewIssueModelOutput",
    "ReviewModelOutput",
    "ReviewProviderOutput",
]
