"""Case 생성 때 받는 가게 이름·상황 진단 항목이 저장·조회되고, AI 근거에는 가게 이름만 빠지는지.

저장·조회는 진짜 MySQL이 필요하다(격리된 mysql:8.0 컨테이너, Docker와 requirements-dev.txt 필요).
입력 길이·범위 검사는 요청 스키마만 만들어 보면 되어 DB 없이 돈다.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine
from testcontainers.community.mysql import MySqlContainer

from app.be.crud.case_history import get_case_created_history
from app.be.crud.member import create_member
from app.be.schemas.case import CaseCreateRequest
from app.be.services.case import create_case, get_case

BASE = dict(business_type="카페", franchise_status=False, lease_status="LEASED_PAID")


@pytest.fixture(scope="module")
def mysql_engine():
    container = MySqlContainer(
        "mysql:8.0", dialect="pymysql", username="test", password="test",
        root_password="test", dbname="case_create_fields_test",
    ).with_env("TZ", "Asia/Seoul")
    with container:
        engine = create_engine(container.get_connection_url() + "?charset=utf8mb4")
        try:
            SQLModel.metadata.create_all(engine)
            yield engine
        finally:
            engine.dispose()


def sign_up(engine, **fields):
    """회원 하나를 새로 만들어 Case를 생성하고, 조회 응답의 case와 가입 근거 원문을 돌려준다."""

    with Session(engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
        case, _ = create_case(session, member.id, CaseCreateRequest(**BASE, **fields))
        raw_input = get_case_created_history(session, case.id).raw_input
        return get_case(session, member.id).case, raw_input


def test_store_name_and_diagnosis_fields_are_saved_and_returned(mysql_engine):
    case, _ = sign_up(
        mysql_engine, store_name="봄날 개인카페",
        has_business_loan=True, has_service_contracts=True, restoration_clause="EXISTS",
    )

    assert case.store_name == "봄날 개인카페"
    assert (case.has_business_loan, case.has_service_contracts, case.restoration_clause) == (True, True, "EXISTS")


def test_fields_left_out_get_their_defaults(mysql_engine):
    case, _ = sign_up(mysql_engine)

    assert case.store_name is None
    assert (case.has_business_loan, case.has_service_contracts, case.restoration_clause) == (False, False, "UNKNOWN")


def test_store_name_is_kept_out_of_the_ai_evidence_but_diagnosis_fields_are_in(mysql_engine):
    _, raw_input = sign_up(
        mysql_engine, store_name="봄날 개인카페", has_business_loan=True, restoration_clause="NOT_EXISTS",
    )

    assert "store_name" not in raw_input and "봄날" not in raw_input
    assert '"has_business_loan": true' in raw_input
    assert '"restoration_clause": "NOT_EXISTS"' in raw_input


@pytest.mark.parametrize("field", ["store_name", "business_type"])
def test_text_longer_than_the_column_is_rejected(field):
    CaseCreateRequest(**{**BASE, field: "가" * 50})
    with pytest.raises(ValidationError):
        CaseCreateRequest(**{**BASE, field: "가" * 51})


@pytest.mark.parametrize("count", [0, 1000])
def test_employee_count_within_range_is_accepted(count):
    assert CaseCreateRequest(**BASE, employee_count=count).employee_count == count


@pytest.mark.parametrize("count", [-1, 1001])
def test_employee_count_out_of_range_is_rejected(count):
    with pytest.raises(ValidationError):
        CaseCreateRequest(**BASE, employee_count=count)


def test_unknown_restoration_clause_is_rejected():
    with pytest.raises(ValidationError):
        CaseCreateRequest(**BASE, restoration_clause="MAYBE")
