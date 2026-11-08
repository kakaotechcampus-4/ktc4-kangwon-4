"""서류 API(/cases/documents): Golden Case 5 — 이체확인증 누락 → 추가 → 점검 완료 → 제출 파일.

모델은 부르지 않는다. Case는 가짜 객체로, 모델은 document_fixtures의 가짜 응답으로 바꾼다.
서류함(case_document_context)은 메모리에 담아 두는 가짜 세션으로 바꾼다 — 저장이 파일에서 표로
옮겨 가면서(멘토님 #187) 읽고 쓰기가 DB를 타기 때문이다. 진짜 MySQL로 보는 것은
test_case_document_log.py(저장)와 test_double_submit.py(겹침)다.
"""

import asyncio
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from threading import Event
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from app.agent.document_tool.documents import DocumentService
from app.agent.document_tool.models import DOCUMENT_FIELD_LABELS, DOCUMENT_LABELS, DocumentKind
from app.agent.document_tool.tool import DocumentTool
from app.be.crud import case as case_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import conflict_reference as conflict_reference_crud
from app.be.db import get_db
from app.be.dependencies.auth import get_current_member_id
from app.be.models.case_document_context import CaseDocumentContext
from app.be.routers import document as document_router
from app.be.services import document as document_service
from app.be.services import judgment as judgment_service
from app.main import app
from document_fixtures import DocumentClient, document_pdf

SETTLEMENT = {
    DocumentKind.CONSTRUCTION_STATEMENT: {"amount": "3,300,000원", "supplier": "그린철거", "buyer": "봄날개인카페"},
    DocumentKind.TAX_INVOICE: {"supply_amount": "3,000,000원", "tax_amount": "300,000원", "supplier": "그린철거", "buyer": "봄날개인카페"},
    DocumentKind.BEFORE_PHOTO: {},
    DocumentKind.AFTER_PHOTO: {},
    DocumentKind.CLOSURE_CERTIFICATE: {"closure_date": "2026년 10월 31일"},
}
TRANSFER = {"amount": "3,300,000원", "sender": "김리본", "recipient": "그린철거"}
# 점검 직전에 사장님이 확인한 이름과 실제 폐업일
OWNER = {"applicant_name": "김리본", "closure_date": "2026-10-31"}


class FakeSession:
    """서류함 줄(case_document_context)만 기억하는 세션. 서비스가 쓰는 것은 이 네 가지뿐이다.

    commit은 "지금까지 더한 줄을 확정"이고 rollback은 "버림"이다. 실제 잠금은 흉내 내지
    않으며, 두 세션의 저장 순서는 test_document_concurrency.py가 MySQL에서 확인한다.
    """

    def __init__(self):
        self.rows, self.staged = {}, []

    def get(self, model, key, **_kwargs):
        return self.rows.get((model, key))

    def add(self, row):
        self.staged.append(row)

    def commit(self):
        for row in self.staged:
            if isinstance(row, CaseDocumentContext):
                self.rows[(CaseDocumentContext, row.case_id)] = row
        self.staged.clear()

    def flush(self):
        pass

    def refresh(self, _row, **_kwargs):
        # Case 객체는 이 준비물에서 하나를 공유한다. 실제 점검 잠금은 MySQL 회귀로 검사한다.
        pass

    def rollback(self):
        self.staged.clear()

    def close(self):
        # 판단을 넘길 때 커넥션을 미리 돌려준다(db.release_request_connection). 담아 둔 줄은 그대로 둔다
        self.staged.clear()


