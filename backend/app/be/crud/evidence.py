from sqlmodel import Session, select

from app.be.models.evidence import Evidence, EvidenceLineage


def creation_form_evidence_id(case_id: int) -> str:
    """case 생성 폼 입력값 근거의 evidence_id. 만들 때와 조회할 때 둘 다 이 함수를 써서 어긋나지 않게 한다."""

    return f"case_{case_id}_creation_form"


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
