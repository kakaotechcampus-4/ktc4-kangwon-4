from sqlmodel import Session, select

from app.be.models.evidence import DecisionRecord, Evidence, EvidenceLineage


def case_history_evidence_id(case_id: int, case_history_id: int) -> str:
    """사용자 입력 한 건을 근거로 남길 때 쓰는 evidence_id.

    만들 때와 조회할 때 둘 다 이 함수를 써서 어긋나지 않게 한다. evidence_id는 UNIQUE라
    케이스 번호만 쓰면 한 케이스에 근거를 하나밖에 못 남긴다 — 사용자가 추가로 입력할
    때마다 근거가 늘어나므로 입력 이력 번호까지 넣는다.
    """

    return f"case_{case_id}_history_{case_history_id}"


def create_evidence(session: Session, evidence: Evidence) -> Evidence:
    session.add(evidence)
    session.flush()
    return evidence


def get_evidence_by_case_id(session: Session, case_id: int) -> list[Evidence]:
    return session.exec(select(Evidence).where(Evidence.case_id == case_id)).all()


def get_evidence_lineages_by_evidence_ids(session: Session, evidence_ids: list[int]) -> list[EvidenceLineage]:
    if not evidence_ids:
        return []
    return session.exec(select(EvidenceLineage).where(EvidenceLineage.evidence_id.in_(evidence_ids))).all()


def get_evidence_lineages_by_case_id(session: Session, case_id: int) -> list[EvidenceLineage]:
    """이 Case의 근거들 사이 파생 관계. evidence.id가 아니라 case_id로 한 번에 읽는다."""

    return session.exec(
        select(EvidenceLineage)
        .join(Evidence, Evidence.id == EvidenceLineage.evidence_id)
        .where(Evidence.case_id == case_id)
    ).all()


def create_evidence_lineage(session: Session, evidence_lineage: EvidenceLineage) -> EvidenceLineage:
    session.add(evidence_lineage)
    session.flush()
    return evidence_lineage


def create_decision_record(session: Session, decision_record: DecisionRecord) -> DecisionRecord:
    session.add(decision_record)
    session.flush()
    return decision_record
