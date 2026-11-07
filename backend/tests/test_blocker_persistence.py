"""검수한 모든 Blocker와 해결 상태가 실제 MySQL을 거쳐 다음 판단에 남는다."""

import asyncio
import json
from uuid import uuid4

import pytest
from app.be.db import MYSQL_IMAGE
from app.agent.review_tool import ReviewTool
from app.agent.schemas import (
    ReviewedPlanOutcome,
    ReviewProof,
    ReviewSubject,
    canonical_digest,
)
from app.agent.supervisor.agent import SupervisorAgent
from app.be.crud.member import create_member
from app.be.models.blocker import Blocker
from app.be.models.case_history import CaseHistory
from app.be.schemas.case import CaseCreateRequest
from app.be.services import decision_record, procedure_registry
from app.be.services.case import create_case, get_case
from app.be.services.case_snapshot import build_case_snapshot
from sqlmodel import Session, SQLModel, create_engine, select
from test_action_codes import NOW, REF
from test_blocker_candidates import ChoiceModel, request_with_state
from testcontainers.community.mysql import MySqlContainer


@pytest.fixture(scope="module")
def mysql_engine():
    with MySqlContainer(
        MYSQL_IMAGE, dialect="pymysql", username="test", password="test",
        root_password="test", dbname="blocker_persistence_test",
    ).with_env("TZ", "Asia/Seoul") as container:
        engine = create_engine(container.get_connection_url() + "?charset=utf8mb4")
        try:
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                procedure_registry.ensure_cafe_procedure_registry(session)
                session.commit()
            yield engine
        finally:
            engine.dispose()


def new_case(engine):
    with Session(engine) as session:
        member = create_member(session, oauth_id=str(uuid4()), nickname="합성 사용자")
        case, _ = create_case(session, member.id, CaseCreateRequest(
            business_type="CAFE", franchise_status=False, lease_status="LEASED_PAID",
        ))
        return case.id, member.id


def reviewed_outcome(case_id, *, choice=0, active=(), confirmed=False):
    async def build():
        request = request_with_state(**({
            "restoration_scope": "FULL", "demolition_required": "REQUIRED",
        } if confirmed else {}))
        # Evidence ID는 Case 전체가 아니라 DB 전체에서 유일하다.
        payload = json.loads(request.model_dump_json().replace(f'"{REF}"', f'"{REF}:{case_id}"'))
        for original, source in zip(request.source_results, payload["source_results"]):
            if source["meta"]["component"] == "INFO_AGENT":
                source["output"]["based_on_procedure_lookup_digest"] = payload["source_results"][0]["output_digest"]
            source["output_digest"] = canonical_digest(type(original.output).model_validate(source["output"]))
        request = type(request).model_validate(payload)
        request.case_snapshot.case_id = case_id
        request.case_snapshot.active_blocker_candidate_ids = list(active)
        run_id = uuid4()
        for source in request.source_results:
            source.meta.case_id = case_id
            source.meta.run_id = run_id
        draft = await SupervisorAgent(ChoiceModel(choice=choice), max_local_attempts=1).draft(request)
        subject = ReviewSubject.create(
            schema_version="agent-io/2.0", review_subject_id=uuid4(), review_attempt=1,
            run_id=run_id, case_id=case_id, trigger=request.trigger,
            snapshot=request.case_snapshot, known_procedure_steps=request.known_procedure_steps,
            source_results=request.source_results, supervisor_draft=draft,
        )
        review = await ReviewTool(ChoiceModel()).review(subject)
        assert review.verdict == "PASS", review
        meta = request.source_results[0].meta.model_copy(update={
            "component": "REVIEW_TOOL", "call_id": uuid4(),
        })
        return ReviewedPlanOutcome(
            outcome_type="REVIEWED_PLAN", review_subject=subject,
            review_proof=ReviewProof.from_passed_review(
                subject=subject, result=review, review_meta=meta, reviewed_at=NOW,
            ),
        )
    return asyncio.run(build())


def submit(engine, case_id, outcome, *, resolved_conflicts=None):
    with Session(engine) as session:
        history = CaseHistory(case_id=case_id, source="USER_INPUT", raw_input="합성 결과", judgment_status="PENDING")
        session.add(history)
        session.commit()
        history_id = history.id
        decision_record.save_reviewed_plan(session, history, outcome, resolved_conflicts=resolved_conflicts)
        return history_id


def rows(session, case_id):
    return session.exec(select(Blocker).where(Blocker.case_id == case_id).order_by(Blocker.id)).all()


def test_all_blockers_and_the_selected_priority_survive_a_new_session(mysql_engine):
    case_id, member_id = new_case(mysql_engine)
    outcome = reviewed_outcome(case_id, choice=1)
    decision = outcome.review_subject.supervisor_draft.decision
    history_id = submit(mysql_engine, case_id, outcome)

    with Session(mysql_engine) as session:
        stored = rows(session, case_id)
        assert len(stored) == len(decision.blockers) == 2
        assert {row.candidate_id for row in stored} == {"procedure:1", "procedure:4"}
        for original in decision.blockers:
            row = next(row for row in stored if row.candidate_id == original.candidate_id)
            assert (row.description, row.blocker_evidence_refs) == (original.description, original.evidence_refs)
        history = session.get(CaseHistory, history_id)
        assert history.next_action_code == decision.next_action.action_code
        assert history.priority_blocker.candidate_id == decision.blocker.candidate_id
        assert set(build_case_snapshot(session, case_id).active_blocker_candidate_ids) == {"procedure:1", "procedure:4"}
        # 기존 화면에는 선택한 한 개만 보여준다.
        assert get_case(session, member_id).blocker == decision.blocker.description


