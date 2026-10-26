"""Closed action vocabulary and evidence-gated candidates; synthetic data only."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from app.agent.action_catalog import build_action_candidates, resolve_procedure_bindings
from app.agent.enrichment import build_confirmed_conflict_overlay, build_fact_overlays
from app.agent.graph import AgentGraph
from app.agent.review_tool import ReviewIntegrityError, ReviewTool
from app.agent.schemas import (
    AgentGraphInput,
    AgentGraphOutput,
    ConflictCandidate,
    ConflictConfirmedTrigger,
    EvidenceRecord,
    InfoAnalysisResult,
    NextAction,
    ProcedureFinding,
    ProcedureLookupResult,
    ProcedureProgress,
    ProcedureProgressChangeCandidate,
    ReviewSourceResult,
    ReviewSubject,
    SupervisorAgentInput,
    SupportAnalysisResult,
    SupportCheck,
    canonical_digest,
)
from app.agent.supervisor.agent import (
    NextActionSemantic,
    SupervisorAgent,
    SupervisorGuardrailError,
    SupervisorModelOutput,
)

NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)
REF = "synthetic-document"
TAX = "FILE_TAX_BUSINESS_CLOSURE"
CONFIRM_TAX = "CONFIRM_TAX_CLOSURE_REQUIREMENTS"


def result_fixes_xfail(*, raises=AssertionError):
    # Only the split PR's missing API gates these known baseline failures.
    # Do not probe behavior: it would hide later regressions. With the API
    # present these remain ordinary tests, including failures of the new behavior.
    return pytest.mark.xfail(
        not hasattr(AgentGraph, "_requested_field_guidance"),
        reason="Agent fixes in PR #74 have not been merged yet",
        strict=True,
        raises=raises,
    )


def evidence(**changes):
    return EvidenceRecord.model_validate(
        {
            "evidence_id": REF,
            "source_type": "OFFICIAL_DOCUMENT",
            "source_ref": "https://example.org/synthetic",
            "source_version": None,
            "locator": None,
            "excerpt": "합성 테스트 절차입니다.",
            "parent_evidence_refs": [],
            "published_at": None,
            "retrieved_at": NOW,
            "freshness_status": "CURRENT",
            "content_hash": "0" * 64,
        }
        | changes
    )


def finding(**changes):
    text = {"text": "합성 테스트 절차입니다.", "evidence_refs": [REF]}
    return ProcedureFinding.model_validate(
        {
            "finding_id": UUID(int=1),
            "procedure_step": {"procedure_step_id": 1, "step_code": TAX},
            "step_name": "합성 절차",
            "summary": text,
            "relevance": "RELEVANT",
            "current_status": "NOT_STARTED",
            "decision_authority": "OFFICIAL_AGENCY",
            "requires_confirmation": True,
            "required_actions": [text],
            "required_documents": [],
            "application_channel": None,
            "application_url": None,
            "deadline": None,
            "evidence_refs": [REF],
        }
        | changes
    )


def source(output, component=None, call_id=3):
    return ReviewSourceResult(
        meta={
            "schema_version": "agent-io/2.0",
            "run_id": UUID(int=2),
            "call_id": UUID(int=call_id),
            "parent_call_id": None,
            "case_id": 1,
            "attempt": 1,
            "requested_at": NOW,
            "trace_id": None,
            "component": component
            or (
                "INFO_AGENT"
                if isinstance(output, InfoAnalysisResult)
                else "SUPPORT_AGENT"
            ),
        },
        output=output,
        output_digest=canonical_digest(output),
    )


def procedure_sources(item):
    return [
        source(
            InfoAnalysisResult(
                completion_status="COMPLETE",
                fact_candidates=[],
                procedure_progress_observations=[],
                procedure_findings=[item],
                conflicts=[],
                missing_fields=[],
                uncertainties=[],
                question_candidates=[],
                evidence_records=[],
                parser_version="synthetic/1",
                based_on_snapshot_id=UUID(int=4),
                based_on_procedure_lookup_call_id=UUID(int=5),
                based_on_procedure_lookup_digest="sha256:" + "0" * 64,
            )
        )
    ]


def support_sources():
    check = SupportCheck(
        support_program={"support_program_id": 1, "wiki_uuid": UUID(int=6)},
        program_name="합성 지원사업",
        related_steps=[],
        match_status="NEEDS_CONFIRMATION",
        criteria=[],
        unknown_field_paths=[],
        required_documents=[],
        application_channel=None,
        application_url=None,
        application_period=None,
        source_version=None,
        freshness_status="CURRENT",
        checked_at=NOW,
        reason_summary="담당기관 확인 필요",
        evidence_refs=[REF],
    )
    return [
        source(
            SupportAnalysisResult(
                completion_status="COMPLETE",
                support_checks=[check],
                no_candidate_reason_code=None,
                uncertainties=[],
                search_summary={
                    "wiki_lookup": "NOT_REQUESTED",
                    "rag_used": False,
                    "official_source_checked": True,
                    "checked_at": NOW,
                },
                evidence_records=[evidence()],
                based_on_snapshot_id=UUID(int=4),
                based_on_candidate_ids=[],
            )
        )
    ]


def action_payload(code=CONFIRM_TAX, title="절차를 확인해 주세요"):
    return {
        "action_code": code,
        "title": title,
        "reason": "입력 항목 확인이 필요합니다.",
        "questions_to_ask": ["무엇을 준비해야 하나요?"],
        "target": {
            "target_kind": "PROCEDURE",
            "procedure_step": {"procedure_step_id": 1, "step_code": TAX},
        },
        "evidence_refs": [REF],
    }


@pytest.mark.parametrize("model", [NextActionSemantic, NextAction])
def test_invented_action_alias_is_rejected(model):
    payload = action_payload("CONFIRM_RESTORATION_SCOPE_WITH_LANDLORD")
    if model is NextAction:
        payload["sequence"] = 1
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_current_tax_procedure_offers_confirmation_and_execution():
    item = finding()
    assert item.requires_confirmation is True
    rows = build_action_candidates(procedure_sources(item), {REF: evidence()})
    by_code = {row["action_code"]: row for row in rows}
    assert set(by_code) == {CONFIRM_TAX}
    assert by_code[CONFIRM_TAX]["confirmation_only"] is True
    ready = ProcedureProgress(procedure_step=item.procedure_step, status="IN_PROGRESS",
                              requirements_confirmed=True, evidence_refs=[REF], updated_at=NOW)
    item.requires_confirmation = False
    executed = build_action_candidates(procedure_sources(item), {REF: evidence()}, procedure_progress=[ready])
    assert [row["action_code"] for row in executed] == [TAX]
    assert executed[0]["confirmation_only"] is False
    assert all(row["target"] == action_payload()["target"] for row in rows)


@pytest.mark.parametrize(
    "freshness,relevance,has_actions,can_execute",
    [
        ("CURRENT", "RELEVANT", True, True),
        ("STALE", "RELEVANT", True, False),
        ("UNKNOWN", "RELEVANT", True, False),
        ("CURRENT", "UNDETERMINED", True, False),
        ("CURRENT", "POSSIBLY_RELEVANT", True, False),
        ("CURRENT", "RELEVANT", False, False),
    ],
)
def test_execution_requires_current_relevant_action_evidence(
    freshness, relevance, has_actions, can_execute
):
    item = finding(
        requires_confirmation=False,
        relevance=relevance,
        **({} if has_actions else {"required_actions": []}),
    )
    ready = ProcedureProgress(
        procedure_step=item.procedure_step, status="IN_PROGRESS",
        requirements_confirmed=True, evidence_refs=[REF], updated_at=NOW,
    )
    rows = build_action_candidates(
        procedure_sources(item), {REF: evidence(freshness_status=freshness)},
        procedure_progress=[ready],
    )
    assert (TAX in {row["action_code"] for row in rows}) is can_execute


@pytest.mark.parametrize("records", [{}, {REF: evidence(source_type="USER_INPUT")}])
def test_user_input_or_missing_evidence_cannot_create_procedure_candidates(records):
    assert build_action_candidates(procedure_sources(finding()), records) == []


def test_stale_official_parent_blocks_execution_through_current_wiki():
    item = finding(requires_confirmation=False)
    ready = ProcedureProgress(
        procedure_step=item.procedure_step, status="IN_PROGRESS",
        requirements_confirmed=True, evidence_refs=[REF], updated_at=NOW,
    )
    wiki = evidence(source_type="REVIEWED_WIKI", parent_evidence_refs=["parent"])
    valid = build_action_candidates(
        procedure_sources(item), {REF: wiki, "parent": evidence(evidence_id="parent")},
        procedure_progress=[ready],
    )
    assert [row["action_code"] for row in valid] == [TAX]
    parent = evidence(evidence_id="parent", freshness_status="STALE")
    rows = build_action_candidates(
        procedure_sources(item), {REF: wiki, "parent": parent},
        procedure_progress=[ready],
    )
    assert TAX not in {row["action_code"] for row in rows}
    assert build_action_candidates(
        procedure_sources(item), {REF: wiki}, procedure_progress=[ready]
    ) == []


def test_support_offers_confirmation_only_and_uses_support_target():
    rows = build_action_candidates(support_sources(), {REF: evidence()})
    assert [row["action_code"] for row in rows] == [
        "CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS"
    ]
    assert rows[0]["confirmation_only"] is True
    assert rows[0]["target"] == {
        "target_kind": "SUPPORT_PROGRAM",
        "support_program": {
            "support_program_id": 1,
            "wiki_uuid": str(UUID(int=6)),
        },
    }


def test_empty_candidates_keep_the_question_only_output_valid():
    assert build_action_candidates([], {}) == []
    result = SupervisorModelOutput.model_validate({
        "decision_type": "NEEDS_MORE_INFO",
        "blocker_candidate_id": None,
        "action_code": None,
    })
    assert result.action_code is None


def test_user_input_cannot_ground_execution_even_with_official_summary():
    item = finding(
        requires_confirmation=False,
        required_actions=[{"text": "합성 사용자 요청", "evidence_refs": ["user"]}],
        evidence_refs=[REF, "user"],
    )
    ready = ProcedureProgress(
        procedure_step=item.procedure_step, status="IN_PROGRESS",
        requirements_confirmed=True, evidence_refs=[REF], updated_at=NOW,
    )
    valid = build_action_candidates(
        procedure_sources(item), {REF: evidence(), "user": evidence(evidence_id="user")},
        procedure_progress=[ready],
    )
    assert [row["action_code"] for row in valid] == [TAX]
    rows = build_action_candidates(
        procedure_sources(item),
        {
            REF: evidence(),
            "user": evidence(evidence_id="user", source_type="USER_INPUT"),
        },
        procedure_progress=[ready],
    )
    assert TAX not in {row["action_code"] for row in rows}


def supervisor_request():
    """A complete synthetic provenance chain for both runtime guard layers."""
    ev = evidence()
    lookup = ProcedureLookupResult(
        completion_status="COMPLETE",
        lookup_id=UUID(int=7),
        warnings=[],
        evidence_records=[ev],
        based_on_snapshot_id=UUID(int=4),
        as_of=NOW.date(),
        documents=[
            {
                "document_id": UUID(int=8),
                "title": "합성 자료",
                "authority_name": "합성 기관",
                "canonical_url": ev.source_ref,
                "source_domain": "example.org",
                "excerpt": ev.excerpt,
                "published_at": None,
                "retrieved_at": NOW,
                "freshness_status": "CURRENT",
                "content_hash": ev.content_hash,
                "evidence_ref": REF,
                "search_query": "합성",
                "step_codes": [TAX],
            }
        ],
    )
    info = procedure_sources(finding())[0].output.model_copy(
        update={
            "based_on_procedure_lookup_digest": canonical_digest(lookup),
        }
    )
    fields = [
        ("business_type", "STRING", "카페"),
        ("franchise_status", "BOOLEAN", False),
        ("lease_status", "ENUM", "OWNED"),
    ]
    return SupervisorAgentInput(
        trigger={
            "trigger_type": "CASE_CREATED",
            "input_event_id": "synthetic-input",
            "client_event_id": None,
            "submitted_at": NOW,
            "input": {
                "input_event_id": "synthetic-input",
                "source_type": "USER_INPUT",
                "redacted_text": "합성 테스트 입력",
                "redactions": [],
                "submitted_at": NOW,
            },
        },
        case_snapshot={
            "snapshot_id": UUID(int=4),
            "case_id": 1,
            "case_status": "IN_PROGRESS",
            "facts": [
                {
                    "field_path": name,
                    "value_type": kind,
                    "value": value,
                    "status": "CONFIRMED",
                    "evidence_refs": [REF],
                    "updated_at": NOW,
                }
                for name, kind, value in fields
            ],
            "procedure_progress": [],
            "evidence_records": [ev],
            "captured_at": NOW,
        },
        known_procedure_steps=[
            {
                "procedure_step": {"procedure_step_id": 1, "step_code": TAX},
                "step_name": "합성 절차",
                "utterance_aliases": [],
                "registry_version": "synthetic/1",
                "applicable_business_type": "ALL",
                "deprecated_at": None,
                "dependencies": [],
                "eligibility_conditions": [],
            }
        ],
        source_results=[source(lookup, "PROCEDURE_TOOL", 5), source(info)],
    )


class StubModel:
    def __init__(self, action_code=CONFIRM_TAX):
        self.action_code, self.calls = action_code, 0

    async def generate(self, model, messages, **kwargs):
        self.calls += 1
        if kwargs["schema_name"] == "reborn_review_output":
            return model.model_validate(
                {
                    "verdict": "PASS",
                    "issues": [],
                    "missing_evidence": [],
                    "recommended_rework_targets": [],
                    "resolution_reason": "합성 테스트에서 모델이 PASS를 반환",
                }
            )
        support_action = self.action_code == "CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS"
        return model.model_validate({
            "decision_type": "ACTION",
            "blocker_candidate_id": "support:1" if support_action else "procedure:1",
            "action_code": self.action_code,
        })


@pytest.mark.parametrize("changed_parent", [False, True])
def test_parent_order_survives_supervisor_and_review_but_changed_lineage_is_rejected(changed_parent):
    async def run():
        request = supervisor_request()
        child = evidence(parent_evidence_refs=["parent-a", "parent-b"])
        request.case_snapshot.evidence_records = [
            child, *(evidence(evidence_id=ref) for ref in ("parent-a", "parent-b", "parent-c")),
        ]
        lookup = request.source_results[0].output.model_copy(deep=True)
        lookup.evidence_records[0] = child.model_copy(update={
            "parent_evidence_refs": ["parent-c", "parent-a"] if changed_parent else ["parent-b", "parent-a"],
        })
        info = request.source_results[1].output.model_copy(update={
            "based_on_procedure_lookup_digest": canonical_digest(lookup),
        })
        request.source_results = [source(lookup, "PROCEDURE_TOOL", 5), source(info)]
        original = request.model_dump_json()
        supervisor = SupervisorAgent(StubModel(), max_local_attempts=1)
        if changed_parent:
            with pytest.raises(SupervisorGuardrailError, match="evidence ID collision"):
                await supervisor.draft(request)
        else:
            draft = await supervisor.draft(request)
            subject = ReviewSubject.create(
                schema_version="agent-io/2.0", review_subject_id=UUID(int=9),
                review_attempt=1, run_id=UUID(int=2), case_id=1,
                trigger=request.trigger, snapshot=request.case_snapshot,
                known_procedure_steps=request.known_procedure_steps,
                source_results=request.source_results, supervisor_draft=draft,
            )
            review = await ReviewTool(StubModel()).review(subject)
            assert review.verdict.value == "PASS"
        assert request.model_dump_json() == original

    asyncio.run(run())


def test_supervisor_blocks_action_not_in_the_selected_candidate():
    client = StubModel("CONFIRM_RESTORATION_SCOPE")
    with pytest.raises(SupervisorGuardrailError):
        asyncio.run(
            SupervisorAgent(client, max_local_attempts=1).draft(supervisor_request())
        )
    assert client.calls == 1


def test_review_blocks_wrong_target_even_when_its_model_returns_pass():
    async def run():
        request = supervisor_request()
        draft = await SupervisorAgent(StubModel(), max_local_attempts=1).draft(request)
        draft.decision.next_action.action_code = "CONFIRM_RESTORATION_SCOPE"
        subject = ReviewSubject.create(
            schema_version="agent-io/2.0",
            review_subject_id=UUID(int=9),
            review_attempt=1,
            run_id=UUID(int=2),
            case_id=1,
            trigger=request.trigger,
            snapshot=request.case_snapshot,
            known_procedure_steps=request.known_procedure_steps,
            source_results=request.source_results,
            supervisor_draft=draft,
        )
        client = StubModel()
        result = await ReviewTool(
            client, max_output_attempts=1, provider_max_retries=0
        ).review(subject)
        assert client.calls == 1
        assert result.verdict.value == "REVISE"
        assert any(
            issue.issue_code.value == "CONTRACT_VIOLATION"
            and issue.severity == "BLOCKING"
            and issue.target_path.endswith("/next_action/action_code")
            for issue in result.issues
        )

    asyncio.run(run())


def test_review_rejects_filing_before_confirmation_even_when_model_passes():
    async def run():
        request = supervisor_request()
        draft = await SupervisorAgent(StubModel(), max_local_attempts=1).draft(request)
        draft.decision.next_action.action_code = TAX
        subject = ReviewSubject.create(
            schema_version="agent-io/2.0", review_subject_id=UUID(int=9),
            review_attempt=1, run_id=UUID(int=2), case_id=1, trigger=request.trigger,
            snapshot=request.case_snapshot, known_procedure_steps=request.known_procedure_steps,
            source_results=request.source_results, supervisor_draft=draft,
        )
        result = await ReviewTool(StubModel(), max_output_attempts=1).review(subject)
        assert result.verdict == "REVISE"
        assert any(issue.issue_code == "CONTRACT_VIOLATION"
                   and issue.target_path.startswith("/supervisor_draft/decision")
                   for issue in result.issues)

    asyncio.run(run())


@pytest.mark.parametrize("text,expected", [
    ("폐업 시 세금 신고를 함께 하세요.", "TAX"),
    ("폐업일 2026-11-01까지 신고하세요.", "DATE_OR_DEADLINE"),
    ("합성 테스트 절차입니다.", "PROCEDURE"),
])
def test_visible_reason_keeps_its_tax_or_deadline_claim_type(text, expected):
    request = supervisor_request()
    draft = asyncio.run(SupervisorAgent(StubModel(), max_local_attempts=1).draft(request))
    fields = draft.decision.model_dump(mode="python")
    fields["next_action"]["reason"] = text
    claims = SupervisorAgent._candidate_claims(request, fields)
    reason = next(item for item in claims if item.target_path.endswith("/next_action/reason"))
    assert reason.claim_type == expected
    assert reason.text == text and reason.evidence_refs == [REF]


@pytest.mark.parametrize("action_code", [CONFIRM_TAX, TAX])
@pytest.mark.parametrize("invented_blocker", [False, True])
def test_review_checks_required_blocker_against_verified_candidate(
    action_code, invented_blocker
):
    async def run():
        request = supervisor_request()
        if action_code == TAX:
            request.case_snapshot.procedure_progress = [ProcedureProgress(procedure_step=request.known_procedure_steps[0].procedure_step, status="IN_PROGRESS", requirements_confirmed=True, evidence_refs=[REF], updated_at=NOW)]
            info = request.source_results[1].output.model_copy(deep=True)
            info.procedure_findings[0].requires_confirmation = False
            request.source_results[1] = source(info)
        draft = await SupervisorAgent(
            StubModel(action_code), max_local_attempts=1
        ).draft(request)
        assert draft.decision.blocker is not None
        assert draft.decision.blocker.evidence_refs == [REF]
        assert draft.decision.next_action.action_code == action_code
        assert draft.decision.questions_for_user == []
        assert any(
            "/blocker/" in claim.target_path for claim in draft.grounded_claims
        )
        if invented_blocker:
            draft.decision.blocker.description = "준비할 항목이 확인되지 않았습니다."
            for item in draft.decision.blockers:
                if item.candidate_id == draft.decision.blocker.candidate_id:
                    item.description = draft.decision.blocker.description
        subject = ReviewSubject.create(
            schema_version="agent-io/2.0",
            review_subject_id=UUID(int=9),
            review_attempt=1,
            run_id=UUID(int=2),
            case_id=1,
            trigger=request.trigger,
            snapshot=request.case_snapshot,
            known_procedure_steps=request.known_procedure_steps,
            source_results=request.source_results,
            supervisor_draft=draft,
        )
        subject = ReviewSubject.model_validate_json(subject.model_dump_json())
        client = StubModel()
        result = await ReviewTool(
            client, max_output_attempts=1, provider_max_retries=0
        ).review(subject)
        assert client.calls == 1
        if invented_blocker:
            assert result.verdict == "REVISE"
            assert any(
                issue.issue_code == "CONTRACT_VIOLATION"
                and issue.target_path == "/supervisor_draft/decision/blocker"
                for issue in result.issues
            )
        else:
            assert subject.supervisor_draft.decision.blocker is not None
            assert result.verdict == "PASS"

    asyncio.run(run())


@pytest.mark.parametrize("problem", [
    None,
    *[
        pytest.param(problem, marks=result_fixes_xfail(raises=pytest.fail.Exception))
        for problem in ("missing", "fact", "progress")
    ],
])
def test_review_preserves_only_the_confirmed_conflict_change(problem):
    async def run():
        request = supervisor_request()
        conflict_evidence = evidence(
            evidence_id="synthetic-conflict-source", source_type="USER_INPUT",
            source_ref="synthetic-conflict-input", excerpt="프랜차이즈입니다.",
        )
        request.case_snapshot.evidence_records.append(conflict_evidence)
        conflict = ConflictCandidate.create(
            conflict_ref="synthetic-conflict", candidate_id=UUID(int=40),
            snapshot_id=request.case_snapshot.snapshot_id,
            field_path="franchise_status", committed_status="CONFIRMED",
            committed_value=False, proposed_operation="SET",
            proposed_status="CONFIRMED", proposed_value=True,
            source_evidence_refs=[conflict_evidence.evidence_id], source_call_id=UUID(int=41),
        )
        request.trigger = ConflictConfirmedTrigger(
            trigger_type="CONFLICT_CONFIRMED", input_event_id="synthetic-confirmation",
            client_event_id=None, confirmed_conflict=conflict, confirmed_at=NOW,
        )
        request.fact_overlays = [build_confirmed_conflict_overlay(
            request.case_snapshot, conflict, uuid_factory=lambda: UUID(int=42),
        )]
        draft = await SupervisorAgent(StubModel(), max_local_attempts=1).draft(request)
        if problem == "missing":
            draft.mutations.fact_changes = []
        elif problem in {"fact", "progress"}:
            text = "직원은 3명입니다." if problem == "fact" else "폐업 신고를 진행 중입니다."
            unapproved = evidence(
                evidence_id="synthetic-unapproved-input", source_type="USER_INPUT",
                source_ref="synthetic-old-input", excerpt=text,
            )
            span = {"input_event_id": "synthetic-old-input", "text": text,
                    "start_offset": 0, "end_offset": len(text)}
            payload = request.source_results[1].output.model_dump()
            payload["evidence_records"] = [unapproved]
            if problem == "fact":
                payload["fact_candidates"] = [{
                    "candidate_id": UUID(int=43), "operation": "SET",
                    "field_path": "employee_count", "value_type": "INTEGER", "value": 3,
                    "source_span": span, "source_evidence_refs": [unapproved.evidence_id],
                    "confidence_bps": 9500, "requires_confirmation": False,
                    "reason_summary": "합성 직원 수 보고",
                }]
            else:
                payload["procedure_progress_observations"] = [{
                    "observation_id": UUID(int=43), "procedure_step": finding().procedure_step,
                    "observed_status": "IN_PROGRESS", "source_span": span,
                    "source_evidence_refs": [unapproved.evidence_id],
                    "requires_confirmation": False, "reason_summary": "합성 진행 보고",
                }]
            info = InfoAnalysisResult.model_validate(payload)
            request.source_results[1] = source(info)
            if problem == "fact":
                draft.mutations.fact_changes.extend(build_fact_overlays(
                    request.case_snapshot, info, UUID(int=3),
                    uuid_factory=lambda: UUID(int=44),
                ))
            else:
                draft.mutations.procedure_progress_changes = [ProcedureProgressChangeCandidate(
                    candidate_id=UUID(int=44), procedure_step=finding().procedure_step,
                    before_status="NOT_STARTED", proposed_status="IN_PROGRESS",
                    reason_summary="합성 진행 보고", execution_evidence_refs=[unapproved.evidence_id],
                    procedure_analysis_call_id=UUID(int=3),
                )]
        subject = ReviewSubject.create(
            schema_version="agent-io/2.0", review_subject_id=UUID(int=9),
            review_attempt=1, run_id=UUID(int=2), case_id=1,
            trigger=request.trigger, snapshot=request.case_snapshot,
            known_procedure_steps=request.known_procedure_steps,
            source_results=request.source_results, supervisor_draft=draft,
        )
        subject = ReviewSubject.model_validate_json(subject.model_dump_json())
        client = StubModel()
        tool = ReviewTool(client, max_output_attempts=1, provider_max_retries=0)
        if problem:
            message = "confirmation must contain only the accepted changes"
            with pytest.raises(ReviewIntegrityError, match=message):
                await tool.review(subject)
            assert client.calls == 0
        else:
            result = await tool.review(subject)
            assert result.verdict == "PASS"
            assert client.calls == 1

    asyncio.run(run())


@pytest.mark.parametrize("trigger_type", ["CASE_CREATED", "RESULT_SUBMITTED"])
@pytest.mark.parametrize("scenario", ["procedure_action", "missing_bindings", "support_action"])
def test_graph_distinguishes_missing_bindings_from_actionable_candidates(trigger_type, scenario):
    async def run():
        template = supervisor_request()
        if scenario != "procedure_action":
            step = template.known_procedure_steps[0]
            template.known_procedure_steps = [
                type(step).model_validate(step.model_dump() | {
                    "procedure_step": {"procedure_step_id": index, "step_code": code},
                    "step_name": name, "registry_version": "temp",
                })
                for index, (code, name) in enumerate([
                    ("TEMP_BUSINESS_CLOSURE_REPORT", "사업자 폐업 신고"),
                    ("TEMP_TAX_CLOSURE_REPORT", "세무서 폐업 신고"),
                    ("TEMP_FOUR_INSURANCE_CANCEL", "4대보험 상실 신고"),
                ], start=1)
            ]
            assert resolve_procedure_bindings(template.known_procedure_steps) == {}
        request = AgentGraphInput(
            trigger=template.trigger.model_dump() | {"trigger_type": trigger_type},
            case_snapshot=template.case_snapshot,
        )
        original = request.model_dump_json()
        lookup = template.source_results[0].output

        async def analyze_info(component_input):
            payload = template.source_results[1].output.model_dump()
            if scenario != "procedure_action":
                payload.update(
                    procedure_findings=[],
                    missing_fields=[{
                        "field_path": "employee_count", "reason_summary": "합성 누락",
                        "blocks": ["SUPERVISOR_DECISION"],
                        "question_candidate_id": UUID(int=20),
                    }],
                    question_candidates=[{
                        "question_id": UUID(int=20), "text": "직원이 몇 명인가요?",
                        "resolves_field_paths": ["employee_count"],
                        "reason_summary": "합성 누락",
                    }],
                )
            return InfoAnalysisResult.model_validate(
                payload
                | {
                    "based_on_procedure_lookup_call_id": component_input.procedure_lookup_call_id,
                    "based_on_procedure_lookup_digest": canonical_digest(
                        component_input.procedure_lookup_result
                    ),
                }
            )

        support_payload = support_sources()[0].output.model_dump()
        if scenario != "support_action":
            support_payload.update({
                "completion_status": "NO_CANDIDATE",
                "support_checks": [],
                "no_candidate_reason_code": "NO_REVIEWED_CANDIDATE",
            })
        support = SupportAnalysisResult.model_validate(support_payload)
        procedure_runner = AsyncMock()
        procedure_runner.lookup.return_value = lookup
        info_runner = AsyncMock()
        info_runner.analyze.side_effect = analyze_info
        support_runner = AsyncMock()
        support_runner.analyze.return_value = support
        review_client = StubModel()
        action_code = (
            "CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS"
            if scenario == "support_action" else CONFIRM_TAX
        )
        supervisor_client = StubModel(action_code)
        graph = AgentGraph(
            procedure_tool=procedure_runner,
            info_agent=info_runner,
            support_agent=support_runner,
            supervisor=SupervisorAgent(
                supervisor_client, clock=lambda: NOW, max_local_attempts=1,
            ),
            review_tool=ReviewTool(review_client),
            known_procedure_steps=template.known_procedure_steps,
            clock=lambda: NOW,
            max_review_revisions=0,
        )
        outcome = await graph.run(request)
        restored = TypeAdapter(AgentGraphOutput).validate_json(outcome.model_dump_json())
        if scenario in {"missing_bindings", "support_action"}:
            assert restored.outcome_type == "SAFE_FAILURE", restored
            assert restored.failure_code == "COMPONENT_UNAVAILABLE"
            assert restored.message_code == "AGENT_PROCEDURE_BINDINGS_MISSING"
            assert restored.recovery_action_code == "CONTACT_SUPPORT"
            assert restored.requested_field_paths == []
            assert restored.retryable is False
            assert restored.failed_component == "SUPERVISOR"
            assert supervisor_client.calls == review_client.calls == 0
        else:
            assert restored.outcome_type == "REVIEWED_PLAN", restored
            restored.assert_integrity()
            decision = restored.review_subject.supervisor_draft.decision
            assert decision.decision_type == "ACTION"
            assert decision.blocker is not None
            assert decision.blocker.evidence_refs == [REF]
            assert decision.next_action.action_code == action_code
            assert decision.evidence_refs and decision.next_action.evidence_refs
            assert restored.review_proof.snapshot_id == request.case_snapshot.snapshot_id
            assert supervisor_client.calls == review_client.calls == 1
        for runner, method in (
            (procedure_runner, "lookup"),
            (info_runner, "analyze"),
        ):
            getattr(runner, method).assert_awaited_once()
        support_runner.analyze.assert_not_awaited()
        assert request.model_dump_json() == original

    asyncio.run(run())
