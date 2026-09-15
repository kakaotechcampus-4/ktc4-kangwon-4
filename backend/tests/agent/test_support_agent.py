from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agent.schemas import (
    CaseFact,
    CaseSnapshot,
    CheckSpecificSupportInput,
    DiscoverSupportInput,
    EvidenceRecord,
    FactChangeCandidate,
    PlanningContext,
    SupportProgramRef,
)
from app.agent.support_agent import (
    CatalogSourcedText,
    ReviewedSupportCatalog,
    ReviewedSupportProgram,
    SupportAgent,
    SupportAnalysisDraft,
    SupportAnalysisGuardrailError,
    SupportAnalysisInputError,
    SupportCatalogUnavailableError,
    SupportCheckDraft,
    SupportCheckModelOutput,
    SupportCriterionDefinition,
    SupportCriterionDraft,
    SupportCriterionModelOutput,
    SupportProviderOutput,
    SupportRequiredDocumentDefinition,
)

NOW = datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc)
PROGRAM_REF = SupportProgramRef(
    support_program_id=101,
    wiki_uuid=UUID("10000000-0000-4000-8000-000000000101"),
)


class FakeLLM:
    def __init__(self, output: Any) -> None:
        self.output = output
        self.calls: list[tuple[type[Any], list[dict[str, str]], str | None]] = []

    async def generate(
        self,
        response_model: type[Any],
        messages: list[dict[str, str]],
        *,
        schema_name: str | None = None,
    ) -> Any:
        self.calls.append((response_model, messages, schema_name))
        return self.output


class SequenceLLM(FakeLLM):
    def __init__(self, outputs: list[Any]) -> None:
        super().__init__(None)
        self.outputs = outputs

    async def generate(
        self,
        response_model: type[Any],
        messages: list[dict[str, str]],
        *,
        schema_name: str | None = None,
    ) -> Any:
        self.calls.append((response_model, messages, schema_name))
        return self.outputs[len(self.calls) - 1]


def _evidence(
    evidence_id: str,
    source_type: str,
    *,
    freshness: str = "CURRENT",
    parents: list[str] | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_type=source_type,
        source_ref=f"fake:{evidence_id}",
        source_version="2026-09",
        locator="section-1",
        excerpt="테스트용으로 검수된 최소 근거입니다.",
        parent_evidence_refs=parents or [],
        published_at=NOW,
        retrieved_at=NOW,
        freshness_status=freshness,
        content_hash="sha256:" + "a" * 64,
    )


def _catalog(*, freshness: str = "CURRENT") -> ReviewedSupportCatalog:
    official = _evidence(
        "support-official",
        "OFFICIAL_DOCUMENT",
        freshness=freshness,
    )
    wiki = _evidence(
        "support-wiki",
        "REVIEWED_WIKI",
        freshness="CURRENT",
        parents=[official.evidence_id],
    )
    program = ReviewedSupportProgram(
        support_program=PROGRAM_REF,
        program_name="가상 소상공인 정리 지원",
        related_steps=[],
        criteria=(
            SupportCriterionDefinition(
                criterion_code="BUSINESS_TYPE",
                field_path="business_type",
                operator="EQ",
                required_values=("CAFE",),
                evidence_refs=(official.evidence_id,),
            ),
            SupportCriterionDefinition(
                criterion_code="EMPLOYEE_LIMIT",
                field_path="employee_count",
                operator="LTE",
                required_values=(5,),
                evidence_refs=(official.evidence_id,),
            ),
        ),
        required_documents=(
            SupportRequiredDocumentDefinition(
                name="사업자 사실 증명",
                submission_stage=None,
                evidence_refs=(official.evidence_id,),
            ),
        ),
        application_channel=CatalogSourcedText(
            text="공식 접수 창구",
            evidence_refs=(official.evidence_id,),
        ),
        application_url=None,
        application_period=None,
        source_version="2026-09",
        freshness_status="CURRENT",
        evidence_refs=(wiki.evidence_id,),
    )
    return ReviewedSupportCatalog(
        catalog_version="test-v1",
        programs=(program,),
        evidence_records=(official, wiki),
    )


