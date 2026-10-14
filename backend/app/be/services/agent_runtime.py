"""AI에 넘길 참고 자료를 BE 쪽 데이터로 만든다.

AI 호출은 AI팀 입구(app/common/agent_service.py)가 맡고, 여기서는 그 입구에 넘길
절차 목록과 지원사업 자료를 만든다. 검수된 절차 문서는 app/be/services/reviewed_procedure.py가
맡는다.

지원사업은 검수된 자료가 아직 없어서 빈 채로 넘긴다 — 없는 걸 지어내면 AI가 존재하지
않는 출처를 근거로 안내하게 되므로, 비어 있다는 사실을 그대로 전달한다.
"""

from sqlmodel import Session

from app.agent.schemas import (
    KnownProcedureStep,
    ProcedureDependency,
    ProcedureEligibility,
    ProcedureStepRef,
)
from app.agent.support_agent import ReviewedSupportCatalog
from app.be.crud import procedure_step as procedure_step_crud
from app.be.models.mixins import KST


def empty_support_catalog() -> ReviewedSupportCatalog:
    return ReviewedSupportCatalog(
        catalog_version="no-reviewed-support-data", programs=(), evidence_records=()
    )


def build_known_procedure_steps(session: Session) -> list[KnownProcedureStep]:
    """procedure_step 테이블을 AI가 아는 절차 목록 형태로 바꾼다."""

    dependencies_by_step: dict[int, list[ProcedureDependency]] = {}
    for dependency in procedure_step_crud.get_all_step_dependencies(session):
        dependencies_by_step.setdefault(dependency.procedure_step_id, []).append(
            ProcedureDependency(
                prerequisite_procedure_step_id=dependency.prerequisite_procedure_step_id,
                dependency_type=dependency.dependency_type,
            )
        )

    eligibilities_by_step: dict[int, list[ProcedureEligibility]] = {}
    for eligibility in procedure_step_crud.get_all_step_eligibilities(session):
        eligibilities_by_step.setdefault(eligibility.procedure_step_id, []).append(
            ProcedureEligibility(
                condition_key=eligibility.condition_key,
                condition_value=eligibility.condition_value,
            )
        )

    return [
        KnownProcedureStep(
            procedure_step=ProcedureStepRef(procedure_step_id=step.id, step_code=step.step_code),
            step_name=step.step_name,
            utterance_aliases=step.utterance_aliases or [],
            registry_version=step.registry_version,
            applicable_business_type=step.applicable_business_type,
            deprecated_at=step.deprecated_at.replace(tzinfo=KST) if step.deprecated_at else None,
            dependencies=dependencies_by_step.get(step.id, []),
            eligibility_conditions=eligibilities_by_step.get(step.id, []),
        )
        for step in procedure_step_crud.get_all_procedure_steps(session)
    ]
