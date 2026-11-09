"""사장님이 고른 충돌 결정이 AI를 거쳐 Case에 반영되는지.

충돌이 나면 Case가 잠긴다 — 확인 대기 중인 충돌이 있는 동안은 새 제출이 거부되는데, 충돌을
닫는 코드가 없으면 영영 안 풀린다. 그래서 "무엇을 언제 닫느냐"가 이 흐름의 핵심이다.

실제 모델은 부르지 않는다. AI 응답은 테스트가 정해서 넣는다.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session

from app.be.db import MYSQL_IMAGE
from app.be.crud import case_history as case_history_crud
from app.be.crud import conflict_reference as conflict_reference_crud
from app.be.services import agent_runtime as agent_runtime_service
from app.be.services import case_snapshot as case_snapshot_service
from app.be.services import conflict_decision
from app.be.services import decision_record as decision_record_service
from app.be.services import procedure_registry
from app.be.services import reviewed_procedure as reviewed_procedure_service

from uuid import UUID, uuid4

from sqlmodel import SQLModel, create_engine, select
from testcontainers.community.mysql import MySqlContainer

from app.be.crud.member import create_member
from app.be.schemas.case import CaseCreateRequest
from app.be.services.case import create_case
from app.agent.schemas import RetainedInfoResult, SafeFailureOutcome, canonical_digest
from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import ConflictReference
from app.be.routers import case as case_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

HISTORY_ID = 9
SNAPSHOT_ID = "11111111-1111-1111-1111-111111111111"


def conflict_row(reference_id: int, conflict_ref: str):
    """보관해 둔 충돌 한 줄. candidate_payload에 AI에 돌려줄 원본이 들어 있다."""
    return SimpleNamespace(
        id=reference_id, conflict_ref=conflict_ref, case_history_id=1,
        candidate_payload={"conflict_ref": conflict_ref}, status="PENDING", decided_at=None,
    )


@pytest.fixture
def flow(monkeypatch):
    """충돌 하나가 보관된 Case에서 결정을 넣고, 무엇이 저장됐는지 돌려준다."""

    def run(outcome_type, choices, *, rows=None, stored_snapshot=SNAPSHOT_ID, retained=None):
        rows = rows if rows is not None else [conflict_row(1, "cr_1")]
        captured = {}

        async def fake_run_case_planning(request, **_kwargs):
            captured["request"] = request
            return SimpleNamespace(outcome_type=outcome_type)

        monkeypatch.setattr(
            case_history_crud, "get_case_history_by_id",
            lambda _s, history_id: SimpleNamespace(
                id=HISTORY_ID, case_id=1,
                created_at=SimpleNamespace(replace=lambda **_: "CONFIRMED_AT"),
                conflict_snapshot={"snapshot_id": stored_snapshot},
                retained_info_result=retained,
            ),
        )
        monkeypatch.setattr(
            conflict_reference_crud, "get_pending_conflicts_by_case_id", lambda *_a: list(rows)
        )
        monkeypatch.setattr(
            conflict_decision, "ConflictCandidate",
            SimpleNamespace(model_validate=lambda payload: SimpleNamespace(**payload)),
        )
        monkeypatch.setattr(
            conflict_decision, "CaseSnapshot",
            SimpleNamespace(model_validate=lambda payload: SimpleNamespace(**payload, model_dump=lambda **_: payload)),
        )
        monkeypatch.setattr(
            conflict_decision, "RetainedInfoResult",
            SimpleNamespace(model_validate=lambda payload: SimpleNamespace(**payload)),
        )
        monkeypatch.setattr(
            conflict_decision, "build_conflict_input",
            lambda **kwargs: SimpleNamespace(**kwargs),
        )
        monkeypatch.setattr(conflict_decision, "run_case_planning", fake_run_case_planning)
        monkeypatch.setattr(
            case_snapshot_service, "build_case_snapshot",
            lambda _s, _c, *, snapshot_id=None, **_: SimpleNamespace(
                snapshot_id=snapshot_id, model_dump=lambda **_: {"snapshot_id": snapshot_id}),
        )
        monkeypatch.setattr(agent_runtime_service, "build_known_procedure_steps", lambda *_a: [])
        monkeypatch.setattr(agent_runtime_service, "empty_support_catalog", lambda: None)
        monkeypatch.setattr(reviewed_procedure_service, "load_reviewed_procedures", lambda: None)
        for name in ("save_conflict", "save_safe_failure", "save_reviewed_plan"):
            captured[name] = []
            monkeypatch.setattr(
                decision_record_service, name,
                lambda *_a, _name=name, **kw: captured[_name].append(kw) or None,
            )

        asyncio.run(conflict_decision.run_conflict_decision(
            MagicMock(spec=Session), HISTORY_ID, choices,
        ))
        return captured

    return run


def test_a_finished_judgment_saves_the_choice_and_closes_the_conflict(flow):
    """DONE이면 고른 값 저장과 충돌 닫기가 같이 간다."""
    captured = flow("REVIEWED_PLAN", {1: "PROPOSED"})

    assert captured["save_reviewed_plan"] == [{"resolved_conflicts": {1: "PROPOSED"}}]
    assert captured["save_safe_failure"] == [] and captured["save_conflict"] == []


def test_more_questions_still_save_the_choice(flow):
    """또 물어볼 것이 생겨도 고른 값은 저장한다.

    안 그러면 사장님이 답을 했는데 Case가 그대로라, 다음 판단이 같은 질문을 또 한다.
    NEEDS_MORE_INFO도 검수를 통과한 판단이라 REVIEWED_PLAN으로 온다.
    """
    captured = flow("REVIEWED_PLAN", {1: "STORED"})

    assert captured["save_reviewed_plan"] == [{"resolved_conflicts": {1: "STORED"}}]


def test_a_failed_judgment_leaves_the_conflict_open(flow):
    """실패하면 아무것도 반영하지 않는다. 충돌이 남아야 다시 결정할 수 있다."""
    captured = flow("SAFE_FAILURE", {1: "PROPOSED"})

    assert captured["save_safe_failure"] == [{}]
    assert captured["save_reviewed_plan"] == [] and captured["save_conflict"] == []


def test_a_new_conflict_still_closes_the_one_just_decided(flow):
    """재판단에서 또 충돌이 나와도 방금 고른 것은 닫는다.

    안 닫으면 다음 확인 화면이 이미 답한 충돌을 다시 묻고, 그 Case는 영영 안 풀린다.
    """
    captured = flow("CONFLICT", {1: "PROPOSED"})

    assert captured["save_conflict"] == [{"resolved_conflicts": {1: "PROPOSED"}}]
    assert captured["save_reviewed_plan"] == []


def test_the_stored_snapshot_id_is_reused_instead_of_a_new_one(flow):
    """확인 요청은 보관한 번호를 그대로 써야 한다.

    새로 찍으면 AI가 "내가 준 충돌이 아니다"로 보고 STALE_CONFLICT_CONFIRMATION으로 거절해서,
    값이 하나도 안 바뀌었어도 모든 결정이 실패한다.
    """
    captured = flow("REVIEWED_PLAN", {1: "PROPOSED"})

    assert captured["request"].case_snapshot.snapshot_id == SNAPSHOT_ID
    assert captured["request"].conflict_snapshot.snapshot_id == SNAPSHOT_ID


def test_every_stored_conflict_needs_a_choice(flow):
    """하나라도 안 고르면 AI를 부르지 않는다. AI는 빠진 선택을 입력 검사에서 거절한다."""
    rows = [conflict_row(1, "cr_1"), conflict_row(2, "cr_2")]

    with pytest.raises(conflict_decision.ConflictDecisionInputError, match="결정하지 않은"):
        flow("REVIEWED_PLAN", {1: "PROPOSED"}, rows=rows)


def test_a_choice_becomes_an_agent_selection(flow):
    """화면이 보낸 DB 번호를 AI 식별자로 바꿔 넘긴다. '새 값'만 채택이다."""
    rows = [conflict_row(1, "cr_1"), conflict_row(2, "cr_2")]
    captured = flow("REVIEWED_PLAN", {1: "PROPOSED", 2: "STORED"}, rows=rows)

    assert [(item.conflict_ref, item.accepted) for item in captured["request"].selections] == [
        ("cr_1", True), ("cr_2", False)
    ]


def test_closing_keeps_which_side_the_owner_picked(monkeypatch):
    """닫을 때 고른 쪽을 그대로 남긴다. 새 값은 채택, 기존 값 유지는 거절이다.

    나중에 "이 Case가 무엇을 보고 그 값이 됐나"를 되짚을 때 이 값이 유일한 기록이다.
    둘 다 CONFIRMED로 적으면 사장님이 바꾸지 않기로 한 것까지 바꾼 것처럼 남는다.
    """
    rows = {1: conflict_row(1, "cr_1"), 2: conflict_row(2, "cr_2")}
    monkeypatch.setattr(
        decision_record_service.conflict_reference_crud, "get_conflict_reference_by_id",
        lambda _s, reference_id: rows[reference_id],
    )

    decision_record_service._resolve_conflicts(
        MagicMock(spec=Session), SimpleNamespace(id=9), {1: "PROPOSED", 2: "STORED"}
    )

    assert (rows[1].status, rows[2].status) == ("CONFIRMED", "REJECTED")
    assert rows[1].decided_at is not None and rows[2].decided_at is not None
    # 어느 결정이 닫았는지 남겨야 그 값의 가림 문구를 되돌릴 수 있다(services.unmasking).
    assert (rows[1].resolved_by_case_history_id, rows[2].resolved_by_case_history_id) == (9, 9)


def test_closing_nothing_is_allowed(monkeypatch):
    """가입·결과 제출 판단은 닫을 충돌이 없다. 같은 저장 함수를 쓰므로 빈 값이 정상이다."""

    decision_record_service._resolve_conflicts(MagicMock(spec=Session), SimpleNamespace(id=9), None)
    decision_record_service._resolve_conflicts(MagicMock(spec=Session), SimpleNamespace(id=9), {})


def test_the_stored_snapshot_survives_a_round_trip_through_mysql(mysql_engine):
    """보관한 Case 상태가 DB를 거쳐도 한 글자도 안 바뀌어야 한다.

    사장님이 고른 뒤 AI에 그대로 돌려주는데, AI는 받은 것이 자기가 준 것과 같은지 대조하고
    다르면 STALE_CONFLICT_CONFIRMATION으로 거절한다. JSON으로 적었다 읽으면서 시각이나
    UUID가 모양만 바뀌어도 그 Case의 결정은 전부 실패한다.
    """
    from datetime import datetime, timezone
    from uuid import UUID
    from app.agent.schemas import CaseSnapshot
    from app.be.models.case_history import CaseHistory

    moment = datetime(2026, 1, 1, 12, 30, 45, 123456, tzinfo=timezone.utc)
    original = CaseSnapshot.model_validate({
        "snapshot_id": UUID(int=7), "case_id": 1, "case_status": "IN_PROGRESS",
        "facts": [
            {"field_path": field, "value_type": kind, "value": value,
             "status": "CONFIRMED", "evidence_refs": ["ev-1"], "updated_at": moment}
            for field, kind, value in (
                ("business_type", "STRING", "카페"),
                ("franchise_status", "BOOLEAN", False),
                ("lease_status", "ENUM", "LEASED_PAID"),
            )
        ],
        "procedure_progress": [],
        "evidence_records": [{
            "evidence_id": "ev-1", "source_type": "USER_INPUT", "source_ref": "case_history:1",
            "source_version": None, "locator": None, "excerpt": "전체 철거래요",
            "parent_evidence_refs": [], "published_at": None, "retrieved_at": moment,
            "freshness_status": "CURRENT", "content_hash": "0" * 64,
        }],
        "captured_at": moment,
    })

    with Session(mysql_engine) as session:
        case_id = new_case_id(session)
        history = CaseHistory(
            case_id=case_id, raw_input="전체 철거래요", source="USER_INPUT",
            judgment_status="PENDING",
        )
        session.add(history)
        session.commit()
        history_id = history.id
        # 실제 저장 경로를 그대로 탄다. 여기서 모양을 잘못 적으면 DB가 받아주지 않거나
        # 받아줘도 읽을 때 달라진다.
        decision_record_service.save_conflict(
            session, history,
            SimpleNamespace(
                evidence_records=[], conflicts=[], conflict_snapshot=original,
                retained_info_result=None,
            ),
        )

    # 다른 세션으로 읽어야 ORM이 들고 있던 객체가 아니라 진짜 DB 값을 본다.
    with Session(mysql_engine) as session:
        stored = session.get(CaseHistory, history_id)
        restored = CaseSnapshot.model_validate(stored.conflict_snapshot)

    assert restored == original




def reviewed_plan_setting_employee_count():
    """employee_count를 2로 바꾸는 검수 통과 판단 하나. 실제 모델은 부르지 않는다."""
    import hashlib
    from app.agent.review_tool import ReviewTool
    from app.agent.schemas import FactCandidate, ReviewProof, ReviewSubject, ReviewedPlanOutcome
    from app.agent.supervisor.agent import SupervisorAgent
    from test_action_codes import NOW, StubModel, evidence, source, supervisor_request

    async def build():
        request = supervisor_request()
        text = "직원은 2명입니다."
        request.trigger.input.redacted_text = text
        user_evidence = evidence(
            evidence_id="synthetic-staff-report", source_type="USER_INPUT",
            source_ref=request.trigger.input.input_event_id, excerpt=text,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        info = request.source_results[1].output.model_copy(deep=True)
        info.evidence_records = [user_evidence]
        info.fact_candidates = [FactCandidate(
            candidate_id=UUID(int=100), operation="SET", field_path="employee_count",
            value_type="INTEGER", value=2,
            source_span={"input_event_id": request.trigger.input.input_event_id,
                         "text": text, "start_offset": 0, "end_offset": len(text)},
            source_evidence_refs=[user_evidence.evidence_id], confidence_bps=9500,
            requires_confirmation=False, reason_summary="합성 직원 보고",
        )]
        request.source_results[1] = source(info)
        draft = await SupervisorAgent(StubModel(), max_local_attempts=1).draft(request)
        subject = ReviewSubject.create(
            schema_version="agent-io/2.0", review_subject_id=UUID(int=90), review_attempt=1,
            run_id=UUID(int=2), case_id=1, trigger=request.trigger, snapshot=request.case_snapshot,
            known_procedure_steps=request.known_procedure_steps,
            source_results=request.source_results, supervisor_draft=draft,
        )
        result = await ReviewTool(StubModel(), max_output_attempts=1).review(subject)
        meta = request.source_results[1].meta.model_copy(
            update={"component": "REVIEW_TOOL", "call_id": UUID(int=91)},
        )
        return ReviewedPlanOutcome(
            outcome_type="REVIEWED_PLAN", review_subject=subject,
            review_proof=ReviewProof.from_passed_review(
                subject=subject, result=result, review_meta=meta, reviewed_at=NOW,
            ),
        )

    return asyncio.run(build())


def reviewed_scope_change(case_id, *, before="PARTIAL", after="FULL", accepted=True, detail="카운터", include_detail=True):
    """실제 충돌 overlay와 검수를 거친 합성 판단. 모델 호출은 없다."""
    from app.agent.enrichment import build_conflict_overlays
    from app.agent.review_tool import ReviewTool
    from app.agent.schemas import (
        CaseFact, ConflictCandidate, ConflictConfirmedTrigger, ReviewProof,
        ReviewSubject, ReviewedPlanOutcome, canonical_digest,
    )
    from app.agent.supervisor.agent import SupervisorAgent
    from test_action_codes import NOW, REF, StubModel, evidence, source as invocation, supervisor_request

    async def build():
        request = supervisor_request()
        data = json.loads(request.model_dump_json().replace(f'"{REF}"', f'"{REF}:{case_id}"'))
        for original, source in zip(request.source_results, data["source_results"]):
            if source["meta"]["component"] == "INFO_AGENT":
                source["output"]["based_on_procedure_lookup_digest"] = data["source_results"][0]["output_digest"]
            source["output_digest"] = canonical_digest(type(original.output).model_validate(source["output"]))
        request = type(request).model_validate(data)
        request.case_snapshot.case_id = case_id
        for source in request.source_results:
            source.meta.case_id = case_id
        reported = evidence(evidence_id=f"scope-report:{case_id}", source_type="USER_INPUT",
                            source_ref=f"synthetic-scope-input:{case_id}", excerpt="원상복구는 전부입니다.")
        request.case_snapshot.evidence_records.append(reported)
        info = request.source_results[1].output.model_copy(deep=True)
        info.evidence_records.append(reported)
        request.source_results[1] = invocation(info)
        request.source_results[1].meta.case_id = case_id
        facts = [("restoration_scope", "ENUM", before)]
        if include_detail:
            facts.append(("restoration_scope_detail", "STRING", detail))
        for field, kind, value in facts:
            request.case_snapshot.facts.append(CaseFact(
                field_path=field, value_type=kind, value=value, status="CONFIRMED" if value is not None else "UNKNOWN",
                evidence_refs=[f"{REF}:{case_id}"] if value is not None else [], updated_at=NOW if value is not None else None,
            ))
        conflict = ConflictCandidate.create(
            conflict_ref=f"scope:{case_id}", candidate_id=uuid4(), snapshot_id=request.case_snapshot.snapshot_id,
            field_path="restoration_scope", committed_status="CONFIRMED", committed_value=before,
            proposed_operation="SET", proposed_status="CONFIRMED", proposed_value=after,
            source_evidence_refs=[reported.evidence_id], source_call_id=request.source_results[1].meta.call_id,
        )
        request.trigger = ConflictConfirmedTrigger(
            trigger_type="CONFLICT_CONFIRMED", input_event_id=f"scope-choice:{case_id}",
            client_event_id=None, conflicts=[conflict], conflict_snapshot=request.case_snapshot.model_copy(deep=True),
            selections=[{"conflict_ref": conflict.conflict_ref, "accepted": accepted}], confirmed_at=NOW,
        )
        request.fact_overlays = build_conflict_overlays(request.case_snapshot, request.trigger)
        draft = await SupervisorAgent(StubModel(), max_local_attempts=1).draft(request)
        subject = ReviewSubject.create(
            schema_version="agent-io/2.0", review_subject_id=uuid4(), review_attempt=1,
            run_id=request.source_results[0].meta.run_id, case_id=case_id, trigger=request.trigger,
            snapshot=request.case_snapshot, known_procedure_steps=request.known_procedure_steps,
            source_results=request.source_results, supervisor_draft=draft,
        )
        result = await ReviewTool(StubModel(), max_output_attempts=1).review(subject)
        meta = request.source_results[0].meta.model_copy(update={"component": "REVIEW_TOOL", "call_id": uuid4()})
        return ReviewedPlanOutcome(outcome_type="REVIEWED_PLAN", review_subject=subject,
            review_proof=ReviewProof.from_passed_review(subject=subject, result=result, review_meta=meta, reviewed_at=NOW))
    return asyncio.run(build())


def scope_case(engine, before="PARTIAL", detail="카운터"):
    from app.be.models.case import Case
    from app.be.models.case_field_history import CaseFieldHistory
    from app.be.models.case_history import CaseHistory
    from app.be.models.evidence import ConflictReference

    with Session(engine) as session:
        case_id = new_case_id(session)
        case = session.get(Case, case_id)
        case.restoration_scope, case.restoration_scope_detail = before, detail
        origin = CaseHistory(case_id=case_id, source="USER_INPUT", raw_input="원상복구는 전부입니다.", judgment_status="CONFLICT")
        session.add(origin)
        session.flush()
        creation = case_history_crud.get_case_created_history(session, case_id)
        seed = CaseFieldHistory(case_id=case_id, case_history_id=origin.id, canonical_field="restoration_scope_detail",
            before_value=None, after_value=detail, source="INFO_ANALYSIS",
            source_evidence_refs=[f"case_{case_id}_history_{creation.id}"])
        conflict = ConflictReference(conflict_ref=f"scope:{case_id}", case_id=case_id, case_history_id=origin.id,
            canonical_field="restoration_scope", committed_value=before, proposed_value="FULL", candidate_payload={})
        history = CaseHistory(case_id=case_id, source="CONFLICT_DECISION", judgment_status="PENDING")
        session.add_all([seed, conflict, history])
        session.commit()
        return case_id, history.id, conflict.id, seed.id


def stale_failure_case(engine):
    from test_action_codes import supervisor_request

    case_id, history_id, conflict_id, _ = scope_case(engine)
    request = supervisor_request()
    subject = reviewed_scope_change(case_id).review_subject
    source = next(row for row in subject.source_results if row.meta.component == "INFO_AGENT")
    info = source.output.model_copy(update={key: [] for key in (
        "fact_candidates", "conflicts", "procedure_findings", "missing_fields", "question_candidates", "uncertainties")})
    retained = RetainedInfoResult(meta=source.meta, output=info, output_digest=canonical_digest(info),
        input=request.trigger.input)
    trigger = subject.trigger.model_copy(update={
        "input_event_id": str(history_id), "retained_info_result": retained,
    })
    with Session(engine) as session:
        row = session.get(ConflictReference, conflict_id)
        row.candidate_payload = trigger.conflicts[0].model_dump(mode="json")
        row.conflict_digest = trigger.conflicts[0].conflict_digest
        origin = session.get(CaseHistory, row.case_history_id)
        origin.conflict_snapshot = trigger.conflict_snapshot.model_dump(mode="json")
        origin.retained_info_result = retained.model_dump(mode="json")
        session.commit()
    outcome = SafeFailureOutcome(outcome_type="SAFE_FAILURE", run_id=uuid4(), case_id=case_id,
        trigger=trigger, snapshot_id=trigger.conflict_snapshot.snapshot_id,
        failure_code="STALE_CONFLICT_CONFIRMATION", message_code="STALE_CONFLICT_CONFIRMATION",
        recovery_action_code="RESUBMIT_INPUT", requested_field_paths=[], retryable=False,
        failed_component=None, trace_id=None)
    return case_id, history_id, conflict_id, outcome


@pytest.mark.parametrize("side", ["PROPOSED", "STORED"])
def test_stale_failure_keeps_original_data_and_opens_new_text(mysql_engine, monkeypatch, side):
    case_id, history_id, conflict_id, outcome = stale_failure_case(mysql_engine)
    with Session(mysql_engine) as session:
        case = session.get(Case, case_id)
        member_id, original_case = case.member_id, case.model_dump()
        original_progress = [row.model_dump() for row in case.case_procedure_steps]
        conflict = session.get(ConflictReference, conflict_id)
        origin_id = conflict.case_history_id
        original_origin = session.get(CaseHistory, origin_id).model_dump()
        original_payload = conflict.candidate_payload
        conflict_decision._save_decision_outcome(session, history_id, outcome, {conflict_id: side})
    app = FastAPI()
    app.include_router(case_router.router)
    def database():
        with Session(mysql_engine) as session:
            yield session
    app.dependency_overrides[case_router.get_db] = database
    app.dependency_overrides[case_router.get_current_member_id] = lambda: member_id
    monkeypatch.setattr(case_router.judgment_service, "run_judgment_in_background", AsyncMock())
    with TestClient(app) as client:
        assert client.get("/cases").json()["judgment_status"] == "FAILED"
        entry = client.get("/cases/results").json()
        assert (entry["judgment_status"], entry["recovery_action_code"], entry["case_history_id"]) == (
            "FAILED", "RESUBMIT_INPUT", history_id)
        status = client.get("/cases/results/status", params={"case_history_id": history_id}).json()
        assert status["result"] == "FAILED" and status["retryable"] is False
        assert any(row["event"] == "JUDGMENT_FAILED" for row in client.get("/cases/logs").json()["logs"])
        response = client.post("/cases/results", json={"case_history_id": history_id, "raw_input": "현재 상황을 다시 알려드려요."})
        assert response.status_code == 200
    with Session(mysql_engine) as session:
        saved = session.get(ConflictReference, conflict_id)
        assert (saved.status, saved.resolved_by_case_history_id) == ("REJECTED", history_id)
        assert saved.decided_at is not None and saved.candidate_payload == original_payload
        assert session.get(CaseHistory, origin_id).model_dump() == original_origin
        case = session.get(Case, case_id)
        assert case.model_dump() == original_case
        assert [row.model_dump() for row in case.case_procedure_steps] == original_progress
        failed = session.get(CaseHistory, history_id)
        assert (failed.judgment_status, failed.failure_code, failed.recovery_action_code) == (
            "FAILED", "STALE_CONFLICT_CONFIRMATION", "RESUBMIT_INPUT")
        assert session.get(CaseHistory, response.json()["case_history_id"]).judgment_status == "PENDING"


@pytest.mark.parametrize("bad", ["case", "event", "ids", "batch", "resolved", "done", "newer", "snapshot", "payload", "retained", "legacy"])
def test_stale_failure_target_and_cleanup_guards_are_independent(mysql_engine, bad):
    case_id, history_id, conflict_id, outcome = stale_failure_case(mysql_engine)
    choices = {conflict_id: "PROPOSED"}
    with Session(mysql_engine) as session:
        history, row = session.get(CaseHistory, history_id), session.get(ConflictReference, conflict_id)
        origin = session.get(CaseHistory, row.case_history_id)
        if bad == "case": outcome = outcome.model_copy(update={"case_id": case_id + 9999})
        elif bad == "event": outcome.trigger.input_event_id = "another-decision"
        elif bad == "ids": choices = {conflict_id + 9999: "PROPOSED"}
        elif bad == "resolved": row.status = "REJECTED"
        elif bad == "done": history.judgment_status = "DONE"
        elif bad == "snapshot": origin.conflict_snapshot = origin.conflict_snapshot | {"snapshot_id": str(uuid4())}
        elif bad == "payload": row.candidate_payload = row.candidate_payload | {"proposed_value": "NOT_REQUIRED"}
        elif bad == "retained": origin.retained_info_result = None
        elif bad == "legacy": origin.conflict_snapshot = {key: value for key, value in origin.conflict_snapshot.items()
                                                         if key != "active_blocker_candidate_ids"}
        elif bad == "batch":
            other = ConflictReference(case_id=case_id, case_history_id=case_history_crud.get_case_created_history(session, case_id).id,
                conflict_ref=str(uuid4()), canonical_field="employee_count", proposed_value="3")
            session.add(other)
            session.flush()
            choices[other.id] = "PROPOSED"
        session.commit()
        session.refresh(history)
        session.refresh(origin)
        original_history = history.model_dump()
        original_origin = origin.model_dump()
        original_rows = [row.model_dump() for row in session.exec(select(ConflictReference).where(ConflictReference.case_id == case_id)).all()]
        if bad == "newer":  # 먼저 읽은 세션의 MySQL 스냅샷보다 최신인 이력도 저장 직전에 확인해야 한다.
            with Session(mysql_engine) as other:
                other.add(CaseHistory(case_id=case_id, source="USER_INPUT", judgment_status="PENDING"))
                other.commit()
        conflict_decision._save_decision_outcome(session, history_id, outcome, choices)
        session.commit()
    with Session(mysql_engine) as session:
        saved = session.get(CaseHistory, history_id)
        if bad in {"case", "event", "done", "newer"}:
            assert saved.model_dump() == original_history
        else:
            assert (saved.judgment_status, saved.failure_code, saved.recovery_action_code) == (
                "FAILED", "STALE_CONFLICT_CONFIRMATION", "RESUBMIT_INPUT")
        assert session.get(CaseHistory, original_origin["id"]).model_dump() == original_origin
        assert [row.model_dump() for row in session.exec(select(ConflictReference).where(ConflictReference.case_id == case_id)).all()] == original_rows


@pytest.mark.parametrize("code,recovery", [
    ("COMPONENT_UNAVAILABLE", "RESUBMIT_INPUT"), ("STALE_CONFLICT_CONFIRMATION", "RETRY"),
    ("STALE_CONFLICT_CONFIRMATION", "CONTACT_SUPPORT"), ("STALE_CONFLICT_CONFIRMATION", "NONE"),
])
def test_other_failures_keep_the_conflict_pending(mysql_engine, code, recovery):
    _, history_id, conflict_id, outcome = stale_failure_case(mysql_engine)
    outcome = SafeFailureOutcome.model_validate(outcome.model_dump(mode="python") | {"failure_code": code, "recovery_action_code": recovery,
        "retryable": recovery == "RETRY", "requested_field_paths": ["employee_count"] if code == "COMPONENT_UNAVAILABLE" else []})
    with Session(mysql_engine) as session:
        conflict_decision._save_decision_outcome(session, history_id, outcome, {conflict_id: "PROPOSED"})
    with Session(mysql_engine) as session:
        assert session.get(CaseHistory, history_id).recovery_action_code == recovery
        assert session.get(ConflictReference, conflict_id).status == "PENDING"


def test_stale_cleanup_and_failure_record_roll_back_together(mysql_engine, monkeypatch):
    _, history_id, conflict_id, outcome = stale_failure_case(mysql_engine)
    resolve = decision_record_service._resolve_conflicts
    def interrupted(*args):
        resolve(*args)
        raise RuntimeError("stop after staging conflict cleanup")
    monkeypatch.setattr(decision_record_service, "_resolve_conflicts", interrupted)
    with Session(mysql_engine) as session, pytest.raises(RuntimeError):
        conflict_decision._save_decision_outcome(session, history_id, outcome, {conflict_id: "PROPOSED"})
    with Session(mysql_engine) as session:
        assert session.get(CaseHistory, history_id).judgment_status == "PENDING"
        assert session.get(ConflictReference, conflict_id).status == "PENDING"


@pytest.mark.parametrize("accepted,detail", [(True, "카운터"), (False, "카운터"), (True, None)],
                         ids=["new-full", "keep-partial", "already-empty-detail"])
def test_full_scope_choice_clears_only_current_detail_and_keeps_old_history(mysql_engine, accepted, detail):
    from app.be.models.case import Case
    from app.be.models.case_field_history import CaseFieldHistory
    from app.be.models.case_history import CaseHistory
    from app.be.models.evidence import ConflictReference

    case_id, history_id, conflict_id, seed_id = scope_case(mysql_engine, detail=detail)
    outcome = reviewed_scope_change(case_id, accepted=accepted, detail=detail)
    with Session(mysql_engine) as session:
        decision_record_service.save_reviewed_plan(session, session.get(CaseHistory, history_id), outcome,
            resolved_conflicts={conflict_id: "PROPOSED" if accepted else "STORED"})
    with Session(mysql_engine) as session:
        case = session.get(Case, case_id)
        assert (case.restoration_scope, case.restoration_scope_detail) == (("FULL", None) if accepted else ("PARTIAL", detail))
        assert session.get(CaseFieldHistory, seed_id).after_value == detail
        if accepted:
            fact = next(f for f in case_snapshot_service.build_case_snapshot(session, case_id).facts
                        if f.field_path == "restoration_scope_detail")
            assert (fact.status, fact.value, fact.evidence_refs) == ("UNKNOWN", None, [])
        rows = session.exec(select(CaseFieldHistory).where(CaseFieldHistory.case_history_id == history_id,
            CaseFieldHistory.canonical_field == "restoration_scope_detail")).all()
        assert len(rows) == int(accepted and detail is not None)
        if rows:
            scope = outcome.review_subject.supervisor_draft.mutations.fact_changes[0]
            assert (rows[0].before_value, rows[0].after_value, rows[0].source) == ("카운터", None, scope.source_type.value)
            assert rows[0].source_evidence_refs == scope.source_evidence_refs
            assert rows[0].reason
        assert session.get(ConflictReference, conflict_id).status == ("CONFIRMED" if accepted else "REJECTED")


@pytest.mark.parametrize("failure", ["stale-detail", "missing-detail", "resolve-rollback"])
def test_full_scope_detail_clear_is_stale_checked_and_atomic(mysql_engine, failure):
    from app.be.models.case import Case
    from app.be.models.case_field_history import CaseFieldHistory
    from app.be.models.case_history import CaseHistory
    from app.be.models.evidence import ConflictReference

    case_id, history_id, conflict_id, _ = scope_case(mysql_engine)
    outcome = reviewed_scope_change(case_id, include_detail=failure != "missing-detail")
    if failure == "stale-detail":
        with Session(mysql_engine) as session:
            session.get(Case, case_id).restoration_scope_detail = "나중에 확인한 바닥"
            session.commit()
    error = ValueError if failure == "resolve-rollback" else decision_record_service.StaleJudgmentError
    with Session(mysql_engine) as session, pytest.raises(error):
        decision_record_service.save_reviewed_plan(session, session.get(CaseHistory, history_id), outcome,
            resolved_conflicts={-1 if failure == "resolve-rollback" else conflict_id: "PROPOSED"})
    with Session(mysql_engine) as session:
        case = session.get(Case, case_id)
        assert case.restoration_scope == "PARTIAL"
        assert case.restoration_scope_detail == ("나중에 확인한 바닥" if failure == "stale-detail" else "카운터")
        assert session.get(CaseHistory, history_id).judgment_status == "PENDING"
        assert session.get(ConflictReference, conflict_id).status == "PENDING"
        assert not session.exec(select(CaseFieldHistory).where(CaseFieldHistory.case_history_id == history_id)).all()


@pytest.mark.parametrize("operation", ["SET", "CLEAR"])
@pytest.mark.parametrize("detail_first", [True, False])
def test_full_scope_clear_wins_over_same_batch_detail_without_duplicate_history(mysql_engine, operation, detail_first):
    from app.agent.schemas import FactChangeCandidate
    from app.be.models.case import Case
    from app.be.models.case_field_history import CaseFieldHistory
    from app.be.models.case_history import CaseHistory

    case_id, history_id, _, _ = scope_case(mysql_engine)
    scope = reviewed_scope_change(case_id).review_subject.supervisor_draft.mutations.fact_changes[0]
    detail = FactChangeCandidate.model_validate(scope.model_dump() | {
        "candidate_id": uuid4(), "field_path": "restoration_scope_detail", "value_type": "STRING",
        "before_value": "카운터", "operation": operation,
        "proposed_status": "CONFIRMED" if operation == "SET" else "UNKNOWN",
        "proposed_value": "새 세부 설명" if operation == "SET" else None,
        "source_evidence_refs": ["separate-detail-report"],
    })
    with Session(mysql_engine) as session:
        decision_record_service._apply_fact_changes(session, session.get(CaseHistory, history_id),
            [detail, scope] if detail_first else [scope, detail])
        session.commit()
    with Session(mysql_engine) as session:
        assert session.get(Case, case_id).restoration_scope_detail is None
        rows = session.exec(select(CaseFieldHistory).where(CaseFieldHistory.case_history_id == history_id,
            CaseFieldHistory.canonical_field == "restoration_scope_detail")).all()
        assert len(rows) == 1
        assert (rows[0].before_value, rows[0].after_value) == ("카운터", None)
        assert rows[0].source_evidence_refs == scope.source_evidence_refs


@pytest.mark.parametrize("before,after", [("FULL", "FULL"), ("PARTIAL", "NOT_REQUIRED"), ("PARTIAL", "PARTIAL")])
def test_detail_clear_policy_only_applies_when_scope_changes_to_full(mysql_engine, before, after):
    from app.be.models.case import Case
    from app.be.models.case_field_history import CaseFieldHistory
    from app.be.models.case_history import CaseHistory

    case_id, history_id, _, _ = scope_case(mysql_engine, before)
    outcome = reviewed_scope_change(case_id, before=before, after=after)
    with Session(mysql_engine) as session:
        decision_record_service._apply_fact_changes(session, session.get(CaseHistory, history_id),
            outcome.review_subject.supervisor_draft.mutations.fact_changes)
        session.commit()
    with Session(mysql_engine) as session:
        assert session.get(Case, case_id).restoration_scope_detail == "카운터"
        assert not session.exec(select(CaseFieldHistory).where(CaseFieldHistory.case_history_id == history_id,
            CaseFieldHistory.canonical_field == "restoration_scope_detail")).all()


def test_the_choice_and_the_saved_value_live_or_die_together(mysql_engine):
    """값 저장과 충돌 닫기가 같은 commit 안에 있는지 진짜 DB로 확인한다.

    흐름 테스트는 save_reviewed_plan을 통째로 가짜로 바꿔 넘긴 인자만 보기 때문에, 값을
    먼저 commit하고 그 뒤에 충돌을 닫도록 순서를 바꿔도 전부 통과한다(현석님·승준님 #136).
    그래서 여기서는 진짜 저장 함수를 부르고, 충돌을 닫는 도중에 일부러 실패를 낸다.
    없는 충돌 번호를 주면 _resolve_conflicts가 바로 거기서 멈춘다.

    둘이 한 트랜잭션이면 값도 같이 되돌아간다. 값을 먼저 commit하면 사장님이 고른 값만
    남고 충돌은 PENDING으로 남아서, 다음 확인 화면이 이미 답한 것을 또 묻는다.
    """
    from app.be.models.case import Case
    from app.be.models.case_history import CaseHistory

    outcome = reviewed_plan_setting_employee_count()
    with Session(mysql_engine) as session:
        case_id = new_case_id(session)
        case = session.get(Case, case_id)
        # 합성 판단이 본 "바뀌기 전 값"에 맞춘다. 다르면 저장 전 대조에서 먼저 걸린다.
        case.employee_count = None
        history = CaseHistory(
            case_id=case_id, raw_input="직원은 2명입니다.", source="USER_INPUT",
            judgment_status="PENDING",
        )
        session.add(history)
        session.commit()
        history_id = history.id

        with pytest.raises(ValueError, match="conflict_reference 9999 not found"):
            decision_record_service.save_reviewed_plan(
                session, history, outcome, resolved_conflicts={9999: "PROPOSED"},
            )

    with Session(mysql_engine) as session:
        assert session.get(Case, case_id).employee_count is None
        assert session.get(CaseHistory, history_id).judgment_status == "PENDING"


def test_a_new_conflict_closes_the_decided_one_without_saving_the_chosen_value(mysql_engine):
    """또 충돌이 난 분기에서 무엇이 남고 무엇이 사라지는지 진짜 DB로 고정한다(승준님 #136).

    이 분기는 Case 값을 건드리지 않는다. AI가 CONFLICT를 돌려줄 때는 검수를 통과한 변경이
    아예 없어서 반영할 것이 없다. 그래서 사장님이 방금 고른 값은 저장되지 않고 고른
    충돌만 닫힌다 — 결정이 기록으로만 남고 Case에는 반영되지 않는 상태다.

    그래도 닫는 쪽을 골랐다. 안 닫으면 다음 확인 묶음에 판단이 다른 충돌 두 개가 섞이는데,
    되살릴 Case 상태는 첫 줄의 판단에서 한 벌만 꺼내므로(_restore_batch) 새 충돌 쪽이
    옛 상태와 함께 넘어가 AI가 묶음 전체를 STALE로 거절한다.
    """
    from app.be.models.case import Case
    from app.be.models.case_history import CaseHistory
    from app.be.models.evidence import ConflictReference

    with Session(mysql_engine) as session:
        case_id = new_case_id(session)
        first = CaseHistory(case_id=case_id, raw_input="전체 철거래요", source="USER_INPUT",
                            judgment_status="CONFLICT")
        session.add(first)
        session.commit()
        decided = decision_record_service.evidence_crud.create_conflict_reference(session, ConflictReference(
            conflict_ref="cr_old", case_id=case_id, case_history_id=first.id,
            canonical_field="demolition_required", committed_value="NOT_REQUIRED",
            proposed_value="REQUIRED", conflict_digest="0" * 64,
            candidate_payload={"conflict_ref": "cr_old"},
        ))
        session.commit()
        decided_id = decided.id

        second = CaseHistory(case_id=case_id, source="CONFLICT_DECISION", judgment_status="PENDING")
        session.add(second)
        session.commit()
        second_id = second.id

        decision_record_service.save_conflict(
            session, second,
            SimpleNamespace(
                evidence_records=[],
                conflicts=[SimpleNamespace(
                    conflict_ref="cr_new", field_path=SimpleNamespace(value="lease_status"),
                    committed_value="OWNED", proposed_value="LEASED_PAID",
                    conflict_digest="1" * 64,
                    model_dump=lambda **_: {"conflict_ref": "cr_new"},
                )],
                conflict_snapshot=SimpleNamespace(model_dump=lambda **_: {"snapshot_id": SNAPSHOT_ID}),
                retained_info_result=None,
            ),
            resolved_conflicts={decided_id: "PROPOSED"},
        )

    with Session(mysql_engine) as session:
        rows = {row.conflict_ref: row for row in session.exec(
            select(ConflictReference).where(ConflictReference.case_id == case_id)
        ).all()}
        # 고른 충돌은 닫히고, 새로 난 충돌만 확인 대기로 남는다.
        assert rows["cr_old"].status == "CONFIRMED" and rows["cr_old"].decided_at is not None
        assert rows["cr_new"].status == "PENDING"
        # 닫은 결정이 남아야 그 결정이 바꾼 값의 가림 문구를 되돌릴 수 있다(services.unmasking).
        assert rows["cr_old"].resolved_by_case_history_id == second_id
        assert rows["cr_new"].resolved_by_case_history_id is None
        # 고른 값(REQUIRED)은 Case에 반영되지 않는다. 이 분기에는 반영할 변경이 없다.
        assert session.get(Case, case_id).demolition_required == "UNKNOWN"


def test_submitting_a_decision_schedules_the_rejudgment(monkeypatch):
    """접수만 하고 끝내면 그 이력은 PENDING에서 안 바뀌고, 그 Case는 다시 잠긴다.

    실제 모델 대신 뒤에서 돌 작업이 등록되는지만 본다(승준님 #136). 화면이 보낸 DB 번호와
    고른 쪽이 그대로 넘어가는지도 함께 본다 — 여기서 어긋나면 엉뚱한 충돌이 닫힌다.
    """
    from fastapi import BackgroundTasks
    from app.be.routers import case as case_router
    from app.be.schemas.case import CaseConflictsDecisionRequest, CaseResultsSubmitAcceptedResponse
    from app.be.services import case as case_service

    monkeypatch.setattr(
        case_service, "submit_case_conflicts_decision",
        lambda *_a: CaseResultsSubmitAcceptedResponse(case_history_id=HISTORY_ID),
    )
    background_tasks = BackgroundTasks()

    case_router.submit_case_conflicts_decision(
        CaseConflictsDecisionRequest(decisions=[
            {"conflict_reference_id": 4, "side": "PROPOSED"},
            {"conflict_reference_id": 7, "side": "STORED"},
        ]),
        background_tasks,
        member_id=1,
        session=MagicMock(spec=Session),
    )

    assert [task.func for task in background_tasks.tasks] == [
        conflict_decision.run_conflict_decision_in_background
    ]
    assert [task.args for task in background_tasks.tasks] == [
        (HISTORY_ID, {4: "PROPOSED", 7: "STORED"})
    ]

@pytest.fixture(scope="module")
def mysql_engine():
    container = MySqlContainer(
        MYSQL_IMAGE, dialect="pymysql", username="test", password="test",
        root_password="test", dbname="conflict_decision_test",
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


def new_case_id(session) -> int:
    member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
    case, _ = create_case(session, member.id, CaseCreateRequest(
        business_type="CAFE", franchise_status=False, employee_count=2,
        lease_status="LEASED_PAID",
    ))
    session.commit()
    return case.id


def test_the_facts_that_were_not_conflicts_go_back_to_the_agent(flow):
    """충돌이 아니었던 사실·진행 보고를 보관해 둔 그대로 돌려줘야 한다.

    사장님이 "자가입니다. 폐업은 12월 20일이고, 폐업신고 서류는 냈어요"라고 한 번에 말하면
    충돌은 임차 형태 하나뿐이다. 이걸 안 돌려주면 AI는 확인 뒤에 원문을 다시 읽지 않으므로
    (ConflictConfirmedTrigger에 입력 글이 없다) 날짜와 신고 보고가 그대로 사라진다.
    """
    captured = flow("REVIEWED_PLAN", {1: "PROPOSED"}, retained={"kept": "폐업신고 제출"})

    assert captured["request"].retained_info_result.kept == "폐업신고 제출"


def test_a_conflict_from_before_this_feature_sends_nothing(flow):
    """이 기능 전에 난 충돌은 보관값이 NULL이라 None으로 넘어간다.

    그 Case도 결정은 되어야 한다. 없는 값을 지어내지 않고 예전처럼 충돌만 다룬다.
    """
    captured = flow("REVIEWED_PLAN", {1: "PROPOSED"}, retained=None)

    assert captured["request"].retained_info_result is None


def test_the_retained_facts_survive_a_round_trip_through_mysql(mysql_engine):
    """보관한 사실·진행 보고가 DB를 거쳐도 한 글자도 안 바뀌어야 한다.

    AI가 비식별 입력·Info 결과·meta·다이제스트를 다시 대조한다. JSON으로 적었다 읽으면서
    시각이나 UUID가 모양만 바뀌어도 그 Case의 결정이 전부 실패한다(conflict_snapshot과 같은
    이유). 실제 저장 함수를 그대로 탄다.
    """
    from app.agent.schemas import RetainedInfoResult
    from app.be.models.case_history import CaseHistory
    from test_action_codes import supervisor_request

    request = supervisor_request()
    original = RetainedInfoResult.model_validate(
        request.source_results[1].model_dump(mode="python")
        | {"input": request.trigger.input.model_dump(mode="python")}
    )

    with Session(mysql_engine) as session:
        case_id = new_case_id(session)
        history = CaseHistory(
            case_id=case_id, raw_input="자가예요. 폐업신고 서류는 냈어요",
            source="USER_INPUT", judgment_status="PENDING",
        )
        session.add(history)
        session.commit()
        history_id = history.id
        decision_record_service.save_conflict(
            session, history,
            SimpleNamespace(
                evidence_records=[], conflicts=[],
                conflict_snapshot=request.case_snapshot,
                retained_info_result=original,
            ),
        )

    # 다른 세션으로 읽어야 ORM이 들고 있던 객체가 아니라 진짜 DB 값을 본다.
    with Session(mysql_engine) as session:
        stored = session.get(CaseHistory, history_id)
        restored = RetainedInfoResult.model_validate(stored.retained_info_result)

    assert restored == original


def test_a_finished_decision_goes_on_to_documents_that_waited(monkeypatch):
    # 충돌 확인을 기다리는 동안 올린 서류는 판단이 미뤄진다. 확인 처리가 끝나면 그 서류를 본다(#173 리뷰).
    checked = []

    async def fake_decision(_session, _case_history_id, _choices):
        return None

    async def fake_owed(case_history_id):
        checked.append(case_history_id)

    monkeypatch.setattr(conflict_decision, "run_conflict_decision", fake_decision)
    monkeypatch.setattr(conflict_decision, "Session", MagicMock())
    monkeypatch.setattr(conflict_decision, "get_engine", MagicMock())
    monkeypatch.setattr(conflict_decision.judgment_service, "judge_owed_documents", fake_owed)

    asyncio.run(conflict_decision.run_conflict_decision_in_background(9, {}))
    assert checked == [9]