@pytest.fixture
def api(tmp_path, monkeypatch):
    client_model = DocumentClient()
    cases = {
        1: SimpleNamespace(id=1, member_id=1, created_at=datetime(2026, 11, 3, 9), store_name="봄날개인카페",
                           planned_closure_date=date(2026, 10, 31)),
        2: SimpleNamespace(id=2, member_id=2, created_at=datetime(2026, 11, 3, 10), store_name="다른가게",
                           planned_closure_date=None),
    }
    member = {"id": 1}

    async def fake_tool():
        yield DocumentTool(DocumentService(tmp_path / "vault", client_model, reviewer=client_model,
                                           submission_policy="RRN_BACK_ONLY"))

    session = FakeSession()

    def fake_db():
        # 서류함만 담아 둔다. 서류 기록(case_document_history) 저장은 test_case_document_log.py가 실제 MySQL로 본다
        yield session

    monkeypatch.setattr(case_crud, "get_case_by_member_id", lambda _session, member_id: cases.get(member_id))
    app.dependency_overrides.update({
        get_db: fake_db,
        get_current_member_id: lambda: member["id"],
        document_router.get_document_directory: lambda: tmp_path / "vault",
        document_router.get_document_tool: fake_tool,
    })
    monkeypatch.setattr(document_service.case_document_history_crud, "create_case_document_history",
                        lambda _session, history: history)
    yield TestClient(app), member, client_model, session
    app.dependency_overrides.clear()


def upload(client, kind, fields):
    return client.post("/cases/documents", files={"file": (f"{kind}.pdf", document_pdf(kind, **fields), "application/pdf")})


