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

from app.agent.document_tool.documents import DocumentError
from app.agent.document_tool.models import DocumentContext, DocumentFieldName, DocumentKind
from app.agent.document_tool.tool import DocumentTool
from app.be.models.case import Case

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
    # 폐업사실증명원과 맞춰 볼 폐업일은 사장님이 알려 준 실제 날짜, 없으면 가입 때 정한 날짜를 쓴다.
    # 둘 다 서류 JSON에만 남기고 Case·AI 판단에는 넣지 않는다.
    context.applicant_name = applicant_name
    context.closure_date = closure_date or case.planned_closure_date
    try:
        updated = tool.check_documents(context)
    except DocumentError as error:
        raise _rejected(error) from None
    save_context(directory, updated)
    return updated


def settlement_zip(tool: DocumentTool, directory: Path, case: Case) -> bytes:
    try:
        return tool.prepare_settlement(load_context(directory, case))
    except DocumentError as error:
        raise _rejected(error) from None