def _snapshot(*, employee_count: int = 3) -> CaseSnapshot:
    business_evidence = _evidence("fact-business", "USER_INPUT")
    employee_evidence = _evidence("fact-employee", "USER_INPUT")
    return CaseSnapshot(
        snapshot_id=UUID("20000000-0000-4000-8000-000000000001"),
        case_id=1,
        case_version=1,
        case_status="IN_PROGRESS",
        facts=[
            CaseFact(
                field_path="business_type",
                value_type="STRING",
                value="CAFE",
                status="CONFIRMED",
                evidence_refs=[business_evidence.evidence_id],
                updated_at=NOW,
            ),
            CaseFact(
                field_path="employee_count",
                value_type="INTEGER",
                value=employee_count,
                status="CONFIRMED",
                evidence_refs=[employee_evidence.evidence_id],
                updated_at=NOW,
            ),
            CaseFact(
                field_path="entity_type",
                value_type="ENUM",
                value=None,
                status="UNKNOWN",
                evidence_refs=[],
                updated_at=None,
            ),
        ],
        procedure_progress=[],
        evidence_records=[business_evidence, employee_evidence],
        captured_at=NOW,
    )


def _request(
    *,
    snapshot: CaseSnapshot | None = None,
    overlays: list[FactChangeCandidate] | None = None,
) -> DiscoverSupportInput:
    return DiscoverSupportInput(
        lookup_goal="DISCOVER_RELEVANT",
        planning_context=PlanningContext(
            case_snapshot=snapshot or _snapshot(),
            fact_overlays=overlays or [],
        ),
        related_steps=[],
        as_of=NOW.date(),
        review_feedback=[],
    )


def _draft(
    *,
    program_ref: SupportProgramRef = PROGRAM_REF,
    match_status: str = "POSSIBLY_RELEVANT",
    employee_status: str = "MET",
    employee_evidence: str = "support-official",
) -> SupportAnalysisDraft:
    return SupportAnalysisDraft(
        completion_status="COMPLETE",
        support_checks=[
            SupportCheckDraft(
                support_program=program_ref,
                match_status=match_status,
                criteria=[
                    SupportCriterionDraft(
                        criterion_code="BUSINESS_TYPE",
                        status="MET",
                        reason_summary="업종 값이 검수 조건과 같습니다.",
                        evidence_refs=["support-official", "fact-business"],
                    ),
                    SupportCriterionDraft(
                        criterion_code="EMPLOYEE_LIMIT",
                        status=employee_status,
                        reason_summary="상시 인원 값을 검수 조건과 비교했습니다.",
                        evidence_refs=[employee_evidence],
                    ),
                ],
                unknown_field_paths=[],
                reason_summary="검토 대상이며 기관의 최종 확인이 필요합니다.",
                evidence_refs=["support-wiki", "support-official"],
            )
        ],
        no_candidate_reason_code=None,
        uncertainties=[],
    )


def _run(agent: SupportAgent, request: Any | None = None) -> Any:
    return asyncio.run(agent.analyze(request or _request()))


def test_analyze_builds_only_catalog_grounded_result() -> None:
    llm = FakeLLM(_draft())
    result = _run(SupportAgent(llm, _catalog(), clock=lambda: NOW))

    assert result.completion_status == "COMPLETE"
    assert result.based_on_snapshot_id == _snapshot().snapshot_id
    assert result.based_on_candidate_ids == []
    assert len(result.support_checks) == 1
    check = result.support_checks[0]
    assert check.support_program == PROGRAM_REF
    assert check.program_name == "가상 소상공인 정리 지원"
    assert check.match_status == "POSSIBLY_RELEVANT"
    assert check.application_channel.text == "공식 접수 창구"
    assert "application_status" not in check.model_dump(mode="json")
    assert {item.evidence_id for item in result.evidence_records} == {
        "support-official",
        "support-wiki",
    }
    assert llm.calls[0][0] is SupportProviderOutput
    assert llm.calls[0][2] == "support_analysis"


