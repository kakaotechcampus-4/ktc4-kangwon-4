"""서류 올리기·확인·점검·제출 파일. 실제 처리는 #128의 DocumentTool이 하고, 여기는 Case와 저장만 맡는다.

DocumentTool은 저장을 호출자에게 맡긴다(tool.py 첫 줄). 서류 원본과 가린 PDF를 이미
`AGENT_DOCUMENT_DIR/<Case UUID>/` 폴더에 두므로, Case별 목록·점검 결과도 그 폴더의
JSON 파일 하나에 둔다. DB 테이블을 늘리지 않아 배포 DB를 초기화하지 않아도 된다(발표 전 결정).
"""

import logging
import os
from datetime import date
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from sqlmodel import Session

from app.agent.document_tool.documents import DocumentError
from app.agent.document_tool.models import DocumentContext, DocumentFieldName, DocumentKind
from app.agent.document_tool.tool import DocumentTool
from app.be.crud import case as case_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import conflict_reference as conflict_reference_crud
from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
from app.common.agent_dto import document_replan_text

logger = logging.getLogger(__name__)

CONTEXT_FILE = "case_documents.json"
MAX_UPLOAD_BYTES = 20_000_000


def document_directory() -> Path:
    return Path(os.environ.get("AGENT_DOCUMENT_DIR") or Path.home() / ".cache/reborn/documents")


def document_case_id(case: Case) -> UUID:
    # 도구는 Case를 UUID로 나눈다. dev는 서버를 켤 때마다 표를 지워 Case 번호가 1부터
    # 다시 시작하므로, 가입 시각까지 섞어 예전 Case의 서류 폴더를 다시 쓰지 않게 한다.
    return uuid5(NAMESPACE_URL, f"reborn-case:{case.id}:{case.created_at.isoformat()}")


def load_context(directory: Path, case: Case) -> DocumentContext:
    path = directory / str(document_case_id(case)) / CONTEXT_FILE
    if path.is_file():
        context = DocumentContext.model_validate_json(path.read_bytes())
    else:
        context = DocumentContext(case_id=document_case_id(case))
    # 가게 이름은 점검에서 서류의 상호·공급받는 자와 맞춰 보는 기준이다. 가입 뒤 바뀔 수 있어
    # 저장해 둔 값을 믿지 않고 매번 Case에서 다시 채운다. 신청인 이름·실제 폐업일은 점검 요청 때 받는다.
    context.business_name = case.store_name
    return context


def save_context(directory: Path, context: DocumentContext) -> None:
    path = directory / str(context.case_id) / CONTEXT_FILE
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending = path.with_suffix(".tmp")
    pending.write_text(context.model_dump_json(), encoding="utf-8")
    pending.replace(path)


def _rejected(error: DocumentError) -> HTTPException:
    # DocumentError 문구는 사장님에게 보여 줄 말로 쓰여 있어(예: "현재 Case의 문서가 아닙니다") 그대로 넘긴다
    return HTTPException(status_code=422, detail=str(error))


async def upload_document(
    tool: DocumentTool, directory: Path, case: Case, filename: str, content: bytes, kind: DocumentKind | None,
) -> DocumentContext:
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=422, detail="20MB 이하의 파일을 올려 주세요.")
    try:
        updated = await tool.add_document(load_context(directory, case), filename, content, kind_hint=kind)
    except DocumentError as error:
        raise _rejected(error) from None
    except Exception:  # noqa: BLE001 - 모델·OCR 실패. 제공자 응답 본문을 사장님에게 보이지 않는다
        logger.exception("서류 처리 실패")
        raise HTTPException(status_code=502, detail="서류를 읽지 못했어요. 잠시 뒤 다시 올려 주세요.") from None
    save_context(directory, updated)
    return updated


def confirm_document(
    tool: DocumentTool, directory: Path, case: Case, document_id: UUID,
    kind: DocumentKind, confirmed_fields: dict[DocumentFieldName, str],
) -> DocumentContext:
    try:
        updated = tool.confirm_document(
            load_context(directory, case), document_id, kind, confirmed_fields=confirmed_fields,
        )
    except DocumentError as error:
        raise _rejected(error) from None
    save_context(directory, updated)
    return updated


