"""시연 계정을 가입 전으로 되돌리는 sql/reset_member_case.sql. 진짜 MySQL이 필요하다(Docker).

판단을 돌리지 않고 Case에 딸린 표마다 행을 직접 넣은 뒤 SQL을 그대로 넣어 본다. 모델 호출은 없다.
"""

import re
from pathlib import Path

import pymysql
import pytest
from sqlalchemy import text
from sqlmodel import Session

from case_world import case_engine, case_world  # noqa: F401

RESET_SQL = Path(__file__).resolve().parents[1] / "sql" / "reset_member_case.sql"


def _reset(engine, member_id: int | None) -> None:
    """운영에서 mysql 클라이언트로 넣는 것처럼 파일 전체를 한 번에 보낸다. 회원 번호는 --init-command처럼 접속할 때 넘긴다."""

    url = engine.url
    connection = pymysql.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, database=url.database,
        init_command=None if member_id is None else f"SET @member_id = {member_id}",
        client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS,
        # mysql 클라이언트는 문장마다 바로 저장한다. pymysql 기본값(모아 두었다 닫을 때 버림)으로 두면
        # SQL 안의 START TRANSACTION이 없어도 검사가 통과해 버린다
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(RESET_SQL.read_text(encoding="utf-8"))
            while cursor.nextset():
                pass
    finally:
        connection.close()


def _fill_every_case_table(engine, case_id: int, history_id: int, support_item_id: int) -> None:
    """case_world가 만들지 않는 표에도 한 줄씩 넣는다. 지울 게 있어야 지웠는지 볼 수 있다."""

    with Session(engine) as session:
        run = lambda sql, **values: session.execute(text(sql), {"case_id": case_id, **values})  # noqa: E731
        for evidence_id in ("a", "b"):
            run("INSERT INTO evidence (evidence_id, case_id, source_type, source_ref, retrieved_at, freshness_status)"
                " VALUES (:evidence_id, :case_id, 'USER_INPUT', 'test', NOW(), 'CURRENT')",
                evidence_id=f"{case_id}-{evidence_id}")
        run("INSERT INTO evidence_lineage (evidence_id, parent_evidence_id)"
            " SELECT MAX(id), MIN(id) FROM evidence WHERE case_id = :case_id")
        run("INSERT INTO decision_record (case_id, case_history_id, run_id, snapshot_id, review_subject_id,"
            " review_attempt, verdict, decision_type, human_confirmation_required, reviewed_at)"
            " VALUES (:case_id, :history_id, 'run', 'snapshot', 'subject', 1, 'PASS', 'NEXT_ACTION', 0, NOW())",
            history_id=history_id)
        run("INSERT INTO case_checklist (case_id, task_id) VALUES (:case_id, 'vat_submission')")
        run("INSERT INTO case_checklist_history (case_id, task_id, completed) VALUES (:case_id, 'vat_submission', 1)")
        run("INSERT INTO case_document_history (case_id, action) VALUES (:case_id, 'UPLOADED')")
        run("INSERT INTO case_procedure_step_history (case_procedure_step_id, case_history_id, previous_status, new_status)"
            " SELECT MIN(id), :history_id, 'NOT_STARTED', 'IN_PROGRESS' FROM case_procedure_step WHERE case_id = :case_id",
            history_id=history_id)
        run("INSERT INTO support_item_application (case_id, support_item_id) VALUES (:case_id, :item)", item=support_item_id)
        run("INSERT INTO support_match (case_id, support_item_id, match_status) VALUES (:case_id, :item, 'POSSIBLY_RELEVANT')",
            item=support_item_id)
        session.commit()


def _shared_support_item(engine) -> int:
    with Session(engine) as session:
        session.execute(text("INSERT INTO support_item (uuid, program_name) VALUES (UUID(), '철거비 지원')"))
        session.commit()
        return session.execute(text("SELECT MAX(id) FROM support_item")).scalar_one()


def _case_tables(engine) -> set[str]:
    """Case에 딸린 표. case를 바로 또는 건너서(case_history·evidence 등) 가리키는 표를 외래키로 따라간다."""

    with Session(engine) as session:
        references = session.execute(text(
            "SELECT table_name, referenced_table_name FROM information_schema.key_column_usage"
            " WHERE table_schema = DATABASE() AND referenced_table_name IS NOT NULL"
        )).all()
    found = {"case"}
    while True:
        more = {table for table, referenced in references if referenced in found} - found
        if not more:
            return found
        found |= more