def test_missing_transfer_is_reported_then_added_and_zip_downloads(api):
    client, _, _, _ = api
    for kind, fields in SETTLEMENT.items():
        assert upload(client, kind, fields).status_code == 200

    # 철거 전후 사진은 AI가 종류를 확신하지 않는다. 사장님이 확인해야 점검을 통과한다
    unconfirmed = client.post("/cases/documents/check", json=OWNER).json()
    assert "DOCUMENT_KIND_UNCONFIRMED" in {issue["code"] for issue in unconfirmed["check"]["issues"]}
    for document in unconfirmed["documents"]:
        if document["needs_confirmation"]:
            assert document["kind"] in {"BEFORE_PHOTO", "AFTER_PHOTO"}
            values = {field["name"]: field["value"] for field in document["fields"]}
            confirmed = client.post(f"/cases/documents/{document['document_id']}/confirm",
                                    json={"kind": document["kind"], "confirmed_fields": values})
            assert confirmed.status_code == 200

    checked = client.post("/cases/documents/check", json=OWNER).json()
    assert checked["check"]["status"] == "ISSUES"
    assert {issue["code"] for issue in checked["check"]["issues"]} == {"MISSING_TRANSFER"}
    assert client.get("/cases/documents/settlement.zip").status_code == 422

    added = upload(client, DocumentKind.TRANSFER, TRANSFER).json()
    # 서류가 바뀌면 지난 점검은 지워져 다시 점검해야 한다
    assert added["check"] is None
    final = client.post("/cases/documents/check", json=OWNER).json()["check"]
    assert final["status"] == "COMPLETE", final["issues"]

    response = client.get("/cases/documents/settlement.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None and "점검결과.json" in archive.namelist()


def test_list_keeps_saved_documents_and_hides_other_cases(api):
    client, member, _, _ = api
    uploaded = upload(client, DocumentKind.TRANSFER, TRANSFER).json()["documents"][0]
    assert uploaded["kind"] == "TRANSFER" and uploaded["kind_label"] == "이체확인증"
    assert {f["name"]: f["value"] for f in uploaded["fields"]}["amount"] == "3,300,000원"
    assert "quote" not in uploaded["fields"][0]

    # 요청마다 새로 읽어도(서버를 다시 켠 것과 같다) 저장한 목록이 그대로 나온다
    assert [d["document_id"] for d in client.get("/cases/documents").json()["documents"]] == [uploaded["document_id"]]

    member["id"] = 2
    empty = client.get("/cases/documents").json()
    assert empty == {
        "store_name": "다른가게", "documents": [], "check": None,
        "document_kinds": [{"kind": kind, "label": label} for kind, label in DOCUMENT_LABELS.items()
                           if kind != DocumentKind.UNKNOWN],
    }
    other = client.post(f"/cases/documents/{uploaded['document_id']}/confirm",
                        json={"kind": "TRANSFER", "confirmed_fields": {"amount": "1원"}})
    assert other.status_code == 422
    assert client.delete(f"/cases/documents/{uploaded['document_id']}").status_code == 422


def test_response_uses_agent_labels_even_after_confirmation_and_reload(api, monkeypatch):
    client, _, _, _ = api
    monkeypatch.setitem(DOCUMENT_FIELD_LABELS, "amount", "확인용 송금액")
    monkeypatch.setitem(DOCUMENT_LABELS, DocumentKind.TRANSFER, "확인용 이체서류")
    kinds = client.get("/cases/documents").json()["document_kinds"]
    assert {item["kind"] for item in kinds} == {kind.value for kind in DocumentKind if kind != DocumentKind.UNKNOWN}
    assert {"kind": "TRANSFER", "label": "확인용 이체서류"} in kinds
    document = upload(client, DocumentKind.TRANSFER, TRANSFER).json()["documents"][0]
    client.post(f"/cases/documents/{document['document_id']}/confirm", json={
        "kind": "TRANSFER", "confirmed_fields": {**TRANSFER, "amount": "1원"},
    })
    restored = client.get("/cases/documents").json()["documents"][0]
    assert restored["kind_label"] == "확인용 이체서류"
    assert next(field for field in restored["fields"] if field["name"] == "amount")["label"] == "확인용 송금액"
    assert restored["confirmed_fields"]["amount"] == "1원"
    schemas = app.openapi()["components"]["schemas"]
    assert set(DOCUMENT_FIELD_LABELS) == set(schemas["DocumentFieldResponse"]["properties"]["name"]["enum"])
    assert schemas["DocumentCheckResponse"]["properties"]["status"]["enum"] == ["COMPLETE", "ISSUES", "ERROR"]
    assert "label" in schemas["DocumentFieldResponse"]["required"]
    assert "document_kinds" in schemas["DocumentListResponse"]["required"]


def test_owner_confirms_uncertain_values_and_can_remove_document(api):
    client, _, client_model, _ = api
    client_model.needs_confirmation = True
    record = upload(client, DocumentKind.TRANSFER, TRANSFER).json()["documents"][0]
    assert record["needs_confirmation"] is True

    confirmed = client.post(f"/cases/documents/{record['document_id']}/confirm", json={
        "kind": "TRANSFER", "confirmed_fields": {**TRANSFER, "amount": "3,000,000원"},
    }).json()["documents"][0]
    assert confirmed["needs_confirmation"] is False
    assert confirmed["confirmed_fields"]["amount"] == "3,000,000원"

    assert client.delete(f"/cases/documents/{record['document_id']}").json()["documents"] == []


@pytest.mark.parametrize("during_analysis", ["remove", "confirm", "upload", "check", "remove_reupload", "confirm_reupload"])
def test_upload_keeps_changes_saved_while_analysis_runs(api, monkeypatch, during_analysis):
    client, _, _, session = api
    content = document_pdf(DocumentKind.TRANSFER, **TRANSFER)
    first = client.post("/cases/documents", files={"file": ("first.pdf", content, "application/pdf")}).json()["documents"][0]
    started, resume = Event(), Event()
    original = DocumentTool.add_document

    async def paused(tool, context, filename, content, **kwargs):
        updated = await original(tool, context, filename, content, **kwargs)
        if filename == "pending.pdf":
            started.set()
            assert await asyncio.to_thread(resume.wait, 10), "동시 변경 후 분석을 재개하지 못했습니다."
        return updated

    monkeypatch.setattr(DocumentTool, "add_document", paused)
    pending_content = content if during_analysis.endswith("reupload") else document_pdf(DocumentKind.BUSINESS_REGISTRATION)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, "/cases/documents", files={"file": ("pending.pdf", pending_content, "application/pdf")})
        try:
            assert started.wait(10), "서류 분석이 시작되지 않았습니다."
            if during_analysis.startswith("remove"):
                response = client.delete(f"/cases/documents/{first['document_id']}")
            elif during_analysis.startswith("confirm"):
                response = client.post(f"/cases/documents/{first['document_id']}/confirm", json={
                    "kind": "TRANSFER", "confirmed_fields": {**TRANSFER, "amount": "3,000,000원"},
                })
            elif during_analysis == "upload":
                response = upload(client, DocumentKind.BANK_COPY, {})
            else:
                response = client.post("/cases/documents/check", json=OWNER)
            assert response.status_code == 200
        finally:
            resume.set()
        uploaded = pending.result(timeout=10)
    assert uploaded.status_code == 200
    restored = client.get("/cases/documents").json()
    assert uploaded.json() == restored
    records = {document["document_id"]: document for document in restored["documents"]}
    if during_analysis.startswith("remove"):
        assert first["document_id"] not in records
    elif during_analysis.startswith("confirm"):
        assert records[first["document_id"]]["confirmed_fields"]["amount"] == "3,000,000원"
    elif during_analysis == "upload":
        assert len(records) == 3
        assert {item["kind"] for item in records.values()} == {"TRANSFER", "BANK_COPY", "BUSINESS_REGISTRATION"}
    else:
        case = case_crud.get_case_by_member_id(None, 1)
        context = document_service.load_context(session, case)
        assert context.applicant_name == OWNER["applicant_name"]
        assert context.closure_date == date(2026, 10, 31)
    assert restored["check"] is None