def test_repeated_candidates_keep_history_and_resolve_every_saved_version(mysql_engine):
    case_id, _ = new_case(mysql_engine)
    other_case_id, _ = new_case(mysql_engine)
    submit(mysql_engine, other_case_id, reviewed_outcome(other_case_id))
    first = submit(mysql_engine, case_id, reviewed_outcome(case_id))
    second = submit(mysql_engine, case_id, reviewed_outcome(case_id, choice=1, active=["procedure:1", "procedure:4"]))
    with Session(mysql_engine) as session:
        first_priority = session.get(CaseHistory, first).priority_blocker_id
        second_priority = session.get(CaseHistory, second).priority_blocker_id
        first_description = session.get(Blocker, first_priority).description
        second_description = session.get(Blocker, second_priority).description
        assert first_priority != second_priority
        assert len(rows(session, case_id)) == 4
        snapshot = build_case_snapshot(session, case_id)
        assert len(snapshot.active_blocker_candidate_ids) == 2
    outcome = reviewed_outcome(case_id, active=snapshot.active_blocker_candidate_ids, confirmed=True)
    assert outcome.review_subject.supervisor_draft.resolved_blocker_candidate_ids == ["procedure:4"]
    resolution = submit(mysql_engine, case_id, outcome)
    with Session(mysql_engine) as session:
        stored = rows(session, case_id)
        resolved = [row for row in stored if row.candidate_id == "procedure:4"]
        assert len(resolved) == 2
        assert all(row.status == "RESOLVED" and row.resolved_from_case_history_id == resolution
                   and row.resolved_at is not None for row in resolved)
        assert build_case_snapshot(session, case_id).active_blocker_candidate_ids == ["procedure:1"]
        assert session.get(CaseHistory, first).priority_blocker_id == first_priority
        assert session.get(CaseHistory, second).priority_blocker_id == second_priority
        assert session.get(Blocker, first_priority).description == first_description
        assert session.get(Blocker, second_priority).description == second_description
        assert all(row.status == "ACTIVE" for row in rows(session, other_case_id))
        assert set(build_case_snapshot(session, other_case_id).active_blocker_candidate_ids) == {"procedure:1", "procedure:4"}


def test_resolution_and_new_blockers_roll_back_together(mysql_engine):
    case_id, _ = new_case(mysql_engine)
    submit(mysql_engine, case_id, reviewed_outcome(case_id))
    outcome = reviewed_outcome(case_id, active=["procedure:1", "procedure:4"], confirmed=True)
    with pytest.raises(ValueError, match="conflict_reference 9999 not found"):
        submit(mysql_engine, case_id, outcome, resolved_conflicts={9999: "PROPOSED"})
    with Session(mysql_engine) as session:
        assert len(rows(session, case_id)) == 2
        assert all(row.status == "ACTIVE" and row.resolved_at is None for row in rows(session, case_id))


def test_legacy_unkeyed_blocker_remains_visible_without_inventing_a_candidate(mysql_engine):
    case_id, _ = new_case(mysql_engine)
    with Session(mysql_engine) as session:
        history = CaseHistory(case_id=case_id, source="USER_INPUT", judgment_status="PENDING")
        session.add(history)
        session.flush()
        session.add(Blocker(case_id=case_id, created_from_case_history_id=history.id,
                           description="예전 판단의 Blocker", blocker_evidence_refs=[]))
        session.commit()
    with Session(mysql_engine) as session:
        assert rows(session, case_id)[0].candidate_id is None
        assert rows(session, case_id)[0].description == "예전 판단의 Blocker"
        assert build_case_snapshot(session, case_id).active_blocker_candidate_ids == []


def test_legacy_single_blocker_outcome_keeps_its_priority_without_a_candidate_id(mysql_engine):
    case_id, _ = new_case(mysql_engine)
    outcome = reviewed_outcome(case_id)
    payload = outcome.review_subject.model_dump(mode="python", exclude={"subject_digest"})
    decision = payload["supervisor_draft"]["decision"]
    decision["blocker"]["candidate_id"] = None
    decision.pop("blockers")
    payload["supervisor_draft"] = type(outcome.review_subject.supervisor_draft).model_validate(
        payload["supervisor_draft"],
    )
    # 후보 식별자를 주지 않던 이전 계약의 PASS를 합성한다. 실제 모델은 부르지 않는다.
    subject = ReviewSubject.create(**payload)
    legacy = ReviewedPlanOutcome(
        outcome_type="REVIEWED_PLAN", review_subject=subject,
        review_proof=outcome.review_proof.model_copy(update={"reviewed_subject_digest": subject.subject_digest}),
    )
    history_id = submit(mysql_engine, case_id, legacy)
    with Session(mysql_engine) as session:
        [stored] = rows(session, case_id)
        assert stored.candidate_id is None
        assert session.get(CaseHistory, history_id).priority_blocker_id == stored.id
        assert stored.description == decision["blocker"]["description"]
        assert build_case_snapshot(session, case_id).active_blocker_candidate_ids == []