def test_prompt_contains_only_precomputed_minimum_projection() -> None:
    snapshot = _snapshot()
    snapshot.evidence_records[0].source_ref = "private-source-ref"
    snapshot.evidence_records[0].excerpt = "redacted_text=private-user-content"
    catalog = _catalog()
    catalog.evidence_records[0].source_ref = "private-catalog-source"
    catalog.evidence_records[0].excerpt = "private-catalog-excerpt"
    llm = FakeLLM(_draft())

    _run(
        SupportAgent(llm, catalog, clock=lambda: NOW),
        _request(snapshot=snapshot),
    )

    prompt = llm.calls[0][1][1]["content"]
    assert '"source_ref"' not in prompt
    assert '"excerpt"' not in prompt
    assert "redacted_text" not in prompt
    assert "private-user-content" not in prompt
    assert "private-catalog-source" not in prompt
    assert "private-catalog-excerpt" not in prompt
    assert "CAFE" not in prompt
    projection = json.loads(prompt.removeprefix("INPUT_JSON="))
    assert set(projection) == {
        "lookup_goal",
        "catalog_version",
        "required_completion_status",
        "review_feedback",
        "programs",
    }
    assert [item["status"] for item in projection["programs"][0]["criteria"]] == [
        "MET",
        "MET",
    ]


@pytest.mark.parametrize(
    ("freshness", "expected_status"),
    [("STALE", "STALE"), ("UNKNOWN", "UNVERIFIABLE")],
)
def test_non_current_source_forces_safe_status_and_partial(
    freshness: str,
    expected_status: str,
) -> None:
    result = _run(
        SupportAgent(
            FakeLLM(_draft(match_status="POSSIBLY_RELEVANT")),
            _catalog(freshness=freshness),
            clock=lambda: NOW,
        )
    )

    assert result.completion_status == "PARTIAL"
    assert result.support_checks[0].match_status == expected_status
    assert result.uncertainties


def test_rejects_invented_program_reference() -> None:
    invented = SupportProgramRef(
        support_program_id=999,
        wiki_uuid=UUID("99999999-0000-4999-8999-999999999999"),
    )
    agent = SupportAgent(
        FakeLLM(_draft(program_ref=invented)),
        _catalog(),
        clock=lambda: NOW,
    )

    with pytest.raises(SupportAnalysisGuardrailError, match="outside"):
        _run(agent)


def test_rejects_invented_evidence_reference() -> None:
    agent = SupportAgent(
        FakeLLM(_draft(employee_evidence="invented-evidence")),
        _catalog(),
        clock=lambda: NOW,
    )

    with pytest.raises(SupportAnalysisGuardrailError, match="unknown"):
        _run(agent)


def test_rejects_model_criterion_that_contradicts_case_fact() -> None:
    agent = SupportAgent(
        FakeLLM(_draft(employee_status="NOT_MET", match_status="NOT_RELEVANT")),
        _catalog(),
        clock=lambda: NOW,
    )

    with pytest.raises(SupportAnalysisGuardrailError, match="criterion"):
        _run(agent)


def test_rejects_eligible_or_application_state_fields_from_raw_model_output() -> None:
    raw = _draft().model_dump(mode="json")
    raw["support_checks"][0]["match_status"] = "ELIGIBLE"
    raw["support_checks"][0]["application_status"] = "APPROVED"
    agent = SupportAgent(FakeLLM(raw), _catalog(), clock=lambda: NOW)

    with pytest.raises(SupportAnalysisGuardrailError, match="draft contract"):
        _run(agent)


def test_rejects_overconfident_eligibility_language() -> None:
    draft = _draft()
    draft.support_checks[0].reason_summary = "이 지원사업은 지원 가능 확정입니다."
    agent = SupportAgent(FakeLLM(draft), _catalog(), clock=lambda: NOW)

    with pytest.raises(SupportAnalysisGuardrailError, match="overstates"):
        _run(agent)


