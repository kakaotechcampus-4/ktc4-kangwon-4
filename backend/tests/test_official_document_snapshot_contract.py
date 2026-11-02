"""공식 문서를 어디에 저장하든 AI가 받는 스냅샷은 그대로여야 한다.

본문을 Case마다 복사하지 않고 공용으로 빼는 중이다. AI는 DB 표를 보지 않고
build_case_snapshot이 조립해 넘긴 것만 보므로, 저장 구조를 바꿔도 여기서 나오는
EvidenceRecord가 같으면 AI 쪽은 바뀐 것을 모른다.

구조를 고치기 전에 지금 나오는 모양을 박아둔다. 안 박아두고 고치면 조용히 어긋나도
모르고, 그러면 절차 문서가 짝을 잃어 모든 판단이 "상담원에게 문의"로 끝난다(#65).
"""

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine
from testcontainers.community.mysql import MySqlContainer

from app.be.crud.member import create_member
from app.be.schemas.case import CaseCreateRequest
from app.be.services import procedure_registry
from app.be.services.case import create_case
from app.be.services.case_snapshot import build_case_snapshot

RETRIEVED = datetime(2026, 10, 4, 1, 2, 3, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def mysql_engine():
    container = MySqlContainer(
        "mysql:8.0", dialect="pymysql", username="test", password="test",
        root_password="test", dbname="official_document_test",
    ).with_env("TZ", "Asia/Seoul")
    with container:
        engine = create_engine(container.get_connection_url() + "?charset=utf8mb4")
        try:
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                procedure_registry.ensure_cafe_procedure_registry(session)
                session.commit()
            yield engine
        finally:
            engine.dispose()


def official_records(engine, case_id):
    with Session(engine) as session:
        snapshot = build_case_snapshot(session, case_id)
    return sorted(
        (item for item in snapshot.evidence_records if item.source_type == "OFFICIAL_DOCUMENT"),
        key=lambda item: item.source_ref,
    )


def new_case(engine):
    with Session(engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
        case, _ = create_case(session, member.id, CaseCreateRequest(
            business_type="카페", franchise_status=False, employee_count=2,
            lease_status="LEASED_PAID",
        ))
        session.commit()
        return case.id


def test_official_documents_reach_the_agent_with_every_field_filled(mysql_engine):
    """AI가 근거를 가리키고 신선도를 따지는 데 쓰는 값들이 다 실려 나간다."""
    records = official_records(mysql_engine, new_case(mysql_engine))

    assert len(records) == 4
    for record in records:
        assert record.evidence_id.startswith("procedure:")
        assert record.source_ref.startswith("https://")
        # 버전과 해시가 있어야 "이 Case가 이 버전의 이 내용을 봤다"가 증명된다.
        # 본문을 공용으로 빼도 이 둘은 Case 쪽에 남아야 한다.
        assert record.source_version == "reviewed-procedures/2026-10-04"
        # AI는 "sha256:" 접두사를 떼고 64자만 들고 있다(schemas._normalize_content_hash).
        assert len(record.content_hash) == 64 and record.content_hash.isalnum()
        assert record.excerpt and len(record.excerpt) > 50
        assert record.freshness_status in {"CURRENT", "STALE", "UNKNOWN"}
        assert record.retrieved_at.tzinfo is not None


def test_two_cases_get_the_same_official_text_under_different_evidence_ids(mysql_engine):
    """본문은 같고 근거 식별자만 Case마다 달라야 한다.

    공용으로 빼도 이 관계가 유지되어야 한다. 본문이 달라지면 AI가 다른 자료로 보고,
    evidence_id가 같아지면 어느 Case의 근거인지 가릴 수 없다.
    """
    first = official_records(mysql_engine, new_case(mysql_engine))
    second = official_records(mysql_engine, new_case(mysql_engine))

    assert [item.excerpt for item in first] == [item.excerpt for item in second]
    assert [item.content_hash for item in first] == [item.content_hash for item in second]
    assert {item.evidence_id for item in first}.isdisjoint({item.evidence_id for item in second})


def test_official_text_is_not_redacted(mysql_engine):
    """공식 자료는 가리지 않는다. 가리면 저장된 content_hash와 어긋난다."""
    from app.be.services.reviewed_procedure import load_reviewed_procedures

    stored = {record.content_hash.removeprefix("sha256:"): record.excerpt
              for record in load_reviewed_procedures().records()}
    for record in official_records(mysql_engine, new_case(mysql_engine)):
        assert record.excerpt == stored[record.content_hash]
