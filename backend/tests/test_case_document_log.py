"""서류를 올리고 점검한 것이 기록 탭(GET /cases/logs)에 남는지. 진짜 MySQL이 필요하다(Docker).

모델은 document_fixtures의 가짜 응답을 쓴다. 저장(case_document_history)과 기록 조회만 실제 DB로 본다.
"""

import asyncio
from datetime import date

import pytest
from sqlmodel import Session

from app.agent.document_tool.documents import DocumentService
from app.agent.document_tool.models import DocumentKind
from app.agent.document_tool.tool import DocumentTool
from app.be.crud import case as case_crud
from app.be.services import document as document_service
from app.be.services.case import get_case_logs
from case_world import case_engine, case_world  # noqa: F401
from document_fixtures import DocumentClient, document_pdf

SETTLEMENT = {
    DocumentKind.CONSTRUCTION_STATEMENT: {"amount": "3,300,000원", "supplier": "그린철거", "buyer": "봄날개인카페"},
    DocumentKind.TAX_INVOICE: {"supply_amount": "3,000,000원", "tax_amount": "300,000원", "supplier": "그린철거", "buyer": "봄날개인카페"},
    DocumentKind.BEFORE_PHOTO: {},
    DocumentKind.AFTER_PHOTO: {},
    DocumentKind.CLOSURE_CERTIFICATE: {"closure_date": "2026년 10월 31일"},
}
TRANSFER = {"amount": "3,300,000원", "sender": "김리본", "recipient": "그린철거"}


@pytest.fixture
def documents(tmp_path, case_world):
    member_id, case_id, _ = case_world.sign_up()
    # 점검은 서류의 공급받는 자를 가게 이름과 맞춰 본다
    with Session(case_world.engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        case.store_name = "봄날개인카페"
        session.commit()
    tool = DocumentTool(DocumentService(tmp_path / "vault", DocumentClient(), reviewer=DocumentClient(),
                                        submission_policy="RRN_BACK_ONLY"))
    return case_world.engine, member_id, tool, tmp_path / "vault"


def _upload(engine, member_id, tool, directory, kind, fields, content=None):
    with Session(engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        return asyncio.run(document_service.upload_document(
            session, tool, directory, case, f"{kind}.pdf", content or document_pdf(kind, **fields), None,
        ))


def _check(engine, member_id, tool, directory):
    with Session(engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        return document_service.check_documents(session, tool, directory, case, "김리본", date(2026, 10, 31))


def _document_logs(engine, member_id):
    with Session(engine) as session:
        return [
            (log.actor, log.event, log.detail) for log in get_case_logs(session, member_id).logs
            if log.event in {"DOCUMENT_UPLOADED", "DOCUMENTS_CHECKED"}
        ]


def test_upload_is_logged_with_its_kind(documents):
    engine, member_id, tool, directory = documents
    _upload(engine, member_id, tool, directory, DocumentKind.TRANSFER, TRANSFER)

    assert _document_logs(engine, member_id) == [("OWNER", "DOCUMENT_UPLOADED", "TRANSFER")]


def test_same_file_uploaded_again_is_logged_once(documents):
    engine, member_id, tool, directory = documents
    # 가짜 PDF는 만들 때마다 내용이 달라져서, 같은 파일을 두 번 올리려면 한 번 만든 것을 다시 쓴다
    content = document_pdf(DocumentKind.TRANSFER, **TRANSFER)
    _upload(engine, member_id, tool, directory, DocumentKind.TRANSFER, TRANSFER, content)
    # 110초에 끊긴 뒤 같은 파일을 다시 올리는 경우. 도구는 같은 서류로 보고 목록에 더하지 않는다
    again = _upload(engine, member_id, tool, directory, DocumentKind.TRANSFER, TRANSFER, content)

    assert len(again.documents) == 1

    assert _document_logs(engine, member_id) == [("OWNER", "DOCUMENT_UPLOADED", "TRANSFER")]


def test_removed_document_stays_in_log(documents):
    engine, member_id, tool, directory = documents
    uploaded = _upload(engine, member_id, tool, directory, DocumentKind.TRANSFER, TRANSFER)
    with Session(engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        document_service.remove_document(tool, directory, case, uploaded.documents[0].document_id)

    assert _document_logs(engine, member_id) == [("OWNER", "DOCUMENT_UPLOADED", "TRANSFER")]


def test_only_passed_check_is_logged_as_ribbon(documents):
    engine, member_id, tool, directory = documents
    for kind, fields in SETTLEMENT.items():
        context = _upload(engine, member_id, tool, directory, kind, fields)
    # 철거 전후 사진은 사장님이 종류를 확인해야 점검을 통과한다
    with Session(engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        for document in context.documents:
            values = {field.name: field.value for field in document.analysis.fields}
            document_service.confirm_document(tool, directory, case, document.document_id,
                                              document.analysis.kind, values)

    # 이체확인증이 빠져 문제가 남은 점검은 기록하지 않는다
    assert _check(engine, member_id, tool, directory).document_check.status == "ISSUES"
    assert ("RIBBON", "DOCUMENTS_CHECKED", None) not in _document_logs(engine, member_id)

    _upload(engine, member_id, tool, directory, DocumentKind.TRANSFER, TRANSFER)
    assert _check(engine, member_id, tool, directory).document_check.status == "COMPLETE"
    # 서류를 바꾸지 않고 [점검]을 다시 눌러 또 통과해도 한 줄만 남는다
    assert _check(engine, member_id, tool, directory).document_check.status == "COMPLETE"

    logs = _document_logs(engine, member_id)
    assert logs.count(("RIBBON", "DOCUMENTS_CHECKED", None)) == 1
    assert [detail for actor, event, detail in logs if event == "DOCUMENT_UPLOADED"].count("TRANSFER") == 1
    assert all(actor == "OWNER" for actor, event, _ in logs if event == "DOCUMENT_UPLOADED")