def test_reanalysis_replaces_only_the_current_document(api):
    client, _, model, session = api
    content = document_pdf(DocumentKind.TRANSFER, **TRANSFER)
    first = client.post("/cases/documents", files={"file": ("first.pdf", content, "application/pdf")}).json()["documents"][0]
    case = case_crud.get_case_by_member_id(None, 1)
    before = document_service.load_context(session, case).documents[0]
    model.config.reasoning_effort = "medium"
    again = client.post("/cases/documents", files={"file": ("first.pdf", content, "application/pdf")})
    assert again.status_code == 200
    assert [document["document_id"] for document in again.json()["documents"]] == [first["document_id"]]
    after = document_service.load_context(session, case).documents[0]
    assert after.cache_key != before.cache_key


@pytest.mark.parametrize("legacy_fields", [{}, {"store_name": None}])
def test_legacy_nameless_case_keeps_checking_then_accepts_the_explicit_name(api, legacy_fields):
    client, _, _, _ = api
    case = case_crud.get_case_by_member_id(None, 1)
    case.store_name = None
    # 업로드에서 읽은 상호로 Case를 채우지 않는다.
    upload(client, DocumentKind.TAX_INVOICE, SETTLEMENT[DocumentKind.TAX_INVOICE])
    assert client.get("/cases/documents").json()["store_name"] is None
    missing = client.post("/cases/documents/check", json={**OWNER, **legacy_fields})
    assert missing.status_code == 200 and missing.json()["check"]["status"] == "ISSUES"
    assert "BUYER_UNCONFIRMED" in {issue["code"] for issue in missing.json()["check"]["issues"]}
    assert client.get("/cases/documents").json()["store_name"] is None

    checked = client.post("/cases/documents/check", json={**OWNER, "store_name": " 봄날개인카페 "})
    assert checked.status_code == 200 and checked.json()["store_name"] == "봄날개인카페"
    assert client.get("/cases/documents").json()["store_name"] == "봄날개인카페"


@pytest.mark.parametrize("name", ["", " \t ", "가" * 51])
def test_invalid_store_name_does_not_replace_the_saved_name(api, name):
    client, _, _, _ = api
    response = client.post("/cases/documents/check", json={**OWNER, "store_name": name})
    assert response.status_code == 422
    assert client.get("/cases/documents").json()["store_name"] == "봄날개인카페"


def test_store_name_accepts_fifty_characters_after_trimming(api):
    client, _, _, _ = api
    response = client.post("/cases/documents/check", json={**OWNER, "store_name": " " + "가" * 50 + " "})
    assert response.status_code == 200 and response.json()["store_name"] == "가" * 50


def test_case_is_required_and_empty_upload_is_rejected(api):
    client, member, _, _ = api
    assert client.post("/cases/documents", files={"file": ("empty.pdf", b"", "application/pdf")}).status_code == 422
    member["id"] = 3
    assert client.get("/cases/documents").status_code == 404


