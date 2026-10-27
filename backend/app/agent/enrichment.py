"""Runtime-owned enrichment that turns validated semantics into change candidates."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.agent.schemas import (
    CASE_FIELD_SPECS,
    CaseSnapshot,
    ConflictCandidate,
    ConflictConfirmedTrigger,
    EvidenceRecord,
    FactChangeCandidate,
    FactChangeSourceType,
    FactOperation,
    FactStatus,
    InfoAnalysisResult,
    case_field_values_equal as same_fact_value,
)


class StaleConfirmationError(ValueError):
    """Raised when a confirmation no longer describes the Case it was made on.

    A confirmation is an answer to one question asked about one snapshot of the
    Case.  If the Case moved on, applying it anyway would silently overwrite
    whatever changed in between -- the exact thing the team rule against
    automatic overwrite exists to prevent.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "STALE_CONFLICT_CONFIRMATION"
        self.retryable = False


def evidence_records_equal(left: EvidenceRecord, right: EvidenceRecord) -> bool:
    """Keep source content exact while tolerating DB time precision and parent order."""
    records = [item.model_dump(mode="python") for item in (left, right)]
    for record in records:
        record["parent_evidence_refs"] = sorted(record["parent_evidence_refs"])
        for field in ("retrieved_at", "published_at"):
            stamp = record[field]
            if stamp is not None:
                record[field] = stamp.astimezone(timezone.utc).replace(microsecond=0)
    return records[0] == records[1]


def confirmation_state(snapshot: CaseSnapshot) -> str:
    """Compare full stored state despite read time, list order and DB time precision."""
    data = snapshot.model_dump(mode="json", exclude={"snapshot_id", "captured_at"})

    def normalize(value, field=None):
        if isinstance(value, dict):
            return {key: normalize(item, key) for key, item in value.items()}
        if isinstance(value, list):
            items = [normalize(item) for item in value]
            return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
        if field in {"updated_at", "retrieved_at", "published_at"} and isinstance(value, str):
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return stamp.astimezone(timezone.utc).replace(microsecond=0).isoformat()
        return value

    return json.dumps(normalize(data), ensure_ascii=False, sort_keys=True)


def build_conflict_overlays(
    snapshot: CaseSnapshot,
    trigger: ConflictConfirmedTrigger,
    *,
    uuid_factory: Callable[[], UUID] = uuid4,
) -> list[FactChangeCandidate]:
    """Validate every stored proposal, then keep only explicitly accepted changes."""
    trigger = ConflictConfirmedTrigger.model_validate(trigger.model_dump(mode="python"))
    baseline = trigger.conflict_snapshot
    if baseline is not None and (
        baseline.snapshot_id != snapshot.snapshot_id
        or confirmation_state(baseline) != confirmation_state(snapshot)
    ):
        raise StaleConfirmationError("Case state changed after the conflict batch")
    overlays = []
    for conflict, accepted in trigger.choices():
        candidate = build_confirmed_conflict_overlay(snapshot, conflict, uuid_factory=uuid_factory)
        if accepted:
            overlays.append(candidate)
    return overlays


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

    conflict.assert_integrity()
    if conflict.snapshot_id != snapshot.snapshot_id:
        raise StaleConfirmationError(
            "confirmation was made against a different Case snapshot"
        )
    current = next(
        (item for item in snapshot.facts if item.field_path == conflict.field_path),
        None,
    )
    if current is None or current.status != FactStatus.CONFIRMED:
        raise StaleConfirmationError(
            "the confirmed field is no longer a confirmed Case fact"
        )
    if not same_fact_value(conflict.field_path, current.value, conflict.committed_value):
        raise StaleConfirmationError(
            "the Case value changed after the conflict was raised"
        )

    if not set(conflict.source_evidence_refs).issubset(
        item.evidence_id for item in snapshot.evidence_records
    ):
        raise ValueError("confirmed-conflict evidence is missing from the snapshot")

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
            and same_fact_value(candidate.field_path, before_value, candidate.value)
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
    "build_conflict_overlays",
    "build_fact_overlays",
    "confirmation_state",
    "evidence_records_equal",
    "same_fact_value",
]
