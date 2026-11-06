"""모델(SQLModel)이 만드는 표를 sql/001_schema.sql로 다시 뽑는다: python -m scripts.dump_schema_sql

운영(ENVIRONMENT=prod)은 표를 만들지 않아서(main.lifespan), 빈 DB에는 이 SQL을 넣는다.
손으로 쓰지 않고 뽑는 이유는 코드가 만드는 표와 글자 하나까지 같게 두려는 것이다.
모델을 바꾸면 이걸 돌리고, 맞는지는 tests/test_schema_sql.py가 본다.

Docker가 필요하다(테스트처럼 빈 MySQL을 잠깐 띄운다). 모델 호출은 없다.
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlmodel import SQLModel
from testcontainers.community.mysql import MySqlContainer

import app.main  # noqa: F401  표를 정의한 모델을 모두 불러온다

SCHEMA_SQL = Path(__file__).resolve().parents[1] / "sql" / "001_schema.sql"

HEADER = """\
-- 빈 DB에 표를 처음 만들 때 넣는다. 이미 표가 있으면 "already exists"로 멈추고 아무것도 지우지 않는다.
-- 손으로 고치지 않는다. 모델을 바꾸면 backend에서 python -m scripts.dump_schema_sql 로 다시 뽑는다.
"""


def dump_schema_sql() -> str:
    with MySqlContainer("mysql:8.0", dialect="pymysql", dbname="closure_agent") as container:
        engine = create_engine(container.get_connection_url() + "?charset=utf8mb4")
        try:
            SQLModel.metadata.create_all(engine)
        finally:
            engine.dispose()
        # DROP TABLE은 넣지 않는다. 잘못 넣어도 운영 데이터가 지워지지 않게 한다.
        # case_history ↔ blocker가 서로를 가리켜도, mysqldump가 앞에서 외래키 검사를 꺼서 순서와 상관없이 만들어진다.
        exit_code, output = container.get_wrapped_container().exec_run(
            ["mysqldump", "-uroot", "--no-data", "--skip-comments", "--skip-add-drop-table",
             "--skip-dump-date", "closure_agent"],
            environment={"MYSQL_PWD": container.root_password},
        )
    if exit_code != 0:
        raise RuntimeError(output.decode())
    return HEADER + output.decode()


if __name__ == "__main__":
    SCHEMA_SQL.parent.mkdir(exist_ok=True)
    SCHEMA_SQL.write_text(dump_schema_sql(), encoding="utf-8")
    print(f"다시 뽑았습니다: {SCHEMA_SQL}")