@pytest.mark.parametrize("decision", ["REFUSE", "CRISIS_SUPPORT"])
def test_safety_blocked_upload_says_why_instead_of_asking_to_retry(api, monkeypatch, caplog, decision):
    # 안전 검사가 막으면 다시 올려도 같은 판정이다. "다시 올려 주세요"(502)가 아니라 422와 판정 코드를 준다
    from app.agent.document_tool.safety import SafetyBlockedError

    async def blocked(*_args, **_kwargs):
        raise SafetyBlockedError(decision)

    monkeypatch.setattr(DocumentTool, "add_document", blocked)
    caplog.set_level("WARNING", logger=document_service.__name__)
    response = api[0].post("/cases/documents", files={"file": ("memo.pdf", b"%PDF-1.4", "application/pdf")})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == f"AGENT_SAFETY_{decision}"
    assert ("109" in response.json()["detail"]["message"]) is (decision == "CRISIS_SUPPORT")
    # 파일명·내용·예외 원문은 남기지 않고 판정 코드만 기록한다(#227 리뷰).
    records = [record for record in caplog.records if record.name == document_service.__name__]
    assert [(record.getMessage(), record.exc_info) for record in records] == [
        (f"서류 안전 검사 차단: AGENT_SAFETY_{decision}", None),
    ]


def test_unavailable_safety_check_still_asks_to_retry(api, monkeypatch):
    from app.agent.document_tool.safety import SafetyCheckUnavailableError

    async def unavailable(*_args, **_kwargs):
        raise SafetyCheckUnavailableError()

    monkeypatch.setattr(DocumentTool, "add_document", unavailable)
    response = api[0].post("/cases/documents", files={"file": ("memo.pdf", b"%PDF-1.4", "application/pdf")})
    assert response.status_code == 502


# 1: 가입 때 폐업 예정일(2026-10-31)을 정한 Case, 2: "예상 달·아직"을 골라 예정일이 없는 Case
@pytest.mark.parametrize("case_id", [1, 2])
def test_only_owner_confirmed_closure_date_is_checked(api, case_id):
    client, member, _, _ = api
    member["id"] = case_id
    upload(client, DocumentKind.CLOSURE_CERTIFICATE, {"closure_date": "2026년 10월 31일"})

    def codes(body):
        return {issue["code"] for issue in client.post("/cases/documents/check", json=body).json()["check"]["issues"]}

    # 예정일이 증명원 날짜와 같아도 실제 폐업일을 확인하지 않았으면 막는다
    assert "CLOSURE_DATE_UNCONFIRMED" in codes({"applicant_name": "김리본"})
    told = codes(OWNER)
    assert not {"CLOSURE_DATE_UNCONFIRMED", "CLOSURE_DATE_MISMATCH"} & told
    assert "CLOSURE_DATE_MISMATCH" in codes({**OWNER, "closure_date": "2026-11-30"})
    assert client.post("/cases/documents/check", json={"applicant_name": ""}).status_code == 422


# ── 서류로 다시 판단하기(#137 연결): 원상복구 조항이 새로 생기거나 바뀔 때만 판단 이력을 남기고 판단을 건다 ──

LEASE_CLAUSE = {"restoration_clause": "임차인은 계약 종료 시 원상복구한다"}


@pytest.fixture
def judged(api, monkeypatch):
    """판단 이력 저장과 판단 실행을 가로채, 무엇이 남고 무엇이 불렸는지 돌려준다."""

    histories, runs = [], []
    state = {"latest_status": "DONE", "case_status": "IN_PROGRESS", "conflicts": []}

    def create_case_history(_session, history):
        history.id = 100 + len(histories)
        histories.append(history)
        return history

    def lock_case(session, member_id):
        # 잠금 조회도 api의 가짜 Case를 돌려준다. 서류 폴더 이름이 Case 번호·가입 시각으로 정해진다
        case = case_crud.get_case_by_member_id(session, member_id)
        return SimpleNamespace(**vars(case), case_status=state["case_status"])

    monkeypatch.setattr(case_crud, "lock_case_by_member_id", lock_case)
    monkeypatch.setattr(conflict_reference_crud, "get_pending_conflicts_by_case_id",
                        lambda _session, _case_id: state["conflicts"])
    monkeypatch.setattr(case_history_crud, "get_latest_user_driven_case_history",
                        lambda _session, _case_id: SimpleNamespace(judgment_status=state["latest_status"]))
    monkeypatch.setattr(case_history_crud, "create_case_history", create_case_history)

    async def fake_run(case_history_id):
        runs.append(case_history_id)

    monkeypatch.setattr(judgment_service, "run_judgment_in_background", fake_run)
    client, _, client_model, session = api
    return SimpleNamespace(client=client, model=client_model, histories=histories, runs=runs, state=state,
                           session=session)