def remove_document(tool: DocumentTool, directory: Path, case: Case, document_id: UUID) -> DocumentContext:
    try:
        updated = tool.remove_document(load_context(directory, case), document_id)
    except DocumentError as error:
        raise _rejected(error) from None
    save_context(directory, updated)
    return updated


def check_documents(
    tool: DocumentTool, directory: Path, case: Case, applicant_name: str, closure_date: date | None,
) -> DocumentContext:
    context = load_context(directory, case)
    # 이체확인증의 보낸 사람과 맞춰 볼 신청인 이름은 서비스가 받는 칸이 없어 점검 직전에 사장님께 묻는다.
    # 폐업사실증명원과 맞춰 볼 폐업일은 사장님이 실제 날짜라고 확인한 값만 쓴다.
    # 가입 때 정한 폐업 예정일(planned_closure_date)은 실제 폐업일과 다른 사실이라 대신 쓰지 않는다.
    # 비우면 점검이 CLOSURE_DATE_UNCONFIRMED로 막는다.
    # 둘 다 서류 JSON에만 남기고 Case·AI 판단에는 넣지 않는다.
    context.applicant_name = applicant_name
    context.closure_date = closure_date
    try:
        updated = tool.check_documents(context)
    except DocumentError as error:
        raise _rejected(error) from None
    save_context(directory, updated)
    return updated


def queue_document_judgment(
    session: Session, member_id: int, before: DocumentContext, after: DocumentContext,
) -> int | None:
    """서류가 바뀌어 다시 판단해야 하면 판단 이력을 PENDING으로 남기고 그 번호를 돌려준다.

    원상복구 조항이 새로 생기거나 바뀐 때만 판단한다(document_replan_text). 같은 조항의
    재업로드·금액 서류 추가·서류 빼기는 None이라 판단하지 않는다.
    판단을 부르는 일은 라우터가 응답 뒤에 한다. 결과는 홈(GET /cases)이 PENDING을 보고 다시 묻는다.
    """

    text = document_replan_text(before, after)
    if text is None:
        return None

    # 결과 제출(case.submit_case_results)과 같은 이유로 Case를 잠그고 확인한다.
    # 같은 Case에 PENDING이 둘 생기면 판단이 서로의 결과를 덮는다.
    case = case_crud.lock_case_by_member_id(session, member_id)
    blocked = _judgment_blocked_reason(session, case)
    if blocked is not None:
        # 서류 저장은 이미 끝났으므로 요청을 실패시키지 않고 판단만 건너뛴다.
        # TODO: 건너뛴 사실을 사장님께 알릴 방법(응답 칸·기록)은 발표 뒤 팀과 정한다.
        logger.warning("Case %s 서류 재판단 건너뜀: %s", case.id if case else None, blocked)
        return None

    history = case_history_crud.create_case_history(
        session,
        CaseHistory(case_id=case.id, raw_input=text, source="DOCUMENT_SUBMITTED", judgment_status="PENDING"),
    )
    session.commit()
    return history.id


def _judgment_blocked_reason(session: Session, case: Case | None) -> str | None:
    """지금 판단을 새로 돌릴 수 없으면 그 이유. 결과 제출이 409로 막는 경우와 같다."""

    if case is None:
        return "Case 없음"
    if case.case_status == "COMPLETED":
        return "폐업 정리를 마친 Case"
    if conflict_reference_crud.get_pending_conflicts_by_case_id(session, case.id):
        return "확인 대기 중인 충돌"
    latest = case_history_crud.get_latest_user_driven_case_history(session, case.id)
    if latest is not None and latest.judgment_status == "PENDING":
        return "직전 판단 처리 중"
    return None


def settlement_zip(tool: DocumentTool, directory: Path, case: Case) -> bytes:
    try:
        return tool.prepare_settlement(load_context(directory, case))
    except DocumentError as error:
        raise _rejected(error) from None
