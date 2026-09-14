from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from app.agent.procedure_tool import (
    ProcedureConditionDefinition,
    ProcedureLookupInputError,
    ProcedureLookupTool,
    ProcedureMaster,
    ProcedureMasterUnavailableError,
    ProcedurePrerequisiteDefinition,
    ProcedureStepDefinition,
)
from app.agent.schemas import (
    AllProcedureLookupInput,
    CaseFact,
    CaseSnapshot,
    EvidenceRecord,
    FactChangeCandidate,
    PlanningContext,
    ProcedureProgress,
    ProcedureStepRef,
    SpecificProcedureLookupInput,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000001")
CANDIDATE_ID = UUID("00000000-0000-4000-8000-000000000002")
SOURCE_CALL_ID = UUID("00000000-0000-4000-8000-000000000003")
SOURCE_FACT_CANDIDATE_ID = UUID("00000000-0000-4000-8000-000000000004")

CHECK_BUSINESS = ProcedureStepRef(
    procedure_step_id=1,
    step_code="CHECK_BUSINESS_TYPE",
)
FILE_REPORT = ProcedureStepRef(
    procedure_step_id=2,
    step_code="FILE_CLOSURE_REPORT",
)


def evidence(
    evidence_id: str,
    *,
    source_type: str = "SYSTEM_RECORD",
    freshness_status: str = "CURRENT",
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_type=source_type,
        source_ref=f"fixture:{evidence_id}",
        source_version="fixture-v1",
        locator="fixture.section",
        excerpt="테스트를 위한 검증된 가짜 근거",
        parent_evidence_refs=[],
        published_at=NOW,
        retrieved_at=NOW,
        freshness_status=freshness_status,
        content_hash="sha256:" + "a" * 64,
    )


def procedure_master(
    *,
    freshness_status: str = "CURRENT",
    evidence_freshness_status: str = "CURRENT",
) -> ProcedureMaster:
    master_evidence = evidence(
        "procedure:master:v1",
        source_type="PROCEDURE_MASTER",
        freshness_status=evidence_freshness_status,
    )
    return ProcedureMaster(
        data_version="procedure-fixture-v1",
        freshness_status=freshness_status,
        evidence_records=[master_evidence],
        steps=[
            ProcedureStepDefinition(
                procedure_step=CHECK_BUSINESS,
                step_name="업종 확인",
                is_active=True,
                effective_from=date(2026, 1, 1),
                effective_until=None,
                conditions=[
                    ProcedureConditionDefinition(
                        condition_id=101,
                        field_path="business_type",
                        operator="EQ",
                        expected_values=["CAFE"],
                        evidence_refs=[master_evidence.evidence_id],
                    )
                ],
                prerequisites=[],
                requires_professional=False,
                professional_type=None,
                decision_authority="USER",
                evidence_refs=[master_evidence.evidence_id],
            ),
            ProcedureStepDefinition(
                procedure_step=FILE_REPORT,
                step_name="폐업 신고",
                is_active=True,
                effective_from=date(2026, 1, 1),
                effective_until=None,
                conditions=[
                    ProcedureConditionDefinition(
                        condition_id=102,
                        field_path="business_type",
                        operator="EQ",
                        expected_values=["CAFE"],
                        evidence_refs=[master_evidence.evidence_id],
                    )
                ],
                prerequisites=[
                    ProcedurePrerequisiteDefinition(
                        procedure_step=CHECK_BUSINESS,
                        dependency_type="REQUIRED",
                        evidence_refs=[master_evidence.evidence_id],
                    )
                ],
                requires_professional=True,
                professional_type="관할 기관 담당자",
                decision_authority="OFFICIAL_AGENCY",
                evidence_refs=[master_evidence.evidence_id],
            ),
        ],
    )


def case_snapshot(
    *,
    business_type: str | None,
    first_step_status: str | None = None,
) -> CaseSnapshot:
    evidence_records = []
    fact_evidence_refs = []
    fact_status = "UNKNOWN"
    if business_type is not None:
        fact_status = "CONFIRMED"
        fact_evidence_refs = ["case:business-type"]
        evidence_records.append(evidence("case:business-type"))

    progress = []
    if first_step_status is not None:
        progress_evidence_refs = []
        if first_step_status == "COMPLETED":
            progress_evidence_refs = ["case:check-business-completed"]
            evidence_records.append(evidence("case:check-business-completed"))
        progress.append(
            ProcedureProgress(
                procedure_step=CHECK_BUSINESS,
                status=first_step_status,
                evidence_refs=progress_evidence_refs,
                updated_at=NOW,
            )
        )

    return CaseSnapshot(
        snapshot_id=SNAPSHOT_ID,
        case_id=1,
        case_version=1,
        case_status="IN_PROGRESS",
        facts=[
            CaseFact(
                field_path="business_type",
                value_type="STRING",
                value=business_type,
                status=fact_status,
                evidence_refs=fact_evidence_refs,
                updated_at=NOW if business_type is not None else None,
            )
        ],
        procedure_progress=progress,
        evidence_records=evidence_records,
        captured_at=NOW,
    )


def overlay_business_type(
    *,
    before_status: str = "UNKNOWN",
    before_value: str | None = None,
) -> FactChangeCandidate:
    return FactChangeCandidate(
        candidate_id=CANDIDATE_ID,
        operation="SET",
        source_fact_candidate_id=SOURCE_FACT_CANDIDATE_ID,
        source_type="INFO_ANALYSIS",
        field_path="business_type",
        value_type="STRING",
        before_status=before_status,
        before_value=before_value,
        proposed_status="CONFIRMED",
        proposed_value="CAFE",
        candidate_status="READY_FOR_REVIEW",
        reason_summary="사용자가 업종을 카페로 명시했습니다.",
        source_evidence_refs=["input:business-type"],
        source_call_id=SOURCE_CALL_ID,
        confirmed_conflict_ref=None,
    )


def test_lookup_applies_relevant_overlay_and_preserves_provenance() -> None:
    request = SpecificProcedureLookupInput(
        lookup_scope="SPECIFIC_STEPS",
        planning_context=PlanningContext(
            case_snapshot=case_snapshot(business_type=None),
            fact_overlays=[overlay_business_type()],
        ),
        step_codes=["CHECK_BUSINESS_TYPE"],
        as_of=date(2026, 9, 14),
    )

    result = ProcedureLookupTool(procedure_master()).lookup(request)

    assert result.completion_status == "COMPLETE"
    assert result.based_on_snapshot_id == SNAPSHOT_ID
    assert result.based_on_candidate_ids == [CANDIDATE_ID]
    assert len(result.step_evaluations) == 1
    evaluation = result.step_evaluations[0]
    assert evaluation.applicability == "APPLICABLE"
    assert evaluation.readiness == "READY"
    assert evaluation.conditions[0].actual_value == "CAFE"
    assert evaluation.conditions[0].status == "MET"
    assert [item.evidence_id for item in result.evidence_records] == [
        "procedure:master:v1"
    ]


def test_unknown_case_fact_stays_undetermined() -> None:
    request = SpecificProcedureLookupInput(
        lookup_scope="SPECIFIC_STEPS",
        planning_context=PlanningContext(
            case_snapshot=case_snapshot(business_type=None),
            fact_overlays=[],
        ),
        step_codes=["CHECK_BUSINESS_TYPE"],
        as_of=date(2026, 9, 14),
    )

    result = ProcedureLookupTool(procedure_master()).lookup(request)

    evaluation = result.step_evaluations[0]
    assert result.completion_status == "COMPLETE"
    assert evaluation.conditions[0].actual_value is None
    assert evaluation.conditions[0].status == "UNKNOWN"
    assert evaluation.applicability == "UNDETERMINED"
    assert evaluation.readiness == "UNDETERMINED"
    assert evaluation.unavailable_reasons[0].code == "CONDITION_UNKNOWN"


@pytest.mark.parametrize(
    ("progress_status", "expected_readiness", "expected_satisfaction"),
    [
        (None, "UNDETERMINED", "UNKNOWN"),
        ("IN_PROGRESS", "BLOCKED", "NOT_SATISFIED"),
        ("COMPLETED", "READY", "SATISFIED"),
    ],
)
def test_required_prerequisite_controls_readiness(
    progress_status: str | None,
    expected_readiness: str,
    expected_satisfaction: str,
) -> None:
    request = SpecificProcedureLookupInput(
        lookup_scope="SPECIFIC_STEPS",
        planning_context=PlanningContext(
            case_snapshot=case_snapshot(
                business_type="CAFE",
                first_step_status=progress_status,
            ),
            fact_overlays=[],
        ),
        step_codes=["FILE_CLOSURE_REPORT"],
        as_of=date(2026, 9, 14),
    )

    result = ProcedureLookupTool(procedure_master()).lookup(request)

    evaluation = result.step_evaluations[0]
    assert evaluation.applicability == "APPLICABLE"
    assert evaluation.readiness == expected_readiness
    assert evaluation.prerequisites[0].satisfaction == expected_satisfaction


@pytest.mark.parametrize(
    ("master_freshness", "evidence_freshness"),
    [
        ("STALE", "CURRENT"),
        ("UNKNOWN", "CURRENT"),
        ("CURRENT", "STALE"),
        ("CURRENT", "UNKNOWN"),
    ],
)
def test_unverified_master_is_partial_and_never_reports_ready(
    master_freshness: str,
    evidence_freshness: str,
) -> None:
    request = SpecificProcedureLookupInput(
        lookup_scope="SPECIFIC_STEPS",
        planning_context=PlanningContext(
            case_snapshot=case_snapshot(business_type="CAFE"),
            fact_overlays=[],
        ),
        step_codes=["CHECK_BUSINESS_TYPE"],
        as_of=date(2026, 9, 14),
    )

    result = ProcedureLookupTool(
        procedure_master(
            freshness_status=master_freshness,
            evidence_freshness_status=evidence_freshness,
        )
    ).lookup(request)

    evaluation = result.step_evaluations[0]
    assert result.completion_status == "PARTIAL"
    assert evaluation.applicability == "UNDETERMINED"
    assert evaluation.readiness == "UNDETERMINED"
    assert evaluation.conditions[0].status == "UNKNOWN"
    assert evaluation.unavailable_reasons[0].code == "CONDITION_UNKNOWN"


@pytest.mark.parametrize(
    ("parent_freshness", "expected_completion", "expected_readiness"),
    [
        ("CURRENT", "COMPLETE", "READY"),
        ("STALE", "PARTIAL", "UNDETERMINED"),
        ("UNKNOWN", "PARTIAL", "UNDETERMINED"),
    ],
)
def test_parent_evidence_is_emitted_and_controls_source_freshness(
    parent_freshness: str,
    expected_completion: str,
    expected_readiness: str,
) -> None:
    base = procedure_master()
    parent = evidence(
        "procedure:official-parent:v1",
        source_type="OFFICIAL_DOCUMENT",
        freshness_status=parent_freshness,
    )
    derived = base.evidence_records[0].model_copy(
        update={"parent_evidence_refs": [parent.evidence_id]}
    )
    master_with_lineage = ProcedureMaster(
        data_version=base.data_version,
        freshness_status=base.freshness_status,
        steps=base.steps,
        evidence_records=[derived, parent],
    )
    request = SpecificProcedureLookupInput(
        lookup_scope="SPECIFIC_STEPS",
        planning_context=PlanningContext(
            case_snapshot=case_snapshot(business_type="CAFE"),
            fact_overlays=[],
        ),
        step_codes=["CHECK_BUSINESS_TYPE"],
        as_of=date(2026, 9, 14),
    )

    result = ProcedureLookupTool(master_with_lineage).lookup(request)

    assert result.completion_status == expected_completion
    assert result.step_evaluations[0].readiness == expected_readiness
    assert {item.evidence_id for item in result.evidence_records} == {
        "procedure:master:v1",
        "procedure:official-parent:v1",
    }


def test_unknown_specific_step_returns_partial_without_fabricating_a_row() -> None:
    request = SpecificProcedureLookupInput(
        lookup_scope="SPECIFIC_STEPS",
        planning_context=PlanningContext(
            case_snapshot=case_snapshot(business_type="CAFE"),
            fact_overlays=[],
        ),
        step_codes=["UNKNOWN_STEP"],
        as_of=date(2026, 9, 14),
    )

    result = ProcedureLookupTool(procedure_master()).lookup(request)

    assert result.completion_status == "PARTIAL"
    assert result.step_evaluations == []
    assert result.evidence_records == []
    assert result.based_on_candidate_ids == []


def test_known_and_unknown_specific_steps_keep_verified_rows_but_are_partial() -> None:
    request = SpecificProcedureLookupInput(
        lookup_scope="SPECIFIC_STEPS",
        planning_context=PlanningContext(
            case_snapshot=case_snapshot(business_type="CAFE"),
            fact_overlays=[],
        ),
        step_codes=["CHECK_BUSINESS_TYPE", "UNKNOWN_STEP"],
        as_of=date(2026, 9, 14),
    )

    result = ProcedureLookupTool(procedure_master()).lookup(request)

    assert result.completion_status == "PARTIAL"
    assert len(result.step_evaluations) == 1
    assert result.step_evaluations[0].readiness == "READY"


def test_overlay_before_state_must_match_the_snapshot() -> None:
    request = SpecificProcedureLookupInput(
        lookup_scope="SPECIFIC_STEPS",
        planning_context=PlanningContext(
            case_snapshot=case_snapshot(business_type=None),
            fact_overlays=[
                overlay_business_type(
                    before_status="CONFIRMED",
                    before_value="RESTAURANT",
                )
            ],
        ),
        step_codes=["CHECK_BUSINESS_TYPE"],
        as_of=date(2026, 9, 14),
    )

    with pytest.raises(ProcedureLookupInputError, match="before state"):
        ProcedureLookupTool(procedure_master()).lookup(request)


def test_empty_master_all_steps_lookup_is_partial() -> None:
    master = ProcedureMaster(
        data_version="procedure-empty-v1",
        freshness_status="CURRENT",
        steps=[],
        evidence_records=[],
    )
    request = AllProcedureLookupInput(
        lookup_scope="ALL_STEPS",
        planning_context=PlanningContext(
            case_snapshot=case_snapshot(business_type="CAFE"),
            fact_overlays=[],
        ),
        as_of=date(2026, 9, 14),
    )

    result = ProcedureLookupTool(master).lookup(request)

    assert result.completion_status == "PARTIAL"
    assert result.step_evaluations == []


def test_missing_master_is_an_explicit_technical_failure() -> None:
    request = AllProcedureLookupInput(
        lookup_scope="ALL_STEPS",
        planning_context=PlanningContext(
            case_snapshot=case_snapshot(business_type="CAFE"),
            fact_overlays=[],
        ),
        as_of=date(2026, 9, 14),
    )

    with pytest.raises(ProcedureMasterUnavailableError):
        ProcedureLookupTool(None).lookup(request)


def test_master_rejects_untrusted_evidence_for_procedure_rules() -> None:
    untrusted = evidence("input:untrusted", source_type="USER_INPUT")

    with pytest.raises(ValidationError, match="procedure-master or official evidence"):
        ProcedureMaster(
            data_version="invalid-v1",
            freshness_status="CURRENT",
            evidence_records=[untrusted],
            steps=[
                ProcedureStepDefinition(
                    procedure_step=CHECK_BUSINESS,
                    step_name="업종 확인",
                    is_active=True,
                    conditions=[],
                    prerequisites=[],
                    requires_professional=False,
                    professional_type=None,
                    decision_authority="USER",
                    evidence_refs=[untrusted.evidence_id],
                )
            ],
        )


def test_tool_deep_copies_injected_master() -> None:
    master = procedure_master()
    tool = ProcedureLookupTool(master)
    master.evidence_records[0].freshness_status = "STALE"
    request = SpecificProcedureLookupInput(
        lookup_scope="SPECIFIC_STEPS",
        planning_context=PlanningContext(
            case_snapshot=case_snapshot(business_type="CAFE"),
            fact_overlays=[],
        ),
        step_codes=["CHECK_BUSINESS_TYPE"],
        as_of=date(2026, 9, 14),
    )

    result = tool.lookup(request)

    assert result.completion_status == "COMPLETE"
    assert result.evidence_records[0].freshness_status == "CURRENT"


def test_master_rejects_unresolved_evidence_parent() -> None:
    base = procedure_master()
    evidence_with_missing_parent = base.evidence_records[0].model_copy(
        update={"parent_evidence_refs": ["procedure:missing-parent"]}
    )

    with pytest.raises(ValidationError, match="unknown parents"):
        ProcedureMaster(
            data_version=base.data_version,
            freshness_status=base.freshness_status,
            steps=base.steps,
            evidence_records=[evidence_with_missing_parent],
        )


def test_master_rejects_missing_prerequisite_step() -> None:
    base = procedure_master()

    with pytest.raises(ValidationError, match="unknown prerequisite"):
        ProcedureMaster(
            data_version=base.data_version,
            freshness_status=base.freshness_status,
            steps=[base.steps[1]],
            evidence_records=base.evidence_records,
        )


def test_master_rejects_prerequisite_cycle() -> None:
    base = procedure_master()
    first_step_with_cycle = base.steps[0].model_copy(
        update={
            "prerequisites": (
                ProcedurePrerequisiteDefinition(
                    procedure_step=FILE_REPORT,
                    dependency_type="REQUIRED",
                    evidence_refs=("procedure:master:v1",),
                ),
            )
        }
    )

    with pytest.raises(ValidationError, match="must not contain a cycle"):
        ProcedureMaster(
            data_version=base.data_version,
            freshness_status=base.freshness_status,
            steps=[first_step_with_cycle, base.steps[1]],
            evidence_records=base.evidence_records,
        )
