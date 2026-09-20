"""Checks run against the repository's actual official material.

Every input here is a file already in the repository: the support notices
collected from the public 기업마당 API and kept unreviewed in the project
vault.  Nothing is invented -- no Case, no business owner, no database
identifier, no reviewer and no eligibility rule.

What passing proves is narrow.  It proves that reading those notes is
deterministic and that a retrieval chunk still quotes its source exactly.  It
does not prove that a real Case ran, that anything was stored, or that a
notice is servable: every notice here is UNREVIEWED and the reviewed set is
still empty.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from app.agent.schemas import SupportProgramRef
from app.agent.support_agent.rag.corpus import (
    PARSER_VERSION,
    load_discovery_corpus,
)
from app.agent.support_agent.wiki.store import MarkdownSupportWikiStore

pytestmark = pytest.mark.real_data

REPO_ROOT = Path(__file__).resolve().parents[3]
VAULT = REPO_ROOT / "docs" / "agent" / "obsidian"
UNREVIEWED = VAULT / "지원사업" / "미검수"
REVIEWED = VAULT / "지원사업" / "검수완료"


def test_the_vault_still_holds_the_collected_notices() -> None:
    """The corpus is built from the notes on disk, not from a fixed list."""

    notes = sorted(path.name for path in UNREVIEWED.glob("PBLN_*.md"))
    assert notes, "no collected notices remain in the vault"

    corpus = load_discovery_corpus(VAULT)

    assert [source.notice.notice_id for source in corpus.sources] == [
        name.removesuffix(".md") for name in notes
    ]
    assert corpus.review_status == "UNREVIEWED"
    assert corpus.parser_version == PARSER_VERSION


def test_every_chunk_quotes_its_source_exactly() -> None:
    """A retrieval hit has to lead back to unaltered official wording.

    This is the property that keeps a search result usable as evidence: the
    stored span must still be a verbatim slice of the field it came from.
    """

    corpus = load_discovery_corpus(VAULT)
    by_notice = {source.notice.notice_id: source for source in corpus.sources}
    assert corpus.chunks, "corpus produced no chunks"

    for chunk in corpus.chunks:
        source = by_notice[chunk.external_notice_id]
        field_value = getattr(source.notice, chunk.field_name)
        assert field_value[chunk.start : chunk.end] == chunk.text
        assert chunk.source_evidence_ref == source.evidence.evidence_id


def test_reading_the_same_notes_twice_gives_the_same_digest() -> None:
    """An unchanged vault must not invalidate an existing index."""

    assert load_discovery_corpus(VAULT).digest == load_discovery_corpus(VAULT).digest


def test_every_notice_records_where_it_actually_came_from() -> None:
    """The evidence says API, because that is what was called.

    These notices came from the public 기업마당 API, not from reading an
    official document or an attachment.  Keeping that distinction visible is
    what stops an API summary from later being cited as the notice text.
    """

    corpus = load_discovery_corpus(VAULT)
    for source in corpus.sources:
        assert source.evidence.source_type.value == "OFFICIAL_API"
        assert source.notice.notice_id.startswith("PBLN_")


def test_the_reviewed_set_is_still_empty() -> None:
    """Guard the claim the documents make, instead of only asserting it there."""

    assert list(REVIEWED.glob("*.md")) == [REVIEWED / "README.md"]


def test_a_lookup_without_a_reviewed_note_is_a_miss() -> None:
    """A missing note is a miss, never a silent fallback to catalog rules."""

    store = MarkdownSupportWikiStore(REVIEWED, known_steps=())
    ref = SupportProgramRef(
        support_program_id=1,
        wiki_uuid=UUID("00000000-0000-4000-8000-000000000000"),
    )

    assert asyncio.run(store.lookup(ref)) is None
