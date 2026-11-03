from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlmodel import Session

from app.agent.document_tool.models import DocumentKind
from app.agent.document_tool.tool import DocumentTool, build_document_tool
from app.be.crud import case as case_crud
from app.be.db import get_db
from app.be.dependencies.auth import get_current_member_id
from app.be.models.case import Case
from app.be.schemas.document import (
    DocumentCheckRequest,
    DocumentConfirmRequest,
    DocumentListResponse,
    document_list_response,
)
from app.be.services import document as document_service

router = APIRouter()


def get_document_directory() -> Path:
    return document_service.document_directory()


async def get_document_tool(directory: Path = Depends(get_document_directory)) -> AsyncIterator[DocumentTool]:
    # 정산 서류는 기관에 내는 자료라 계좌·사업자번호를 남기고 주민번호 뒷자리만 가린다(#128 평가와 같은 기준)
    tool = await build_document_tool(directory, submission_policy="RRN_BACK_ONLY")
    try:
        yield tool
    finally:
        await tool.aclose()


def _current_case(session: Session, member_id: int) -> Case:
    case = case_crud.get_case_by_member_id(session, member_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case를 찾을 수 없습니다.")
    return case


@router.get("/cases/documents", response_model=DocumentListResponse)
def list_documents(
    member_id: int = Depends(get_current_member_id),
    session: Session = Depends(get_db),
    directory: Path = Depends(get_document_directory),
):
    case = _current_case(session, member_id)
    return document_list_response(document_service.load_context(directory, case))


@router.post("/cases/documents", response_model=DocumentListResponse)
async def upload_document(
    file: UploadFile = File(...),
    # 사장님이 "이체확인증 올리기"처럼 고르고 올렸으면 그 종류. 서류함에서 그냥 올리면 비워 AI가 나눈다.
    kind: DocumentKind | None = Form(default=None),
    member_id: int = Depends(get_current_member_id),
    session: Session = Depends(get_db),
    directory: Path = Depends(get_document_directory),
    tool: DocumentTool = Depends(get_document_tool),
):
    # 값 꺼내기에 모델·OCR을 써서 수십 초 걸린다. 시연에서는 한 장씩 올리므로 끝날 때까지 기다려 결과를 돌려준다.
    case = _current_case(session, member_id)
    content = await file.read(document_service.MAX_UPLOAD_BYTES + 1)
    context = await document_service.upload_document(
        tool, directory, case, file.filename or "document", content, kind,
    )
    return document_list_response(context)


@router.post("/cases/documents/{document_id}/confirm", response_model=DocumentListResponse)
def confirm_document(
    document_id: UUID,
    confirm_request: DocumentConfirmRequest,
    member_id: int = Depends(get_current_member_id),
    session: Session = Depends(get_db),
    directory: Path = Depends(get_document_directory),
    tool: DocumentTool = Depends(get_document_tool),
):
    case = _current_case(session, member_id)
    context = document_service.confirm_document(
        tool, directory, case, document_id, confirm_request.kind, confirm_request.confirmed_fields,
    )
    return document_list_response(context)


@router.delete("/cases/documents/{document_id}", response_model=DocumentListResponse)
def remove_document(
    document_id: UUID,
    member_id: int = Depends(get_current_member_id),
    session: Session = Depends(get_db),
    directory: Path = Depends(get_document_directory),
    tool: DocumentTool = Depends(get_document_tool),
):
    case = _current_case(session, member_id)
    return document_list_response(document_service.remove_document(tool, directory, case, document_id))


@router.post("/cases/documents/check", response_model=DocumentListResponse)
def check_documents(
    check_request: DocumentCheckRequest,
    member_id: int = Depends(get_current_member_id),
    session: Session = Depends(get_db),
    directory: Path = Depends(get_document_directory),
    tool: DocumentTool = Depends(get_document_tool),
):
    # 점검은 규칙만 돌고 모델을 부르지 않는다(checks.check_settlement)
    case = _current_case(session, member_id)
    context = document_service.check_documents(
        tool, directory, case, check_request.applicant_name, check_request.closure_date,
    )
    return document_list_response(context)


@router.get("/cases/documents/settlement.zip")
def download_settlement(
    member_id: int = Depends(get_current_member_id),
    session: Session = Depends(get_db),
    directory: Path = Depends(get_document_directory),
    tool: DocumentTool = Depends(get_document_tool),
):
    case = _current_case(session, member_id)
    content = document_service.settlement_zip(tool, directory, case)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="settlement.zip"'},
    )
