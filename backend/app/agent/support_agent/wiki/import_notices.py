"""Import real discovery results into unreviewed Obsidian source notes.

The AI-local ``reborn-support-discovery`` payload stores only an existing
``SupportNoticeCandidate`` and its original ``EvidenceRecord``. It is not the
reviewed ``reborn-support-entry`` format or a BE/API/DB contract. Importing a
notice never creates database identities, eligibility criteria, or approval.
No network requests or attachment downloads are performed.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import secrets
import stat
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.agent.schemas import EvidenceRecord, FreshnessStatus
from app.agent.support_agent.discovery_models import (
    BIZINFO_SUPPORT_API_ENDPOINT,
    SupportNoticeCandidate,
    SupportNoticeDiscoveryResult,
    _candidate_content_digest,
    _candidate_evidence_excerpt,
)
from app.agent.support_agent.refresh import _TITLE_TERMS
from app.agent.support_agent.wiki.store import _root_descriptor

_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_MAX_NOTE_BYTES = 256 * 1024
_NOTE_LANGUAGE = "reborn-support-discovery"
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})([^\r\n]*)(?:\r?\n)?")
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+.!|>~-])")


class SupportNoticeImportError(RuntimeError):
    """A source or destination could not be used safely; no raw data in errors."""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.exit(2, "support notice import: invalid arguments; use --help\n")


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


def _decode_json(payload: str) -> Any:
    return json.loads(
        payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant
    )


def _read_file(path: Path, limit: int) -> bytes:
    # Normalize dot segments without resolving symlinks; every directory and the
    # final file are then opened through descriptors with O_NOFOLLOW.
    absolute = Path(os.path.abspath(path))
    with _root_descriptor(absolute.parent) as directory:
        descriptor = os.open(
            absolute.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
                raise ValueError("input must be a bounded regular file")
            body = source.read(limit + 1)
            if len(body) > limit:
                raise ValueError("input exceeds its size limit")
            return body


def _validate_pair(notice: SupportNoticeCandidate, evidence: EvidenceRecord) -> None:
    """Preserve the discovery result's identity, content, and source lineage."""

    values = notice.model_dump(mode="python")
    digest = _candidate_content_digest(values)
    expected_id = f"support:bizinfo:{notice.notice_id}:{digest.removeprefix('sha256:')}"
    if (
        notice.evidence_ref != evidence.evidence_id
        or evidence.evidence_id != expected_id
        or evidence.source_type != "OFFICIAL_API"
        or notice.freshness_status != FreshnessStatus.UNKNOWN
        or evidence.freshness_status != FreshnessStatus.UNKNOWN
        or evidence.source_ref != BIZINFO_SUPPORT_API_ENDPOINT
        or evidence.locator != notice.detail_url
        or evidence.content_hash != digest
        or evidence.source_version != digest
        or evidence.excerpt != _candidate_evidence_excerpt(values)
        or evidence.parent_evidence_refs
        or evidence.published_at is not None
    ):
        raise ValueError("discovery note source linkage is invalid")


def _discovery_payload(note: str) -> str:
    marker: str | None = None
    is_discovery = False
    payload_start = 0
    offset = 0
    payloads: list[str] = []
    for line in note.splitlines(keepends=True):
        fence = _FENCE.fullmatch(line)
        if fence is not None:
            found_marker, info = fence.groups()
            if marker is None:
                marker = found_marker
                is_discovery = info.strip() == _NOTE_LANGUAGE
                if is_discovery and marker != "```":
                    raise ValueError("discovery fence must use three backticks")
                payload_start = offset + len(line)
            elif (
                found_marker[0] == marker[0]
                and len(found_marker) >= len(marker)
                and not info.strip()
            ):
                if is_discovery:
                    payloads.append(note[payload_start:offset])
                marker = None
                is_discovery = False
        offset += len(line)
    if marker is not None or len(payloads) != 1:
        raise ValueError("note requires exactly one closed discovery fence")
    return payloads[0]


