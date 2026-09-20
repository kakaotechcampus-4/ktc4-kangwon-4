"""JSON-file adapter for the reviewed procedure snapshot.

This is the MVP store.  The file is read once when the store is constructed, so
a user request never touches the disk or the network.  When BE exposes the
procedure master, a database-backed reader implements the same
``ReviewedProcedureStore`` protocol and only the construction site changes.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Self

from app.agent.procedure_tool.store import (
    ProcedureStoreError,
    ReviewedProcedureRecord,
    ReviewedProcedureSnapshot,
)
from dotenv import dotenv_values
from pydantic import ValidationError

__all__ = ["DEFAULT_SNAPSHOT_PATH", "JsonFileProcedureStore"]

# 2 MiB is far above any reviewed snapshot we expect and far below anything
# that could exhaust memory if the path is pointed somewhere unintended.
_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024

DEFAULT_SNAPSHOT_PATH = (
    Path(__file__).resolve().parent / "data" / "reviewed-procedures.ko-KR.json"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


class JsonFileProcedureStore:
    """Serve reviewed procedure documents from a snapshot file held in memory."""

    def __init__(self, snapshot: ReviewedProcedureSnapshot) -> None:
        self._snapshot = snapshot
        self._records = tuple(snapshot.records)

    @property
    def snapshot_version(self) -> str:
        return self._snapshot.snapshot_version

    @property
    def generated_at(self) -> str:
        return self._snapshot.generated_at.isoformat()

    def records(self) -> Sequence[ReviewedProcedureRecord]:
        return self._records

    @classmethod
    def from_path(cls, path: str | Path) -> Self:
        snapshot_path = Path(path)
        try:
            size = snapshot_path.stat().st_size
        except OSError as exc:
            raise ProcedureStoreError(
                "reviewed procedure snapshot could not be opened"
            ) from exc
        if size > _MAX_SNAPSHOT_BYTES:
            raise ProcedureStoreError("reviewed procedure snapshot is too large")
        try:
            raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProcedureStoreError(
                "reviewed procedure snapshot could not be read"
            ) from exc
        try:
            snapshot = ReviewedProcedureSnapshot.model_validate(raw)
        except ValidationError as exc:
            # The message is safe: it names fields and rules, never page content.
            raise ProcedureStoreError(
                f"reviewed procedure snapshot failed its contract: {exc.error_count()} "
                "problem(s)"
            ) from exc
        return cls(snapshot)

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> Self:
        """Load the snapshot named by ``AGENT_PROCEDURE_STORE_PATH``.

        Unset means the snapshot shipped with the package, which is the normal
        case.  The override exists so a refresh draft can be tried before it is
        committed.
        """

        environment = os.environ if environ is None else environ
        dotenv_path = Path(env_file) if env_file is not None else _repo_root() / ".env"
        file_values: Mapping[str, str | None] = {}
        if dotenv_path.is_file():
            try:
                file_values = dotenv_values(dotenv_path)
            except (OSError, ValueError) as exc:
                raise ProcedureStoreError(
                    "procedure-store environment file could not be read"
                ) from exc
        raw = environment.get("AGENT_PROCEDURE_STORE_PATH")
        if raw is None:
            raw = file_values.get("AGENT_PROCEDURE_STORE_PATH")
        configured = str(raw).strip() if raw is not None else ""
        return cls.from_path(configured or DEFAULT_SNAPSHOT_PATH)
