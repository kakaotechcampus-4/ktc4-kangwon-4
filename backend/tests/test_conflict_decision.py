"""사장님이 고른 충돌 결정이 AI를 거쳐 Case에 반영되는지.

충돌이 나면 Case가 잠긴다 — 확인 대기 중인 충돌이 있는 동안은 새 제출이 거부되는데, 충돌을
닫는 코드가 없으면 영영 안 풀린다. 그래서 "무엇을 언제 닫느냐"가 이 흐름의 핵심이다.

실제 모델은 부르지 않는다. AI 응답은 테스트가 정해서 넣는다.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session

from app.be.crud import case_history as case_history_crud
from app.be.crud import conflict_reference as conflict_reference_crud
from app.be.services import agent_runtime as agent_runtime_service
from app.be.services import case_snapshot as case_snapshot_service
from app.be.services import conflict_decision
from app.be.services import decision_record as decision_record_service
from app.be.services import reviewed_procedure as reviewed_procedure_service

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

    def run(outcome_type, choices, *, rows=None, stored_snapshot=SNAPSHOT_ID):
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
            SimpleNamespace(model_validate=lambda payload: SimpleNamespace(**payload)),
        )
        monkeypatch.setattr(
            conflict_decision, "build_conflict_input",
            lambda **kwargs: SimpleNamespace(**kwargs),
        )
        monkeypatch.setattr(conflict_decision, "run_case_planning", fake_run_case_planning)
        monkeypatch.setattr(
            case_snapshot_service, "build_case_snapshot",
            lambda _s, _c, *, snapshot_id=None: SimpleNamespace(snapshot_id=snapshot_id),
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
        MagicMock(spec=Session), {1: "PROPOSED", 2: "STORED"}
    )

    assert (rows[1].status, rows[2].status) == ("CONFIRMED", "REJECTED")
    assert rows[1].decided_at is not None and rows[2].decided_at is not None


def test_closing_nothing_is_allowed(monkeypatch):
    """가입·결과 제출 판단은 닫을 충돌이 없다. 같은 저장 함수를 쓰므로 빈 값이 정상이다."""

    decision_record_service._resolve_conflicts(MagicMock(spec=Session), None)
    decision_record_service._resolve_conflicts(MagicMock(spec=Session), {})
