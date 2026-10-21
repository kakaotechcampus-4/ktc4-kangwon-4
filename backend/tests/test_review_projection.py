"""Review projection preserves procedure details and original source ownership."""

import asyncio
import json
from uuid import UUID

import pytest
from test_action_codes import (
    NOW,
    REF,
    TAX,
    StubModel,
    evidence,
    source,
    support_sources,
)
from test_blocker_candidates import request_with_state
from test_completion import CompletionModel, complete_request, reviewed_subject

from app.agent.review_tool import ReviewTool
from app.agent.review_tool.tool import (
    _resolve_json_pointer,
    _review_prompt_projection,
    _validate_integrity,
    _visible_draft_strings,
)
from app.agent.schemas import (
    ProcedureProgressObservation,
    ProcedureProgressReport,
    ProcedureStepRef,
    SourcedText,
    Uncertainty,
    canonical_digest,
    procedure_report_evidence,
)
from app.agent.supervisor.agent import SupervisorAgent

DETAILS = {
    "required_actions",
    "required_documents",
    "application_channel",
    "application_url",
    "deadline",
    "followup_guidance",
}


def rich_request(progress=False):
    request = request_with_state()
    info = request.source_results[1].output
    for finding in info.procedure_findings:
        text = SourcedText(text="합성 테스트 절차입니다.", evidence_refs=[REF])
        finding.required_actions = [text]
        finding.required_documents = [
            {"name": text.text, "submission_stage": None, "evidence_refs": [REF]}
        ]
        finding.application_channel = text
        finding.application_url = SourcedText(
            text="https://example.org/synthetic", evidence_refs=[REF]
        )
        finding.deadline = text
        finding.followup_guidance = [text]
    if progress:
        text = "원상복구 범위 확인을 진행 중입니다."
        request.trigger.input.redacted_text = text
        selected = ProcedureProgressReport(
            procedure_step=info.procedure_findings[1].procedure_step,
            status="IN_PROGRESS",
        )
        request.trigger.input.procedure_reports = [selected]
        report = procedure_report_evidence(request.trigger.input, 0)
        info.evidence_records.append(report)
        info.procedure_progress_observations = [
            ProcedureProgressObservation(
                observation_id=UUID(int=777),
                procedure_step=info.procedure_findings[1].procedure_step,
                observed_status="IN_PROGRESS",
                source_span=None,
                structured_report=selected,
                source_evidence_refs=[report.evidence_id],
                requires_confirmation=False,
                reason_summary="합성 진행 보고",
            )
        ]
    request.source_results[1] = source(info)
    return request


@pytest.mark.parametrize("progress", [False, True])
def test_only_unused_details_and_duplicate_claim_text_are_omitted(progress):
    async def run():
        request = rich_request(progress)
        draft = await SupervisorAgent(StubModel(), clock=lambda: NOW).draft(request)
        subject = reviewed_subject(request, draft)
        original, digest = subject.model_dump_json(), subject.subject_digest
        payload = _review_prompt_projection(subject, _validate_integrity(subject))
        raw_findings = subject.source_results[1].output.procedure_findings
        findings = payload["source_results"][1]["output"]["procedure_findings"]
        assert len(findings) == len(raw_findings) == 2
        assert draft.decision.next_action.target.procedure_step.step_code == TAX
        for index, (raw, projected) in enumerate(
            zip(raw_findings, findings, strict=True)
        ):
            for key in (
                "procedure_step",
                "step_name",
                "summary",
                "relevance",
                "current_status",
                "decision_authority",
                "requires_confirmation",
                "evidence_refs",
            ):
                assert projected[key] == raw.model_dump(mode="json")[key]
            if index == 0 or progress:
                assert DETAILS <= projected.keys()
                for key in DETAILS:
                    assert projected[key] == raw.model_dump(mode="json")[key]
            else:
                assert not DETAILS & projected.keys()
        for path, text in _visible_draft_strings(subject):
            assert _resolve_json_pointer(payload, path) == text
        assert len(payload["supervisor_draft"]["grounded_claims"]) == len(
            draft.grounded_claims
        )
        for raw, claim in zip(
            draft.grounded_claims,
            payload["supervisor_draft"]["grounded_claims"],
            strict=True,
        ):
            assert "text" not in claim
            for key in (
                "claim_type",
                "target_path",
                "assertion_level",
                "evidence_refs",
            ):
                assert claim[key] == raw.model_dump(mode="json")[key]
            assert _resolve_json_pointer(payload, claim["target_path"]) == raw.text
        if progress:
            assert draft.mutations.procedure_progress_changes
            assert (
                payload["source_results"][1]["output"][
                    "procedure_progress_observations"
                ][0]["source_span"]
                is None
            )
            assert payload["source_results"][1]["output"][
                "procedure_progress_observations"
            ][0]["structured_report"] == request.trigger.input.procedure_reports[0].model_dump(mode="json")
            assert (
                payload["supervisor_draft"]["mutations"]["procedure_progress_changes"][
                    0
                ]["reason_summary"]
                == "합성 진행 보고"
            )
        reviewed = await ReviewTool(StubModel()).review(subject)
        assert reviewed.verdict == "PASS"
        assert reviewed.reviewed_subject_digest == digest
        assert subject.model_dump_json() == original
        subject.assert_integrity()

    asyncio.run(run())


