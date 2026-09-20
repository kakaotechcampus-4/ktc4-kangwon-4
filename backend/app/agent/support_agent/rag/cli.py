"""Build and search an isolated index of real, unreviewed discovery notes.

Commands never touch Case data, the reviewed catalog, MySQL or S3. A successful
search is a source lookup, not eligibility analysis or a freshness assessment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent.guardrails import ensure_no_sensitive_text
from app.agent.support_agent.discovery_tool import _ensure_no_support_search_identifiers
from app.agent.support_agent.rag.corpus import (
    PARSER_VERSION,
    DiscoveryIndexManifest,
    load_discovery_corpus,
)
from app.agent.support_agent.rag.embeddings import EmbeddingClient
from app.agent.support_agent.rag.index import ChromaDiscoveryIndex, IndexRecord
from app.agent.support_agent.wiki.import_notices import _decode_json, _read_file
from app.agent.support_agent.wiki.store import _root_descriptor

_MANIFEST_FILE = "corpus.json"
_MAX_MANIFEST_BYTES = 32 * 1024 * 1024
_MAX_RUN_SECONDS = 120


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.exit(2, "discovery retrieval: invalid arguments; use --help\n")


def _new_directory(path: Path) -> Path:
    root = Path(os.path.abspath(path))
    with _root_descriptor(root.parent) as parent:
        os.mkdir(root.name, mode=0o700, dir_fd=parent)
    return root


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("discovery retrieval exceeded its publication deadline")


def _write_new_json(path: Path, value: Any, *, deadline: float) -> None:
    body = (
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode()
    if len(body) > _MAX_MANIFEST_BYTES:
        raise ValueError("retrieval artifact exceeds the size limit")
    root = Path(os.path.abspath(path))
    with _root_descriptor(root.parent) as parent:
        temporary = f".reborn-retrieval-{secrets.token_hex(16)}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        try:
            with os.fdopen(descriptor, "wb") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
            _check_deadline(deadline)
            os.link(
                temporary,
                root.name,
                src_dir_fd=parent,
                dst_dir_fd=parent,
                follow_symlinks=False,
            )
        finally:
            os.unlink(temporary, dir_fd=parent)


async def _build(args: argparse.Namespace, deadline: float) -> dict[str, Any]:
    corpus = load_discovery_corpus(args.vault)
    _check_deadline(deadline)
    records = [
        IndexRecord(
            chunk_id=chunk.chunk_id,
            text=chunk.text,
            metadata={
                "external_notice_id": chunk.external_notice_id,
                "source_evidence_ref": chunk.source_evidence_ref,
                "field_name": chunk.field_name,
                "start": chunk.start,
                "end": chunk.end,
                "parser_version": PARSER_VERSION,
                "review_status": "UNREVIEWED",
                "freshness_status": "UNKNOWN",
            },
        )
        for chunk in corpus.chunks
    ]
    # Exclusive directory creation means a build can never overwrite an index.
    # Until the final manifest exists, search treats an interrupted build as invalid.
    root = _new_directory(args.index)
    chroma_path = _new_directory(root / "chroma")
    vectors = []
    async with EmbeddingClient.from_env() as embeddings:
        for offset in range(0, len(records), 32):
            vectors.extend(
                await embeddings.embed(
                    [item.text for item in records[offset : offset + 32]]
                )
            )
        dimensions = len(vectors[0])
        _check_deadline(deadline)
        index = ChromaDiscoveryIndex.create(
            chroma_path,
            embedding_model=embeddings.model,
            dimensions=dimensions,
            corpus_digest=corpus.digest,
        )
        index.add(records, vectors)
        _check_deadline(deadline)
        if index.count() != len(records):
            raise ValueError("stored chunk count does not match corpus")
        manifest = DiscoveryIndexManifest(
            embedding_model=embeddings.model,
            reported_embedding_model=embeddings.reported_model,
            dimensions=dimensions,
            corpus_digest=corpus.digest,
            corpus=corpus,
        )
        _write_new_json(
            root / _MANIFEST_FILE, manifest.model_dump(mode="json"), deadline=deadline
        )
    return {
        "result": "INDEXED_UNREVIEWED_DISCOVERY",
        "notices": len(corpus.sources),
        "chunks": len(records),
        "embedding_dimensions": dimensions,
        "embedding_model": embeddings.model,
        "reported_embedding_model": embeddings.reported_model,
        "embedding_requests": embeddings.request_count,
        "corpus_digest": corpus.digest,
        "review_status": "UNREVIEWED",
        "s3_original_checked": False,
    }


async def _search(args: argparse.Namespace, deadline: float) -> dict[str, Any]:
    if not args.query.strip() or len(args.query) > 1000:
        raise ValueError("public discovery query length is outside the limit")
    ensure_no_sensitive_text([args.query])
    _ensure_no_support_search_identifiers([args.query])
    body = _read_file(args.index / _MANIFEST_FILE, _MAX_MANIFEST_BYTES)
    _decode_json(body.decode("utf-8"))
    manifest = DiscoveryIndexManifest.model_validate_json(body, strict=True)
    actual = load_discovery_corpus(args.vault)
    _check_deadline(deadline)
    if actual.digest != manifest.corpus_digest:
        raise ValueError("current source notes differ from the indexed corpus")
    sources = {source.notice.notice_id: source for source in actual.sources}
    if args.notice_id is not None and args.notice_id not in sources:
        raise ValueError("notice filter is outside the indexed corpus")
    index = ChromaDiscoveryIndex.open(
        args.index / "chroma",
        embedding_model=manifest.embedding_model,
        dimensions=manifest.dimensions,
        corpus_digest=manifest.corpus_digest,
    )
    if index.count() != len(actual.chunks):
        raise ValueError("stored chunk count does not match corpus")
    _check_deadline(deadline)
    async with EmbeddingClient.from_env(
        expected_dimensions=manifest.dimensions
    ) as embeddings:
        if embeddings.model != manifest.embedding_model:
            raise ValueError("embedding model differs from the index model")
        vector = (await embeddings.embed([args.query]))[0]
        if embeddings.reported_model != manifest.reported_embedding_model:
            raise ValueError("reported embedding model differs from the index model")
    hits = index.search(vector, limit=args.limit, external_notice_id=args.notice_id)
    _check_deadline(deadline)
    chunks = {chunk.chunk_id: chunk for chunk in actual.chunks}
    matches = []
    for hit in hits:
        chunk = chunks.get(hit.chunk_id)
        if chunk is None:
            raise ValueError("retrieval returned a chunk outside the verified corpus")
        source = sources[chunk.external_notice_id]
        if args.notice_id is not None and source.notice.notice_id != args.notice_id:
            raise ValueError("retrieval returned a different notice from the filter")
        matches.append(
            {
                "external_notice_id": source.notice.notice_id,
                "title": source.notice.title,
                "canonical_url": source.notice.detail_url,
                "agency": source.notice.jurisdiction_institution,
                "chunk_id": chunk.chunk_id,
                "field_name": chunk.field_name,
                "start": chunk.start,
                "end": chunk.end,
                "excerpt": chunk.text,
                "distance": hit.distance,
                "source_evidence_ref": source.evidence.evidence_id,
                "source_version": source.evidence.source_version,
                "source_content_hash": source.evidence.content_hash,
                "parser_version": PARSER_VERSION,
                "retrieved_at": source.evidence.retrieved_at.isoformat(),
                "provider_updated_at": (
                    source.notice.provider_updated_at.isoformat()
                    if source.notice.provider_updated_at is not None
                    else None
                ),
                "freshness_status": "UNKNOWN",
                "review_status": "UNREVIEWED",
            }
        )
    report = {
        "result": "DISCOVERY_MATCHES" if matches else "DISCOVERY_NOT_FOUND",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "corpus_digest": actual.digest,
        "source_note_integrity_checked": True,
        "s3_original_checked": False,
        "policy_freshness_checked": False,
        "review_status": "UNREVIEWED",
        "matches": matches,
        "embedding_requests": embeddings.request_count,
    }
    _write_new_json(args.output, report, deadline=deadline)
    return {
        "result": report["result"],
        "match_count": len(matches),
        "source_note_integrity_checked": True,
        "s3_original_checked": False,
        "policy_freshness_checked": False,
        "review_status": "UNREVIEWED",
        "embedding_requests": embeddings.request_count,
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    deadline = time.monotonic() + _MAX_RUN_SECONDS
    async with asyncio.timeout(_MAX_RUN_SECONDS):
        return await (
            _build(args, deadline)
            if args.command == "index"
            else _search(args, deadline)
        )


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(
        description="Index/search real unreviewed public support notices."
    )
    commands = parser.add_subparsers(
        dest="command", required=True, parser_class=_SafeParser
    )
    for command in ("index", "search"):
        child = commands.add_parser(command)
        child.add_argument("--vault", type=Path, required=True)
        child.add_argument("--index", type=Path, required=True)
        if command == "search":
            child.add_argument(
                "--query",
                required=True,
                help="public information only; never Case text",
            )
            child.add_argument("--notice-id", default=None)
            child.add_argument("--limit", type=int, choices=range(1, 11), default=5)
            child.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(_run(args))
    except (OSError, ValueError, RuntimeError, TypeError, TimeoutError):
        # Source text, paths, provider responses and credentials are not errors.
        print(
            "discovery retrieval failed: configuration, source or index validation failed",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
