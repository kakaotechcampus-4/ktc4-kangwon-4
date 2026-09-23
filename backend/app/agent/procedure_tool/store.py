"""Procedure records and the caller-supplied, in-memory lookup contract."""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Annotated, Protocol
from urllib.parse import urlsplit

from pydantic import Field, StrictInt, StrictStr, model_validator

from app.agent.schemas import (
    AgentSchema,
    AwareDatetime,
    Digest,
    FreshnessStatus,
    NonEmptyStr,
    RuntimeDateTime,
    UpperSnakeCode,
)

__all__ = [
    "ProcedureStoreError",
    "ReviewedProcedureRecord",
    "ReviewedProcedureSnapshot",
    "ReviewedProcedureStore",
]


class ProcedureStoreError(RuntimeError):
    """Raised when a snapshot cannot be loaded or fails its own contract.

    Only the local, gitignored JSON-file loader raises this -- the tracked
    request-path runtime never reads a snapshot from disk.
    """


class ReviewedProcedureRecord(AgentSchema):
    """One official document that a person checked and approved for serving.

    ``excerpt`` and ``content_hash`` are the bytes that were actually fetched.
    They are not re-derived at request time, so a claim built on this record
    stays traceable to the document as it looked on ``retrieved_at``.
    """

    record_id: UpperSnakeCode = Field(
        description="Stable snapshot-local identifier for this document."
    )
    title: NonEmptyStr
    authority_name: NonEmptyStr = Field(
        description="Publishing institution, shown to the user as the source."
    )
    canonical_url: NonEmptyStr
    source_domain: NonEmptyStr
    excerpt: Annotated[StrictStr, Field(min_length=1, max_length=6000)]
    content_hash: Digest = Field(
        description="SHA-256 of the fetched body, carried over from the refresh run."
    )
    published_at: AwareDatetime | None = Field(
        description="Publication time when the page states one; otherwise null."
    )
    retrieved_at: RuntimeDateTime = Field(
        description="When the refresh command fetched this body."
    )
    reviewed_by: NonEmptyStr | None = Field(
        description="Person who approved this text. Null means not reviewed yet."
    )
    reviewed_at: AwareDatetime | None = Field(
        description="When that approval happened. Null means not reviewed yet."
    )
    review_valid_days: Annotated[StrictInt, Field(ge=1, le=3650)] = Field(
        description="How long an approval stays current before it reads as STALE."
    )
    step_codes: list[UpperSnakeCode] = Field(
        description="Canonical procedure steps this document may be bound to."
    )
    required_terms: list[NonEmptyStr] = Field(
        description="Every term must appear in a query for this record to match."
    )
    any_terms: list[NonEmptyStr] = Field(
        description="At least one term must appear. Empty means no extra condition."
    )

    @model_validator(mode="after")
    def validate_record(self) -> ReviewedProcedureRecord:
        if (self.reviewed_by is None) != (self.reviewed_at is None):
            raise ValueError("reviewed_by and reviewed_at must be set together")
        if not self.required_terms:
            raise ValueError("a record must declare at least one required term")
        for name, terms in (
            ("step_codes", self.step_codes),
            ("required_terms", self.required_terms),
            ("any_terms", self.any_terms),
        ):
            if len(set(terms)) != len(terms):
                raise ValueError(f"{name} must be unique")
        if not self.step_codes:
            raise ValueError("a record must bind to at least one procedure step")
        self._validate_url()
        return self

    def _validate_url(self) -> None:
        # Same identity rules as ProcedureSourceDocument. Checking them here too
        # means a bad snapshot fails at load, not halfway through a user request.
        parsed = urlsplit(self.canonical_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("reviewed procedure URL must be absolute HTTPS")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("reviewed procedure URL must not carry credentials")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("reviewed procedure URL has an invalid port") from exc
        if port is not None:
            raise ValueError("reviewed procedure URL must omit its port")
        try:
            hostname = (
                parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
            )
        except UnicodeError as exc:
            raise ValueError("reviewed procedure hostname is invalid") from exc
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise ValueError("reviewed procedure URL must not use an IP literal")
        if self.source_domain != hostname or parsed.netloc != hostname:
            raise ValueError("source_domain must equal the canonical lowercase host")
        if not parsed.path:
            raise ValueError("reviewed procedure URL must have a path")

    def matches(self, query: str) -> bool:
        """Return whether this record answers ``query``.

        Same rule the code-reviewed URL registry uses, so moving a source from
        live fetch into the snapshot does not change which query finds it.
        """

        normalized = query.casefold()
        if not all(term.casefold() in normalized for term in self.required_terms):
            return False
        return not self.any_terms or any(
            term.casefold() in normalized for term in self.any_terms
        )

    def freshness(self, as_of: date) -> FreshnessStatus:
        """Report how much this record may be relied on.

        Only a record a person approved can read as ``CURRENT``.  An unreviewed
        one stays ``UNKNOWN``, which is what keeps Info from stating deadlines
        and documents as settled fact and what makes Review block a bare claim
        built on it.  Serving unreviewed text as current would quietly undo
        those two guards.
        """

        if self.reviewed_by is None or self.reviewed_at is None:
            return FreshnessStatus.UNKNOWN
        expires_on = self.reviewed_at.date() + timedelta(days=self.review_valid_days)
        if as_of <= expires_on:
            return FreshnessStatus.CURRENT
        return FreshnessStatus.STALE


class ReviewedProcedureSnapshot(AgentSchema):
    """A whole snapshot file: a version, when it was built, and its records.

    Only the local, gitignored JSON-file loader constructs this -- the
    tracked request-path runtime is handed records directly.
    """

    snapshot_version: NonEmptyStr = Field(
        description="Version recorded on every document served from this snapshot."
    )
    generated_at: RuntimeDateTime = Field(
        description="When the refresh command produced this snapshot."
    )
    locale: NonEmptyStr
    records: list[ReviewedProcedureRecord]

    @model_validator(mode="after")
    def validate_snapshot(self) -> ReviewedProcedureSnapshot:
        for name, values in (
            ("record_id", [item.record_id for item in self.records]),
            ("canonical_url", [item.canonical_url for item in self.records]),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"snapshot {name} must be unique")
        return self


class ReviewedProcedureStore(Protocol):
    """Read preloaded records; the caller owns persistence and review."""

    @property
    def snapshot_version(self) -> str: ...

    def records(self) -> Sequence[ReviewedProcedureRecord]: ...
