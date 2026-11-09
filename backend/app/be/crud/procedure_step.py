from sqlalchemy import exists
from sqlalchemy.orm import joinedload
from sqlmodel import Session, select

from app.be.models.procedure_step import (
    CaseProcedureStep,
    CaseProcedureStepHistory,
    ProcedureStep,
    StepDependency,
    StepEligibility,
)


def get_procedure_step_by_code(session: Session, step_code: str) -> ProcedureStep | None:
    return session.exec(select(ProcedureStep).where(ProcedureStep.step_code == step_code)).one_or_none()


def create_procedure_step(session: Session, procedure_step: ProcedureStep) -> ProcedureStep:
    session.add(procedure_step)
    session.flush()
    return procedure_step


def create_case_procedure_step(session: Session, case_procedure_step: CaseProcedureStep) -> CaseProcedureStep:
    session.add(case_procedure_step)
    session.flush()
    return case_procedure_step


def get_case_procedure_steps_by_case_id(session: Session, case_id: int) -> list[CaseProcedureStep]:
    # 부르는 쪽(case_snapshot)이 절차마다 이름(procedure_step.step_code)을 읽는다. 같이 가져오지
    # 않으면 절차 수만큼 procedure_step을 한 번씩 더 읽는다(N+1, 카페 8번).
    return session.exec(
        select(CaseProcedureStep)
        .options(joinedload(CaseProcedureStep.procedure_step))
        .where(CaseProcedureStep.case_id == case_id)
    ).all()


def get_case_procedure_step(
    session: Session, case_id: int, procedure_step_id: int
) -> CaseProcedureStep | None:
    return session.exec(
        select(CaseProcedureStep)
        .where(CaseProcedureStep.case_id == case_id)
        .where(CaseProcedureStep.procedure_step_id == procedure_step_id)
    ).one_or_none()


def create_case_procedure_step_history(
    session: Session, history: CaseProcedureStepHistory
) -> CaseProcedureStepHistory:
    session.add(history)
    session.flush()
    return history


def has_case_procedure_step_history(session: Session, case_history_id: int) -> bool:
    return session.exec(
        select(exists().where(CaseProcedureStepHistory.case_history_id == case_history_id))
    ).one()


def get_all_procedure_steps(session: Session) -> list[ProcedureStep]:
    return session.exec(select(ProcedureStep)).all()


def get_all_step_dependencies(session: Session) -> list[StepDependency]:
    return session.exec(select(StepDependency)).all()


def get_all_step_eligibilities(session: Session) -> list[StepEligibility]:
    return session.exec(select(StepEligibility)).all()


def create_step_dependency(session: Session, dependency: StepDependency) -> StepDependency:
    session.add(dependency)
    session.flush()
    return dependency


def create_step_eligibility(session: Session, eligibility: StepEligibility) -> StepEligibility:
    session.add(eligibility)
    session.flush()
    return eligibility
