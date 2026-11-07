import asyncio
from copy import deepcopy
from uuid import UUID

import pytest
from test_action_codes import NOW, REF, StubModel, source
from test_blocker_candidates import ChoiceModel, request_with_state
from test_info_replanning import Responses, finding, output

from app.agent.action_catalog import build_action_candidates
from app.agent.blocker_candidates import build_blocker_candidates
from app.agent.info_agent.agent import InfoAnalysisAgent
from app.agent.review_tool import ReviewTool
from app.agent.schemas import (
    CASE_FIELD_SPECS,
    FreshnessStatus,
    InfoAnalysisInput,
    KnownProcedureStep,
    MutationSet,
    ProcedureProgress,
    ProcedureStepRef,
    ReviewSubject,
)
from app.agent.supervisor.agent import SupervisorAgent, SupervisorGuardrailError

EXCERPT = "점포철거비 정산 증빙: 공사내역서, 전자세금계산서, 이체확인증, 점포철거 전·후 사진."
DOCUMENTS = ["공사내역서", "전자세금계산서", "이체확인증", "점포철거 전·후 사진"]


def preparation_request(*, fresh=True, prepared=False, report=False, held=False):
    request = request_with_state(restoration_scope="FULL", demolition_required="REQUIRED",
                                 restoration_status="NOT_STARTED")
    step = ProcedureStepRef(procedure_step_id=5, step_code="PERFORM_RESTORATION")
    request.known_procedure_steps.append(KnownProcedureStep(
        procedure_step=step, step_name="원상복구·철거 작업", utterance_aliases=[],
        registry_version="synthetic/1", applicable_business_type="ALL", deprecated_at=None,
        dependencies=[], eligibility_conditions=[],
    ))
    request.case_snapshot.procedure_progress.append(ProcedureProgress(
        procedure_step=step, status="IN_PROGRESS", requirements_confirmed=prepared,
        evidence_refs=[REF], updated_at=NOW,
    ))
    lookup = request.source_results[0].output.model_copy(deep=True)
    ev = lookup.evidence_records[0].model_copy(update={
        "evidence_id": "demolition-notice", "source_ref": "https://example.org/demolition",
        "excerpt": EXCERPT, "freshness_status": FreshnessStatus.CURRENT if fresh else FreshnessStatus.STALE,
    })
    doc = lookup.documents[0].model_copy(update={
        "document_id": UUID(int=51), "title": "합성 점포철거비 공고", "excerpt": EXCERPT,
        "canonical_url": ev.source_ref, "evidence_ref": ev.evidence_id,
        "step_codes": [step.step_code], "freshness_status": ev.freshness_status,
    })
    lookup.documents.append(doc)
    lookup.evidence_records.append(ev)
    row = finding(step.step_code, "doc2")
    row["summary"]["text"] = EXCERPT
    row["required_documents"] = [{"name": name, "submission_stage": None, "evidence_refs": ["doc2"]}
                                 for name in DOCUMENTS]
    row["relevance"] = "RELEVANT" if fresh else "UNDETERMINED"
    raw = output([finding("FILE_TAX_BUSINESS_CLOSURE", "doc1"),
                  finding("CONFIRM_RESTORATION_SCOPE", "doc1"), row])
    if report:
        request.trigger.input.redacted_text = "철거 전 사진을 찍고, 업체와 증빙 준비사항을 확인했습니다."
        raw["procedure_observations"] = [{
            "step_code": step.step_code, "observed_status": "IN_PROGRESS",
            "source_text": request.trigger.input.redacted_text,
            "requirements_confirmed": True, "submitted": False,
            "requires_confirmation": held, "reason_summary": "사용자의 철거 전 준비 확인 보고",
        }]
    client = Responses(raw)
    info = asyncio.run(InfoAnalysisAgent(client, clock=lambda: NOW, max_local_attempts=1).analyze(
        InfoAnalysisInput(input=request.trigger.input, case_snapshot=request.case_snapshot,
                          allowed_field_paths=list(CASE_FIELD_SPECS), known_procedure_steps=request.known_procedure_steps,
                          source_call_id=UUID(int=40), procedure_lookup_call_id=UUID(int=5),
                          procedure_lookup_result=lookup, review_feedback=[])))
    request.source_results = [source(lookup, "PROCEDURE_TOOL", 5), source(info, "INFO_AGENT", 40)]
    evidence = {item.evidence_id: item for item in [*request.case_snapshot.evidence_records,
                                                  *lookup.evidence_records, *info.evidence_records]}
    return request, evidence


