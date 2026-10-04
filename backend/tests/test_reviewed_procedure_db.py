"""Existing BE CRUD -> isolated MySQL -> CaseSnapshot -> procedure lookup.

Requires Docker and requirements-dev.txt. Never imports the application's DB
engine or starts the API; all rows live in a disposable mysql:8.0 container.
"""

import asyncio
import hashlib
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from app.agent import runtime as runtime_module
from app.agent.procedure_tool.store import ProcedureStoreError
from app.agent.procedure_tool.stored_tool import StoredProcedureLookupTool
from app.agent.schemas import ProcedureLookupInput, ProcedureStepRef
from app.be.crud import evidence as evidence_crud
from app.be.crud.case_history import get_case_created_history
from app.be.crud.member import create_member
from app.be.models.mixins import KST
from app.be.schemas.case import CaseCreateRequest
from app.be.services.agent_runtime import build_agent_runtime
from app.be.services.case import create_case
from app.be.services.case_snapshot import build_case_created_input, build_case_snapshot
from app.common.agent_data import (
    import_reviewed_procedures,
    load_reviewed_procedure_store,
)
from sqlmodel import Session, SQLModel, create_engine
from testcontainers.community.mysql import MySqlContainer

AS_OF = date(2026, 10, 4)
RETRIEVED = datetime(2026, 10, 4, 1, 2, 3, 456789, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def mysql_engine():
    container = MySqlContainer(
        "mysql:8.0", dialect="pymysql", username="test", password="test",
        root_password="test", dbname="reviewed_procedures_test",
    ).with_env("TZ", "Asia/Seoul")
    with container:
        engine = create_engine(container.get_connection_url() + "?charset=utf8mb4")
        try:
            SQLModel.metadata.create_all(engine)
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def approved_store():
    return load_reviewed_procedure_store({
        "snapshot_version": "synthetic/1",
        "generated_at": RETRIEVED,
        "locale": "ko-KR",
        "records": [
            {
                "record_id": code,
                "title": f"합성 문서 {code}",
                "authority_name": "합성 기관",
                "canonical_url": f"https://example.org/{code.lower()}",
                "source_domain": "example.org",
                "excerpt": "합성 원문 " + "가" * 1200,
                "content_hash": "sha256:" + hashlib.sha256(code.encode()).hexdigest(),
                "published_at": RETRIEVED,
                "retrieved_at": RETRIEVED,
                "reviewed_by": "synthetic-reviewer",
                "reviewed_at": RETRIEVED,
                "review_valid_days": 90,
                "step_codes": [code],
                "required_terms": ["합성"],
                "any_terms": [],
            }
            for code in ("FILE_TAX_BUSINESS_CLOSURE", "CONFIRM_RESTORATION_SCOPE")
        ],
    })


def create_test_case(engine):
    with Session(engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
        case = create_case(session, member.id, CaseCreateRequest(
            business_type="카페", franchise_status=False, employee_count=2,
            lease_status="LEASED_PAID",
        ))
        history = get_case_created_history(session, case.id)
        history.created_at = RETRIEVED.astimezone(KST).replace(tzinfo=None, microsecond=0)
        session.commit()
        return case.id


def official_rows(session, case_id):
    return [
        row for row in evidence_crud.get_evidence_by_case_id(session, case_id)
        if row.source_type == "OFFICIAL_DOCUMENT"
    ]


def lookup_request(snapshot):
    return ProcedureLookupInput(
        lookup_goal="BUSINESS_CLOSURE", search_queries=["합성 절차"],
        as_of=AS_OF, locale="ko-KR", source_policy="OFFICIAL_ONLY",
        max_results_per_query=4, based_on_snapshot_id=snapshot.snapshot_id,
        evidence_records=snapshot.evidence_records, review_feedback=[],
    )


def test_committed_rows_reach_tool_without_new_evidence_ids(mysql_engine, approved_store):
    bindings = {
        record.step_codes[0]: ProcedureStepRef(
            procedure_step_id=index, step_code=f"SYNTHETIC_BE_STEP_{index}",
        )
        for index, record in enumerate(approved_store.records(), start=1)
    }
    case_ids = [create_test_case(mysql_engine) for _ in range(2)]
    ids_by_case = []
    for case_id in case_ids:
        with Session(mysql_engine) as session:
            imported = import_reviewed_procedures(
                session, case_id, approved_store, as_of=AS_OF
            )
            ids_by_case.append({row.evidence_id for row in imported})
            session.commit()

        # A fresh session proves these are persisted rows, not ORM identity-map data.
        with Session(mysql_engine) as session:
            rows = official_rows(session, case_id)
            records = {record.canonical_url: record for record in approved_store.records()}
            assert len(rows) == 2
            for row in rows:
                source = records[row.source_ref]
                assert row.excerpt == source.excerpt
                assert row.content_hash == source.content_hash.removeprefix("sha256:")
                assert row.source_version == approved_store.snapshot_version
                assert row.locator == source.canonical_url
                assert row.retrieved_at == RETRIEVED.astimezone(KST).replace(
                    tzinfo=None, microsecond=0
                )
            snapshot = build_case_snapshot(session, case_id)
            result = asyncio.run(StoredProcedureLookupTool(
                approved_store, procedure_bindings=bindings,
            ).lookup(lookup_request(snapshot)))
            assert result.completion_status == "COMPLETE"
            assert len(result.documents) == 2
            assert {code for document in result.documents for code in document.step_codes} == {
                ref.step_code for ref in bindings.values()
            }
            originals = {record.evidence_id: record for record in snapshot.evidence_records}
            assert {record.evidence_id for record in result.evidence_records} == ids_by_case[-1]
            for record in result.evidence_records:
                assert record.model_dump() == originals[record.evidence_id].model_dump()

            repeated = import_reviewed_procedures(
                session, case_id, approved_store, as_of=AS_OF
            )
            assert {row.evidence_id for row in repeated} == ids_by_case[-1]
            session.commit()
            assert len(official_rows(session, case_id)) == 2
    assert ids_by_case[0].isdisjoint(ids_by_case[1])


def test_new_version_preserves_old_evidence(mysql_engine, approved_store):
    case_id = create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        old_ids = {row.evidence_id for row in import_reviewed_procedures(
            session, case_id, approved_store, as_of=AS_OF
        )}
        updated = load_reviewed_procedure_store({
            "snapshot_version": "synthetic/2", "generated_at": RETRIEVED,
            "locale": "ko-KR",
            "records": [item.model_dump() for item in approved_store.records()],
        })
        new_ids = {row.evidence_id for row in import_reviewed_procedures(
            session, case_id, updated, as_of=AS_OF
        )}
        session.commit()
    with Session(mysql_engine) as session:
        assert old_ids.isdisjoint(new_ids)
        assert {row.evidence_id for row in official_rows(session, case_id)} == old_ids | new_ids


def test_same_id_changed_payload_is_rejected(mysql_engine, approved_store):
    case_id = create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        import_reviewed_procedures(session, case_id, approved_store, as_of=AS_OF)
        session.commit()
        records = [item.model_dump() for item in approved_store.records()]
        records[-1]["excerpt"] = "변조된 합성 원문"
        changed = load_reviewed_procedure_store({
            "snapshot_version": approved_store.snapshot_version,
            "generated_at": RETRIEVED, "locale": "ko-KR", "records": records,
        })
        with pytest.raises(ProcedureStoreError):
            import_reviewed_procedures(session, case_id, changed, as_of=AS_OF)
        session.rollback()
    with Session(mysql_engine) as session:
        assert {row.excerpt for row in official_rows(session, case_id)} == {
            record.excerpt for record in approved_store.records()
        }


def test_caller_rolls_back_partial_import(mysql_engine, approved_store, monkeypatch):
    case_id = create_test_case(mysql_engine)
    create = evidence_crud.create_evidence
    calls = 0

    def fail_second_insert(session, evidence):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic write failure")
        return create(session, evidence)

    monkeypatch.setattr(evidence_crud, "create_evidence", fail_second_insert)
    with Session(mysql_engine) as session:
        with pytest.raises(RuntimeError, match="synthetic write failure"):
            import_reviewed_procedures(session, case_id, approved_store, as_of=AS_OF)
        session.rollback()
    with Session(mysql_engine) as session:
        assert official_rows(session, case_id) == []


@pytest.mark.parametrize("problem", ["missing_case", "unreviewed", "long_url"])
def test_invalid_import_writes_nothing(mysql_engine, approved_store, problem):
    case_id = create_test_case(mysql_engine)
    records = [item.model_dump() for item in approved_store.records()]
    if problem == "unreviewed":
        records[-1].update(reviewed_by=None, reviewed_at=None)
    elif problem == "long_url":
        records[-1]["canonical_url"] = "https://example.org/" + "a" * 600
    store = load_reviewed_procedure_store({
        "snapshot_version": approved_store.snapshot_version,
        "generated_at": RETRIEVED, "locale": "ko-KR", "records": records,
    })
    target_id = 2**31 if problem == "missing_case" else case_id
    with Session(mysql_engine) as session:
        with pytest.raises(ProcedureStoreError):
            import_reviewed_procedures(session, target_id, store, as_of=AS_OF)
        # No rollback yet: even the valid first record must not have been inserted.
        assert official_rows(session, case_id) == []
        session.commit()
    with Session(mysql_engine) as session:
        assert official_rows(session, case_id) == []


def test_existing_be_runtime_uses_db_rows_with_empty_store(
    mysql_engine, approved_store, monkeypatch,
):
    case_id = create_test_case(mysql_engine)
    metadata_loader = Mock(return_value=approved_store)
    monkeypatch.setattr(runtime_module, "load_reviewed_procedures", metadata_loader)
    monkeypatch.setattr(runtime_module, "resolve_max_calls_per_run", lambda: 5)
    monkeypatch.setattr(runtime_module, "resolve_run_deadline_seconds", lambda: 60)
    monkeypatch.setattr(runtime_module.LangfuseTraceSink, "from_env", lambda: None)
    monkeypatch.setattr(
        runtime_module.StructuredLLMClient, "from_env",
        lambda **kwargs: Mock(aclose=AsyncMock()),
    )

    async def lookup_from_be(session):
        runtime = await build_agent_runtime(session)
        try:
            request = build_case_created_input(session, case_id)
            monkeypatch.setattr(runtime._graph, "_procedure_queries", lambda _: ["합성 절차"])
            result = await runtime._graph._procedure_node({
                "request": request, "run_id": uuid4(),
            })
            assert result["phase"] == "PROCEDURE_LOOKUP"
            output = result["source_results"][0].output
            originals = {item.evidence_id: item for item in request.case_snapshot.evidence_records}
            for record in output.evidence_records:
                assert record.model_dump() == originals[record.evidence_id].model_dump()
            return output
        finally:
            await runtime.aclose()

    with Session(mysql_engine) as session:
        missing = asyncio.run(lookup_from_be(session))
        assert missing.completion_status == "NO_RESULTS"
        assert missing.documents == []
        import_reviewed_procedures(session, case_id, approved_store, as_of=AS_OF)
        session.commit()
    with Session(mysql_engine) as session:
        found = asyncio.run(lookup_from_be(session))
        assert found.completion_status == "COMPLETE"
        assert len(found.documents) == 2
        assert all(document.step_codes == [] for document in found.documents)
        assert {item.evidence_id for item in found.evidence_records} == {
            row.evidence_id for row in official_rows(session, case_id)
        }
    assert metadata_loader.call_count == 2
