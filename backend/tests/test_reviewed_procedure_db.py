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
from sqlmodel import Session, SQLModel, create_engine, select
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
from app.agent.schemas import FactStatus
from app.agent.procedure_tool.rules import procedure_applicability
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
from app.be.crud import procedure_step as procedure_step_crud
import logging
from unittest.mock import patch
from app.agent.schemas import AgentFieldKey, FactOperation
from app.be.crud import case as case_crud
from app.be.crud import case_field_history as case_field_history_crud
from app.be.services import procedure_registry
from app.be.services.procedure_registry import (
    ProcedureRegistryMissingError,
    load_cafe_procedure_step_ids,
)

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
            # 앱이 뜰 때 하는 적재를 그대로 한다(main.lifespan). 요청 경로는 읽기만 하므로
            # 이게 없으면 Case 생성이 ProcedureRegistryMissingError로 멈춘다.
            with Session(engine) as session:
                procedure_registry.ensure_cafe_procedure_registry(session)
                session.commit()
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


def body_of(session, row):
    """근거 한 줄의 본문. 공식 자료는 Case가 아니라 공용 줄이 들고 있다."""

    return evidence_crud.get_official_document_bodies(session, [row.official_document_id])[
        row.official_document_id
    ]


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
        # 본문은 Case마다 복사되지 않는다. 공용 줄에서 읽어야 자료와 같다.
        assert {row["excerpt"] for row in baseline.values()} == {None}
        assert {body_of(session, row) for row in official_rows(session, case_id)} == {
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
                assert row.excerpt is None
                assert body_of(session, row) == source.excerpt
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
        assert {
            body_of(session, row)
            for row in official_rows(session, case_id, version=approved_store.snapshot_version)
        } == {record.excerpt for record in approved_store.records()}


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


def test_case_creation_never_loads_the_registry_itself(monkeypatch, mysql_engine):
    """적재는 앱이 뜰 때 하고, 가입 요청은 읽기만 한다.

    가입 요청 안에서 적재하면 두 사람이 동시에 가입할 때 step_code가 unique라 한쪽이
    IntegrityError로 떨어지고, 아무도 가입하지 않으면 절차 표가 빈 채로 남는다.
    적재 함수를 터지게 해두고도 가입이 끝나야 요청 경로에 적재가 없는 것이다.
    """
    def must_not_run(session):
        raise AssertionError("가입 요청이 절차 마스터 표를 적재하려 했다")

    monkeypatch.setattr(procedure_registry, "ensure_cafe_procedure_registry", must_not_run)
    case_id = create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        roadmap = procedure_step_crud.get_case_procedure_steps_by_case_id(session, case_id)
    assert len(roadmap) == len(PROCEDURE_LABELS)


def test_case_creation_stops_instead_of_building_an_empty_roadmap(monkeypatch, mysql_engine):
    """적재가 안 돈 상태에서 가입하면 멈춘다. 빈 로드맵으로 조용히 끝내지 않는다."""
    monkeypatch.setattr(
        procedure_step_crud, "get_procedure_step_by_code", lambda session, code: None
    )
    with Session(mysql_engine) as session, pytest.raises(ProcedureRegistryMissingError) as error:
        load_cafe_procedure_step_ids(session)
    # 어느 절차가 비었는지 그대로 적는다. "절차가 없다"만으로는 적재가 안 돈 것인지
    # 일부만 들어간 것인지 구분할 수 없다.
    assert "CONFIRM_RESTORATION_SCOPE" in str(error.value)


def create_case_with(engine, *, employee_count=2, **answers):
    """가입 폼에 답을 더 받은 Case 하나."""
    with Session(engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
        case, _ = create_case(session, member.id, CaseCreateRequest(
            business_type="CAFE", franchise_status=False, employee_count=employee_count,
            lease_status="LEASED_PAID", **answers,
        ))
        session.commit()
        return case.id


def applicability_of(engine, case_id):
    """이 Case에서 절차 8개가 각각 해당함/해당없음/모름 중 무엇인지."""
    with Session(engine) as session:
        snapshot = build_case_snapshot(session, case_id)
        steps = agent_runtime_service.build_known_procedure_steps(session)
    return [procedure_applicability(step, snapshot) for step in steps]


def test_insurance_answers_reach_the_agent_and_settle_two_procedures(mysql_engine):
    """4대보험 가입 이력을 받으면 보험 절차 2개가 "모름"에서 벗어난다.

    AI는 네 값에서 has_workplace_insurance를 계산한다. 넷 중 하나라도 가입이면 해당,
    넷 다 미가입이어야 해당 없음이다(rules.py:129-136). 그래서 네 칸을 같이 받아야 한다.
    """
    insured = dict(
        pension_enrolled=True, health_insurance_enrolled=True,
        employment_insurance_enrolled=True, industrial_accident_insurance_enrolled=True,
    )
    uninsured = {field: False for field in insured}

    nothing_asked = applicability_of(mysql_engine, create_case_with(mysql_engine))
    all_insured = applicability_of(mysql_engine, create_case_with(mysql_engine, **insured))
    # 직원을 둔 적 없는 1인 사장님. 지금 2명인데 과거엔 없었다고 하면 AI는 모순으로 보고
    # 판단을 멈춘다(rules.employment_history_conflicts).
    none_insured = applicability_of(
        mysql_engine,
        create_case_with(mysql_engine, employee_count=0, had_employees=False, **uninsured),
    )

    # 안 물어보면 모름 3개(원상복구 + 보험 2개)가 남는다.
    assert nothing_asked.count(None) == 3
    # 가입했다고 답하면 보험 2개가 해당함으로 바뀌고, 계약서를 봐야 아는 원상복구만 남는다.
    assert all_insured.count(None) == 1 and all_insured.count(True) == 7
    # 전부 미가입이면 보험 2개와 직원 정산이 해당 없음이 된다.
    assert none_insured.count(False) == 3


def test_an_unanswered_insurance_question_stays_unknown_instead_of_becoming_no(mysql_engine):
    """안 물어본 칸은 "아니오"가 아니라 "모름"으로 넘어간다.

    안 물어본 것을 false로 채우면 AI가 그 절차를 "해당 없음"으로 보고 로드맵에서 빼버린다.
    사장님은 해야 할 신고를 안내받지 못한다.
    """
    case_id = create_case_with(mysql_engine, pension_enrolled=True)
    with Session(mysql_engine) as session:
        facts = {fact.field_path: fact for fact in build_case_snapshot(session, case_id).facts}

    assert facts["pension_enrolled"].status == FactStatus.CONFIRMED
    assert facts["pension_enrolled"].value is True
    # 안 보낸 세 칸도 스냅샷에는 실린다. 빠지는 것과 모름은 다르다.
    assert facts["health_insurance_enrolled"].status == FactStatus.UNKNOWN
    assert facts["health_insurance_enrolled"].value is None
    # 하나만 가입으로 와도 나머지가 모름이면 보험 조건은 "해당함"이다(하나라도 가입이므로).
    assert applicability_of(mysql_engine, case_id).count(None) == 1


def test_onboarding_only_fields_are_not_written_by_an_agent_conversation(caplog):
    """AI 대화가 보낸 변경 중 가입 폼 전용 5칸은 저장하지 않는다.

    사장님이 가입할 때 직접 답한 값을, AI가 대화 중에 추정한 값으로 덮으면 안 된다
    (승준님 #132 연동 요청). 컬럼이 있느냐로 가르면 5칸도 컬럼이 생겨서 다 통과해 버린다.
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from app.be.services.decision_record import _apply_fact_changes

    def change(field_path):
        return SimpleNamespace(
            field_path=AgentFieldKey(field_path), operation=FactOperation.SET,
            proposed_value=True, source_type=SimpleNamespace(value="INFO_ANALYSIS"),
            source_evidence_refs=["ev-1"], reason_summary="합성",
        )

    case = SimpleNamespace(id=1, pension_enrolled=None, had_employees=None)
    with patch.object(case_crud, "get_case_by_id", return_value=case), \
         patch.object(case_field_history_crud, "create_case_field_history") as writer, \
         caplog.at_level(logging.WARNING):
        _apply_fact_changes(
            MagicMock(spec=Session), SimpleNamespace(id=9, case_id=1),
            [change("pension_enrolled"), change("had_employees")],
        )

    # 건너뛰되 흔적은 남는다. 조용히 버리면 왜 안 저장됐는지 아무도 모른다.
    writer.assert_not_called()
    assert case.pension_enrolled is None and case.had_employees is None
    assert len(caplog.records) == 2
