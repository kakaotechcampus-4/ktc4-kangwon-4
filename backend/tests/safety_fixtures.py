"""Synthetic reviewed plans for safety tests; no provider or database calls."""

from datetime import datetime, timezone
from uuid import UUID

from app.agent.schemas import (
    AgentGraphInput,
    EvidenceRecord,
    ProcedureLookupResult,
    ReviewedPlanOutcome,
    ReviewSourceResult,
    ReviewSubject,
    SupervisorDraft,
    canonical_digest,
)

NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)


def fixture():
    evidence = EvidenceRecord(
        evidence_id="synthetic-user",
        source_type="USER_INPUT",
        source_ref="synthetic:input",
        source_version=None,
        locator=None,
        excerpt="합성 카페 입력",
        parent_evidence_refs=[],
        published_at=None,
        retrieved_at=NOW,
        freshness_status="CURRENT",
        content_hash="0" * 64,
    )
    facts = [
        ("business_type", "STRING", "카페"),
        ("franchise_status", "BOOLEAN", False),
        ("lease_status", "ENUM", "LEASED_PAID"),
        ("employee_count", "INTEGER", None),
    ]
    request = AgentGraphInput(
        trigger={
            "trigger_type": "CASE_CREATED",
            "input_event_id": "synthetic-event",
            "client_event_id": None,
            "submitted_at": NOW,
            "input": {
                "input_event_id": "synthetic-event",
                "source_type": "USER_INPUT",
                "redacted_text": "합성 카페 입력",
                "redactions": [],
                "submitted_at": NOW,
            },
        },
        case_snapshot={
            "snapshot_id": UUID(int=1),
            "case_id": 1,
            "case_status": "IN_PROGRESS",
            "facts": [
                {
                    "field_path": key,
                    "value_type": kind,
                    "value": value,
                    "status": "UNKNOWN" if value is None else "CONFIRMED",
                    "evidence_refs": [] if value is None else [evidence.evidence_id],
                    "updated_at": None if value is None else NOW,
                }
                for key, kind, value in facts
            ],
            "procedure_progress": [],
            "evidence_records": [evidence],
            "captured_at": NOW,
        },
    )
    lookup = ProcedureLookupResult(
        completion_status="NO_RESULTS",
        lookup_id=UUID(int=2),
        documents=[],
        warnings=[],
        evidence_records=[],
        based_on_snapshot_id=UUID(int=1),
        as_of=NOW.date(),
    )
    source = ReviewSourceResult(
        meta={
            "schema_version": "agent-io/2.0",
            "run_id": UUID(int=3),
            "call_id": UUID(int=4),
            "parent_call_id": None,
            "case_id": 1,
            "component": "PROCEDURE_TOOL",
            "attempt": 1,
            "requested_at": NOW,
            "trace_id": None,
        },
        output=lookup,
        output_digest=canonical_digest(lookup),
    )
    draft = SupervisorDraft(
        decision={
            "decision_type": "NEEDS_MORE_INFO",
            "draft_id": UUID(int=5),
            "draft_version": 1,
            "selection_summary": "확인이 필요합니다.",
            "requires_human": True,
            "evidence_refs": [evidence.evidence_id],
            "based_on_call_ids": [UUID(int=4)],
            "created_at": NOW,
            "blocker": {
                "description": "확인되지 않은 항목이 있습니다.",
                "evidence_refs": [evidence.evidence_id],
            },
            "next_action": None,
            "questions_for_user": ["직원 수를 알려 주세요."],
        },
        mutations={
            "fact_changes": [],
            "procedure_progress_changes": [],
            "support_match_updates": [],
        },
        grounded_claims=[],
        source_call_ids=[UUID(int=4)],
    )
    subject = ReviewSubject.create(
        schema_version="agent-io/2.0",
        review_subject_id=UUID(int=6),
        review_attempt=1,
        run_id=UUID(int=3),
        case_id=1,
        trigger=request.trigger,
        snapshot=request.case_snapshot,
        known_procedure_steps=[],
        source_results=[source],
        supervisor_draft=draft,
    )
    outcome = ReviewedPlanOutcome(
        outcome_type="REVIEWED_PLAN",
        review_subject=subject,
        review_proof={
            "review_call_id": UUID(int=7),
            "run_id": UUID(int=3),
            "case_id": 1,
            "snapshot_id": UUID(int=1),
            "review_subject_id": UUID(int=6),
            "reviewed_subject_digest": subject.subject_digest,
            "verdict": "PASS",
            "reviewed_at": NOW,
        },
    )
    return request, outcome
