from sqlmodel import Session, select

from app.be.models.evidence import Evidence, EvidenceLineage


def create_evidence(session: Session, evidence: Evidence) -> Evidence:
    session.add(evidence)
    session.flush()
    return evidence


def get_evidence_by_case_id(session: Session, case_id: int) -> list[Evidence]:
    return session.exec(select(Evidence).where(Evidence.case_id == case_id)).all()


def create_evidence_lineage(session: Session, evidence_lineage: EvidenceLineage) -> EvidenceLineage:
    session.add(evidence_lineage)
    session.flush()
    return evidence_lineage