def test_support_notice_only_offers_conditional_preparation_before_owner_prepared():
    request, evidence = preparation_request()
    info = request.source_results[1].output
    finding = next(f for f in info.procedure_findings if f.procedure_step.step_code == "PERFORM_RESTORATION")
    assert finding.requires_confirmation
    assert finding.relevance == "POSSIBLY_RELEVANT"
    assert finding.application_url is finding.application_channel is finding.deadline is None
    # A model cannot turn the notice into permission to execute demolition.
    finding.requires_confirmation = False
    actions = [a["action_code"] for a in build_action_candidates(request.source_results, evidence)
               if a["target"].get("procedure_step", {}).get("step_code") == "PERFORM_RESTORATION"]
    assert actions == ["CONFIRM_RESTORATION_REQUIREMENTS"]
    finding.requires_confirmation = True
    rows = build_blocker_candidates(request.case_snapshot, request.known_procedure_steps,
                                    request.source_results, MutationSet(fact_changes=[],
                                    procedure_progress_changes=[], support_match_updates=[]), evidence)
    action = next(r for r in rows if r["candidate_id"] == "procedure:5")["actions"][0]
    assert "증빙 제출이 필요한 경우" in action["reason"]
    assert all(any(name in q for q in action["questions_to_ask"]) for name in DOCUMENTS)
    assert "접수 가능 여부" not in action["reason"]
    assert "적용 조건" not in action["reason"]
    assert any("철거 업체" in q for q in action["questions_to_ask"])


def test_review_passes_preparation_but_rejects_demolition_execution_or_grant_claims():
    request, evidence = preparation_request()
    rows = build_blocker_candidates(request.case_snapshot, request.known_procedure_steps,
                                    request.source_results, MutationSet(fact_changes=[],
                                    procedure_progress_changes=[], support_match_updates=[]), evidence)
    choice = next(i for i, row in enumerate(rows) if row["candidate_id"] == "procedure:5")
    draft = asyncio.run(SupervisorAgent(ChoiceModel(choice=choice), clock=lambda: NOW, max_local_attempts=1).draft(request))
    subject = ReviewSubject.create(schema_version="agent-io/2.0", review_subject_id=UUID(int=500), review_attempt=1,
        run_id=request.source_results[0].meta.run_id, case_id=1, trigger=request.trigger,
        snapshot=request.case_snapshot, known_procedure_steps=request.known_procedure_steps,
        source_results=request.source_results, supervisor_draft=draft)
    assert asyncio.run(ReviewTool(StubModel()).review(subject)).verdict == "PASS"
    for code, text in [("PERFORM_RESTORATION", "지금 철거를 진행하세요."),
                       ("CONFIRM_RESTORATION_REQUIREMENTS", "지금 신청하면 지원금 600만원을 받을 수 있습니다.")]:
        changed = deepcopy(draft)
        changed.decision.next_action.action_code = code
        changed.decision.next_action.title = text
        bad = ReviewSubject.create(**{**subject.model_dump(exclude={"subject_digest", "supervisor_draft"}),
                                      "supervisor_draft": changed})
        assert asyncio.run(ReviewTool(StubModel()).review(bad)).verdict == "REVISE"


def test_stale_notice_does_not_offer_current_preparation_details():
    request, evidence = preparation_request(fresh=False)
    rows = build_blocker_candidates(request.case_snapshot, request.known_procedure_steps,
                                    request.source_results, MutationSet(fact_changes=[],
                                    procedure_progress_changes=[], support_match_updates=[]), evidence)
    assert all(row["candidate_id"] != "procedure:5" for row in rows)


