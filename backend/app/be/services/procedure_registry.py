"""카페 폐업 절차 마스터 데이터를 DB에 적재한다.

절차 정의(이름·별칭·의존·조건)는 AI팀이 app/agent/procedure_tool/cafe.py에 한 벌로
들고 있다. BE가 같은 내용을 따로 적으면 두 벌이 되어 조용히 어긋나므로,
build_cafe_procedure_steps가 돌려주는 것을 그대로 세 표에 옮긴다.

AI는 이 표를 읽어서 절차 목록을 받는다(agent_runtime.build_known_procedure_steps).
step_code를 AI 논리 코드와 똑같이 두는 것이 중요하다 — 이름이 정확히 같을 때만
절차 대응표가 자동으로 맺히고, 대응표가 비면 Supervisor가 판단을 멈춘다.
"""

from sqlmodel import Session

from app.agent.action_catalog import PROCEDURE_LABELS
from app.agent.procedure_tool.cafe import CAFE_REGISTRY_VERSION, build_cafe_procedure_steps
from app.agent.schemas import KnownProcedureStep
from app.be.crud import procedure_step as procedure_step_crud
from app.be.models.procedure_step import ProcedureStep, StepDependency, StepEligibility

__all__ = ["ensure_cafe_procedure_registry"]


def ensure_cafe_procedure_registry(session: Session) -> dict[str, int]:
    """절차 8개를 적재하고 step_code → DB id를 돌려준다. 이미 있으면 그대로 쓴다.

    의존·조건은 절차 행에 딸린 별도 표라, 이미 적재된 Case가 있을 때 다시 쓰면
    같은 줄이 한 벌 더 쌓인다. 그래서 8개가 모두 이 버전으로 있으면 손대지 않는다.
    """

    stored = {
        code: procedure_step_crud.get_procedure_step_by_code(session, code)
        for code in PROCEDURE_LABELS
    }
    if all(
        step is not None and step.registry_version == CAFE_REGISTRY_VERSION
        for step in stored.values()
    ):
        return {code: step.id for code, step in stored.items()}

    steps = {
        code: stored[code]
        or procedure_step_crud.create_procedure_step(
            session,
            ProcedureStep(step_code=code, step_name=label, registry_version=CAFE_REGISTRY_VERSION),
        )
        for code, label in PROCEDURE_LABELS.items()
    }
    step_ids = {code: step.id for code, step in steps.items()}
    for known in build_cafe_procedure_steps(step_ids):
        _store(session, steps[known.procedure_step.step_code], known)
    return step_ids


def _store(session: Session, step: ProcedureStep, known: KnownProcedureStep) -> None:
    step.step_name = known.step_name
    step.utterance_aliases = list(known.utterance_aliases)
    step.registry_version = known.registry_version
    step.applicable_business_type = known.applicable_business_type
    session.add(step)
    for dependency in known.dependencies:
        procedure_step_crud.create_step_dependency(
            session,
            StepDependency(
                procedure_step_id=step.id,
                prerequisite_procedure_step_id=dependency.prerequisite_procedure_step_id,
                dependency_type=dependency.dependency_type,
            ),
        )
    for condition in known.eligibility_conditions:
        procedure_step_crud.create_step_eligibility(
            session,
            StepEligibility(
                procedure_step_id=step.id,
                condition_key=condition.condition_key,
                condition_value=condition.condition_value,
            ),
        )
