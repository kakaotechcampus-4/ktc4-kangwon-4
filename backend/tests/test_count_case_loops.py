"""격리 MySQL의 합성 이력만 사용한다. 모델·운영 DB 호출은 없다."""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event
from sqlmodel import Session, select

from app.be.models.case_field_history import CaseFieldHistory
from app.be.models.case_history import CaseHistory
from app.be.models.procedure_step import CaseProcedureStep, CaseProcedureStepHistory
from scripts import count_case_loops as script
from case_world import case_engine, case_world  # noqa: F401

START = datetime(2026, 11, 7)
END = START + timedelta(days=1)


def history(session, case_id, *, source="USER_INPUT", status="DONE", at=START, changed=True):
    row = CaseHistory(case_id=case_id, source=source, judgment_status=status, judged_at=at,
                      next_action="합성 다음 행동", next_action_code="CONFIRM_RESTORATION_SCOPE")
    session.add(row)
    session.flush()
    if changed:
        field_change(session, row, None, "FULL")
    return row


def field_change(session, row, before, after, case_id=None):
    session.add(CaseFieldHistory(case_id=case_id or row.case_id, case_history_id=row.id,
                                canonical_field="restoration_scope", before_value=before,
                                after_value=after, source="INFO_ANALYSIS"))


def test_two_rounds_count_each_submission_once_and_cli_only_selects(case_engine, case_world, monkeypatch, capsys):
    _, case_id, _ = case_world.sign_up()
    with Session(case_engine) as session:
        first = history(session, case_id)
        field_change(session, first, "FULL", "PARTIAL")  # 같은 판단의 여러 변경
        second = history(session, case_id, changed=False)
        step = session.exec(select(CaseProcedureStep).where(CaseProcedureStep.case_id == case_id)).first()
        for previous, new in [("NOT_STARTED", "IN_PROGRESS"), ("IN_PROGRESS", "COMPLETED")]:
            session.add(CaseProcedureStepHistory(case_procedure_step_id=step.id, case_history_id=second.id,
                                                previous_status=previous, new_status=new))
        duplicate = history(session, case_id, changed=False)
        field_change(session, duplicate, "PARTIAL", "PARTIAL")
        field_change(session, duplicate, None, None)
        session.add(CaseProcedureStepHistory(case_procedure_step_id=step.id, case_history_id=duplicate.id,
                                            previous_status="COMPLETED", new_status="COMPLETED"))
        expected, ambiguous = [first.id, second.id], [duplicate.id]
        session.commit()
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)
    event.listen(case_engine, "before_cursor_execute", capture)
    try:
        monkeypatch.setattr(script, "get_engine", lambda: case_engine)
        script.main(["--case-id", str(case_id), "--since", START.isoformat(), "--until", END.isoformat()])
    finally:
        event.remove(case_engine, "before_cursor_execute", capture)
    report = json.loads(capsys.readouterr().out)
    assert report["loop_count"] == 2 and report["case_history_ids"] == expected
    assert report["ambiguous_case_history_ids"] == ambiguous  # 같은 status는 확정 수에 포함하지 않는다
    assert "복원 불가" in report["count_scope"]
    assert report["case_id"] == case_id and len(report["code_sha"]) == 40
    assert statements and all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    assert set(report) == {"code_sha", "case_id", "since_kst_inclusive", "until_kst_exclusive",
                           "loop_count", "case_history_ids", "count_scope", "ambiguous_case_history_ids"}


@pytest.mark.parametrize("source,status", [
    ("CASE_CREATED", "DONE"), ("CONFLICT_DECISION", "DONE"), ("DOCUMENT_SUBMITTED", "DONE"),
    ("SYSTEM_BATCH", "DONE"), ("USER_INPUT", "NEEDS_MORE_INFO"), ("USER_INPUT", "FAILED"),
    ("USER_INPUT", "PENDING"), ("USER_INPUT", "CONFLICT"),
])
def test_non_rounds_are_excluded_even_with_changes(case_engine, case_world, source, status):
    _, case_id, _ = case_world.sign_up()
    with Session(case_engine) as session:
        history(session, case_id, source=source, status=status)
        session.commit()
        assert script.loop_history_ids(session, case_id, START, END) == ([], [])


def test_window_other_case_missing_judgment_and_retry(case_engine, case_world):
    _, case_id, _ = case_world.sign_up()
    _, other_case, _ = case_world.sign_up()
    with Session(case_engine) as session:
        for at in [START - timedelta(seconds=1), END, None]:
            history(session, case_id, at=at)
        history(session, other_case)
        row = history(session, case_id)
        row.next_action_code = None
        row = history(session, case_id)
        row.next_action = None
        wrong_case = history(session, case_id, changed=False)
        field_change(session, wrong_case, None, "FULL", case_id=other_case)
        step = session.exec(select(CaseProcedureStep).where(CaseProcedureStep.case_id == other_case)).first()
        session.add(CaseProcedureStepHistory(case_procedure_step_id=step.id, case_history_id=wrong_case.id,
                                            previous_status="NOT_STARTED", new_status="COMPLETED"))
        failed = history(session, case_id, status="FAILED")
        retried = history(session, case_id)  # 재시도 성공 건만 한 번, 이전 실패는 제외
        expected = [retried.id]
        session.commit()
        assert script.loop_history_ids(session, case_id, START, END) == (expected, [])
        assert session.get(CaseHistory, failed.id).judgment_status == "FAILED"


def test_kst_window_validation_does_not_connect(monkeypatch):
    assert script.kst_time("2026-11-06T15:00:00Z") == START
    assert script.kst_time("2026-11-07") == START
    monkeypatch.setattr(script, "get_engine", lambda: pytest.fail("invalid input connected to DB"))
    for case_id, since, until in [("0", "2026-11-07", "2026-11-08"),
                                  ("1", "2026-11-08", "2026-11-07"), ("1", "bad", "2026-11-08")]:
        with pytest.raises(SystemExit) as exc:
            script.main(["--case-id", case_id, "--since", since, "--until", until])
        assert exc.value.code == 2