def test_new_restoration_clause_starts_document_judgment(judged):
    assert upload(judged.client, DocumentKind.LEASE, LEASE_CLAUSE).status_code == 200

    [history] = judged.histories
    assert history.source == "DOCUMENT_SUBMITTED" and history.judgment_status == "PENDING"
    assert "원상복구 조항: 임차인은 계약 종료 시 원상복구한다" in history.raw_input
    assert judged.runs == [history.id]


def test_same_clause_or_amount_only_document_does_not_judge_again(judged):
    upload(judged.client, DocumentKind.LEASE, LEASE_CLAUSE)
    upload(judged.client, DocumentKind.LEASE, LEASE_CLAUSE)
    upload(judged.client, DocumentKind.TRANSFER, TRANSFER)
    assert len(judged.histories) == 1 and len(judged.runs) == 1


def test_owner_confirmed_clause_change_judges_after_confirm(judged):
    # 확인이 필요한 서류는 올릴 때 판단 글에 들어가지 않고, 사장님이 확인한 뒤에 판단한다
    judged.model.needs_confirmation = True
    record = upload(judged.client, DocumentKind.LEASE, LEASE_CLAUSE).json()["documents"][0]
    assert judged.runs == []

    confirmed = judged.client.post(f"/cases/documents/{record['document_id']}/confirm", json={
        "kind": "LEASE", "confirmed_fields": {"restoration_clause": "카운터·싱크대만 철거한다"},
    })
    assert confirmed.status_code == 200
    [history] = judged.histories
    assert "원상복구 조항(사장님 확인): 카운터·싱크대만 철거한다" in history.raw_input
    assert judged.runs == [history.id]


@pytest.mark.parametrize("blocked", [
    {"latest_status": "PENDING"}, {"case_status": "COMPLETED"}, {"conflicts": [object()]},
])
def test_document_is_saved_but_judgment_is_skipped_when_case_cannot_be_judged(judged, blocked):
    judged.state.update(blocked)
    response = upload(judged.client, DocumentKind.LEASE, LEASE_CLAUSE)
    assert response.status_code == 200 and len(response.json()["documents"]) == 1
    assert judged.histories == [] and judged.runs == []


@pytest.mark.parametrize("blocked", [{"latest_status": "PENDING"}, {"conflicts": [object()]}])
def test_document_skipped_while_blocked_is_judged_once_the_block_ends(judged, monkeypatch, blocked):
    # 판단 중·충돌 확인 대기 중에 올린 조항은 저장만 된다. 같은 서류를 다시 올려도 그 사이엔 판단하지 않는다
    judged.state.update(blocked)
    upload(judged.client, DocumentKind.LEASE, LEASE_CLAUSE)
    upload(judged.client, DocumentKind.LEASE, LEASE_CLAUSE)
    assert judged.histories == []

    # 앞 판단(7번)·충돌 확인이 끝나면 미뤄 둔 조항으로 한 번 판단하고, 그다음엔 멈춘다
    judged.state.update({"latest_status": "DONE", "conflicts": []})
    monkeypatch.setattr(case_history_crud, "get_case_history_by_id",
                        lambda _session, _history_id: SimpleNamespace(case_id=1))
    monkeypatch.setattr(case_crud, "get_case_by_id", lambda session, _case_id: case_crud.get_case_by_member_id(session, 1))
    queued = document_service.queue_owed_document_judgment(judged.session, 7)

    [history] = judged.histories
    assert queued == history.id and history.source == "DOCUMENT_SUBMITTED"
    assert "원상복구 조항: 임차인은 계약 종료 시 원상복구한다" in history.raw_input
    assert document_service.queue_owed_document_judgment(judged.session, history.id) is None
