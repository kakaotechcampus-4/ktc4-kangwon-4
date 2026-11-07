"""Case 입력 순서·기존 값의 출처로 표식을 정한다. 모델·DB 연결은 사용하지 않는다."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.agent.schemas import InputSourceType, RedactedInput
from app.be.crud import case_field_history, case_history, conflict_reference
from app.be.services.redaction import numbered_placeholders, redact
from app.be.services.unmasking import build_case_placeholders
from case_world import case_engine, case_world  # noqa: F401
from sqlmodel import Session

A = "서울 마포구 월드컵북로 12"
B = "서울 마포구 성산로 34"


def history(id, text):
    return SimpleNamespace(id=id, raw_input=text)


def changed(id, value):
    return SimpleNamespace(id=id, case_history_id=id, canonical_field="restoration_scope_detail", after_value=value)


@pytest.fixture
def case_map(monkeypatch):
    def build(histories, changes=()):
        monkeypatch.setattr(case_history, "get_case_histories_by_case_id", lambda *_: histories)
        monkeypatch.setattr(case_field_history, "get_case_field_histories_by_case_id", lambda *_: changes)
        monkeypatch.setattr(conflict_reference, "get_decided_conflicts_by_case_id", lambda *_: [])
        return build_case_placeholders(MagicMock(spec=Session), 7)
    return build


def test_case_order_is_by_history_id_and_same_address_keeps_its_number(case_map):
    mapping, unclear = case_map([history(3, A), history(2, B), history(1, A)])
    assert not unclear
    assert redact(A, placeholders=mapping)[0] == "서울 마포구 [주소#1]"
    assert redact(B, placeholders=mapping)[0] == "서울 마포구 [주소#2]"
    assert mapping == numbered_placeholders([A, B, A])
    # 다른 Case의 순서는 섞이지 않는다.
    assert redact(B, placeholders=numbered_placeholders([B]))[0] == "서울 마포구 [주소#1]"


def test_offsets_use_the_final_numbered_placeholder():
    text = f"포함: {A}, 제외: {B}"
    masked, spans = redact(text, placeholders=numbered_placeholders([text]))
    result = RedactedInput(
        input_event_id="history:1", source_type=InputSourceType.USER_INPUT,
        redacted_text=masked, redactions=spans, submitted_at=datetime.fromisoformat("2026-11-07T09:00:00+09:00"),
    )
    assert [r.placeholder for r in result.redactions] == ["[주소#1]", "[주소#2]"]


def test_other_redaction_types_use_their_own_placeholder_names():
    text = "010-1234-5678, test@example.com, 이름은 김리본입니다"
    masked, _ = redact(text, placeholders=numbered_placeholders([text]))
    assert masked == "[전화번호#1], [이메일#1], 이름은 [이름#1]입니다"


def test_legacy_alias_survives_a_new_value_and_repeated_old_address(case_map):
    # A([주소]) → B([주소#2])가 확정된 뒤에도 과거 이력으로 A의 표식을 유지한다.
    changes = [changed(1, "서울 마포구 [주소]"), changed(2, "서울 마포구 [주소#2]")]
    first, unclear = case_map([history(1, A), history(2, B)], changes)
    repeated, still_unclear = case_map([history(1, A), history(2, B), history(3, A)], changes)
    assert not unclear and not still_unclear
    assert first == repeated
    assert redact(A, placeholders=repeated)[0] == "서울 마포구 [주소]"
    assert redact(B, placeholders=repeated)[0] == "서울 마포구 [주소#2]"


@pytest.mark.parametrize(
    ("histories", "changes"),
    [
        ([history(1, f"{A}, {B}")], [changed(1, "[주소]")]),
        ([history(1, A), history(2, B)], [changed(1, "[주소]"), changed(2, "[주소]")]),
        ([history(1, None)], [changed(1, "[주소]")]),
    ],
)
def test_unclear_legacy_sources_are_reported_without_guessing(case_map, histories, changes):
    original_values = [row.after_value for row in changes]
    mapping, unclear = case_map(histories, changes)
    assert unclear
    assert "[주소]" not in mapping.values()
    assert [row.after_value for row in changes] == original_values


def test_an_evidence_only_address_is_hidden_without_extending_the_case_map():
    mapping = numbered_placeholders([A])
    before = dict(mapping)
    assert redact(B, placeholders=mapping)[0] == "서울 마포구 [주소]"
    assert mapping == before


def test_input_and_user_evidence_use_the_same_map():
    from app.be.services.case_snapshot import _build_evidence_record, build_user_input
    from test_redaction import SUBMITTED_AT, evidence

    mapping = numbered_placeholders([A, B])
    user_input = build_user_input(1, B, SUBMITTED_AT, placeholders=mapping)
    record = _build_evidence_record(evidence(B, "USER_INPUT"), [], placeholders=mapping)
    assert user_input.redacted_text == record.excerpt == "서울 마포구 [주소#2]"
    # 이미 생성된 근거와 공식 자료는 다시 번호를 붙이지 않는다.
    numbered = evidence(record.excerpt, "USER_INPUT")
    assert _build_evidence_record(numbered, [], placeholders=mapping).excerpt == record.excerpt
    assert _build_evidence_record(evidence(B, "OFFICIAL_DOCUMENT"), [], placeholders=mapping).excerpt == B


def address_analysis(mapping, *, case_id=7, history_id=1, snapshot=None, part="바닥"):
    import asyncio

    from app.agent.info_agent.agent import InfoAnalysisAgent
    from app.agent.schemas import CaseFact
    from app.be.services.case_snapshot import build_user_input
    from test_action_codes import NOW
    from test_info_replanning import (
        FOOD,
        TAX,
        Responses,
        finding,
        output,
        request_for_replanning,
    )

    request = request_for_replanning(status="IN_PROGRESS", scope="PARTIAL")
    if snapshot is not None:
        data = request.model_dump(mode="python")
        data["case_snapshot"] = snapshot.model_dump(mode="python")
        data["procedure_lookup_result"]["based_on_snapshot_id"] = snapshot.snapshot_id
        request = type(request).model_validate(data)
    else:
        request.case_snapshot.case_id = case_id
    stored = "서울 마포구 [주소]의 바닥"
    if snapshot is None:
        request.case_snapshot.facts.append(CaseFact(
            field_path="restoration_scope_detail", value_type="STRING", value=stored,
            status="CONFIRMED", evidence_refs=["synthetic-document"], updated_at=NOW,
        ))
    request.input = build_user_input(history_id, f"원상복구 범위는 {A}의 {part}입니다.",
                                     NOW.replace(tzinfo=None), placeholders=mapping)
    proposed = redact(A, placeholders=mapping)[0] + f"의 {part}"
    response = output([finding(TAX, "doc1"), finding(FOOD, "doc2")])
    response["facts"] = [{
        "operation": "SET", "field_path": "restoration_scope_detail", "value_type": "STRING",
        "value": proposed, "source_text": request.input.redacted_text, "confidence_bps": 10000,
        "requires_confirmation": False, "reason_summary": "합성 범위 보고",
    }]
    result = asyncio.run(InfoAnalysisAgent(Responses(response), max_local_attempts=1).analyze(request))
    return result, request


def test_a_proven_legacy_alias_does_not_create_a_false_conflict(case_map):
    mapping, unclear = case_map([history(1, A), history(2, B), history(3, A)], [changed(1, "[주소]")])
    result, _ = address_analysis(mapping)
    assert not unclear and not result.conflicts and not result.fact_candidates


def test_retry_keeps_numbered_input_and_evidence_identical(case_world):  # noqa: F811
    from app.be.models.case_history import CaseHistory
    from app.be.models.evidence import Evidence
    from app.be.models.mixins import kst_now
    from app.be.services import case as service
    from app.be.services import judgment

    member_id, case_id, _ = case_world.sign_up()
    old_id = case_world.add_history(case_id, "USER_INPUT", "DONE")
    failed_id = case_world.add_history(case_id, "USER_INPUT", "FAILED")
    with Session(case_world.engine) as session:
        session.get(CaseHistory, old_id).raw_input = A
        session.get(CaseHistory, failed_id).raw_input = B
        session.add(Evidence(case_id=case_id, evidence_id="numbered-retry", source_type="USER_INPUT",
                             source_ref=f"case_history:{failed_id}", excerpt=B,
                             retrieved_at=kst_now(), freshness_status="CURRENT"))
        session.commit()
        first, _ = judgment._read_judgment_input(session, failed_id)
        assert service.retry_case_judgment(session, member_id).case_history_id == failed_id
    with Session(case_world.engine) as session:
        retried, _ = judgment._read_judgment_input(session, failed_id)
        assert session.get(CaseHistory, failed_id).raw_input == B
    assert first.trigger.input == retried.trigger.input
    assert retried.trigger.input.redacted_text == "서울 마포구 [주소#2]"
    assert next(e.excerpt for e in retried.case_snapshot.evidence_records
                if e.evidence_id == "numbered-retry") == retried.trigger.input.redacted_text


@pytest.mark.parametrize("numbered,accepted,state_changed", [
    (True, True, False), (True, False, False), (False, True, False),
    (False, False, False), (True, True, True), (False, True, True),
])
def test_conflict_input_overlays_and_storage_preserve_numbered_or_legacy_values(  # noqa: F811
    case_world, numbered, accepted, state_changed,  # noqa: F811
):
    """실제 결정 입력·overlay·저장 구간. 합성 Info만 사용하고 Supervisor는 실행하지 않는다."""
    from app.agent.enrichment import StaleConfirmationError, build_conflict_overlays
    from app.be.models.case import Case
    from app.be.models.case_field_history import CaseFieldHistory
    from app.be.models.case_history import CaseHistory
    from app.be.models.evidence import ConflictReference, Evidence
    from app.be.models.mixins import kst_now
    from app.be.services import case_snapshot, conflict_decision, decision_record

    _, case_id, _ = case_world.sign_up()
    legacy_id = case_world.add_history(case_id, "USER_INPUT", "DONE")
    input_id = case_world.add_history(case_id, "USER_INPUT", "PENDING")
    original = f"포함: {A}, 제외: {B}"
    part = "바닥" if numbered else "벽"
    report = f"원상복구 범위는 {A}의 {part}입니다."
    with Session(case_world.engine) as session:
        case = session.get(Case, case_id)
        case.restoration_scope = "PARTIAL"
        case.restoration_scope_detail = "서울 마포구 [주소]의 바닥"
        session.get(CaseHistory, legacy_id).raw_input = original
        session.get(CaseHistory, input_id).raw_input = report
        session.add(Evidence(case_id=case_id, evidence_id=f"raw-{input_id}", source_type="USER_INPUT",
                             source_ref=f"case_history:{legacy_id}", excerpt=original,
                             retrieved_at=kst_now(), freshness_status="CURRENT"))
        session.add(CaseFieldHistory(case_id=case_id, case_history_id=legacy_id,
                    canonical_field="restoration_scope_detail", before_value=None,
                    after_value=case.restoration_scope_detail, source="INFO_ANALYSIS",
                    source_evidence_refs=[f"raw-{input_id}"]))
        session.commit()
        mapping, unclear = build_case_placeholders(session, case_id)
        assert unclear
        mapping = mapping if numbered else None
        snapshot = case_snapshot.build_case_snapshot(session, case_id, placeholders=mapping)
    result, request = address_analysis(mapping, case_id=case_id, history_id=input_id, snapshot=snapshot, part=part)
    conflict, = result.conflicts
    frozen = conflict.model_dump(mode="json")
    assert conflict.committed_value == "서울 마포구 [주소]의 바닥"
    assert conflict.proposed_value == ("서울 마포구 [주소#1]의 바닥" if numbered else "서울 마포구 [주소]의 벽")
    request.case_snapshot.evidence_records.extend(result.evidence_records)
    with Session(case_world.engine) as session:
        origin = session.get(CaseHistory, input_id)
        decision_record.save_conflict(session, origin, SimpleNamespace(
            evidence_records=result.evidence_records, conflicts=[conflict],
            conflict_snapshot=request.case_snapshot, retained_info_result=None,
        ))
        row = conflict_reference.get_pending_conflicts_by_case_id(session, case_id)[0]
        row_id = row.id
        decision = CaseHistory(case_id=case_id, source="CONFLICT_DECISION", judgment_status="PENDING")
        session.add(decision)
        session.commit()
        if state_changed:
            session.get(Case, case_id).employee_count = 3
            session.commit()
        graph_input, _ = conflict_decision._read_decision_input(
            session, decision.id, {row_id: "PROPOSED" if accepted else "STORED"})
        assert graph_input.trigger.conflicts[0].model_dump(mode="json") == frozen
        assert origin.conflict_snapshot == graph_input.trigger.conflict_snapshot.model_dump(mode="json")
        if state_changed:
            with pytest.raises(StaleConfirmationError):
                build_conflict_overlays(graph_input.case_snapshot, graph_input.trigger)
            assert session.get(Case, case_id).restoration_scope_detail == conflict.committed_value
            return
        changes = build_conflict_overlays(graph_input.case_snapshot, graph_input.trigger)
        decision_record._assert_changes_are_current(session, decision, SimpleNamespace(
            fact_changes=changes, procedure_progress_changes=[]))
        decision_record._apply_fact_changes(session, decision, changes)
        decision_record._resolve_conflicts(session, decision, {row_id: "PROPOSED" if accepted else "STORED"})
        session.commit()
    with Session(case_world.engine) as session:
        assert session.get(Case, case_id).restoration_scope_detail == (
            conflict.proposed_value if accepted else conflict.committed_value)
        row = session.get(ConflictReference, row_id)
        assert row.candidate_payload == frozen
        assert row.status == ("CONFIRMED" if accepted else "REJECTED")
        assert session.get(CaseHistory, input_id).raw_input == report
