"""검수된 절차 문서를 BE가 보관하고 AI에 넘긴다.

문서 본문은 app/common/reviewed-procedures.ko-KR.json에 들어 있다. AI는 그 파일을
직접 읽지 않고, BE가 Case의 evidence로 저장해 스냅샷에 담아 넘긴 것만 쓴다
(app/agent/procedure_tool/stored_tool.py). 그래서 Case를 만들 때 한 번 적재해 둔다.

적재 함수는 원래 app/common/agent_data.py에 있었다. BE Session으로 BE 테이블에 쓰고
AI 쪽에서는 부르지 않아서, 저장은 BE가 맡기로 하고 여기로 옮겼다.
"""

import json
from datetime import date, datetime
from hashlib import sha256

from sqlmodel import Session

from app.agent.procedure_tool.store import (
    ProcedureStoreError,
    ReviewedProcedureRecord,
    ReviewedProcedureStore,
)
from app.be.crud import case as case_crud
from app.be.crud import evidence as evidence_crud
from app.be.models.evidence import Evidence
from app.be.models.mixins import KST
from app.common.agent_data import load_reviewed_procedures

__all__ = ["import_reviewed_procedures", "load_reviewed_procedures"]


def import_reviewed_procedures(
    session: Session,
    case_id: int,
    store: ReviewedProcedureStore,
    *,
    as_of: date,
) -> list[Evidence]:
    """검수 자료를 기존 Case에 저장한다. commit/rollback은 호출자가 수행한다.

    같은 버전의 같은 자료는 다시 쓰지 않으며, 변경하려면 새 버전이 필요하다.
    MySQL DATETIME의 초 정밀도와 BE의 KST 저장 규칙에 맞춰 시각을 저장한다.
    """
    if type(case_id) is not int or case_id <= 0:
        raise ValueError("case_id must be a positive integer")
    if type(as_of) is not date:
        raise TypeError("as_of must be a date")
    version = store.snapshot_version
    if not isinstance(version, str) or not version:
        raise ProcedureStoreError("검수 자료 버전이 필요합니다.")
    rows: list[Evidence] = []
    seen: set[str] = set()
    for item in store.records():
        record = ReviewedProcedureRecord.model_validate(item.model_dump(mode="python"))
        if record.reviewed_by is None or record.reviewed_at is None:
            raise ProcedureStoreError("사람이 검수한 자료만 저장할 수 있습니다.")
        identity = json.dumps([case_id, version, record.record_id], ensure_ascii=False)
        evidence_id = "procedure:" + sha256(identity.encode("utf-8")).hexdigest()
        if evidence_id in seen:
            raise ProcedureStoreError("검수 자료 식별자가 중복됐습니다.")
        seen.add(evidence_id)
        payload = {
            "evidence_id": evidence_id,
            "case_id": case_id,
            "source_type": "OFFICIAL_DOCUMENT",
            "source_ref": record.canonical_url,
            "source_version": version,
            "locator": record.canonical_url,
            "excerpt": record.excerpt,
            "published_at": _procedure_db_time(record.published_at),
            "retrieved_at": _procedure_db_time(record.retrieved_at),
            "freshness_status": record.freshness(as_of).value,
            "content_hash": record.content_hash.removeprefix("sha256:"),
        }
        for field, value in payload.items():
            limit = getattr(Evidence.__table__.c[field].type, "length", None)
            if isinstance(value, str) and limit is not None and len(value) > limit:
                raise ProcedureStoreError(f"검수 자료가 DB 필드 길이를 초과했습니다: {field}")
        rows.append(Evidence.model_validate(payload))

    # 입력을 다 검증하기 전에 읽기가 보류된 작업을 flush하지 않도록 막는다.
    with session.no_autoflush:
        if case_crud.get_case_by_id(session, case_id) is None:
            raise ProcedureStoreError("자료를 저장할 Case가 없습니다.")
        existing = {
            row.evidence_id: row
            for row in evidence_crud.get_evidence_by_case_id(session, case_id)
        }
    for row in rows:
        previous = existing.get(row.evidence_id)
        if previous is not None:
            fields = row.model_dump(exclude={"id", "created_at"})
            if any(getattr(previous, key) != value for key, value in fields.items()):
                raise ProcedureStoreError("같은 검수 자료 ID에 다른 내용이 저장돼 있습니다.")
    return [
        existing[row.evidence_id]
        if row.evidence_id in existing
        else evidence_crud.create_evidence(session, row)
        for row in rows
    ]


def _procedure_db_time(value: datetime | None) -> datetime | None:
    return (
        None
        if value is None
        else value.astimezone(KST).replace(tzinfo=None, microsecond=0)
    )
