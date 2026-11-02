"""Existing BE CRUD -> isolated MySQL -> CaseSnapshot -> procedure lookup.

Requires Docker and requirements-dev.txt. Never imports the application's DB
engine or starts the API; all rows live in a disposable mysql:8.0 container.
"""

import asyncio
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine
from testcontainers.community.mysql import MySqlContainer

from app.agent import runtime as runtime_module
from app.agent.action_catalog import PROCEDURE_LABELS
from app.agent.procedure_tool.store import ProcedureStoreError
from app.agent.procedure_tool.stored_tool import StoredProcedureLookupTool
from app.agent.schemas import ProcedureLookupInput, ProcedureStepRef, RedactedInput
from app.be.crud import evidence as evidence_crud
from app.be.crud.case_history import get_case_created_history
from app.be.crud.member import create_member
from app.agent.procedure_tool.cafe import build_cafe_procedure_steps
from app.be.crud.procedure_step import (
    get_all_procedure_steps,
    get_all_step_dependencies,
    get_all_step_eligibilities,
    get_case_procedure_steps_by_case_id,
)
from app.be.services import agent_runtime as agent_runtime_service
from app.be.models.mixins import KST
from app.be.schemas.case import CaseCreateRequest
from app.be.services import case as case_service
from app.be.services.agent_runtime import empty_support_catalog
from app.be.services.case import create_case
from app.be.services.case_snapshot import build_case_snapshot
from app.be.services.reviewed_procedure import (
    import_reviewed_procedures,
    load_reviewed_procedures,
)
from app.common.agent_data import (
    InMemoryReviewedProcedureStore,
    build_known_procedure_steps,
    load_reviewed_procedure_store,
)
from app.common.agent_service import build_planning_input

