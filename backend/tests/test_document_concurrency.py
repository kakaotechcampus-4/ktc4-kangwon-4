"""서류를 분석하는 사이 사장님이 다른 서류를 지우면 그 삭제가 살아남는지. 진짜 MySQL이 필요하다(Docker).

멘토님이 #187에서 짚은 상황이다. 서류 하나를 올리면 값을 꺼내는 데 수십 초가 걸린다.
그 사이 사장님이 서류함에서 다른 서류를 지우면, 올리기가 "분석 시작 전에 읽어 둔 목록"에
새 서류를 얹어 저장하면서 그 삭제를 통째로 되돌려 버린다(lost update).

파일 하나에 목록 전체를 쓰던 때는 막을 방법이 없었다. 지금은 표의 그 줄을 잠그고 다시 읽어
얹으므로(services/document.load_context(for_update=True)) 삭제가 남는다.
한 프로세스 안에서 잠금을 흉내 내면 재현되지 않아, 세션 두 개를 실제로 겹치게 만든다.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlmodel import Session

from app.agent.document_tool.documents import DocumentService
from app.agent.document_tool.models import DocumentKind
from app.agent.document_tool.tool import DocumentTool
from app.be.crud import case as case_crud
from app.be.services import document as document_service
from case_world import case_engine, case_world  # noqa: F401
from document_fixtures import DocumentClient, document_pdf

TRANSFER = {"amount": "3,300,000원", "sender": "김리본", "recipient": "그린철거"}
TAX = {"supply_amount": "3,000,000원", "tax_amount": "300,000원", "supplier": "그린철거", "buyer": "봄날개인카페"}


@pytest.fixture
def documents(tmp_path, case_world):
    member_id, _, _ = case_world.sign_up()
    tool = DocumentTool(DocumentService(tmp_path / "vault", DocumentClient(), reviewer=DocumentClient(),
                                        submission_policy="RRN_BACK_ONLY"))
    return case_world.engine, member_id, tool


def _upload(engine, member_id, tool, kind, fields):
    with Session(engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        return asyncio.run(document_service.upload_document(
            session, tool, case, f"{kind}.pdf", document_pdf(kind, **fields), None,
        ))


def _document_ids(engine, member_id):
    with Session(engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        return {row.document_id for row in document_service.load_context(session, case).documents}


def test_a_delete_during_a_slow_upload_is_not_undone(documents, monkeypatch):
    engine, member_id, tool = documents
    [kept] = _upload(engine, member_id, tool, DocumentKind.TAX_INVOICE, TAX).documents

    # 올리기가 "분석 전 목록"을 읽은 바로 그 지점에서 삭제를 끼워 넣는다. 느린 분석을 기다리는 대신이다.
    started, analysed = Barrier(2), Barrier(2)
    real_add_document = tool.add_document

    slow = [True]

    async def slow_add_document(context, *args, **kwargs):
        # 느리게 구는 것은 처음 한 번뿐이다. 목록이 바뀌었으면 서비스가 최신 목록 위에
        # 다시 얹는데(임계구역), 그건 캐시에 있는 결과라 기다릴 일이 없다.
        if slow[0]:
            slow[0] = False
            started.wait(timeout=30)
            analysed.wait(timeout=30)
        return await real_add_document(context, *args, **kwargs)

    monkeypatch.setattr(tool, "add_document", slow_add_document)

    def remove_while_it_analyses():
        started.wait(timeout=30)
        with Session(engine) as session:
            case = case_crud.get_case_by_member_id(session, member_id)
            document_service.remove_document(session, tool, case, kept.document_id)
        analysed.wait(timeout=30)

    with ThreadPoolExecutor(max_workers=2) as pool:
        uploading = pool.submit(_upload, engine, member_id, tool, DocumentKind.TRANSFER, TRANSFER)
        removing = pool.submit(remove_while_it_analyses)
        added = uploading.result(timeout=60)
        removing.result(timeout=60)

    # 올린 서류는 들어가고, 그 사이의 삭제도 그대로 남는다. 고치기 전에는 지운 서류가 되살아났다.
    saved = _document_ids(engine, member_id)
    assert kept.document_id not in saved
    assert saved == {row.document_id for row in added.documents}
    assert len(saved) == 1
