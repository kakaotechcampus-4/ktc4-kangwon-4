"""Offline command that discovers support notices and writes a review draft.

This never runs inside a user request, and it never decides who qualifies.
It fills in what the official API actually states -- name, notice ID, URL, and
the notice's own words about who it is for -- and leaves the eligibility rules
empty for a person to write after reading the notice.

    PYTHONPATH=backend python -m app.agent.support_agent.refresh --out draft.json

An entry with no rules is kept in the file and simply not served, so a draft
can be committed without any risk of it being compared against a real Case.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid5

from app.agent.support_agent.discovery_models import SupportNoticeDiscoveryInput
from app.agent.support_agent.discovery_tool import BizInfoSupportDiscoveryTool
from app.agent.support_agent.json_store import DEFAULT_CATALOG_PATH
from app.agent.support_agent.store import (
    ReviewedSupportEntry,
    ReviewedSupportSnapshot,
    SupportStoreError,
)

__all__ = ["main"]

# Bizinfo matches on hashtags, so these are the terms that actually surface
# closure support rather than general small-business notices. "점포철거비" is
# what finds the one-stop closure package the hero case is about.
_KEYWORD_SETS: tuple[tuple[str, ...], ...] = (
    ("폐업",),
    ("점포철거비",),
    ("폐업", "재창업"),
)
# Only notices whose title says so are kept. A hashtag match alone pulls in
# unrelated notices such as department-store tenancy calls.
_TITLE_TERMS = ("폐업", "철거", "재기", "재도전", "희망리턴", "사업정리", "점포정리")
_NAMESPACE = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
# Asking for more raises the chance one malformed notice fails strict parsing
# and takes the whole keyword set with it. Several small sets beat one big one.
_MAX_PER_KEYWORD = 8


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover closure-support notices from the official Bizinfo API and "
            "write a catalog draft. Eligibility rules are left empty: a person "
            "must read each notice and write them before it can be served."
        )
    )
    parser.add_argument("--out", required=True, help="path of the catalog draft")
    parser.add_argument(
        "--catalog-version",
        default=None,
        help="version stamped on the catalog; defaults to today's date",
    )
    parser.add_argument(
        "--merge",
        default=None,
        help=(
            "existing catalog to keep reviewed entries from; defaults to the "
            "one shipped with the package"
        ),
    )
    return parser


def _load_existing(path: str | None) -> dict[str, ReviewedSupportEntry]:
    source = Path(path) if path else DEFAULT_CATALOG_PATH
    if not source.is_file():
        return {}
    try:
        snapshot = ReviewedSupportSnapshot.model_validate(
            json.loads(source.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise SupportStoreError("existing support catalog could not be read") from exc
    return {entry.external_notice_id: entry for entry in snapshot.entries}


async def _discover(tool: BizInfoSupportDiscoveryTool) -> dict[str, object]:
    found: dict[str, object] = {}
    for keywords in _KEYWORD_SETS:
        try:
            result = await tool.discover(
                SupportNoticeDiscoveryInput(
                    keywords=keywords, max_results=_MAX_PER_KEYWORD
                )
            )
        except Exception as exc:  # noqa: BLE001 - one keyword set failing is not fatal
            print(
                f"warning: keyword set {keywords} failed ({type(exc).__name__})",
                file=sys.stderr,
            )
            continue
        evidence = {item.evidence_id: item for item in result.evidence_records}
        for candidate in result.candidates:
            if not any(term in candidate.title for term in _TITLE_TERMS):
                continue
            # The evidence's source_ref is the API endpoint; the notice's own
            # address is its locator.
            record = next(
                (
                    item
                    for item in evidence.values()
                    if item.locator == candidate.detail_url
                ),
                None,
            )
            if record is None:
                continue
            found.setdefault(candidate.notice_id, (candidate, record))
    return found


def _entry(
    candidate: object,
    record: object,
    *,
    program_id: int,
    existing: ReviewedSupportEntry | None,
) -> ReviewedSupportEntry:
    if existing is not None:
        # A reviewed entry keeps its rules; only the freshly observed evidence
        # is replaced, so re-running the command never discards a person's work.
        return existing.model_copy(update={"evidence": record})
    return ReviewedSupportEntry(
        support_program_id=program_id,
        wiki_uuid=uuid5(_NAMESPACE, candidate.notice_id),
        program_name=candidate.title,
        external_notice_id=candidate.notice_id,
        detail_url=candidate.detail_url,
        discovered_target=candidate.target,
        discovered_period=candidate.application_period,
        evidence=record,
        reviewed_by=None,
        reviewed_at=None,
        related_step_codes=[],
        criteria=[],
        required_documents=[],
        application_channel=None,
        application_url=None,
        application_period=None,
    )


async def _build(args: argparse.Namespace) -> tuple[ReviewedSupportSnapshot, int, int]:
    now = datetime.now(timezone.utc)
    existing = _load_existing(args.merge)
    tool = BizInfoSupportDiscoveryTool.from_env()
    try:
        found = await _discover(tool)
    finally:
        await tool.aclose()

    entries: list[ReviewedSupportEntry] = []
    next_id = max((item.support_program_id for item in existing.values()), default=0)
    for notice_id in sorted(found):
        candidate, record = found[notice_id]
        prior = existing.get(notice_id)
        if prior is None:
            next_id += 1
        entries.append(
            _entry(
                candidate,
                record,
                program_id=prior.support_program_id if prior else next_id,
                existing=prior,
            )
        )
    kept = sum(1 for entry in entries if entry.is_servable)
    snapshot = ReviewedSupportSnapshot(
        catalog_version=args.catalog_version or f"reviewed-support/{now:%Y-%m-%d}",
        generated_at=now,
        entries=entries,
    )
    return snapshot, kept, len(entries) - kept


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        snapshot, servable, pending = asyncio.run(_build(args))
    except Exception:  # noqa: BLE001 - never surface provider or path detail
        print("Support catalog refresh failed safely.", file=sys.stderr)
        return 2

    if not snapshot.entries:
        print("No closure-support notice was found; no draft written.", file=sys.stderr)
        return 2

    payload = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2)
    try:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
    except OSError:
        print("Support catalog refresh could not write the draft.", file=sys.stderr)
        return 2

    print(
        f"Wrote {len(snapshot.entries)} notice(s) to {args.out}: "
        f"{servable} already reviewed, {pending} waiting for eligibility rules. "
        "Read each notice, then fill in reviewed_by, reviewed_at and criteria.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
