"""Runtime-owned enrichment that turns validated semantics into change candidates."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

from app.agent.schemas import (
    CASE_FIELD_SPECS,
    CaseSnapshot,
    ConflictCandidate,
    FactChangeCandidate,
    FactChangeSourceType,
    FactOperation,
    FactStatus,
    InfoAnalysisResult,
)


class StaleConfirmationError(ValueError):
    """Raised when a confirmation no longer describes the Case it was made on.

    A confirmation is an answer to one question asked about one version of the
    Case.  If the Case moved on, applying it anyway would silently overwrite
    whatever changed in between -- the exact thing the team rule against
    automatic overwrite exists to prevent.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "STALE_CONFLICT_CONFIRMATION"
        self.retryable = False


def build_confirmed_conflict_overlay(
    snapshot: CaseSnapshot,
    conflict: ConflictCandidate,
    *,
    uuid_factory: Callable[[], UUID] = uuid4,
) -> FactChangeCandidate:
    """Turn a user-confirmed conflict into one reviewable change candidate.

    The result is a candidate, not a write.  It goes to Review with every other
    proposed change, because the user settled *which value was meant*, not
    whether the plan built on it is sound.
    """

    if conflict.snapshot_id != snapshot.snapshot_id:
        raise StaleConfirmationError(
            "confirmation was made against a different Case snapshot"
        )
    if conflict.case_version != snapshot.case_version:
        raise StaleConfirmationError(
            "confirmation was made against a different Case version"
        )

    current = next(
        (item for item in snapshot.facts if item.field_path == conflict.field_path),
        None,
    )
    if current is None or current.status != FactStatus.CONFIRMED:
        raise StaleConfirmationError(
            "the confirmed field is no longer a confirmed Case fact"
        )
    # Compared by type as well as value so a stored 1 cannot silently satisfy a
    # confirmation recorded against True.
    if (
        type(current.value) is not type(conflict.committed_value)
        or current.value != conflict.committed_value
    ):
        raise StaleConfirmationError(
            "the Case value changed after the conflict was raised"
        )

    return FactChangeCandidate(
        candidate_id=uuid_factory(),
        operation=conflict.proposed_operation,
        source_fact_candidate_id=conflict.candidate_id,
        source_type=FactChangeSourceType.CONFIRMED_CONFLICT,
        field_path=conflict.field_path,
        value_type=CASE_FIELD_SPECS[conflict.field_path][0],
        before_status=current.status,
        before_value=current.value,
        proposed_status=conflict.proposed_status,
        proposed_value=conflict.proposed_value,
        candidate_status="READY_FOR_REVIEW",
        reason_summary="사용자가 기존 값 대신 새 값을 쓰겠다고 확인했습니다.",
        source_evidence_refs=list(conflict.source_evidence_refs),
        # Provenance is the conflict reference, not a component call: the change
        # came from a person answering, and the reference is what resolves back
        # to the call that raised it. The schema enforces this either/or.
        source_call_id=None,
        confirmed_conflict_ref=conflict.conflict_ref,
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


__all__ = [
    "StaleConfirmationError",
    "build_confirmed_conflict_overlay",
    "build_fact_overlays",
]
