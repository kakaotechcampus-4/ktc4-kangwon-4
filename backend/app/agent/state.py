"""Typed state passed through the bounded Agent graph."""

from __future__ import annotations

from typing import Literal, TypedDict
from uuid import UUID

from app.agent.schemas import (
    AgentGraphInput,
    AgentGraphOutput,
    Component,
    FactChangeCandidate,
    InvocationMeta,
    ReviewIssue,
    ReviewResult,
    ReviewSourceResult,
    ReviewSubject,
    SupervisorDraft,
)

GraphPhase = Literal[
    "PLANNING",
    "INFO_ANALYSIS",
    "PROCEDURE_LOOKUP",
    "SUPPORT_ANALYSIS",
    "DRAFTING",
    "REVIEWING",
    "REVISING",
    "COMPLETED",
    "SAFE_FAILED",
]


class AgentGraphState(TypedDict, total=False):
    request: AgentGraphInput
    run_id: UUID
    trace_id: str | None
    phase: GraphPhase
    source_results: list[ReviewSourceResult]
    fact_overlays: list[FactChangeCandidate]
    current_draft: SupervisorDraft
    review_subject: ReviewSubject
    review_result: ReviewResult
    review_meta: InvocationMeta
    review_feedback: list[ReviewIssue]
    rework_targets: list[Component]
    revision_count: int
    outcome: AgentGraphOutput
    failure_code: str
    failure_message_code: str
    failed_component: Component | None
    retryable: bool
    # Set only when a failure has a more useful follow-up than retry-or-nothing.
    recovery_action_code: str


__all__ = ["AgentGraphState", "GraphPhase"]
