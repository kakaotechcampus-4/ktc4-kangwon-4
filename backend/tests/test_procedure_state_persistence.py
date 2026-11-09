"""신고 준비 확인·제출 상태가 실제 DB를 거쳐 다음 판단에도 남아야 한다."""

from uuid import uuid4

import pytest
import test_reviewed_procedure_db as procedure_db
from app.agent.schemas import MutationSet, ProcedureProgressChangeCandidate
from app.be.crud import procedure_step as procedure_step_crud
from app.be.crud.case_history import get_case_created_history
from app.be.services import decision_record as decision_record_service
from app.be.services.case_snapshot import build_case_snapshot
from sqlmodel import Session

mysql_engine = procedure_db.mysql_engine


def test_submitted_procedure_keeps_its_receipt_action_after_reload(mysql_engine):
    from app.agent.action_catalog import build_action_candidates
    from test_action_codes import REF, evidence, finding, procedure_sources

    case_id = procedure_db.create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        snapshot = build_case_snapshot(session, case_id)
        assert all(
            not item.requirements_confirmed and not item.submitted
            for item in snapshot.procedure_progress
        )
        progress = next(
            p
            for p in snapshot.procedure_progress
            if p.procedure_step.step_code == "FILE_TAX_BUSINESS_CLOSURE"
        )
        history = get_case_created_history(session, case_id)
        change = ProcedureProgressChangeCandidate(
            candidate_id=uuid4(),
            procedure_step=progress.procedure_step,
            before_status=progress.status,
            proposed_status="IN_PROGRESS",
            proposed_requirements_confirmed=True,
            proposed_submitted=True,
            reason_summary="합성 신고 접수 보고",
            execution_evidence_refs=snapshot.facts[0].evidence_refs,
            procedure_analysis_call_id=uuid4(),
        )
        decision_record_service._apply_procedure_progress_changes(
            session, history, [change]
        )
        session.commit()

    with Session(mysql_engine) as session:
        restored = next(
            p
            for p in build_case_snapshot(session, case_id).procedure_progress
            if p.procedure_step == progress.procedure_step
        )
        assert (
            restored.status,
            restored.requirements_confirmed,
            restored.submitted,
        ) == ("IN_PROGRESS", True, True)
        sources = procedure_sources(
            finding(procedure_step=restored.procedure_step, requires_confirmation=False)
        )
        actions = build_action_candidates(
            sources, {REF: evidence()}, procedure_progress=[restored]
        )
        assert [action["action_code"] for action in actions] == [
            "CONFIRM_PROCEDURE_COMPLETION"
        ]


@pytest.mark.parametrize(
    "before,after",
    [
        (("NOT_STARTED", False, False), ("NOT_STARTED", True, False)),
        (("IN_PROGRESS", True, False), ("IN_PROGRESS", True, True)),
        (("IN_PROGRESS", True, True), ("COMPLETED", True, True)),
    ],
)
def test_flag_only_changes_and_completion_survive_reload(mysql_engine, before, after):
    case_id = procedure_db.create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        history = get_case_created_history(session, case_id)
        snapshot = build_case_snapshot(session, case_id)
        step = procedure_step_crud.get_case_procedure_steps_by_case_id(
            session, case_id
        )[0]
        step.status, step.requirements_confirmed, step.submitted = before
        step.evidence_refs = snapshot.facts[0].evidence_refs
        session.commit()
        reference = next(
            p.procedure_step
            for p in snapshot.procedure_progress
            if p.procedure_step.procedure_step_id == step.procedure_step_id
        )
        change = ProcedureProgressChangeCandidate(
            candidate_id=uuid4(),
            procedure_step=reference,
            before_status=before[0],
            proposed_status=after[0],
            before_requirements_confirmed=before[1],
            proposed_requirements_confirmed=after[1],
            before_submitted=before[2],
            proposed_submitted=after[2],
            reason_summary="합성 준비 확인·제출·완료 보고",
            execution_evidence_refs=step.evidence_refs,
            procedure_analysis_call_id=uuid4(),
        )
        mutations = MutationSet(
            fact_changes=[],
            procedure_progress_changes=[change],
            support_match_updates=[],
        )
        decision_record_service._assert_changes_are_current(session, history, mutations, snapshot=snapshot)
        decision_record_service._apply_procedure_progress_changes(
            session, history, [change]
        )
        session.commit()
    with Session(mysql_engine) as session:
        restored = next(
            p
            for p in build_case_snapshot(session, case_id).procedure_progress
            if p.procedure_step == reference
        )
        assert (
            restored.status,
            restored.requirements_confirmed,
            restored.submitted,
        ) == after


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "IN_PROGRESS"),
        ("requirements_confirmed", True),
        ("submitted", True),
    ],
)
def test_newer_progress_or_flags_reject_the_old_judgment(mysql_engine, field, value):
    case_id = procedure_db.create_test_case(mysql_engine)
    with Session(mysql_engine) as session:
        history = get_case_created_history(session, case_id)
        snapshot = build_case_snapshot(session, case_id)
        progress = snapshot.procedure_progress[0]
        step_id = progress.procedure_step.procedure_step_id
        # 판단이 처음 읽은 상태를 이 세션에 남긴 뒤, 다른 세션에서 보고를 먼저 반영한다.
        original_step = procedure_step_crud.get_case_procedure_step(
            session, case_id, step_id
        )
        assert (
            original_step.status,
            original_step.requirements_confirmed,
            original_step.submitted,
        ) == ("NOT_STARTED", False, False)
        with Session(mysql_engine) as other:
            step = procedure_step_crud.get_case_procedure_step(other, case_id, step_id)
            setattr(step, field, value)
            step.evidence_refs = snapshot.facts[0].evidence_refs
            other.commit()
        change = ProcedureProgressChangeCandidate(
            candidate_id=uuid4(),
            procedure_step=progress.procedure_step,
            before_status="NOT_STARTED",
            proposed_status="IN_PROGRESS",
            proposed_requirements_confirmed=True,
            proposed_submitted=True,
            reason_summary="뒤늦게 끝난 합성 판단",
            execution_evidence_refs=snapshot.facts[0].evidence_refs,
            procedure_analysis_call_id=uuid4(),
        )
        mutations = MutationSet(
            fact_changes=[],
            procedure_progress_changes=[change],
            support_match_updates=[],
        )
        session.rollback()  # save_reviewed_plan이 저장 전 대조 직전에 하는 것과 같다.
        with pytest.raises(decision_record_service.StaleJudgmentError):
            decision_record_service._assert_changes_are_current(
                session, history, mutations, snapshot=snapshot
            )
    with Session(mysql_engine) as session:
        step = procedure_step_crud.get_case_procedure_step(session, case_id, step_id)
        assert getattr(step, field) == value
