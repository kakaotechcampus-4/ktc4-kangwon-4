"""Runtime-owned enrichment that turns validated semantics into change candidates."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

from app.agent.schemas import (
    CaseSnapshot,
    FactChangeCandidate,
    FactChangeSourceType,
    FactOperation,
    FactStatus,
    InfoAnalysisResult,
)


def build_fact_overlays(
    snapshot: CaseSnapshot,
    info_result: InfoAnalysisResult,
    source_call_id: UUID,
    *,
    uuid_factory: Callable[[], UUID] = uuid4,
) -> list[FactChangeCandidate]:
    """Build reviewable overlays without mutating the immutable Case snapshot."""

    facts = {item.field_path: item for item in snapshot.facts}
    overlays: list[FactChangeCandidate] = []
    for candidate in info_result.fact_candidates:
        if candidate.requires_confirmation:
            continue
        before = facts.get(candidate.field_path)
        before_status = before.status if before else FactStatus.UNKNOWN
        before_value = before.value if before else None
        if (
            candidate.operation == FactOperation.CLEAR
            and before_status == FactStatus.UNKNOWN
        ):
            continue
        if (
            candidate.operation == FactOperation.SET
            and before_status == FactStatus.CONFIRMED
            and type(before_value) is type(candidate.value)
            and before_value == candidate.value
        ):
            continue
        overlays.append(
            FactChangeCandidate(
                candidate_id=uuid_factory(),
                operation=candidate.operation,
                source_fact_candidate_id=candidate.candidate_id,
                source_type=FactChangeSourceType.INFO_ANALYSIS,
                field_path=candidate.field_path,
                value_type=candidate.value_type,
                before_status=before_status,
                before_value=before_value,
                proposed_status=(
                    FactStatus.UNKNOWN
                    if candidate.operation == FactOperation.CLEAR
                    else FactStatus.CONFIRMED
                ),
                proposed_value=candidate.value,
                candidate_status="READY_FOR_REVIEW",
                reason_summary=candidate.reason_summary,
                source_evidence_refs=candidate.source_evidence_refs,
                source_call_id=source_call_id,
                confirmed_conflict_ref=None,
            )
        )
    return overlays


__all__ = ["build_fact_overlays"]