def test_specific_lookup_rejects_program_not_in_catalog_without_calling_llm() -> None:
    llm = FakeLLM(_draft())
    request = CheckSpecificSupportInput(
        lookup_goal="CHECK_SPECIFIC",
        planning_context=PlanningContext(
            case_snapshot=_snapshot(),
            fact_overlays=[],
        ),
        related_steps=[],
        as_of=NOW.date(),
        review_feedback=[],
        support_programs=[
            SupportProgramRef(
                support_program_id=999,
                wiki_uuid=UUID("99999999-0000-4999-8999-999999999999"),
            )
        ],
    )

    with pytest.raises(SupportAnalysisInputError, match="outside"):
        _run(SupportAgent(llm, _catalog(), clock=lambda: NOW), request)
    assert llm.calls == []


def test_specific_lookup_requires_a_check_for_every_requested_program() -> None:
    no_candidate = SupportAnalysisDraft(
        completion_status="NO_CANDIDATE",
        support_checks=[],
        no_candidate_reason_code="NO_MATCH",
        uncertainties=[],
    )
    request = CheckSpecificSupportInput(
        lookup_goal="CHECK_SPECIFIC",
        planning_context=PlanningContext(
            case_snapshot=_snapshot(),
            fact_overlays=[],
        ),
        related_steps=[],
        as_of=NOW.date(),
        review_feedback=[],
        support_programs=[PROGRAM_REF],
    )

    with pytest.raises(SupportAnalysisGuardrailError, match="resolver-selected"):
        _run(
            SupportAgent(FakeLLM(no_candidate), _catalog(), clock=lambda: NOW),
            request,
        )


def test_official_parent_freshness_propagates_through_reviewed_wiki() -> None:
    source = _catalog(freshness="STALE")
    original = source.programs[0]
    wiki_only = ReviewedSupportProgram(
        support_program=original.support_program,
        program_name=original.program_name,
        related_steps=original.related_steps,
        criteria=tuple(
            item.model_copy(update={"evidence_refs": ("support-wiki",)})
            for item in original.criteria
        ),
        required_documents=(),
        application_channel=None,
        application_url=None,
        application_period=None,
        source_version=original.source_version,
        freshness_status="CURRENT",
        evidence_refs=("support-wiki",),
    )
    catalog = ReviewedSupportCatalog(
        catalog_version=source.catalog_version,
        programs=(wiki_only,),
        evidence_records=source.evidence_records,
    )
    draft = _draft()
    for criterion in draft.support_checks[0].criteria:
        criterion.evidence_refs = ["support-wiki"]
    draft.support_checks[0].evidence_refs = ["support-wiki"]
    llm = FakeLLM(draft)

    result = _run(SupportAgent(llm, catalog, clock=lambda: NOW))

    assert result.support_checks[0].match_status == "STALE"
    assert {item.evidence_id for item in result.evidence_records} == {
        "support-official",
        "support-wiki",
    }
    assert "support-official" not in llm.calls[0][1][1]["content"]


def test_discover_requires_every_resolver_selected_program() -> None:
    no_candidate = SupportAnalysisDraft(
        completion_status="NO_CANDIDATE",
        support_checks=[],
        no_candidate_reason_code="NO_MATCH",
        uncertainties=[],
    )
    llm = FakeLLM(no_candidate)

    with pytest.raises(SupportAnalysisGuardrailError, match="resolver-selected"):
        _run(SupportAgent(llm, _catalog(), clock=lambda: NOW))

    assert len(llm.calls) == 3


