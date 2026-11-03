from sqlmodel import Session, select

from app.be.models.case_checklist import CaseChecklist, CaseChecklistHistory


def get_case_checklist(session: Session, case_id: int, task_id: str) -> CaseChecklist | None:
    return session.exec(
        select(CaseChecklist).where(CaseChecklist.case_id == case_id, CaseChecklist.task_id == task_id)
    ).one_or_none()


def create_case_checklist(session: Session, checklist: CaseChecklist) -> CaseChecklist:
    session.add(checklist)
    session.flush()
    return checklist


def delete_case_checklist(session: Session, checklist: CaseChecklist) -> None:
    session.delete(checklist)
    session.flush()


def create_case_checklist_history(session: Session, history: CaseChecklistHistory) -> CaseChecklistHistory:
    session.add(history)
    session.flush()
    return history


def get_case_checklist_histories_by_case_id(session: Session, case_id: int) -> list[CaseChecklistHistory]:
    return session.exec(select(CaseChecklistHistory).where(CaseChecklistHistory.case_id == case_id)).all()