def _rows_of(engine, case_id: int) -> dict[str, int]:
    """표마다 이 Case에 딸린 행 수."""

    counts = {
        "evidence_lineage": "SELECT COUNT(*) FROM evidence_lineage WHERE evidence_id IN"
                            " (SELECT id FROM evidence WHERE case_id = :case_id)",
        "case_procedure_step_history": "SELECT COUNT(*) FROM case_procedure_step_history WHERE case_procedure_step_id IN"
                                       " (SELECT id FROM case_procedure_step WHERE case_id = :case_id)",
        "case": "SELECT COUNT(*) FROM `case` WHERE id = :case_id",
    }
    with Session(engine) as session:
        return {
            table: session.execute(
                text(counts.get(table, f"SELECT COUNT(*) FROM `{table}` WHERE case_id = :case_id")), {"case_id": case_id}
            ).scalar_one()
            for table in sorted(_case_tables(engine))
        }


def test_reset_removes_only_that_members_case(case_world):
    item = _shared_support_item(case_world.engine)
    cases = {}
    for name in ("demo", "other"):
        member_id, case_id, history_id = case_world.sign_up()
        case_world.add_conflict(case_id, history_id)
        case_world.add_change(case_id, history_id)
        _fill_every_case_table(case_world.engine, case_id, history_id, item)
        cases[name] = (member_id, case_id)
    other_before = _rows_of(case_world.engine, cases["other"][1])
    # 모든 표에 행이 있어야 지웠는지 볼 수 있다
    assert all(_rows_of(case_world.engine, cases["demo"][1]).values()) and all(other_before.values())

    _reset(case_world.engine, cases["demo"][0])

    assert not any(_rows_of(case_world.engine, cases["demo"][1]).values())
    assert _rows_of(case_world.engine, cases["other"][1]) == other_before
    with Session(case_world.engine) as session:
        # 같은 카카오 계정으로 다시 로그인할 수 있게 회원은 남고, 같이 쓰는 지원 항목도 남는다
        assert session.execute(text("SELECT COUNT(*) FROM members WHERE id = :id"), {"id": cases["demo"][0]}).scalar_one()
        assert session.execute(text("SELECT COUNT(*) FROM support_item WHERE id = :id"), {"id": item}).scalar_one()


def test_reset_of_a_member_without_a_case_changes_nothing(case_world):
    _, case_id, _ = case_world.sign_up()
    before = _rows_of(case_world.engine, case_id)

    _reset(case_world.engine, case_world.stranger())

    assert _rows_of(case_world.engine, case_id) == before


def test_reset_without_a_member_id_changes_nothing(case_world):
    # --init-command를 빠뜨려도 아무것도 지우지 않는다
    _, case_id, _ = case_world.sign_up()
    before = _rows_of(case_world.engine, case_id)

    _reset(case_world.engine, None)

    assert _rows_of(case_world.engine, case_id) == before


def test_reset_that_fails_halfway_deletes_nothing(case_world):
    # 빠진 표가 있으면 case를 못 지워 멈춘다. 그때 앞에서 지운 것도 되돌아가야 반쯤 지워진 Case가 안 남는다
    member_id, case_id, _ = case_world.sign_up()
    before = _rows_of(case_world.engine, case_id)
    with Session(case_world.engine) as session:
        session.execute(text("CREATE TABLE not_in_reset (case_id BIGINT NOT NULL, FOREIGN KEY (case_id) REFERENCES `case` (id))"))
        session.execute(text("INSERT INTO not_in_reset VALUES (:case_id)"), {"case_id": case_id})
        session.commit()
    try:
        with pytest.raises(pymysql.err.IntegrityError):
            _reset(case_world.engine, member_id)
        assert {table: count for table, count in _rows_of(case_world.engine, case_id).items()
                if table != "not_in_reset"} == before
    finally:
        with Session(case_world.engine) as session:
            session.execute(text("DROP TABLE not_in_reset"))
            session.commit()


def test_every_case_table_is_in_the_reset_sql(case_engine):
    # Case를 가리키는 표가 새로 생겼는데 여기 없으면, 그 표 때문에 case를 못 지워 초기화가 통째로 실패한다
    deleted = set(re.findall(r"DELETE FROM `?(\w+)`?", RESET_SQL.read_text(encoding="utf-8")))

    assert _case_tables(case_engine) == deleted, "sql/reset_member_case.sql에 빠진 표가 있습니다."
