"""Offline command that rebuilds the reviewed procedure snapshot.

This is the only place that still fetches an official site, and it never runs
inside a user request.  It writes a *draft*: every record comes out unreviewed,
which makes it read as ``UNKNOWN`` freshness until a person fills in who
approved it and when.  That is deliberate — an unread draft must not be able to
raise the confidence of anything the Agent says.

    PYTHONPATH=backend python -m app.agent.procedure_tool.refresh --out draft.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.agent.procedure_tool.store import (
    ReviewedProcedureRecord,
    ReviewedProcedureSnapshot,
)
from app.agent.procedure_tool.tool import ProcedureLookupTool
from app.agent.schemas import ProcedureLookupInput

__all__ = ["main"]

_DEFAULT_REVIEW_VALID_DAYS = 90


@dataclass(frozen=True, slots=True)
class _RefreshTarget:
    """One reviewed document to rebuild.

    ``required_terms``/``any_terms`` repeat the code-reviewed URL registry's
    matching rule, so moving a source from live fetch into the snapshot does not
    change which query finds it.  ``step_codes`` records the canonical procedure
    steps this document belongs to; it is what a future database-backed store
    will join on (``PROCEDURE_STEP.step_code``).
    """

    record_id: str
    query: str
    step_codes: tuple[str, ...]
    required_terms: tuple[str, ...]
    any_terms: tuple[str, ...]


_REFRESH_TARGETS: tuple[_RefreshTarget, ...] = (
    _RefreshTarget(
        record_id="TAX_BUSINESS_CLOSURE",
        query="사업자 폐업 신고 절차 국세청",
        step_codes=("FILE_TAX_BUSINESS_CLOSURE",),
        required_terms=("폐업",),
        any_terms=("사업자", "국세청", "세무", "홈택스"),
    ),
    _RefreshTarget(
        record_id="FOOD_SERVICE_CLOSURE",
        query="휴게음식점 폐업 신고 절차 정부24",
        step_codes=("FILE_FOOD_SERVICE_CLOSURE",),
        required_terms=("폐업",),
        any_terms=("카페", "음식점", "식품", "휴게음식점", "일반음식점"),
    ),
    _RefreshTarget(
        record_id="WORKPLACE_INSURANCE_CLOSURE",
        query="4대보험 탈퇴 사업장 폐업 신고 절차",
        step_codes=("REPORT_WORKPLACE_INSURANCE_CLOSURE",),
        required_terms=("폐업",),
        any_terms=("4대보험", "근로자", "직원", "사업장", "국민연금"),
    ),
    # The step code here is an AI-internal candidate name, like the three
    # above: the real PROCEDURE_STEP rows do not exist yet, so none of these
    # is a database identifier. What this target adds is the official text
    # that restoration scope had none of.
    _RefreshTarget(
        record_id="LEASE_RESTORATION_SCOPE",
        query="임차인 원상회복 의무 임대차 보증금 반환",
        step_codes=("CONFIRM_RESTORATION_SCOPE",),
        required_terms=("임차",),
        any_terms=("원상회복", "원상복구", "임대차", "반환", "보증금"),
    ),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the code-reviewed official procedure sources and write a "
            "snapshot draft. Every record is written unreviewed; a person must "
            "read it and fill in reviewed_by/reviewed_at before it is served."
        )
    )
    parser.add_argument("--out", required=True, help="path of the snapshot draft")
    parser.add_argument(
        "--snapshot-version",
        default=None,
        help="version stamped on the snapshot; defaults to today's date",
    )
    parser.add_argument(
        "--review-valid-days",
        type=int,
        default=_DEFAULT_REVIEW_VALID_DAYS,
        help=(
            "how long an approval stays CURRENT before it reads as STALE "
            f"(default {_DEFAULT_REVIEW_VALID_DAYS})"
        ),
    )
    return parser


async def _collect(
    tool: ProcedureLookupTool,
    *,
    review_valid_days: int,
) -> tuple[list[ReviewedProcedureRecord], list[str]]:
    records: list[ReviewedProcedureRecord] = []
    problems: list[str] = []
    today = datetime.now(timezone.utc).date()
    for target in _REFRESH_TARGETS:
        result = await tool.lookup(
            ProcedureLookupInput(
                lookup_goal="BUSINESS_CLOSURE",
                search_queries=[target.query],
                as_of=today,
                locale="ko-KR",
                source_policy="OFFICIAL_ONLY",
                max_results_per_query=5,
                based_on_snapshot_id=uuid4(),
                review_feedback=[],
            )
        )
        if not result.documents:
            problems.append(
                f"{target.record_id}: no official document was retrieved "
                f"({result.completion_status.value})"
            )
            continue
        if len(result.documents) > 1:
            problems.append(
                f"{target.record_id}: {len(result.documents)} documents matched; "
                "kept the first and dropped the rest"
            )
        document = result.documents[0]
        records.append(
            ReviewedProcedureRecord(
                record_id=target.record_id,
                title=document.title,
                authority_name=document.authority_name,
                canonical_url=document.canonical_url,
                source_domain=document.source_domain,
                excerpt=document.excerpt,
                content_hash=document.content_hash,
                published_at=document.published_at,
                retrieved_at=document.retrieved_at,
                # Written unreviewed on purpose: a draft may not read as CURRENT.
                reviewed_by=None,
                reviewed_at=None,
                review_valid_days=review_valid_days,
                step_codes=list(target.step_codes),
                required_terms=list(target.required_terms),
                any_terms=list(target.any_terms),
            )
        )
    return records, problems


async def _build(
    args: argparse.Namespace,
) -> tuple[ReviewedProcedureSnapshot | None, list[str]]:
    now = datetime.now(timezone.utc)
    tool = ProcedureLookupTool.from_env()
    try:
        records, problems = await _collect(
            tool,
            review_valid_days=args.review_valid_days,
        )
    finally:
        await tool.aclose()
    if not records:
        return None, problems
    snapshot = ReviewedProcedureSnapshot(
        snapshot_version=args.snapshot_version or f"reviewed-procedures/{now:%Y-%m-%d}",
        generated_at=now,
        locale="ko-KR",
        records=records,
    )
    return snapshot, problems


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.review_valid_days < 1:
        _parser().error("--review-valid-days must be at least 1")
    try:
        snapshot, problems = asyncio.run(_build(args))
    except Exception:  # noqa: BLE001 - never surface provider or path detail
        print("Procedure refresh failed safely.", file=sys.stderr)
        return 2

    for problem in problems:
        print(f"warning: {problem}", file=sys.stderr)
    if snapshot is None:
        print(
            "No official document could be retrieved; no draft written.",
            file=sys.stderr,
        )
        return 2

    payload = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2)
    try:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
    except OSError:
        print("Procedure refresh could not write the draft.", file=sys.stderr)
        return 2
    print(
        f"Wrote {len(snapshot.records)} unreviewed record(s) to {args.out}. "
        "Read each excerpt, then set reviewed_by and reviewed_at before serving it.",
        file=sys.stderr,
    )
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