AS_OF = date(2026, 10, 4)
RETRIEVED = datetime(2026, 10, 4, 1, 2, 3, 456789, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def case_creation_clock(monkeypatch):
    # Keep automatic approval freshness stable without replacing create_case.
    monkeypatch.setattr(case_service, "kst_now", lambda: RETRIEVED.astimezone(KST))


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
        case, _ = create_case(session, member.id, CaseCreateRequest(
            business_type="CAFE", franchise_status=False, employee_count=2,
            lease_status="LEASED_PAID",
        ))
        history = get_case_created_history(session, case.id)
        history.created_at = RETRIEVED.astimezone(KST).replace(tzinfo=None, microsecond=0)
        session.commit()
        return case.id


def official_rows(session, case_id, *, version=None):
    return [
        row for row in evidence_crud.get_evidence_by_case_id(session, case_id)
        if row.source_type == "OFFICIAL_DOCUMENT"
        and (version is None or row.source_version == version)
    ]


def official_payloads(session, case_id):
    return {row.evidence_id: row.model_dump() for row in official_rows(session, case_id)}


def lookup_request(snapshot):
    return ProcedureLookupInput(
        lookup_goal="BUSINESS_CLOSURE", search_queries=["합성 절차"],
        as_of=AS_OF, locale="ko-KR", source_policy="OFFICIAL_ONLY",
        max_results_per_query=4, based_on_snapshot_id=snapshot.snapshot_id,
        evidence_records=snapshot.evidence_records, review_feedback=[],
    )


def test_case_creation_imports_four_approved_documents_and_reuses_their_ids(mysql_engine):
    store = load_reviewed_procedures()
    case_id = create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        baseline = official_payloads(session, case_id)
        assert len(baseline) == len(store.records()) == 4
        assert {row["source_version"] for row in baseline.values()} == {store.snapshot_version}
        assert {row["excerpt"] for row in baseline.values()} == {
            record.excerpt for record in store.records()
        }
        repeated = import_reviewed_procedures(session, case_id, store, as_of=AS_OF)
        assert {row.evidence_id for row in repeated} == set(baseline)
        session.commit()
    with Session(mysql_engine) as session:
        assert official_payloads(session, case_id) == baseline
        snapshot = build_case_snapshot(session, case_id)
        request = lookup_request(snapshot)
        request.search_queries = [
            " ".join([*item.required_terms, *item.any_terms[:1]]) for item in store.records()
        ]
        result = asyncio.run(StoredProcedureLookupTool(store).lookup(request))
        assert result.completion_status == "COMPLETE"
        assert len(result.documents) == 4
        assert {item.evidence_id for item in result.evidence_records} == set(baseline)
        # 로드맵에는 카페 폐업 절차 8개가 모두 올라가고, 검수 문서는 그중 일부만 가리킨다.
        # 문서가 가리키는 절차가 로드맵에 없으면 조회 결과를 절차에 맺을 수 없다.
        roadmap = {item.procedure_step.step_code for item in snapshot.procedure_progress}
        assert roadmap == set(PROCEDURE_LABELS)
        assert {code for record in store.records() for code in record.step_codes} <= roadmap


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
            rows = official_rows(session, case_id, version=approved_store.snapshot_version)
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
            assert len(official_rows(
                session, case_id, version=approved_store.snapshot_version,
            )) == 2
    assert ids_by_case[0].isdisjoint(ids_by_case[1])


def test_new_version_preserves_old_evidence(mysql_engine, approved_store):
    case_id = create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        baseline = official_payloads(session, case_id)
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
        actual = official_payloads(session, case_id)
        assert set(actual) == set(baseline) | old_ids | new_ids
        assert {key: actual[key] for key in baseline} == baseline


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
        assert {row.excerpt for row in official_rows(
            session, case_id, version=approved_store.snapshot_version,
        )} == {
            record.excerpt for record in approved_store.records()
        }


def test_caller_rolls_back_partial_import(mysql_engine, approved_store, monkeypatch):
    case_id = create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        baseline = official_payloads(session, case_id)
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
        assert official_payloads(session, case_id) == baseline


@pytest.mark.parametrize("problem", ["missing_case", "unreviewed", "long_url"])
def test_invalid_import_writes_nothing(mysql_engine, approved_store, problem):
    case_id = create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        baseline = official_payloads(session, case_id)
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
        assert official_payloads(session, case_id) == baseline
        session.commit()
    with Session(mysql_engine) as session:
        assert official_payloads(session, case_id) == baseline


def test_runtime_keeps_empty_store_without_reading_procedure_file(
    mysql_engine, approved_store, monkeypatch,
):
    case_id = create_test_case(mysql_engine)
    file_reader = Mock(side_effect=AssertionError("Runtime must not read procedure files"))
    monkeypatch.setattr(Path, "read_text", file_reader)
    monkeypatch.setattr(runtime_module, "resolve_max_calls_per_run", lambda: 5)
    monkeypatch.setattr(runtime_module, "resolve_run_deadline_seconds", lambda: 60)
    monkeypatch.setattr(runtime_module.LangfuseTraceSink, "from_env", lambda: None)
    monkeypatch.setattr(
        runtime_module.StructuredLLMClient, "from_env",
        lambda **kwargs: Mock(aclose=AsyncMock()),
    )

    async def lookup_from_be(session):
        runtime = await runtime_module.build_runtime(
            known_procedure_steps=build_known_procedure_steps(
                get_all_procedure_steps(session), [], [], db_timezone=KST,
            ),
            support_catalog=empty_support_catalog(),
            procedure_store=InMemoryReviewedProcedureStore("synthetic/empty", ()),
        )
        try:
            history = get_case_created_history(session, case_id)
            request = build_planning_input(
                trigger_type="CASE_CREATED",
                case_snapshot=build_case_snapshot(session, case_id),
                user_input=RedactedInput(
                    input_event_id=f"case_history:{history.id}",
                    source_type="USER_INPUT", redacted_text=history.raw_input,
                    redactions=[], submitted_at=history.created_at.replace(tzinfo=KST),
                ),
            )
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
        assert len(official_rows(
            session, case_id, version=approved_store.snapshot_version,
        )) == 2
        missing_metadata = asyncio.run(lookup_from_be(session))
        assert missing_metadata.completion_status == "NO_RESULTS"
        assert missing_metadata.documents == []
        assert missing_metadata.evidence_records == []
    file_reader.assert_not_called()


def test_cli_reimport_and_new_source_version_preserve_existing_evidence(
    mysql_engine, monkeypatch, tmp_path,
):
    from scripts import import_reviewed_procedures as import_cli

    case_id = create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        baseline = official_payloads(session, case_id)
    # The CLI's database import resolves only to this disposable test engine.
    database = ModuleType("app.be.db")
    database.get_engine = lambda: mysql_engine
    monkeypatch.setitem(sys.modules, "app.be.db", database)
    monkeypatch.setattr(import_cli, "datetime", Mock(now=lambda tz: RETRIEVED.astimezone(tz)))
    command = ["import_reviewed_procedures", "--case-id", str(case_id)]
    monkeypatch.setattr(sys, "argv", command)
    import_cli.main()
    with Session(mysql_engine) as session:
        assert official_payloads(session, case_id) == baseline

    source = {
        "snapshot_version": "synthetic/cli-next",
        "generated_at": RETRIEVED.isoformat(),
        "locale": "ko-KR",
        "records": [record.model_dump(mode="json") for record in load_reviewed_procedures().records()],
    }
    source_path = tmp_path / "new-version.json"
    source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [*command, "--source", str(source_path)])
    import_cli.main()
    with Session(mysql_engine) as session:
        updated = official_payloads(session, case_id)
        assert len(updated) == 8
        assert {key: updated[key] for key in baseline} == baseline
        new_ids = set(updated) - set(baseline)
        assert {updated[key]["source_version"] for key in new_ids} == {source["snapshot_version"]}
    import_cli.main()
    with Session(mysql_engine) as session:
        assert official_payloads(session, case_id) == updated
        snapshot = build_case_snapshot(session, case_id)
        request = lookup_request(snapshot)
        store = load_reviewed_procedure_store(source)
        request.search_queries = [
            " ".join([*item.required_terms, *item.any_terms[:1]]) for item in store.records()
        ]
        result = asyncio.run(StoredProcedureLookupTool(store).lookup(request))
        assert result.completion_status == "COMPLETE"
        assert len(result.documents) == 4
        assert {item.evidence_id for item in result.evidence_records} == new_ids


