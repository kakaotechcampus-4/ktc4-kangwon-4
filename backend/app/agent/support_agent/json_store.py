"""JSON-file adapter for the reviewed support catalog.

Same shape as the procedure snapshot: read once at construction, answer from
memory, and swap the implementation when a database is ready.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Self

from dotenv import dotenv_values
from pydantic import ValidationError

from app.agent.support_agent.store import (
    ReviewedSupportSnapshot,
    SupportStoreError,
)

__all__ = ["DEFAULT_CATALOG_PATH", "JsonFileSupportStore"]

_MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024

DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parent / "data" / "reviewed-support.ko-KR.json"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


class JsonFileSupportStore:
    """Serve the reviewed support catalog from a snapshot file held in memory."""

    def __init__(self, snapshot: ReviewedSupportSnapshot) -> None:
        self._snapshot = snapshot

    @property
    def catalog_version(self) -> str:
        return self._snapshot.catalog_version

    def snapshot(self) -> ReviewedSupportSnapshot:
        return self._snapshot

    @classmethod
    def from_path(cls, path: str | Path) -> Self:
        snapshot_path = Path(path)
        try:
            size = snapshot_path.stat().st_size
        except OSError as exc:
            raise SupportStoreError(
                "reviewed support catalog could not be opened"
            ) from exc
        if size > _MAX_SNAPSHOT_BYTES:
            raise SupportStoreError("reviewed support catalog is too large")
        try:
            raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SupportStoreError(
                "reviewed support catalog could not be read"
            ) from exc
        try:
            snapshot = ReviewedSupportSnapshot.model_validate(raw)
        except ValidationError as exc:
            raise SupportStoreError(
                "reviewed support catalog failed its contract: "
                f"{exc.error_count()} problem(s)"
            ) from exc
        return cls(snapshot)

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> Self:
        """Load the catalog named by ``AGENT_SUPPORT_CATALOG_PATH``."""

        environment = os.environ if environ is None else environ
        dotenv_path = Path(env_file) if env_file is not None else _repo_root() / ".env"
        file_values: Mapping[str, str | None] = {}
        if dotenv_path.is_file():
            try:
                file_values = dotenv_values(dotenv_path)
            except (OSError, ValueError) as exc:
                raise SupportStoreError(
                    "support-catalog environment file could not be read"
                ) from exc
        raw = environment.get("AGENT_SUPPORT_CATALOG_PATH")
        if raw is None:
            raw = file_values.get("AGENT_SUPPORT_CATALOG_PATH")
        configured = str(raw).strip() if raw is not None else ""
        return cls.from_path(configured or DEFAULT_CATALOG_PATH)
