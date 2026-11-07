"""공식 자료 본문을 앱이 뜰 때 넣어서, 빈 DB에 동시 가입이 와도 자료 연결이 깨지지 않는지. 진짜 MySQL(Docker).

예전에는 가입할 때마다 본문이 없으면 넣었다. 빈 DB에 가입이 동시에 오면 같은 문서를 둘 다
넣으려다 unique(uq_official_document_source_version)에 걸려 하나만 남고, 나머지 Case는 자료
없이 판단으로 넘어가 COMPONENT_UNAVAILABLE로 실패했다(#252 리뷰에서 E2E로 재현). 모델 호출은 없다.
"""

import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlmodel import Session, SQLModel, create_engine, select
from testcontainers.community.mysql import MySqlContainer

from app.be.crud.member import create_member
from app.be.db import MYSQL_IMAGE
from app.be.models.evidence import Evidence, OfficialDocument
from app.be.schemas.case import CaseCreateRequest
from app.be.services import case as case_service
from app.be.services import judgment as judgment_service
from app.be.services import reviewed_procedure
from app.main import app

SIGNUPS = 8


@pytest.fixture
def empty_engine():
    """매번 빈 DB. 다른 검사가 먼저 가입해 본문을 넣어 두면 이 경쟁이 재현되지 않는다."""

    with MySqlContainer(MYSQL_IMAGE, dialect="pymysql") as container:
        engine = create_engine(container.get_connection_url() + "?charset=utf8mb4", pool_size=SIGNUPS + 2)
        SQLModel.metadata.create_all(engine)
        try:
            yield engine
        finally:
            engine.dispose()


def _start_app(engine, monkeypatch) -> None:
    """운영처럼(ENVIRONMENT=prod) 앱을 한 번 켰다 끈다. 표는 지우지 않는다."""

    monkeypatch.setattr("app.main.get_engine", lambda: engine)
    monkeypatch.setattr(judgment_service, "get_engine", lambda: engine)
    monkeypatch.setattr("app.main.get_settings", lambda: SimpleNamespace(ENVIRONMENT="prod"))
    with TestClient(app):
        pass


def _sign_up_at_once(engine) -> list[int]:
    """회원 SIGNUPS명이 동시에 가입한다. 만든 Case 번호를 돌려준다."""

    with Session(engine) as session:
        members = [create_member(session, oauth_id=str(uuid4()), nickname="동시 가입").id for _ in range(SIGNUPS)]
        session.commit()
    start = threading.Barrier(SIGNUPS)
    case_ids, errors = [], []

    def sign_up(member_id: int) -> None:
        start.wait()
        try:
            with Session(engine) as session:
                case, _ = case_service.create_case(session, member_id, CaseCreateRequest(
                    business_type="CAFE", franchise_status=False, lease_status="LEASED_PAID",
                ))
                case_ids.append(case.id)
        except Exception as error:  # noqa: BLE001 - 가입 자체가 실패하면 그대로 드러낸다
            errors.append(error)

    threads = [threading.Thread(target=sign_up, args=(member_id,)) for member_id in members]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    return case_ids


def _documents_per_case(engine, case_ids: list[int]) -> dict[int, int]:
    with Session(engine) as session:
        return {
            case_id: session.exec(
                select(func.count()).select_from(Evidence)
                .where(Evidence.case_id == case_id, Evidence.official_document_id.is_not(None))
            ).one()
            for case_id in case_ids
        }


def test_startup_loads_the_official_documents(empty_engine, monkeypatch):
    store = reviewed_procedure.load_reviewed_procedures()

    _start_app(empty_engine, monkeypatch)

    with Session(empty_engine) as session:
        loaded = session.exec(
            select(func.count()).select_from(OfficialDocument)
            .where(OfficialDocument.source_version == store.snapshot_version)
        ).one()
    assert loaded == len({record.content_hash for record in store.records()})


def test_simultaneous_signups_on_an_empty_db_all_get_their_documents(empty_engine, monkeypatch):
    _start_app(empty_engine, monkeypatch)

    documents = _documents_per_case(empty_engine, _sign_up_at_once(empty_engine))

    # 자료 연결이 하나라도 비면 그 Case의 판단은 자료 없이 돌다 실패한다
    assert len(documents) == SIGNUPS
    assert all(documents.values()), documents
