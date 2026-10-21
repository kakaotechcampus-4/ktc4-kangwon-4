"""Official-source policy and transitive evidence traversal for Agent claims."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.agent.schemas import EvidenceRecord, EvidenceSourceType

# Every claim type Review can authorise needs an official source; there is no
# per-type allowlist to configure.
REQUIRED_CLAIM_SOURCES = frozenset(
    {
        EvidenceSourceType.OFFICIAL_DOCUMENT,
        EvidenceSourceType.OFFICIAL_API,
    }
)


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



__all__ = ["REQUIRED_CLAIM_SOURCES", "expand_evidence"]
