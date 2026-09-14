"""Shared deterministic policy for high-risk, user-visible Agent claims."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from app.agent.schemas import ClaimType, EvidenceRecord, EvidenceSourceType

_AMOUNT_PATTERN = re.compile(r"(?<!\d)\d[\d,]*(?:\.\d+)?\s*(?:원|만원|억원)\b")
_DATE_PATTERN = re.compile(
    r"(?:\b20\d{2}[-./]\d{1,2}(?:[-./]\d{1,2})?\b|"
    r"20\d{2}년\s*\d{1,2}월(?:\s*\d{1,2}일)?|"
    r"\b\d+\s*(?:일|개월|년)\s*(?:이내|전|후)\b)"
)
_LEGAL_PATTERN = re.compile(r"(?:법적으로|법적 의무|위법|합법|소송|배상 책임)")
_TAX_PATTERN = re.compile(r"(?:세법상|세금|부가세|소득세|종합소득세)")
_ELIGIBILITY_PATTERN = re.compile(
    r"(?:지원\s*(?:가능|대상|자격)|수령\s*(?:가능|확정)|자격(?:이|은)\s*(?:있|된다))"
)
_OVERCONFIDENT_PATTERN = re.compile(
    r"(?:확정입니다|확정되었습니다|확정됐습니다|보장됩니다|무조건|"
    r"반드시\s+받을\s+수|자격(?:이|은)\s+있습니다|"
    r"지원(?:금)?\s*가능합니다|지원\s*대상입니다|"
    r"법적으로\s+문제없습니다)"
)


def required_sources_for_claim(
    claim_type: ClaimType,
) -> frozenset[EvidenceSourceType]:
    """Return the Review-authoritative source allowlist for a claim type."""

    official = frozenset(
        {
            EvidenceSourceType.OFFICIAL_DOCUMENT,
            EvidenceSourceType.OFFICIAL_API,
        }
    )
    if claim_type in {ClaimType.PROCEDURE, ClaimType.DATE_OR_DEADLINE}:
        return frozenset({EvidenceSourceType.PROCEDURE_MASTER, *official})
    return official


def high_risk_metadata(
    text: str,
    support_program_names: frozenset[str],
) -> tuple[frozenset[ClaimType], frozenset[EvidenceSourceType]]:
    """Classify visible text using the exact policy shared by Supervisor/Review."""

    risk_types: set[ClaimType] = set()
    required: set[EvidenceSourceType] = set()
    official = {
        EvidenceSourceType.OFFICIAL_DOCUMENT,
        EvidenceSourceType.OFFICIAL_API,
    }
    if _AMOUNT_PATTERN.search(text):
        risk_types.add(ClaimType.AMOUNT)
        required.update(official)
    if _DATE_PATTERN.search(text):
        risk_types.add(ClaimType.DATE_OR_DEADLINE)
        required.update({EvidenceSourceType.PROCEDURE_MASTER, *official})
    if _LEGAL_PATTERN.search(text):
        risk_types.add(ClaimType.LEGAL)
        required.update(official)
    if _TAX_PATTERN.search(text):
        risk_types.add(ClaimType.TAX)
        required.update(official)
    if _ELIGIBILITY_PATTERN.search(text) or any(
        program_name in text for program_name in support_program_names
    ):
        risk_types.update({ClaimType.SUPPORT_PROGRAM, ClaimType.ELIGIBILITY})
        required.update(official)
    return frozenset(risk_types), frozenset(required)


def is_overconfident(text: str) -> bool:
    """Return whether text uses language Review always rejects."""

    return _OVERCONFIDENT_PATTERN.search(text) is not None


def has_explicit_eligibility_language(text: str) -> bool:
    """Return whether visible text itself makes a support-eligibility claim.

    A support-program name alone is not an eligibility conclusion.  Keeping
    this predicate separate prevents a generic ``SUPPORT_PROGRAM`` claim from
    satisfying the stricter ``ELIGIBILITY`` confirmation rule.
    """

    return _ELIGIBILITY_PATTERN.search(text) is not None


def expand_evidence(
    evidence_records: Sequence[EvidenceRecord],
    evidence_by_id: Mapping[str, EvidenceRecord],
) -> tuple[EvidenceRecord, ...]:
    """Expand evidence through its transitive parent links without looping."""

    expanded: list[EvidenceRecord] = []
    pending = list(evidence_records)
    seen: set[str] = set()
    while pending:
        evidence = pending.pop()
        if evidence.evidence_id in seen:
            continue
        seen.add(evidence.evidence_id)
        expanded.append(evidence)
        pending.extend(
            evidence_by_id[parent_ref]
            for parent_ref in evidence.parent_evidence_refs
            if parent_ref in evidence_by_id
        )
    return tuple(expanded)


__all__ = [
    "expand_evidence",
    "has_explicit_eligibility_language",
    "high_risk_metadata",
    "is_overconfident",
    "required_sources_for_claim",
]
