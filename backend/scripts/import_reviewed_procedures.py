"""검수 원본을 기존 Case에 적재: cd backend && python -m scripts.import_reviewed_procedures --case-id 1."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from sqlmodel import Session

from app.be.models.mixins import KST
from app.common.agent_data import (
    import_reviewed_procedures,
    load_reviewed_procedure_store,
    load_reviewed_procedures,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", type=int, required=True)
    parser.add_argument("--source", type=Path, help="검수 JSON 경로. 생략하면 동봉 자료 사용")
    args = parser.parse_args()
    store = (
        load_reviewed_procedure_store(json.loads(args.source.read_text(encoding="utf-8")))
        if args.source
        else load_reviewed_procedures()
    )
    # Only an explicit CLI invocation configures a DB connection; never reset tables.
    from app.be.db import _engine

    with Session(_engine) as session:
        try:
            rows = import_reviewed_procedures(
                session, args.case_id, store, as_of=datetime.now(KST).date()
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
    print(f"Case {args.case_id}: 검수 자료 {len(rows)}건 저장 확인")


if __name__ == "__main__":
    main()
