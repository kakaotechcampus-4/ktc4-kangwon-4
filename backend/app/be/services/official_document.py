"""공식 자료 본문을 전체가 함께 쓰는 한 벌로 적재한다.

전에는 Case를 만들 때마다 본문을 evidence에 복사했다. 사장님이 늘수록 같은 안내문이
그만큼 쌓이고, 문서를 고치려면 Case 수만큼 다시 써야 했다.

적재는 앱이 뜰 때 한 번 한다(main.lifespan). 절차 표와 같은 이유다 — 전체에 한 벌만
있으면 되는 값이라 요청마다 확인할 이유가 없고, 가입 요청 안에서 적재하면 동시 가입 때
unique에 걸린다.
"""

from sqlmodel import Session, select

from app.agent.procedure_tool.store import ProcedureStoreError, ReviewedProcedureStore
from app.be.models.evidence import OfficialDocument
from app.be.models.mixins import kst_db_time

__all__ = ["ensure_official_documents", "load_official_documents"]


def ensure_official_documents(session: Session, store: ReviewedProcedureStore) -> dict[str, int]:
    """검수 자료의 본문을 적재하고 content_hash → DB id를 돌려준다.

    같은 문서의 같은 버전은 다시 쓰지 않는다. 버전이 올라가면 이 줄을 고치는 것이 아니라
    새 줄이 생긴다. 그래야 예전 Case가 예전 줄을 계속 가리킨다.

    예전 Case를 새 버전으로 옮기는 것은 별개다. 절차조회가 버전이 같은 자료만 고르므로
    (stored_tool.py:73), 옮기려면 그 Case를 다시 적재해야 한다.
    """

    version = store.snapshot_version
    rows = {row.content_hash: row for row in load_official_documents(session, version)}
    stored = {content_hash: row.id for content_hash, row in rows.items()}
    for record in store.records():
        content_hash = record.content_hash.removeprefix("sha256:")
        if content_hash in stored:
            # 해시는 같은데 본문이 다르면 둘 중 하나가 틀린 것이다. 그냥 넘기면 예전 본문이
            # 그대로 남아, 바뀐 줄 아는 사람과 실제로 AI가 읽는 글이 어긋난다.
            if rows[content_hash].excerpt != record.excerpt:
                raise ProcedureStoreError(
                    f"같은 내용 해시({content_hash[:12]}…)에 다른 본문이 저장돼 있습니다."
                )
            continue
        document = OfficialDocument(
            source_ref=record.canonical_url,
            source_version=version,
            excerpt=record.excerpt,
            content_hash=content_hash,
            published_at=kst_db_time(record.published_at),
            retrieved_at=kst_db_time(record.retrieved_at),
        )
        session.add(document)
        session.flush()
        stored[content_hash] = document.id
    return stored


def load_official_documents(session: Session, version: str) -> list[OfficialDocument]:
    """이 버전으로 적재된 공식 자료 전부."""

    return list(
        session.exec(select(OfficialDocument).where(OfficialDocument.source_version == version))
    )
