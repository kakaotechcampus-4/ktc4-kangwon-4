"""BE 저장 함수로 검수 자료를 재적재: python -m scripts.import_reviewed_procedures --case-id 1.

본문 자체는 official_document 한 줄에만 있으므로(2026-11), 문서 글자를 고치려고 Case마다
돌릴 일은 없어졌다. 남은 쓰임은 **버전을 올렸을 때 예전 Case를 새 버전으로 옮기는 것**이다 —
절차조회가 Case 근거의 source_version이 지금 검수 목록 버전과 같은 자료만 고르기 때문에
(stored_tool.py:73), 옮기지 않으면 그 Case는 조용히 "자료 없음"이 된다.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from sqlmodel import Session

from app.be.models.mixins import KST
from app.be.services.reviewed_procedure import (
    import_reviewed_procedures,
    load_reviewed_procedures,
)
from app.common.agent_data import load_reviewed_procedure_store


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
    from app.be.db import get_engine

    with Session(get_engine()) as session:
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
