"""Bounded reuse of an unchanged, independently reviewed planning outcome.

Keys compare typed data exactly; no text similarity, new proof, or Case mutation
is involved. This is process-local reuse, not persistent Case storage.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.agent.schemas import (
    AgentGraphInput,
    AgentGraphOutput,
    InfoAnalysisResult,
    ReviewedPlanOutcome,
    SupportAnalysisResult,
)

RULES_VERSION = "reviewed-decision-cache/1"


def fingerprint(value: Any) -> str:
    """JSON retains null, false and zero as distinct values."""
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class _Entry:
    case_id: int
    day: str
    expires_at: float
    payload: str
    digest: str


class DecisionCache:
    def __init__(
        self,
        *,
        max_size: int = 128,
        ttl_seconds: float = 300,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(max_size) is not int or max_size < 1:
            raise ValueError("cache max_size must be a positive integer")
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("cache ttl_seconds must be finite and positive")
        self._max_size, self._ttl = max_size, ttl_seconds
        self._clock, self._monotonic = clock, monotonic
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._hits = self._misses = self._stores = 0

    def key(self, request: AgentGraphInput, context: Mapping[str, Any]) -> str:
        return fingerprint(
            {
                "rules_version": RULES_VERSION,
                "request": request.model_dump(mode="json"),
                "context": context,
            }
        )

    def get(self, key: str) -> ReviewedPlanOutcome | None:
        entry = self._entries.get(key)
        if entry is not None:
            try:
                if (
                    entry.expires_at <= self._monotonic()
                    or entry.day != self._clock().date().isoformat()
                ):
                    raise ValueError("cache entry expired")
                if fingerprint(entry.payload) != entry.digest:
                    raise ValueError("cache entry changed")
                outcome = ReviewedPlanOutcome.model_validate_json(entry.payload)
                outcome.assert_integrity()
                self._entries.move_to_end(key)
                self._hits += 1
                return outcome
            except (ValueError, TypeError):
                del self._entries[key]
        self._misses += 1
        return None

    def put(
        self, key: str, request: AgentGraphInput, outcome: AgentGraphOutput
    ) -> bool:
        if not isinstance(outcome, ReviewedPlanOutcome):
            return False
        try:
            outcome.assert_integrity()
            subject = outcome.review_subject
            mutations = subject.supervisor_draft.mutations
            if any(
                (
                    mutations.fact_changes,
                    mutations.procedure_progress_changes,
                    mutations.support_match_updates,
                )
            ):
                return False
            if (
                subject.snapshot != request.case_snapshot
                or subject.trigger != request.trigger
            ):
                return False
            evidence = list(subject.snapshot.evidence_records)
            for source in subject.source_results:
                evidence.extend(source.output.evidence_records)
                if isinstance(source.output, InfoAnalysisResult) and any(
                    (
                        source.output.fact_candidates,
                        source.output.conflicts,
                        source.output.procedure_progress_observations,
                    )
                ):
                    return False
                if isinstance(source.output, SupportAnalysisResult) and any(
                    check.freshness_status != "CURRENT"
                    for check in source.output.support_checks
                ):
                    return False
            if any(item.freshness_status != "CURRENT" for item in evidence):
                return False
            # Serialization owns the data and performs another full DTO validation.
            payload = outcome.model_dump_json()
            ReviewedPlanOutcome.model_validate_json(payload)
        except (ValueError, TypeError):
            return False
        self._entries[key] = _Entry(
            request.case_snapshot.case_id,
            self._clock().date().isoformat(),
            self._monotonic() + self._ttl,
            payload,
            fingerprint(payload),
        )
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_size:
            self._entries.popitem(last=False)
        self._stores += 1
        return True

    def clear(self) -> None:
        self._entries.clear()

    def invalidate_case(self, case_id: int) -> None:
        for key in [
            key for key, entry in self._entries.items() if entry.case_id == case_id
        ]:
            del self._entries[key]

    def inspect(self) -> dict[str, int | float]:
        return {
            "size": len(self._entries),
            "max_size": self._max_size,
            "ttl_seconds": self._ttl,
            "hits": self._hits,
            "misses": self._misses,
            "stores": self._stores,
        }
