"""운영 DB에 넣는 sql/ 파일들이 모델이 만드는 표와 같은지. 진짜 MySQL이 필요하다(Docker).

운영은 표를 만들지 않아서(main.lifespan) 이 SQL로 만들고 고친다. 모델만 바꾸고 SQL을 안 뽑으면
테스트는 통과하는데 운영에는 칸이 없어 그 기능이 터진다. 그걸 여기서 막는다. 모델 호출은 없다.
"""

from pathlib import Path

import pymysql
import pytest
from sqlalchemy import create_engine, text
from sqlmodel import SQLModel
from testcontainers.community.mysql import MySqlContainer

import app.main  # noqa: F401  표를 정의한 모델을 모두 불러온다
from scripts.dump_schema_sql import SCHEMA_SQL

DOCUMENT_SUBMITTED_SQL = SCHEMA_SQL.parent / "002_case_history_source_document_submitted.sql"


@pytest.fixture(scope="module")
def mysql():
    with MySqlContainer("mysql:8.0", dialect="pymysql") as container:
        yield container


def _root_url(container: MySqlContainer, database: str) -> str:
    host, port = container.get_container_host_ip(), container.get_exposed_port(3306)
    return f"mysql+pymysql://root:{container.root_password}@{host}:{port}/{database}?charset=utf8mb4"


def _execute(container: MySqlContainer, database: str, sql: str) -> None:
    """운영에서 mysql 클라이언트로 파일을 넣는 것처럼 여러 문장을 한 번에 보낸다."""

    connection = pymysql.connect(
        host=container.get_container_host_ip(), port=int(container.get_exposed_port(3306)),
        user="root", password=container.root_password, database=database,
        client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            while cursor.nextset():
                pass
    finally:
        connection.close()


def _run_file(container: MySqlContainer, database: str, path: Path) -> None:
    _execute(container, database, path.read_text(encoding="utf-8"))


def _new_database(container: MySqlContainer, database: str) -> None:
    _execute(container, "", f"CREATE DATABASE `{database}`")


def _show_create(container: MySqlContainer, database: str) -> dict[str, str]:
    """표마다 SHOW CREATE TABLE. 칸·타입·기본값·ENUM 값·인덱스·외래키·설명이 한 줄에 다 들어 있다."""

    engine = create_engine(_root_url(container, database))
    try:
        with engine.connect() as connection:
            tables = connection.execute(text("SHOW TABLES")).scalars().all()
            return {table: connection.execute(text(f"SHOW CREATE TABLE `{table}`")).one()[1] for table in tables}
    finally:
        engine.dispose()


def test_schema_sql_matches_the_models(mysql):
    _new_database(mysql, "from_code")
    engine = create_engine(_root_url(mysql, "from_code"))
    SQLModel.metadata.create_all(engine)
    engine.dispose()
    _new_database(mysql, "from_sql")
    _run_file(mysql, "from_sql", SCHEMA_SQL)

    assert _show_create(mysql, "from_sql") == _show_create(mysql, "from_code"), (
        "모델과 sql/001_schema.sql이 다릅니다. backend에서 python -m scripts.dump_schema_sql 로 다시 뽑아 주세요."
    )


def test_schema_sql_never_drops_tables():
    # 운영 DB에 잘못 넣어도 데이터가 지워지지 않아야 한다. 이미 표가 있으면 만들다 멈추면 된다.
    assert "DROP " not in SCHEMA_SQL.read_text(encoding="utf-8").upper()


def test_document_submitted_sql_brings_an_old_db_up_to_the_schema(mysql):
    _new_database(mysql, "before_173")
    _run_file(mysql, "before_173", SCHEMA_SQL)
    expected = _show_create(mysql, "before_173")["case_history"]
    # #173 전 모양으로 되돌린다
    _execute(mysql, "before_173", (
        "ALTER TABLE `case_history` MODIFY COLUMN `source` "
        "enum('USER_INPUT','SYSTEM_BATCH','CASE_CREATED','CONFLICT_DECISION') NOT NULL"
    ))
    assert _show_create(mysql, "before_173")["case_history"] != expected

    _run_file(mysql, "before_173", DOCUMENT_SUBMITTED_SQL)
    assert _show_create(mysql, "before_173")["case_history"] == expected

    # 이미 넣은 DB에 다시 넣어도 그대로다
    _run_file(mysql, "before_173", DOCUMENT_SUBMITTED_SQL)
    assert _show_create(mysql, "before_173")["case_history"] == expected
