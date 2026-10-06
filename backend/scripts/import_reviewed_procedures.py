"""DB 검수 자료를 Case에 적재: python -m scripts.import_reviewed_procedures --case-id 1."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime

from sqlmodel import Session

from app.agent.procedure_tool.store import ProcedureStoreError
from app.agent.schemas import ProcedureStepRef
from app.be.crud import procedure_step as procedure_step_crud
from app.be.models.mixins import KST
from app.be.models.procedure_step import ProcedureStep
from app.common.agent_data import (
    build_known_procedure_steps,
    build_reviewed_procedure_store,
    import_reviewed_procedures,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", type=int, required=True)
    parser.add_argument(
        "--binding", action="append", default=[], metavar="LOGICAL_CODE=DB_STEP_CODE",
        help="확정된 절차 대응. 생략하면 동일한 코드만 연결하며 이름으로 추정하지 않습니다.",
    )
    args = parser.parse_args()
    if "reviewed_source_snapshot" not in ProcedureStep.model_fields:
        raise ProcedureStoreError("BE의 procedure_step 검수 자료 컬럼 반영이 필요합니다.")
    # Only an explicit CLI invocation configures a DB connection; never reset tables.
    from app.be.db import _engine

    with Session(_engine) as session:
        try:
            steps = procedure_step_crud.get_all_procedure_steps(session)
            known = build_known_procedure_steps(
                steps, procedure_step_crud.get_all_step_dependencies(session),
                procedure_step_crud.get_all_step_eligibilities(session), db_timezone=KST,
            )
            bindings = parse_bindings(args.binding, {
                item.procedure_step.step_code: item.procedure_step for item in known
            })
            store = build_reviewed_procedure_store(
                {row.step_code: row.reviewed_source_snapshot for row in steps
                 if row.reviewed_source_snapshot is not None},
                known_procedure_steps=known, procedure_bindings=bindings,
            )
            rows = import_reviewed_procedures(
                session, args.case_id, store, as_of=datetime.now(KST).date()
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
    print(f"Case {args.case_id}: 검수 자료 {len(rows)}건 저장 확인")


def parse_bindings(
    values: list[str], refs: Mapping[str, ProcedureStepRef],
) -> dict[str, ProcedureStepRef] | None:
    """Resolve explicitly supplied codes against persisted procedure references."""
    if not values:
        return None
    bindings = {}
    for value in values:
        logical, separator, actual = value.partition("=")
        if not separator or not logical or actual not in refs or logical in bindings:
            raise ProcedureStoreError("--binding에는 중복 없는 논리 코드=등록된 DB 코드가 필요합니다.")
        bindings[logical] = refs[actual]
    return bindings


if __name__ == "__main__":
    main()