def test_completed_custom_tax_binding_keeps_original_info_guidance_rework_path():
    async def run():
        request = complete_request()
        physical = ProcedureStepRef(procedure_step_id=1, step_code="BE_CAFE_TAX")
        bindings = {
            step.procedure_step.step_code: physical
            if step.procedure_step.step_code == TAX
            else step.procedure_step
            for step in request.known_procedure_steps
        }
        request.known_procedure_steps[0].procedure_step = physical
        for progress in request.case_snapshot.procedure_progress:
            if progress.procedure_step.step_code == TAX:
                progress.procedure_step = physical
        lookup, info = (
            request.source_results[0].output,
            request.source_results[1].output,
        )
        lookup.documents[0].step_codes = [physical.step_code]
        info.procedure_findings[0].procedure_step = physical
        request.source_results[0] = source(lookup, "PROCEDURE_TOOL", 5)
        info.based_on_procedure_lookup_digest = request.source_results[0].output_digest
        request.source_results[1] = source(info)
        draft = await SupervisorAgent(
            CompletionModel(), procedure_bindings=bindings, clock=lambda: NOW
        ).draft(request)
        subject = reviewed_subject(request, draft)
        original = subject.model_dump_json()
        path = "/source_results/1/output/procedure_findings/0/followup_guidance/0/text"

        class Rework:
            async def generate(self, model, messages, **kwargs):
                assert "Info finding.followup_guidance의 canonical 경로" in messages[0]["content"]
                payload = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))
                assert _resolve_json_pointer(payload, path) == "합성 테스트 절차입니다."
                assert payload["supervisor_draft"]["decision"]["followup_guidance"][0][
                    "text"
                ] == _resolve_json_pointer(payload, path)
                return model.model_validate(
                    {
                        "verdict": "REVISE",
                        "issues": [
                            {
                                "issue_code": "CONTRACT_VIOLATION",
                                "category": "CONTRACT",
                                "severity": "BLOCKING",
                                "target_component": "INFO_AGENT",
                                "target_call_id": str(UUID(int=3)),
                                "target_path": path,
                                "reason_summary": "합성 원본 안내 수정 요청",
                                "evidence_refs": [REF],
                            }
                        ],
                        "missing_evidence": [],
                        "recommended_rework_targets": ["INFO_AGENT"],
                        "resolution_reason": "합성 재작업 요청",
                    }
                )

        reviewed = await ReviewTool(Rework(), procedure_bindings=bindings).review(
            subject
        )
        assert reviewed.verdict == "REVISE" and reviewed.recommended_rework_targets == [
            "INFO_AGENT"
        ]
        assert reviewed.issues[0].target_path == path
        assert (
            reviewed.issues[0].target_call_id == request.source_results[1].meta.call_id
        )
        assert subject.model_dump_json() == original

    asyncio.run(run())


def extra_document(request):
    lookup = request.source_results[0].output
    record = evidence(
        evidence_id="lookup-extra",
        excerpt="합성 추가 자료의 고유한 원문입니다.",
        source_ref="https://example.org/extra",
    )
    lookup.evidence_records.append(record)
    lookup.documents.append(
        lookup.documents[0].model_copy(
            update={
                "document_id": UUID(int=800),
                "canonical_url": record.source_ref,
                "excerpt": record.excerpt,
                "evidence_ref": record.evidence_id,
            }
        )
    )
    return record


def refresh_sources(request):
    lookup, info = request.source_results[0].output, request.source_results[1].output
    info.based_on_procedure_lookup_digest = canonical_digest(lookup)
    request.source_results = [source(lookup, "PROCEDURE_TOOL", 5), source(info)]


