"""결과 제출→실제 상태 변경→다음 행동 판단 성공을 1회로 센다(#235).

backend에서 PYTHONPATH=. python scripts/count_case_loops.py --case-id 1
--since 2026-11-07T00:00:00 --until 2026-11-08T00:00:00
기간은 판단 완료 시각 기준 KST [since, until). 조회만 하며 모델을 호출하지 않는다.
Case 필드·절차 status 변경을 확인한 건만 센다. 절차의 준비사항 확인·제출 여부만
바뀐 경우에는 과거 값이 이력에 없어 확정 집계할 수 없다. 해당 후보 ID는 따로 낸다.
"""

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

from sqlalchemy import or_
from sqlmodel import Session, select

from app.be.db import get_engine
from app.be.models.case_field_history import CaseFieldHistory
from app.be.models.case_history import CaseHistory
from app.be.models.mixins import KST
from app.be.models.procedure_step import CaseProcedureStep, CaseProcedureStepHistory

COUNT_SCOPE = "Case 필드 또는 절차 status 변경 확인분. 준비사항 확인·제출 여부만의 변경은 이력으로 복원 불가"


def kst_time(value: str) -> datetime:
    """시차가 없으면 KST로 읽고, DB와 같은 시차 없는 KST 시각으로 맞춘다."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ISO 날짜·시각을 입력해 주세요") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(KST)
    return parsed.replace(tzinfo=None)


def loop_history_ids(session: Session, case_id: int, since: datetime, until: datetime) -> tuple[list[int], list[int]]:
    """변경이 확인된 판단 ID와, 같은 status 이력만 있어 변경 여부가 불명확한 ID."""
    if case_id <= 0 or since >= until:
        raise ValueError("양수 Case ID와 시작보다 늦은 종료 시각이 필요합니다")
    # 변경 여러 건을 JOIN하면 같은 제출을 여러 번 세므로, 실제 변경 존재 여부만 본다.
    field_changed = select(CaseFieldHistory.id).where(
        CaseFieldHistory.case_history_id == CaseHistory.id,
        CaseFieldHistory.case_id == CaseHistory.case_id,
        CaseFieldHistory.before_value.is_distinct_from(CaseFieldHistory.after_value),
    ).exists()
    procedure_history = select(CaseProcedureStepHistory.id).join(CaseProcedureStep).where(
        CaseProcedureStepHistory.case_history_id == CaseHistory.id,
        CaseProcedureStep.case_id == CaseHistory.case_id,
    )
    procedure_changed = procedure_history.where(
        CaseProcedureStepHistory.previous_status != CaseProcedureStepHistory.new_status,
    ).exists()
    same_status_history = procedure_history.where(
        CaseProcedureStepHistory.previous_status == CaseProcedureStepHistory.new_status,
    ).exists()
    changed = or_(field_changed, procedure_changed)
    query = select(CaseHistory.id).where(
        CaseHistory.case_id == case_id,
        CaseHistory.source == "USER_INPUT",
        CaseHistory.judgment_status == "DONE",
        CaseHistory.judged_at >= since,
        CaseHistory.judged_at < until,
        CaseHistory.next_action.is_not(None),
        CaseHistory.next_action_code.is_not(None),
    ).order_by(CaseHistory.judged_at, CaseHistory.id)
    with session.no_autoflush:
        confirmed = list(session.exec(query.where(changed)).all())
        ambiguous = list(session.exec(query.where(~changed, same_status_history)).all())
    return confirmed, ambiguous


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", type=int, required=True)
    parser.add_argument("--since", type=kst_time, required=True, help="KST 시작 시각(포함)")
    parser.add_argument("--until", type=kst_time, required=True, help="KST 종료 시각(제외)")
    args = parser.parse_args(argv)
    if args.case_id <= 0 or args.since >= args.until:
        parser.error("양수 Case ID와 시작보다 늦은 종료 시각이 필요합니다")
    code_sha = subprocess.check_output(
        ["git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"], text=True,
    ).strip()
    with Session(get_engine(), autoflush=False) as session:
        history_ids, ambiguous_ids = loop_history_ids(session, args.case_id, args.since, args.until)
    print(json.dumps({
        "code_sha": code_sha, "case_id": args.case_id,
        "since_kst_inclusive": args.since.isoformat(), "until_kst_exclusive": args.until.isoformat(),
        "loop_count": len(history_ids), "case_history_ids": history_ids,
        "count_scope": COUNT_SCOPE, "ambiguous_case_history_ids": ambiguous_ids,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
