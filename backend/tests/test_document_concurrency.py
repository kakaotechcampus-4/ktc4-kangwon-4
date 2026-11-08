"""서류를 분석하는 사이 사장님이 다른 서류를 지우면 그 삭제가 살아남는지. 진짜 MySQL이 필요하다(Docker).

멘토님이 #187에서 짚은 상황이다. 서류 하나를 올리면 값을 꺼내는 데 수십 초가 걸린다.
그 사이 사장님이 서류함에서 다른 서류를 지우면, 올리기가 "분석 시작 전에 읽어 둔 목록"에
새 서류를 얹어 저장하면서 그 삭제를 통째로 되돌려 버린다(lost update).

파일 하나에 목록 전체를 쓰던 때는 막을 방법이 없었다. 지금은 표의 그 줄을 잠그고 다시 읽어
얹으므로(services/document.load_context(for_update=True)) 삭제가 남는다.
한 프로세스 안에서 잠금을 흉내 내면 재현되지 않아, 세션 두 개를 실제로 겹치게 만든다.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import date
from threading import Barrier, Event

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


def _upload(engine, member_id, tool, kind, fields, content=None):
    with Session(engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        return asyncio.run(document_service.upload_document(
            session, tool, case, f"{kind}.pdf", content or document_pdf(kind, **fields), None,
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
        # 분석을 기다리는 동안에만 삭제를 끼워 넣는다. 저장할 때는 계산한 변경만 합친다.
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


def _checked(documents, **changes):
    engine, member_id, tool = documents
    values = {"applicant_name": "김리본", "closure_date": date(2026, 10, 31), **changes}
    with Session(engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        return document_service.check_documents(session, tool, case, **values)


def _loaded(documents):
    engine, member_id, _ = documents
    with Session(engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        return document_service.load_context(session, case)


@pytest.mark.parametrize("during", ["check", "remove_reupload"])
def test_upload_preserves_latest_inputs_and_same_file_deletion(documents, monkeypatch, during):
    engine, member_id, tool = documents
    with Session(engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        case.store_name = "봄날개인카페"
        session.commit()
    content = document_pdf(DocumentKind.TRANSFER, **TRANSFER)
    first = _upload(engine, member_id, tool, DocumentKind.TRANSFER, TRANSFER, content)
    assert first.business_name == "봄날개인카페"
    started, resume = Event(), Event()
    real_add = tool.add_document

    async def paused(context, *args, **kwargs):
        result = await real_add(context, *args, **kwargs)
        started.set()
        assert await asyncio.to_thread(resume.wait, 10)
        return result

    monkeypatch.setattr(tool, "add_document", paused)
    kind = DocumentKind.TRANSFER if during == "remove_reupload" else DocumentKind.BUSINESS_REGISTRATION
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(_upload, engine, member_id, tool, kind, {},
                              content if during == "remove_reupload" else document_pdf(kind))
        try:
            assert started.wait(10)
            if during == "check":
                _checked(documents, store_name="새 가게 이름")
            else:
                with Session(engine) as session:
                    case = case_crud.get_case_by_member_id(session, member_id)
                    document_service.remove_document(session, tool, case, first.documents[0].document_id)
        finally:
            resume.set()
        result = pending.result(timeout=10)
    saved = _loaded(documents)
    assert result == saved
    if during == "check":
        assert (saved.business_name, saved.applicant_name, saved.closure_date) == (
            "새 가게 이름", "김리본", date(2026, 10, 31))
        assert saved.document_check is None
    else:
        assert saved.documents == []


@pytest.mark.parametrize("changed", ["store_name", "applicant_name", "closure_date"])
def test_concurrent_checks_keep_latest_inputs_and_result(documents, monkeypatch, changed):
    engine, member_id, tool = documents
    files = {DocumentKind.CONSTRUCTION_STATEMENT: {"amount": "3,300,000원", "supplier": "그린철거", "buyer": "봄날개인카페"},
             DocumentKind.TAX_INVOICE: TAX, DocumentKind.TRANSFER: TRANSFER,
             DocumentKind.BEFORE_PHOTO: {}, DocumentKind.AFTER_PHOTO: {},
             DocumentKind.CLOSURE_CERTIFICATE: {"closure_date": "2026년 10월 31일"}}
    for kind, fields in files.items():
        context = _upload(engine, member_id, tool, kind, fields)
    with Session(engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        for record in context.documents:
            if record.analysis.needs_confirmation:
                document_service.confirm_document(session, tool, case, record.document_id, record.analysis.kind,
                                                  {field.name: field.value for field in record.analysis.fields})
    assert _checked(documents, store_name="봄날개인카페").document_check.status == "COMPLETE"
    started, resume = Event(), Event()
    real_check = tool.check_documents

    def paused(context):
        result = real_check(context)
        if not started.is_set():
            started.set()
            assert resume.wait(10)
        return result

    monkeypatch.setattr(tool, "check_documents", paused)
    changes = {"store_name": "다른 가게", "applicant_name": "다른 신청인", "closure_date": date(2026, 11, 30)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_checked, documents)
        try:
            assert started.wait(10)
            second = pool.submit(_checked, documents, **{changed: changes[changed]})
            # Case 잠금으로 두 번째 점검이 기다리는 경우도 허용한다.
            try:
                latest = second.result(timeout=0.25)
            except TimeoutError:
                resume.set()
                latest = second.result(timeout=10)
            assert latest.document_check.status == "ISSUES"
        finally:
            resume.set()
        first.result(timeout=10)
    saved = _loaded(documents)
    assert saved.document_check.status == "ISSUES"
    assert saved.business_name == (changes[changed] if changed == "store_name" else "봄날개인카페")
    assert saved.applicant_name == (changes[changed] if changed == "applicant_name" else "김리본")
    assert saved.closure_date == (changes[changed] if changed == "closure_date" else date(2026, 10, 31))


def test_confirmed_value_is_saved_after_an_old_transaction_read(documents):
    engine, member_id, tool = documents
    record = _upload(engine, member_id, tool, DocumentKind.TRANSFER, TRANSFER).documents[0]
    first_fields = {**TRANSFER, "amount": "3,000,000원"}
    second_fields = {**TRANSFER, "amount": "3,100,000원"}
    with Session(engine) as session:
        case = case_crud.get_case_by_member_id(session, member_id)
        document_service.confirm_document(session, tool, case, record.document_id, DocumentKind.TRANSFER, first_fields)
    # 예전 값을 읽은 뒤 다른 요청이 바꿔도, 마지막 확인은 응답과 같은 값으로 저장한다.
    with Session(engine) as old_session:
        old_case = case_crud.get_case_by_member_id(old_session, member_id)
        assert document_service.load_context(old_session, old_case).documents[0].confirmed_fields == first_fields
        with Session(engine) as newer_session:
            newer_case = case_crud.get_case_by_member_id(newer_session, member_id)
            document_service.confirm_document(newer_session, tool, newer_case, record.document_id,
                                              DocumentKind.TRANSFER, second_fields)
        result = document_service.confirm_document(old_session, tool, old_case, record.document_id,
                                                    DocumentKind.TRANSFER, first_fields)
    saved = _loaded(documents)
    assert saved.documents[0].confirmed_fields == first_fields
    assert result == saved