def test_case_creation_puts_all_eight_cafe_procedures_on_the_roadmap(mysql_engine):
    case_id = create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        steps = {step.id: step for step in get_all_procedure_steps(session)}
        assert {step.step_code for step in steps.values()} == set(PROCEDURE_LABELS)
        roadmap = get_case_procedure_steps_by_case_id(session, case_id)
        assert {steps[row.procedure_step_id].step_code for row in roadmap} == set(PROCEDURE_LABELS)


def test_stored_registry_round_trips_to_what_the_agent_expects(mysql_engine):
    """DB에 넣었다 꺼낸 절차 목록이 AI팀 정의와 글자 하나까지 같아야 한다.

    AI는 cafe.py가 아니라 이 표를 읽는다. 적재하면서 별칭·의존·조건 하나라도 흘리면
    절차가 조용히 빠지거나 조건이 안 걸린 채로 판단이 돌아간다.
    """
    create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        stored = {
            step.procedure_step.step_code: step
            for step in agent_runtime_service.build_known_procedure_steps(session)
        }
        step_ids = {code: step.procedure_step.procedure_step_id for code, step in stored.items()}
        assert stored == {
            step.procedure_step.step_code: step
            for step in build_cafe_procedure_steps(step_ids)
        }


def test_a_second_case_reuses_the_registry_instead_of_stacking_it(mysql_engine):
    """절차는 Case마다 새로 만드는 것이 아니라 한 벌을 함께 쓴다.

    의존·조건은 절차에 딸린 별도 표라, 다시 적재하면 같은 줄이 한 벌 더 쌓인다.
    그러면 AI가 받는 절차 하나에 같은 조건이 두 번 달린다.
    """
    create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        before = (
            len(get_all_procedure_steps(session)),
            len(get_all_step_dependencies(session)),
            len(get_all_step_eligibilities(session)),
        )
    create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        after = (
            len(get_all_procedure_steps(session)),
            len(get_all_step_dependencies(session)),
            len(get_all_step_eligibilities(session)),
        )
    assert before == after
