"""사용자가 충돌을 확인한 뒤 다시 계획하는 경로.

충돌이 났을 때 실행이 거기서 끝나 버리면 Hero Loop이 끊긴다. 사용자가 어느 값을
쓸지 골라도 그 선택을 받아 다시 계획할 길이 없었기 때문이다. 이 경로가 그 길이다.

확인된 값도 **Review를 거친다.** 사용자가 정한 것은 "어느 값이 맞는가"이지
"그 값으로 세운 계획이 옳은가"가 아니다.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from app.agent.enrichment import (
    StaleConfirmationError,
    build_confirmed_conflict_overlay,
)
from app.agent.schemas import (
    AgentGraphInput,
    CaseFact,
    CaseSnapshot,
    ConflictCandidate,
    ConflictConfirmedTrigger,
    canonical_digest,
)

_spec = importlib.util.spec_from_file_location(
    "graph_fixtures", "backend/tests/agent/test_graph.py"
)
_fixtures = importlib.util.module_from_spec(_spec)
sys.modules["graph_fixtures"] = _fixtures
_spec.loader.exec_module(_fixtures)

NOW = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000401")
CANDIDATE_ID = UUID("00000000-0000-4000-8000-000000000402")
CALL_ID = UUID("00000000-0000-4000-8000-000000000403")


def snapshot(*, committed: str = "FULL", version: int | None = 1) -> CaseSnapshot:
    committed_text = {
        "FULL": "원상복구 범위는 전체입니다.",
        "PARTIAL": "원상복구 범위는 일부입니다.",
        "NOT_REQUIRED": "원상복구가 필요하지 않습니다.",
    }[committed]
    return CaseSnapshot(
        snapshot_id=SNAPSHOT_ID,
        case_id=1,
        case_version=version,
        case_status="IN_PROGRESS",
        facts=[
            CaseFact(
                field_path="restoration_scope",
                value_type="ENUM",
                value=committed,
                status="CONFIRMED",
                evidence_refs=["ev-system"],
                updated_at=NOW,
            )
        ],
        procedure_progress=[],
        evidence_records=[
            _fixtures.evidence("ev-system").model_copy(
                update={"excerpt": committed_text}
            ),
            _fixtures.evidence("ev-proposed-scope", "USER_INPUT").model_copy(
                update={"excerpt": "원상복구 범위는 일부입니다."}
            ),
        ],
        captured_at=NOW,
    )


def conflict(**updates: Any) -> ConflictCandidate:
    values: dict[str, Any] = {
        "candidate_id": CANDIDATE_ID,
        "snapshot_id": SNAPSHOT_ID,
        "case_version": 1,
        "field_path": "restoration_scope",
        "committed_status": "CONFIRMED",
        "committed_value": "FULL",
        "proposed_operation": "SET",
        "proposed_status": "CONFIRMED",
        "proposed_value": "PARTIAL",
        "source_evidence_refs": ["ev-proposed-scope"],
        "source_call_id": CALL_ID,
    }
    values.update(updates)
    # create_standalone binds the digest, so a tampered candidate cannot be built.
    return ConflictCandidate.create_standalone(**values)


def confirm_request(
    *,
    case_snapshot: CaseSnapshot | None = None,
    candidate: ConflictCandidate | None = None,
) -> AgentGraphInput:
    return AgentGraphInput(
        trigger=ConflictConfirmedTrigger(
            trigger_type="CONFLICT_CONFIRMED",
            input_event_id="input-confirm",
            client_event_id="client-confirm",
            confirmed_conflict=candidate or conflict(),
            confirmed_at=NOW,
        ),
        case_snapshot=case_snapshot or snapshot(),
        trace_id=None,
    )


def graph(**kw: Any):
    info = kw.get("info", _fixtures.FakeInfo())
    procedure = kw.get("procedure", _fixtures.FakeProcedure())
    support = kw.get("support", _fixtures.FakeSupport())
    supervisor = kw.get("supervisor", _fixtures.FakeSupervisor())
    review = kw.get("review", _fixtures.FakeReview(["PASS"]))
    runtime = _fixtures.AgentGraph(
        info_agent=info,
        procedure_tool=procedure,
        support_agent=support,
        supervisor=supervisor,
        review_tool=review,
        known_procedure_steps=[],
        clock=lambda: NOW,
    )
    return runtime, info, procedure, support, supervisor, review


# --- 변환 자체 -------------------------------------------------------------


def test_a_confirmation_becomes_one_reviewable_change() -> None:
    overlay = build_confirmed_conflict_overlay(snapshot(), conflict())

    assert overlay.source_type.value == "CONFIRMED_CONFLICT"
    assert overlay.field_path.value == "restoration_scope"
    assert overlay.before_value == "FULL"
    assert overlay.proposed_value == "PARTIAL"
    assert overlay.candidate_status == "READY_FOR_REVIEW"
    # The link back to the original conflict is what lets a reviewer see that
    # this change came from a person answering, not from analysis.
    assert overlay.confirmed_conflict_ref.startswith("standalone:")


def test_a_confirmation_for_another_snapshot_is_refused() -> None:
    other = UUID("00000000-0000-4000-8000-0000000004ff")
    with pytest.raises(StaleConfirmationError):
        build_confirmed_conflict_overlay(snapshot(), conflict(snapshot_id=other))


def test_a_confirmation_for_another_case_version_is_refused() -> None:
    with pytest.raises(StaleConfirmationError):
        build_confirmed_conflict_overlay(snapshot(version=2), conflict(case_version=1))


def test_a_confirmation_is_refused_once_the_value_has_moved_on() -> None:
    """The reason this path cannot be a plain write.

    Between raising the conflict and the user answering it, the Case may have
    changed. Applying the answer anyway would overwrite that change without
    anyone seeing it.
    """

    with pytest.raises(StaleConfirmationError):
        build_confirmed_conflict_overlay(snapshot(committed="NOT_REQUIRED"), conflict())


def test_a_confirmation_is_refused_when_the_field_is_no_longer_confirmed() -> None:
    cleared = CaseSnapshot(
        snapshot_id=SNAPSHOT_ID,
        case_id=1,
        case_version=1,
        case_status="IN_PROGRESS",
        facts=[
            CaseFact(
                field_path="restoration_scope",
                value_type="ENUM",
                value=None,
                status="UNKNOWN",
                evidence_refs=[],
                updated_at=None,
            )
        ],
        procedure_progress=[],
        evidence_records=[_fixtures.evidence("ev-system")],
        captured_at=NOW,
    )
    with pytest.raises(StaleConfirmationError):
        build_confirmed_conflict_overlay(cleared, conflict())


# --- 그래프 경로 -----------------------------------------------------------


def test_a_confirmation_replans_and_still_goes_through_review() -> None:
    runtime, info, procedure, support, supervisor, review = graph()

    outcome = asyncio.run(runtime.run(confirm_request()))

    assert outcome.outcome_type == "REVIEWED_PLAN"
    assert outcome.review_proof.verdict == "PASS"
    # Replanning, not re-reading: there is no new user sentence to analyse and
    # no reason to fetch procedures again.
    assert procedure.calls == 0
    assert info.calls == 0
    assert support.calls == 1
    assert supervisor.calls == 1
    assert review.calls == 1


class RecordingSupervisor(_fixtures.FakeSupervisor):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[Any] = []

    async def draft(self, component_input: Any) -> Any:
        self.inputs.append(component_input)
        return await super().draft(component_input)


class RecordingSupport(_fixtures.FakeSupport):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[Any] = []

    async def analyze(self, component_input: Any) -> Any:
        self.inputs.append(component_input)
        return await super().analyze(component_input)


def test_the_confirmed_value_reaches_the_planner_as_a_change() -> None:
    supervisor = RecordingSupervisor()
    support = RecordingSupport()
    runtime, _, _, _, _, _ = graph(supervisor=supervisor, support=support)

    asyncio.run(runtime.run(confirm_request()))

    overlays = supervisor.inputs[0].fact_overlays
    assert len(overlays) == 1
    assert overlays[0].source_type.value == "CONFIRMED_CONFLICT"
    assert overlays[0].proposed_value == "PARTIAL"
    # The change is traced by the conflict reference, not by a component call.
    assert overlays[0].source_call_id is None
    assert overlays[0].confirmed_conflict_ref
    # Support compares against the confirmed value too, not the old one.
    assert support.inputs[0].planning_context.fact_overlays == overlays


def test_a_stale_confirmation_fails_closed_without_planning() -> None:
    runtime, _, _, support, supervisor, review = graph()
    stale = confirm_request(case_snapshot=snapshot(committed="NOT_REQUIRED"))

    outcome = asyncio.run(runtime.run(stale))

    assert outcome.outcome_type == "SAFE_FAILURE"
    # Its own code, not a generic one: the caller has to tell "the model
    # misbehaved" from "show the user the current value and ask again".
    assert outcome.failure_code == "STALE_CONFLICT_CONFIRMATION"
    assert outcome.recovery_action_code == "RESUBMIT_INPUT"
    assert outcome.retryable is False
    assert support.calls == supervisor.calls == review.calls == 0


def test_a_confirmation_leaves_the_case_snapshot_untouched() -> None:
    runtime, _, _, _, _, _ = graph()
    payload = confirm_request()
    before = canonical_digest(payload.case_snapshot)

    asyncio.run(runtime.run(payload))

    assert canonical_digest(payload.case_snapshot) == before


def test_the_real_planner_puts_the_confirmed_change_into_its_mutation_set() -> None:
    """The graph hands the overlay over; this checks the planner keeps it.

    Verified against the real SupervisorAgent rather than a stand-in, because
    a stand-in cannot show that the confirmed change survives into the set
    Review actually inspects.
    """

    spec = importlib.util.spec_from_file_location(
        "supervisor_fixtures", "backend/tests/agent/test_supervisor.py"
    )
    sup = importlib.util.module_from_spec(spec)
    sys.modules["supervisor_fixtures"] = sup
    spec.loader.exec_module(sup)

    overlay = build_confirmed_conflict_overlay(snapshot(), conflict())
    request = sup.supervisor_input(
        [sup.source(), sup.procedure_source()],
        fact_overlays=[overlay],
    )
    draft = asyncio.run(
        sup.SupervisorAgent(sup.FakeLLM(sup.semantic_payload())).draft(request)
    )

    changes = draft.mutations.fact_changes
    assert [item.source_type.value for item in changes] == ["CONFIRMED_CONFLICT"]
    assert changes[0].proposed_value == "PARTIAL"
    assert changes[0].confirmed_conflict_ref == overlay.confirmed_conflict_ref
