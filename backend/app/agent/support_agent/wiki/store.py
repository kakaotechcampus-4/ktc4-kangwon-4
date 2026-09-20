"""Read one existing reviewed support entry from an exact UUID Markdown note.

The opt-in AI-local format is one ``reborn-support-entry`` fenced JSON block
containing the existing ``ReviewedSupportEntry`` model. This is not a shared
BE/API/DB contract. Prose outside that block never supplies eligibility rules.
The reader performs no writes, network fetches, or automatic human approval.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.agent.schemas import (
    CASE_FIELD_SPECS,
    EvidenceRecord,
    KnownProcedureStep,
    SupportProgramRef,
    validate_case_field_value,
)
from app.agent.support_agent.models import (
    ReviewedSupportCatalog,
    ReviewedSupportProgram,
)
from app.agent.support_agent.store import (
    ReviewedSupportEntry,
    ReviewedSupportSnapshot,
    SupportStoreError,
)

_MAX_NOTE_BYTES = 256 * 1024
_MAX_EXCERPT_CHARS = 4000
_ENTRY_LANGUAGE = "reborn-support-entry"
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})([^\r\n]*)(?:\r?\n)?")


class SupportWikiStore(Protocol):
    async def lookup(self, ref: SupportProgramRef) -> ReviewedSupportCatalog | None: ...


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise ValueError("nonstandard JSON constant")


def _entry_payload(note: str) -> str:
    """Extract one top-level entry fence; ignore unrelated Markdown prose."""

    marker: str | None = None
    is_entry = False
    payload_start = 0
    offset = 0
    payloads: list[str] = []
    for line in note.splitlines(keepends=True):
        fence = _FENCE.fullmatch(line)
        if fence is not None:
            found_marker, info = fence.groups()
            if marker is None:
                marker = found_marker
                is_entry = info.strip() == _ENTRY_LANGUAGE
                if is_entry and marker != "```":
                    raise ValueError("entry fence must use three backticks")
                payload_start = offset + len(line)
            elif (
                found_marker[0] == marker[0]
                and len(found_marker) >= len(marker)
                and not info.strip()
            ):
                if is_entry:
                    payloads.append(note[payload_start:offset])
                marker = None
                is_entry = False
        offset += len(line)
    if marker is not None or len(payloads) != 1:
        raise ValueError("note requires exactly one closed entry fence")
    return payloads[0]


@contextmanager
def _root_descriptor(root: Path) -> Iterator[int]:
    """Walk the configured absolute directory without following any symlink."""

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(root.anchor, flags)
    try:
        for part in root.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


class MarkdownSupportWikiStore:
    """Read only ``<wiki_uuid>.md`` for the requested ID/UUID pair.

    A missing note or a valid but unservable entry is a miss. Invalid notes and
    unsafe paths raise sanitized ``SupportStoreError`` values. The catalog
    version is the SHA-256 of bytes read from the note, not a database version.
    UNKNOWN/STALE source freshness is preserved even when the note is reviewed.
    """

    def __init__(self, root: Path, known_steps: Sequence[KnownProcedureStep]) -> None:
        # abspath normalizes dot segments but deliberately does not resolve links.
        self._root = Path(os.path.abspath(root))
        self._known_steps = tuple(step.model_copy(deep=True) for step in known_steps)

    async def lookup(self, ref: SupportProgramRef) -> ReviewedSupportCatalog | None:
        try:
            reference = SupportProgramRef.model_validate(ref.model_dump(mode="python"))
        except (TypeError, ValueError):
            raise SupportStoreError(
                "support wiki reference failed its contract"
            ) from None
        return await asyncio.to_thread(self._lookup, reference)

    def _read_note(self, filename: str) -> bytes | None:
        try:
            with _root_descriptor(self._root) as directory:
                try:
                    descriptor = os.open(
                        filename,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                        dir_fd=directory,
                    )
                except FileNotFoundError:
                    return None
                with os.fdopen(descriptor, "rb") as source:
                    metadata = os.fstat(source.fileno())
                    if not stat.S_ISREG(metadata.st_mode):
                        raise SupportStoreError(
                            "support wiki note must be a regular file"
                        )
                    if metadata.st_size > _MAX_NOTE_BYTES:
                        raise SupportStoreError(
                            "support wiki note exceeds its size limit"
                        )
                    body = source.read(_MAX_NOTE_BYTES + 1)
                    if len(body) > _MAX_NOTE_BYTES:
                        raise SupportStoreError(
                            "support wiki note exceeds its size limit"
                        )
                    return body
        except OSError:
            raise SupportStoreError(
                "support wiki note could not be read safely"
            ) from None

    def _lookup(self, ref: SupportProgramRef) -> ReviewedSupportCatalog | None:
        body = self._read_note(f"{ref.wiki_uuid}.md")
        if body is None:
            return None
        read_at = datetime.now(timezone.utc)
        try:
            payload = _entry_payload(body.decode("utf-8"))
            # Pydantic handles typed JSON dates/UUIDs; first reject duplicate keys
            # and nonstandard constants that ordinary JSON decoding can conceal.
            json.loads(
                payload,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
            entry = ReviewedSupportEntry.model_validate_json(payload, strict=True)
            if (
                entry.wiki_uuid != ref.wiki_uuid
                or entry.support_program_id != ref.support_program_id
            ):
                raise SupportStoreError(
                    "support wiki note identity does not match request"
                )
            if entry.reviewed_at is not None and entry.reviewed_at > read_at:
                raise SupportStoreError(
                    "support wiki review time must not be in the future"
                )
            if not entry.is_servable:
                return None
            if entry.evidence.source_type not in {"OFFICIAL_DOCUMENT", "OFFICIAL_API"}:
                return None
            # This existing entry format contains one official Evidence record.
            # Any parents would be absent from the returned lineage; do not invent them.
            if entry.evidence.parent_evidence_refs:
                raise SupportStoreError(
                    "support wiki official evidence lineage is incomplete"
                )
            known_codes = {step.procedure_step.step_code for step in self._known_steps}
            if set(entry.related_step_codes) - known_codes:
                raise SupportStoreError(
                    "support wiki refers to an unknown procedure step"
                )
            for criterion in entry.criteria:
                value_type = CASE_FIELD_SPECS[criterion.field_path][0]
                for value in criterion.required_values:
                    validate_case_field_value(
                        criterion.field_path, value_type, value, allow_null=False
                    )
            digest = hashlib.sha256(body).hexdigest()
            version = f"sha256:{digest}"
            snapshot = ReviewedSupportSnapshot(
                catalog_version=version,
                generated_at=read_at,
                entries=[entry],
            )
            catalog, _ = snapshot.build_catalog(known_steps=self._known_steps)
            wiki_evidence = EvidenceRecord(
                evidence_id=f"wiki:{ref.wiki_uuid}:{digest}",
                source_type="REVIEWED_WIKI",
                source_ref=f"wiki:{ref.wiki_uuid}",
                source_version=version,
                locator=f"wiki:{ref.wiki_uuid}",
                excerpt=payload[:_MAX_EXCERPT_CHARS],
                parent_evidence_refs=[entry.evidence.evidence_id],
                published_at=None,
                retrieved_at=read_at,
                freshness_status=entry.evidence.freshness_status,
                content_hash=version,
            )
            program = catalog.programs[0]
            program = ReviewedSupportProgram.model_validate(
                {
                    **program.model_dump(mode="python"),
                    "evidence_refs": (
                        *program.evidence_refs,
                        wiki_evidence.evidence_id,
                    ),
                }
            )
            return ReviewedSupportCatalog(
                catalog_version=version,
                programs=(program,),
                evidence_records=(*catalog.evidence_records, wiki_evidence),
            )
        except (TypeError, ValueError, RecursionError):
            raise SupportStoreError("support wiki note failed its contract") from None


__all__ = ["MarkdownSupportWikiStore", "SupportWikiStore"]