@pytest.mark.parametrize("report", [False, True], ids=["stored", "same-judgment"])
def test_confirmed_demolition_preparation_is_not_selected_again(report):
    request, evidence = preparation_request(prepared=not report, report=report)
    before = request.model_dump_json()
    draft = asyncio.run(SupervisorAgent(ChoiceModel(), clock=lambda: NOW, max_local_attempts=1).draft(request))
    changes = draft.mutations.procedure_progress_changes
    assert len(changes) == int(report)
    if report:
        assert changes[0].proposed_requirements_confirmed is True
        assert changes[0].proposed_status == "IN_PROGRESS"
        assert changes[0].proposed_submitted is False
    rows = build_blocker_candidates(request.case_snapshot, request.known_procedure_steps,
                                    request.source_results, draft.mutations, evidence)
    assert all(row["candidate_id"] != "procedure:5" for row in rows)
    assert draft.decision.next_action.action_code == "CONFIRM_TAX_CLOSURE_REQUIREMENTS"
    subject = ReviewSubject.create(schema_version="agent-io/2.0", review_subject_id=UUID(int=500), review_attempt=1,
        run_id=request.source_results[0].meta.run_id, case_id=1, trigger=request.trigger,
        snapshot=request.case_snapshot, known_procedure_steps=request.known_procedure_steps,
        source_results=request.source_results, supervisor_draft=draft)
    assert asyncio.run(ReviewTool(StubModel()).review(subject)).verdict == "PASS"
    # A Review model's PASS cannot restore the obsolete preparation action.
    repeated = deepcopy(draft)
    repeated.decision.next_action.action_code = "CONFIRM_RESTORATION_REQUIREMENTS"
    repeated.decision.next_action.target.procedure_step = request.known_procedure_steps[-1].procedure_step
    bad = ReviewSubject.create(**{**subject.model_dump(exclude={"subject_digest", "supervisor_draft"}),
                                  "supervisor_draft": repeated})
    review = asyncio.run(ReviewTool(StubModel()).review(bad))
    assert review.verdict == "REVISE"
    assert any(issue.target_path.endswith("/next_action/action_code") for issue in review.issues)
    assert request.model_dump_json() == before


def test_uncertain_preparation_report_keeps_confirmation_without_marking_submitted_or_complete():
    request, evidence = preparation_request(report=True, held=True)
    rows = build_blocker_candidates(request.case_snapshot, request.known_procedure_steps,
                                    request.source_results, MutationSet(fact_changes=[],
                                    procedure_progress_changes=[], support_match_updates=[]), evidence)
    choice = next(i for i, row in enumerate(rows) if row["candidate_id"] == "procedure:5")
    draft = asyncio.run(SupervisorAgent(ChoiceModel(choice=choice), clock=lambda: NOW, max_local_attempts=1).draft(request))
    assert draft.mutations.procedure_progress_changes == []
    assert draft.decision.next_action.action_code == "CONFIRM_RESTORATION_REQUIREMENTS"
    progress = request.case_snapshot.procedure_progress[-1]
    assert progress.requirements_confirmed is progress.submitted is False
    assert progress.status == "IN_PROGRESS"


def test_confirmed_preparation_with_no_other_grounded_action_does_not_restore_old_action():
    request, evidence = preparation_request(prepared=True)
    info = request.source_results[1].output
    info.procedure_findings = [item for item in info.procedure_findings
                              if item.procedure_step.step_code == "PERFORM_RESTORATION"]
    request.source_results[1] = source(info, "INFO_AGENT", 40)
    rows = build_blocker_candidates(request.case_snapshot, request.known_procedure_steps,
                                    request.source_results, MutationSet(fact_changes=[],
                                    procedure_progress_changes=[], support_match_updates=[]), evidence)
    assert rows == []
    # With no grounded action or missing-information question, fail closed.
    with pytest.raises(SupervisorGuardrailError):
        asyncio.run(SupervisorAgent(ChoiceModel(), clock=lambda: NOW, max_local_attempts=1).draft(request))
