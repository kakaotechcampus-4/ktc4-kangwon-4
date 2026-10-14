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
    return session.exec(select(CaseProcedureStep).where(CaseProcedureStep.case_id == case_id)).all()


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


def get_all_procedure_steps(session: Session) -> list[ProcedureStep]:
    return session.exec(select(ProcedureStep)).all()


def get_all_step_dependencies(session: Session) -> list[StepDependency]:
    return session.exec(select(StepDependency)).all()


def get_all_step_eligibilities(session: Session) -> list[StepEligibility]:
    return session.exec(select(StepEligibility)).all()