def read_discovery_note(
    path: Path,
) -> tuple[SupportNoticeCandidate, EvidenceRecord]:
    """Read and revalidate one bounded source note without approving it.

    The filename must be the candidate's validated external notice ID plus
    ``.md``. Prose outside the payload supplies no structured facts or criteria.
    """

    try:
        body = _read_file(path, _MAX_NOTE_BYTES)
        payload = _decode_json(_discovery_payload(body.decode("utf-8")))
        if not isinstance(payload, dict) or set(payload) != {"notice", "evidence"}:
            raise ValueError("discovery payload fields are invalid")
        notice = SupportNoticeCandidate.model_validate_json(
            json.dumps(payload["notice"], allow_nan=False), strict=True
        )
        evidence = EvidenceRecord.model_validate_json(
            json.dumps(payload["evidence"], allow_nan=False), strict=True
        )
        if path.name != f"{notice.notice_id}.md":
            raise ValueError("discovery filename does not match notice ID")
        _validate_pair(notice, evidence)
        return notice, evidence
    except (OSError, UnicodeError, TypeError, ValueError, RecursionError):
        raise SupportNoticeImportError(
            "support discovery note could not be read or validated safely"
        ) from None


def _quoted(value: str | None) -> str:
    # Escape HTML, Markdown links/embeds and fences, and prefix EVERY source
    # line. External text cannot become document headings or executable embeds.
    text = value if value is not None else "API 제공 값 없음"
    return "\n".join(
        "> " + _MARKDOWN_SPECIAL.sub(r"\\\1", html.escape(line, quote=False))
        for line in (text.splitlines() or [""])
    )


def _render_note(notice: SupportNoticeCandidate, evidence: EvidenceRecord) -> bytes:
    _validate_pair(notice, evidence)
    fields = (
        ("공고명", notice.title),
        ("외부 공고 ID", notice.notice_id),
        ("공식 공고 출처", notice.detail_url),
        ("공식 API 출처", evidence.source_ref),
        ("소관 기관", notice.jurisdiction_institution),
        ("수행 기관", notice.executing_institution),
        ("API 제공 대상", notice.target),
        ("API 제공 신청 기간", notice.application_period),
        ("API 제공 신청 방법", notice.application_method),
        ("API 제공 요약", notice.summary),
        ("정규화 공고 데이터 SHA-256", evidence.content_hash),
        ("API 수집 시각", evidence.retrieved_at.isoformat()),
        ("근거 ID", evidence.evidence_id),
    )
    sections = [
        (
            "---\nreview_status: UNREVIEWED\nreviewed_by: null\n"
            "reviewed_at: null\ndb_mapping: PENDING\n"
            "tags:\n  - support\n  - unreviewed\n---"
        ),
        "# 지원사업 공고 (미검수)",
        "[[지원사업/목록|공고 목록]] · [[검수 안내]] · [[시작하기]]",
        # The discovery model constrains this to the fixed HTTPS detail URL
        # and a validated notice ID; prose URLs below remain escaped.
        f"[공식 공고 열기]({notice.detail_url})",
        (
            "공식 API가 제공한 수집 필드입니다. 검수 여부는 미검수이며 "
            "최신성은 UNKNOWN입니다. 지원 자격이나 현재 접수 여부를 확정하지 "
            "않습니다. Agent의 검수된 지원사업 저장소에 자동 반영되지 않습니다."
        ),
        (
            "아래 해시는 정규화 공고 데이터의 SHA-256입니다. "
            "HTTP 응답 전체, 공고 본문 전체 또는 첨부 PDF의 해시가 아닙니다. "
            "이미지와 첨부파일은 다운로드하지 않았습니다."
        ),
    ]
    sections.extend(f"## {label}\n\n{_quoted(value)}" for label, value in fields)
    # ASCII serialization also escapes Unicode line separators: source strings
    # cannot inject physical lines or a closing Markdown fence into the payload.
    payload = json.dumps(
        {
            "notice": notice.model_dump(mode="json"),
            "evidence": evidence.model_dump(mode="json"),
        },
        ensure_ascii=True,
        indent=2,
        allow_nan=False,
    )
    sections.append(f"## 검수 전 수집 데이터\n\n```{_NOTE_LANGUAGE}\n{payload}\n```")
    body = ("\n\n".join(sections) + "\n").encode("utf-8")
    if len(body) > _MAX_NOTE_BYTES:
        raise ValueError("rendered discovery note exceeds its size limit")
    return body


