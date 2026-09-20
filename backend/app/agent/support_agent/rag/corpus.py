"""Versioned discovery corpus with exact source-field spans.

This is an AI-local retrieval artifact, never a ReviewedSupportCatalog. No
database identities, human approval or eligibility rules are created here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Self

from app.agent.guardrails import sha256_digest
from app.agent.schemas import AgentSchema, Digest, EvidenceRecord, NonEmptyStr
from app.agent.support_agent.discovery_models import SupportNoticeCandidate
from app.agent.support_agent.wiki.import_notices import (
    _validate_pair,
    read_discovery_note,
)
from app.agent.support_agent.wiki.store import _root_descriptor
from pydantic import Field, StrictInt, model_validator

PARSER_VERSION = "bizinfo-api-fields-v1"
MAX_NOTICES = 100
MAX_CHUNKS = 1000
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 120
SourceField = Literal[
    "title", "summary", "target", "application_period", "application_method"
]
_FIELDS: tuple[SourceField, ...] = (
    "title",
    "summary",
    "target",
    "application_period",
    "application_method",
)


class DiscoveryCorpusError(RuntimeError):
    """A corpus failed source integrity checks; never includes raw contents."""


class DiscoverySource(AgentSchema):
    notice: SupportNoticeCandidate
    evidence: EvidenceRecord

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        _validate_pair(self.notice, self.evidence)
        return self


class DiscoveryChunk(AgentSchema):
    chunk_id: Digest
    external_notice_id: NonEmptyStr
    source_evidence_ref: NonEmptyStr
    field_name: SourceField
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(gt=0)
    text: NonEmptyStr = Field(max_length=CHUNK_CHARS)


def _chunks_for(source: DiscoverySource) -> list[DiscoveryChunk]:
    chunks = []
    for field in _FIELDS:
        value = getattr(source.notice, field)
        if not value:
            continue
        start = 0
        while start < len(value):
            end = min(start + CHUNK_CHARS, len(value))
            excerpt = value[start:end]
            if excerpt.strip():
                identity = {
                    "parser_version": PARSER_VERSION,
                    "source_evidence_ref": source.evidence.evidence_id,
                    "field_name": field,
                    "start": start,
                    "end": end,
                    "text": excerpt,
                }
                chunks.append(
                    DiscoveryChunk(
                        chunk_id=sha256_digest(identity),
                        external_notice_id=source.notice.notice_id,
                        source_evidence_ref=source.evidence.evidence_id,
                        field_name=field,
                        start=start,
                        end=end,
                        text=excerpt,
                    )
                )
            if end == len(value):
                break
            start = end - CHUNK_OVERLAP
    return chunks


class DiscoveryCorpus(AgentSchema):
    format_version: Literal["reborn-support-discovery-v1"] = (
        "reborn-support-discovery-v1"
    )
    parser_version: Literal["bizinfo-api-fields-v1"] = PARSER_VERSION
    review_status: Literal["UNREVIEWED"] = "UNREVIEWED"
    sources: list[DiscoverySource] = Field(min_length=1, max_length=MAX_NOTICES)
    chunks: list[DiscoveryChunk] = Field(min_length=1, max_length=MAX_CHUNKS)

    @model_validator(mode="after")
    def validate_exact_chunks(self) -> Self:
        notice_ids = [source.notice.notice_id for source in self.sources]
        if notice_ids != sorted(set(notice_ids)):
            raise ValueError("corpus notice identifiers must be unique and sorted")
        expected = [chunk for source in self.sources for chunk in _chunks_for(source)]
        if self.chunks != expected:
            raise ValueError("corpus chunks must match exact source-field spans")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))


class DiscoveryIndexManifest(AgentSchema):
    embedding_model: NonEmptyStr
    reported_embedding_model: NonEmptyStr
    dimensions: StrictInt = Field(ge=1, le=65536)
    corpus_digest: Digest
    corpus: DiscoveryCorpus

    @model_validator(mode="after")
    def validate_digest(self) -> Self:
        if self.corpus_digest != self.corpus.digest:
            raise ValueError("index manifest corpus digest does not match")
        return self


def load_discovery_corpus(vault: Path) -> DiscoveryCorpus:
    """Read only existing, externally identified discovery notes in this vault."""

    try:
        root = Path(os.path.abspath(vault)) / "지원사업" / "미검수"
        with _root_descriptor(root) as directory:
            names = sorted(
                name
                for name in os.listdir(directory)
                if name.startswith("PBLN_") and name.endswith(".md")
            )
        if not 1 <= len(names) <= MAX_NOTICES:
            raise ValueError("corpus notice count is outside the permitted range")
        sources = [
            DiscoverySource(notice=notice, evidence=evidence)
            for name in names
            for notice, evidence in [read_discovery_note(root / name)]
        ]
        chunks = [chunk for source in sources for chunk in _chunks_for(source)]
        return DiscoveryCorpus(sources=sources, chunks=chunks)
    except (OSError, ValueError, RuntimeError):
        raise DiscoveryCorpusError(
            "discovery corpus could not be read or source-validated"
        ) from None


__all__ = [
    "DiscoveryChunk",
    "DiscoveryCorpus",
    "DiscoveryCorpusError",
    "DiscoveryIndexManifest",
    "DiscoverySource",
    "load_discovery_corpus",
]