@pytest.mark.parametrize(
    "consumer",
    [
        "none",
        "parent",
        "snapshot",
        "supervisor",
        "info",
        "local_path",
        "canonical_path",
        "support",
    ],
)
def test_only_referenced_lookup_documents_and_parent_bodies_reach_the_model(consumer):
    async def run():
        request = rich_request()
        record = extra_document(request)
        info = request.source_results[1].output
        if consumer == "parent":
            for item in [
                *request.case_snapshot.evidence_records,
                *request.source_results[0].output.evidence_records,
            ]:
                if item.evidence_id == REF:
                    item.parent_evidence_refs = [record.evidence_id]
        elif consumer == "snapshot":
            request.case_snapshot.facts[0].evidence_refs.append(record.evidence_id)
            request.case_snapshot.evidence_records.append(record.model_copy(deep=True))
        elif consumer in {"info", "local_path", "canonical_path"}:
            info.uncertainties = [
                Uncertainty(
                    code="SOURCE_UNAVAILABLE",
                    reason_summary="합성 출처 확인 필요",
                    target_path=(
                        "/procedure_lookup_result/documents/1"
                        if consumer == "local_path"
                        else "/source_results/0/output/documents/1/title"
                        if consumer == "canonical_path"
                        else "/procedure_lookup_result"
                    ),
                    evidence_refs=[record.evidence_id] if consumer == "info" else [],
                )
            ]
        refresh_sources(request)
        draft = await SupervisorAgent(StubModel(), clock=lambda: NOW).draft(request)
        if consumer == "supervisor":
            draft.decision.evidence_refs.append(record.evidence_id)
        elif consumer == "support":
            support = support_sources()[0].output
            support.support_checks[0].evidence_refs = [record.evidence_id]
            request.source_results.append(source(support, "SUPPORT_AGENT", 6))
            draft.source_call_ids.append(UUID(int=6))
            draft.decision.based_on_call_ids.append(UUID(int=6))
        subject = reviewed_subject(request, draft)
        original = subject.model_dump_json()
        payload = _review_prompt_projection(subject, _validate_integrity(subject))
        lookup = payload["source_results"][0]["output"]
        assert len(lookup["documents"]) == len(lookup["evidence_records"]) == 2
        if consumer == "none":
            assert lookup["documents"][1] is lookup["evidence_records"][1] is None
            assert record.excerpt not in json.dumps(payload, ensure_ascii=False)
        else:
            assert lookup["documents"][1]["evidence_ref"] == record.evidence_id
            records = [
                *payload["snapshot"]["evidence_records"],
                *(
                    item
                    for source_payload in payload["source_results"]
                    for item in source_payload["output"]["evidence_records"]
                ),
            ]
            assert [
                item["excerpt"]
                for item in records
                if item and item["evidence_id"] == record.evidence_id
            ] == [record.excerpt]
            assert _resolve_json_pointer(
                payload, "/source_results/0/output/documents/1/title"
            )
        assert subject.model_dump_json() == original
        subject.assert_integrity()

    asyncio.run(run())


def test_retained_document_issue_keeps_its_original_procedure_tool_owner():
    async def run():
        request = rich_request()
        record = extra_document(request)
        request.source_results[1].output.uncertainties = [
            Uncertainty(
                code="SOURCE_UNAVAILABLE",
                target_path="/procedure_lookup_result/documents/1",
                reason_summary="합성 문서 확인 필요",
                evidence_refs=[],
            )
        ]
        refresh_sources(request)
        draft = await SupervisorAgent(StubModel(), clock=lambda: NOW).draft(request)
        subject = reviewed_subject(request, draft)
        path = "/source_results/0/output/documents/1/title"

        class Rework:
            async def generate(self, model, messages, **kwargs):
                payload = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))
                assert _resolve_json_pointer(payload, path)
                return model.model_validate(
                    {
                        "verdict": "REVISE",
                        "issues": [
                            {
                                "issue_code": "CONTRACT_VIOLATION",
                                "category": "CONTRACT",
                                "severity": "BLOCKING",
                                "target_component": "PROCEDURE_TOOL",
                                "target_call_id": str(UUID(int=5)),
                                "target_path": path,
                                "reason_summary": "합성 원문 재조회 요청",
                                "evidence_refs": [record.evidence_id],
                            }
                        ],
                        "missing_evidence": [],
                        "recommended_rework_targets": ["PROCEDURE_TOOL"],
                        "resolution_reason": "합성 절차 자료 재작업",
                    }
                )

        reviewed = await ReviewTool(Rework()).review(subject)
        assert reviewed.recommended_rework_targets == ["PROCEDURE_TOOL"]
        assert reviewed.issues[0].target_path == path
        assert reviewed.issues[0].target_call_id == UUID(int=5)

    asyncio.run(run())