@contextmanager
def _destination_directory(vault: Path) -> Iterator[int]:
    with _root_descriptor(Path(os.path.abspath(vault))) as root:
        descriptor = os.dup(root)
        try:
            for part in ("지원사업", "미검수"):
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = child
            yield descriptor
        finally:
            os.close(descriptor)


def _existing_note_matches(directory: int, filename: str, body: bytes) -> bool:
    descriptor = os.open(
        filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
    )
    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("existing discovery note must be a regular file")
        return metadata.st_size == len(body) and source.read(len(body) + 1) == body


def _publish_note(directory: int, filename: str, body: bytes) -> str:
    # Prepare the complete bytes before publishing the final name. A failed
    # write must not leave a partial final note that future imports skip.
    temporary = f".reborn-discovery-{secrets.token_hex(16)}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory,
    )
    try:
        with os.fdopen(descriptor, "wb") as destination:
            os.fchmod(destination.fileno(), 0o600)
            destination.write(body)
            destination.flush()
            os.fsync(destination.fileno())
        try:
            # Unlike rename/replace, link fails if a human or another import
            # has already created the destination. Never overwrite that file.
            os.link(
                temporary,
                filename,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
        except FileExistsError:
            return (
                "unchanged"
                if _existing_note_matches(directory, filename, body)
                else "skipped"
            )
        return "created"
    finally:
        os.unlink(temporary, dir_fd=directory)


def import_notices(sources: Sequence[Path], vault: Path) -> dict[str, int]:
    """Create new notes only, counting identical and differing existing notes.

    Counts refer to candidate occurrences across all supplied result files.
    ``filtered_out`` uses the existing closure-support title filter. Existing
    differing files are ``skipped`` and never overwritten, including human edits.
    """

    counts = {"created": 0, "unchanged": 0, "skipped": 0, "filtered_out": 0}
    try:
        if not sources:
            raise ValueError("at least one real discovery source is required")
        pending: list[tuple[str, bytes]] = []
        # Validate every source before starting writes; never mix raw API rows or
        # a generated approximation into this existing discovery contract.
        for path in sources:
            payload = _read_file(path, _MAX_SOURCE_BYTES).decode("utf-8")
            _decode_json(payload)
            result = SupportNoticeDiscoveryResult.model_validate_json(
                payload, strict=True
            )
            evidence_by_id = {
                record.evidence_id: record for record in result.evidence_records
            }
            for notice in result.candidates:
                if not any(term in notice.title for term in _TITLE_TERMS):
                    counts["filtered_out"] += 1
                    continue
                pending.append(
                    (
                        f"{notice.notice_id}.md",
                        _render_note(notice, evidence_by_id[notice.evidence_ref]),
                    )
                )
        with _destination_directory(vault) as directory:
            for filename, body in pending:
                counts[_publish_note(directory, filename, body)] += 1
        return counts
    except (OSError, UnicodeError, TypeError, ValueError, RecursionError):
        raise SupportNoticeImportError(
            "support notice import could not validate sources or write safely"
        ) from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = _SafeArgumentParser(
        description=(
            "Import real SupportNoticeDiscoveryResult JSON files into unreviewed "
            "Obsidian notes, without overwriting existing files."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        action="append",
        required=True,
        help="actual discovery result JSON (up to 4 MiB); may be repeated",
    )
    parser.add_argument(
        "--vault", type=Path, required=True, help="existing Obsidian vault root"
    )
    args = parser.parse_args(argv)
    try:
        counts = import_notices(args.source, args.vault)
    except SupportNoticeImportError:
        print(
            "support notice import failed: invalid source or unsafe file operation",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SupportNoticeImportError",
    "import_notices",
    "main",
    "read_discovery_note",
]
