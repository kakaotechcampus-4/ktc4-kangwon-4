from sqlmodel import Session, select

from app.be.models.procedure_step import CaseProcedureStep, ProcedureStep


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
