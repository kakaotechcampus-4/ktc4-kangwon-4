"""카페 폐업 절차 마스터 데이터를 DB에 적재한다.

절차 정의(이름·별칭·의존·조건)는 AI팀이 app/agent/procedure_tool/cafe.py에 한 벌로
들고 있다. BE가 같은 내용을 따로 적으면 두 벌이 되어 조용히 어긋나므로,
build_cafe_procedure_steps가 돌려주는 것을 그대로 세 표에 옮긴다.

AI는 이 표를 읽어서 절차 목록을 받는다(agent_runtime.build_known_procedure_steps).
step_code를 AI 논리 코드와 똑같이 두는 것이 중요하다 — 이름이 정확히 같을 때만
절차 대응표가 자동으로 맺히고, 대응표가 비면 Supervisor가 판단을 멈춘다.

적재는 앱이 뜰 때 한 번 한다(main.lifespan). 가입 요청 안에서 적재하면 세 가지가
어긋난다. 첫 가입자만 적재 비용을 내고, 두 사람이 동시에 가입하면 step_code가
unique라 한쪽이 IntegrityError로 떨어지며, 아무도 가입하지 않으면 절차 표가 빈 채로
남아 절차 목록을 읽는 쪽이 아무것도 못 받는다. 요청 쪽은 읽기만 한다
(load_cafe_procedure_step_ids).
"""

from sqlmodel import Session

from app.agent.action_catalog import PROCEDURE_LABELS
from app.agent.procedure_tool.cafe import CAFE_REGISTRY_VERSION, build_cafe_procedure_steps
from app.agent.schemas import KnownProcedureStep
from app.be.crud import procedure_step as procedure_step_crud
from app.be.models.procedure_step import ProcedureStep, StepDependency, StepEligibility

__all__ = ["ensure_cafe_procedure_registry", "load_cafe_procedure_step_ids"]


class ProcedureRegistryMissingError(RuntimeError):
    """절차 마스터 표가 비어 있어 Case 로드맵을 만들 수 없는 상태.

    사용자가 보낸 값이 아니라 적재가 안 돈 것이 원인이라, 같은 요청을 다시 보내도
    풀리지 않는다. 가입을 조용히 빈 로드맵으로 끝내지 않고 여기서 멈춘다.
    """


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


def load_cafe_procedure_step_ids(session: Session) -> dict[str, int]:
    """적재된 절차 8개의 step_code → DB id를 읽는다. 쓰지 않는다."""

    stored = {
        code: procedure_step_crud.get_procedure_step_by_code(session, code)
        for code in PROCEDURE_LABELS
    }
    missing = sorted(code for code, step in stored.items() if step is None)
    if missing:
        raise ProcedureRegistryMissingError(
            f"절차 마스터 표에 {', '.join(missing)}가 없다. 앱 시작 때 적재가 돌았는지 확인해야 한다"
        )
    return {code: step.id for code, step in stored.items()}


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
