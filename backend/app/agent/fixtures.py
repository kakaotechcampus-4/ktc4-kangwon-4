"""Synthetic, non-production providers for standalone Agent verification.

Nothing in this module represents a real support program or legal requirement.
It exists so the Agent graph can be exercised before BE read adapters are ready.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from app.agent.procedure_tool import (
    ProcedureConditionDefinition,
    ProcedureMaster,
    ProcedurePrerequisiteDefinition,
    ProcedureStepDefinition,
)
from app.agent.schemas import (
    CaseCreatedTrigger,
    CaseFact,
    CaseSnapshot,
    EvidenceRecord,
    KnownProcedureStep,
    RedactedInput,
    SupervisorRunInput,
    SupportProgramRef,
)
from app.agent.support_agent import (
    ReviewedSupportCatalog,
    ReviewedSupportProgram,
    SupportCriterionDefinition,
    SupportRequiredDocumentDefinition,
)

DEMO_NOW = datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class StandaloneFixture:
    request: SupervisorRunInput
    procedure_master: ProcedureMaster
    support_catalog: ReviewedSupportCatalog
    known_procedure_steps: tuple[KnownProcedureStep, ...]


def _evidence(
    evidence_id: str,
    *,
    source_type: str,
    excerpt: str,
    source_ref: str,
    parent_evidence_refs: list[str] | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_type=source_type,
        source_ref=source_ref,
        source_version="standalone-fixture/1.0",
        locator="fixture:record",
        excerpt=excerpt,
        parent_evidence_refs=parent_evidence_refs or [],
        published_at=DEMO_NOW,
        retrieved_at=DEMO_NOW,
        freshness_status="CURRENT",
        content_hash=None,
    )


def build_standalone_fixture() -> StandaloneFixture:
    """Build a deterministic, PII-free first-turn Hero Loop fixture."""

    case_evidence = _evidence(
        "fixture:case:profile",
        source_type="USER_INPUT",
        source_ref="fixture-input-profile",
        excerpt="임차형 1인 비프랜차이즈 카페를 운영 중입니다.",
    )
    case_detail_evidence = _evidence(
        "fixture:case:verified-details",
        source_type="USER_INPUT",
        source_ref="fixture-input-profile-details",
        excerpt=(
            "개인사업자이며 건축물 용도는 근린생활시설이고, "
            "이전에 점포정리 지원을 받은 적은 없습니다."
        ),
    )
    unknown_scope_evidence = _evidence(
        "fixture:case:restoration-scope:unknown",
        source_type="SYSTEM_RECORD",
        source_ref="fixture-case-1",
        excerpt="restoration_scope 상태가 UNKNOWN입니다.",
    )
    unknown_demolition_evidence = _evidence(
        "fixture:case:demolition-required:unknown",
        source_type="SYSTEM_RECORD",
        source_ref="fixture-case-1",
        excerpt="demolition_required 상태가 UNKNOWN입니다.",
    )
    snapshot = CaseSnapshot(
        snapshot_id=UUID("11111111-1111-4111-8111-111111111111"),
        case_id=1,
        case_version=1,
        case_status="IN_PROGRESS",
        facts=[
            _fact("business_type", "STRING", "CAFE", case_evidence.evidence_id),
            _fact("franchise_status", "BOOLEAN", False, case_evidence.evidence_id),
            _fact("employee_count", "INTEGER", 1, case_evidence.evidence_id),
            _fact("lease_status", "ENUM", "ACTIVE", case_evidence.evidence_id),
            _fact(
                "entity_type",
                "ENUM",
                "SOLE_PROPRIETOR",
                case_detail_evidence.evidence_id,
            ),
            _fact(
                "building_use_type",
                "ENUM",
                "NEIGHBORHOOD_LIVING",
                case_detail_evidence.evidence_id,
            ),
            _fact(
                "previous_support_history",
                "ENUM",
                "NONE",
                case_detail_evidence.evidence_id,
            ),
            _unknown_fact("restoration_status", "ENUM"),
            _unknown_fact("restoration_scope", "ENUM"),
            _unknown_fact("demolition_required", "ENUM"),
        ],
        procedure_progress=[],
        evidence_records=[
            case_evidence,
            case_detail_evidence,
            unknown_scope_evidence,
            unknown_demolition_evidence,
        ],
        captured_at=DEMO_NOW,
    )

    input_text = (
        "카페를 정리하려고 합니다. 현재 임차 중이고 원상복구 범위와 "
        "철거 필요 여부는 아직 임대인에게 확인하지 못했습니다."
    )
    redacted_input = RedactedInput(
        input_event_id="fixture-input-1",
        source_type="USER_INPUT",
        redacted_text=input_text,
        redactions=[],
        submitted_at=DEMO_NOW,
    )
    request = SupervisorRunInput(
        trigger=CaseCreatedTrigger(
            trigger_type="CASE_CREATED",
            input_event_id=redacted_input.input_event_id,
            client_event_id="fixture-client-event-1",
            input=redacted_input,
            submitted_at=DEMO_NOW,
        ),
        case_snapshot=snapshot,
    )

    procedure_evidence = _evidence(
        "fixture:procedure:master",
        source_type="PROCEDURE_MASTER",
        source_ref="fixture-procedure-master",
        excerpt="데모 절차 순서와 조건입니다. 실제 행정·법률 정보가 아닙니다.",
    )
    restoration_step = ProcedureStepDefinition(
        procedure_step={
            "procedure_step_id": 1,
            "step_code": "CONFIRM_RESTORATION_SCOPE",
        },
        step_name="원상복구 범위 확인",
        is_active=True,
        effective_from=None,
        effective_until=None,
        conditions=(
            ProcedureConditionDefinition(
                condition_id=1,
                field_path="lease_status",
                operator="IN",
                expected_values=("ACTIVE", "TERMINATION_NOTIFIED"),
                evidence_refs=(procedure_evidence.evidence_id,),
            ),
        ),
        prerequisites=(),
        requires_professional=False,
        professional_type=None,
        decision_authority="LANDLORD",
        evidence_refs=(procedure_evidence.evidence_id,),
    )
    support_check_step = ProcedureStepDefinition(
        procedure_step={
            "procedure_step_id": 2,
            "step_code": "CHECK_DEMOLITION_SUPPORT",
        },
        step_name="철거 전 지원조건 확인",
        is_active=True,
        effective_from=None,
        effective_until=None,
        conditions=(
            ProcedureConditionDefinition(
                condition_id=2,
                field_path="demolition_required",
                operator="EQ",
                expected_values=("REQUIRED",),
                evidence_refs=(procedure_evidence.evidence_id,),
            ),
        ),
        prerequisites=(
            ProcedurePrerequisiteDefinition(
                procedure_step=restoration_step.procedure_step,
                dependency_type="REQUIRED",
                evidence_refs=(procedure_evidence.evidence_id,),
            ),
        ),
        requires_professional=False,
        professional_type=None,
        decision_authority="OFFICIAL_AGENCY",
        evidence_refs=(procedure_evidence.evidence_id,),
    )
    procedure_master = ProcedureMaster(
        data_version="standalone-procedure/1.0",
        freshness_status="CURRENT",
        steps=(restoration_step, support_check_step),
        evidence_records=(procedure_evidence,),
    )

    support_official = _evidence(
        "fixture:support:official",
        source_type="OFFICIAL_DOCUMENT",
        source_ref="fixture-support-document",
        excerpt=(
            "데모 카탈로그 조건: 카페, 비프랜차이즈, 5인 이하, 철거 필요. "
            "실제 지원사업이 아닙니다."
        ),
    )
    support_wiki = _evidence(
        "fixture:support:wiki",
        source_type="REVIEWED_WIKI",
        source_ref="fixture-support-wiki",
        excerpt="팀 검수용 데모 지원 항목입니다. 실제 지원사업이 아닙니다.",
        parent_evidence_refs=[support_official.evidence_id],
    )
    program_ref = SupportProgramRef(
        support_program_id=101,
        wiki_uuid=UUID("22222222-2222-4222-8222-222222222222"),
    )
    support_program = ReviewedSupportProgram(
        support_program=program_ref,
        program_name="데모 점포정리 지원 검토 항목(실제 사업 아님)",
        related_steps=(support_check_step.procedure_step,),
        criteria=(
            _criterion(
                "BUSINESS_TYPE", "business_type", "EQ", ("CAFE",), support_official
            ),
            _criterion(
                "NON_FRANCHISE", "franchise_status", "EQ", (False,), support_official
            ),
            _criterion(
                "EMPLOYEE_LIMIT", "employee_count", "LTE", (5,), support_official
            ),
            _criterion(
                "DEMOLITION_REQUIRED",
                "demolition_required",
                "EQ",
                ("REQUIRED",),
                support_official,
            ),
        ),
        required_documents=(
            SupportRequiredDocumentDefinition(
                name="데모 검토용 사업자 확인 서류",
                submission_stage=None,
                evidence_refs=(support_official.evidence_id,),
            ),
        ),
        application_channel=None,
        application_url=None,
        application_period=None,
        source_version="standalone-support/1.0",
        freshness_status="CURRENT",
        evidence_refs=(support_wiki.evidence_id,),
    )
    support_catalog = ReviewedSupportCatalog(
        catalog_version="standalone-support/1.0",
        programs=(support_program,),
        evidence_records=(support_official, support_wiki),
    )

    known_steps = tuple(
        KnownProcedureStep(
            procedure_step=step.procedure_step,
            step_name=step.step_name,
            utterance_aliases=(
                ["원상복구 범위", "임대인 확인"]
                if step is restoration_step
                else ["철거 지원", "지원조건 확인"]
            ),
        )
        for step in procedure_master.steps
    )
    return StandaloneFixture(
        request=request,
        procedure_master=procedure_master,
        support_catalog=support_catalog,
        known_procedure_steps=known_steps,
    )


def _fact(
    field_path: str,
    value_type: str,
    value: str | int | bool,
    evidence_id: str,
) -> CaseFact:
    return CaseFact(
        field_path=field_path,
        value_type=value_type,
        value=value,
        status="CONFIRMED",
        evidence_refs=[evidence_id],
        updated_at=DEMO_NOW,
    )


def _unknown_fact(field_path: str, value_type: str) -> CaseFact:
    return CaseFact(
        field_path=field_path,
        value_type=value_type,
        value=None,
        status="UNKNOWN",
        evidence_refs=[],
        updated_at=None,
    )


def _criterion(
    code: str,
    field_path: str,
    operator: str,
    expected: tuple[str | int | bool, ...],
    evidence: EvidenceRecord,
) -> SupportCriterionDefinition:
    return SupportCriterionDefinition(
        criterion_code=code,
        field_path=field_path,
        operator=operator,
        required_values=expected,
        evidence_refs=(evidence.evidence_id,),
    )


__all__ = ["StandaloneFixture", "build_standalone_fixture"]
