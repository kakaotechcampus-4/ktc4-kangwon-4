"""빈 DB에서 서버를 시작한 뒤 동시 가입해도 각 Case가 공식 근거를 받는지. 실제 모델은 부르지 않는다."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from testcontainers.community.mysql import MySqlContainer

import app.main as main
from app.agent.procedure_tool.stored_tool import StoredProcedureLookupTool
from app.agent.schemas import ProcedureLookupInput
from app.be.crud.member import create_member
from app.be.db import MYSQL_IMAGE, get_db
from app.be.dependencies.auth import get_current_member_id
from app.be.models.evidence import OfficialDocument
from app.be.models.mixins import KST
from app.be.services import case as case_service
from app.be.services import judgment as judgment_service
from app.be.services import official_document, reviewed_procedure
from app.be.services.case_snapshot import build_case_snapshot

AS_OF = date(2026, 11, 7)


@pytest.fixture
def empty_engine():
    with MySqlContainer(MYSQL_IMAGE, dialect="pymysql", username="test", password="test",
                        root_password="test", dbname="official_startup") as mysql:
        engine = create_engine(mysql.get_connection_url() + "?charset=utf8mb4", pool_size=10, max_overflow=0)
        SQLModel.metadata.create_all(engine)
        try:
            yield engine
        finally:
            engine.dispose()


def test_startup_commits_sources_before_eight_concurrent_signups(empty_engine, monkeypatch):
    store = reviewed_procedure.load_reviewed_procedures()
    monkeypatch.setattr(main, "get_engine", lambda: empty_engine)
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(ENVIRONMENT="prod"))
    monkeypatch.setattr(judgment_service, "get_engine", lambda: empty_engine)
    monkeypatch.setattr(case_service, "kst_now", lambda: datetime(2026, 11, 7, tzinfo=KST))

    async def skip_model(_history_id):
        pass  # 이번 검사는 가입·근거 저장만 본다. 실제 절차 조회는 아래에서 실행한다.

    monkeypatch.setattr(judgment_service, "run_judgment_in_background", skip_model)

    def db():
        with Session(empty_engine) as session:
            yield session

    def member_id(request: Request):
        return int(request.headers["Access-Token"])  # 인증 자체는 기존 JWT 검사에서 다룬다.

    monkeypatch.setattr(main.app, "dependency_overrides", {get_db: db, get_current_member_id: member_id})
    with Session(empty_engine) as session:
        members = [create_member(session, oauth_id=str(uuid4()), nickname="합성 동시 가입").id for _ in range(8)]
        session.commit()

    with TestClient(main.app) as client:
        # 원래 lifespan을 실행했고, 새 세션에서도 보이는지 확인해 commit 누락도 잡는다.
        with Session(empty_engine) as session:
            startup_ids = {row.id for row in session.exec(select(OfficialDocument)).all()}

        gate = Barrier(8, timeout=10)
        original = official_document.load_official_documents

        def read_together(session, version):
            rows = original(session, version)
            gate.wait()
            return rows

        def signup(member):
            return client.post("/cases", headers={"Access-Token": str(member)}, json={
                "business_type": "CAFE", "franchise_status": False,
                "employee_count": 0, "lease_status": "LEASED_PAID",
            })

        # 시작 시 적재에는 동기화를 걸지 않는다. 요청의 조회만 겹쳐, 다시 요청 안에서
        # 처음 적재하게 되면 1062/1213으로 일부 Case의 근거가 빠지는 경합을 재현한다(#261).
        with monkeypatch.context() as request_patch, ThreadPoolExecutor(max_workers=8) as pool:
            request_patch.setattr(official_document, "load_official_documents", read_together)
            responses = list(pool.map(signup, members))
        assert [response.status_code for response in responses] == [200] * 8
        assert len(startup_ids) == len(store.records())
        case_ids = {response.json()["id"] for response in responses}
        assert len(case_ids) == 8

    terms = " ".join(dict.fromkeys(term for record in store.records()
                                  for term in [*record.required_terms, *record.any_terms[:1]]))
    with Session(empty_engine) as session:
        documents = session.exec(select(OfficialDocument)).all()
        assert {row.id for row in documents} == startup_ids
        assert {row.excerpt for row in documents} == {record.excerpt for record in store.records()}
        for case_id in case_ids:
            snapshot = build_case_snapshot(session, case_id)
            evidence = [item for item in snapshot.evidence_records if item.source_type == "OFFICIAL_DOCUMENT"]
            assert len(evidence) == len(store.records())
            result = asyncio.run(StoredProcedureLookupTool(store).lookup(ProcedureLookupInput(
                lookup_goal="BUSINESS_CLOSURE", search_queries=[terms], as_of=AS_OF, locale="ko-KR",
                source_policy="OFFICIAL_ONLY", max_results_per_query=10,
                based_on_snapshot_id=snapshot.snapshot_id, evidence_records=snapshot.evidence_records, review_feedback=[],
            )))
            assert result.completion_status == "COMPLETE" and len(result.documents) == len(store.records())

    # 재시작이 같은 버전 본문을 덮어쓰거나 중복 생성하지 않는다.
    with TestClient(main.app), Session(empty_engine) as session:
        assert {row.id for row in session.exec(select(OfficialDocument)).all()} == startup_ids
