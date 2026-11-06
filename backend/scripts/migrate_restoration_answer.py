"""선택형 원상복구 답변에 필요한 nullable 칸 두 개. 기본 실행은 SQL 출력만 한다.

backend에서 PYTHONPATH=. python scripts/migrate_restoration_answer.py 로 확인하고,
DB 적용을 승인받은 뒤 --apply를 붙인다. 기존 행을 고치거나 표를 초기화하지 않는다.
"""

import argparse

from sqlalchemy import inspect, text

from app.be.db import get_engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="설정된 MySQL DB에 실제 적용")
    args = parser.parse_args()
    columns = {
        "restoration_answer": "JSON NULL",
        "next_action_code": "VARCHAR(100) NULL",
    }
    statements = {name: f"ALTER TABLE case_history ADD COLUMN {name} {definition}"
                  for name, definition in columns.items()}
    if not args.apply:
        for statement in statements.values():
            print(statement + ";")
        print("미리보기만 했습니다. DB에는 연결하지 않았습니다.")
        return
    engine = get_engine()
    if engine.dialect.name != "mysql":
        raise ValueError("MySQL에만 적용할 수 있습니다")
    existing = {item["name"] for item in inspect(engine).get_columns("case_history")}
    # MySQL의 ALTER TABLE은 자체 커밋한다. 중간 실패 후 다시 실행해도 있는 칸은 건너뛴다.
    with engine.connect() as connection:
        for name, statement in statements.items():
            if name not in existing:
                connection.execute(text(statement))
                print(f"추가했습니다: {name}")
        connection.commit()


if __name__ == "__main__":
    main()