def test_guardrail_failure_retries_with_generic_prompt_and_can_recover() -> None:
    bad = _draft(employee_evidence="invented-evidence")
    good = _draft()
    llm = SequenceLLM([bad, good])

    result = _run(SupportAgent(llm, _catalog(), clock=lambda: NOW))

    assert result.support_checks[0].match_status == "POSSIBLY_RELEVANT"
    assert len(llm.calls) == 2
    assert len(llm.calls[0][1]) == 2
    assert len(llm.calls[1][1]) == 3
    retry_messages = json.dumps(llm.calls[1][1], ensure_ascii=False)
    assert "invented-evidence" not in retry_messages
    assert "previous structured response failed deterministic validation" in (
        retry_messages.lower()
    )


def test_provider_semantic_completion_failure_retries_and_recovers() -> None:
    invalid = SupportProviderOutput.model_validate(
        {
            **_draft().model_dump(mode="python"),
            "no_candidate_reason_code": "INVALID_COMPLETE_COMBINATION",
        }
    )
    good = SupportProviderOutput.model_validate(_draft().model_dump(mode="python"))
    llm = SequenceLLM([invalid, good])

    result = _run(SupportAgent(llm, _catalog(), clock=lambda: NOW))

    assert result.completion_status == "COMPLETE"
    assert len(llm.calls) == 2
    assert all(call[0] is SupportProviderOutput for call in llm.calls)
    assert len(llm.calls[1][1]) == 3


def test_provider_semantic_uniqueness_failure_exhausts_local_retries() -> None:
    criterion = SupportCriterionModelOutput(
        criterion_code="BUSINESS_TYPE",
        status="MET",
        reason_summary="검수 조건과 비교했습니다.",
        evidence_refs=["support-official", "fact-business"],
    )
    invalid = SupportProviderOutput(
        completion_status="COMPLETE",
        support_checks=[
            SupportCheckModelOutput(
                support_program=PROGRAM_REF,
                match_status="POSSIBLY_RELEVANT",
                criteria=[criterion, criterion.model_copy(deep=True)],
                unknown_field_paths=[],
                reason_summary="기관의 최종 확인이 필요합니다.",
                evidence_refs=["support-wiki", "support-official"],
            )
        ],
        no_candidate_reason_code=None,
        uncertainties=[],
    )
    llm = SequenceLLM([invalid, invalid, invalid])

    with pytest.raises(SupportAnalysisGuardrailError, match="draft contract"):
        _run(SupportAgent(llm, _catalog(), clock=lambda: NOW))

    assert len(llm.calls) == 3
    assert all(call[0] is SupportProviderOutput for call in llm.calls)
    assert [len(call[1]) for call in llm.calls] == [2, 3, 3]


def test_fact_overlay_is_compared_and_reported_without_mutating_snapshot() -> None:
    snapshot = _snapshot(employee_count=6)
    overlay = FactChangeCandidate(
        candidate_id=UUID("30000000-0000-4000-8000-000000000001"),
        operation="SET",
        source_fact_candidate_id=UUID("30000000-0000-4000-8000-000000000002"),
        source_type="INFO_ANALYSIS",
        field_path="employee_count",
        value_type="INTEGER",
        before_status="CONFIRMED",
        before_value=6,
        proposed_status="CONFIRMED",
        proposed_value=3,
        candidate_status="READY_FOR_REVIEW",
        reason_summary="사용자가 인원을 정정했습니다.",
        source_evidence_refs=["overlay-employee"],
        source_call_id=UUID("30000000-0000-4000-8000-000000000003"),
        confirmed_conflict_ref=None,
    )
    request = _request(snapshot=snapshot, overlays=[overlay])
    draft = _draft(employee_evidence="overlay-employee")

    result = _run(
        SupportAgent(FakeLLM(draft), _catalog(), clock=lambda: NOW),
        request,
    )

    assert result.based_on_candidate_ids == [overlay.candidate_id]
    assert result.support_checks[0].criteria[1].case_value == 3
    assert snapshot.facts[1].value == 6


def test_catalog_is_required() -> None:
    with pytest.raises(SupportCatalogUnavailableError):
        _run(SupportAgent(FakeLLM(_draft()), None, clock=lambda: NOW))
