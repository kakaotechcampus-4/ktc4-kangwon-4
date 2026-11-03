"""서류 API(/cases/documents): Golden Case 5 — 이체확인증 누락 → 추가 → 점검 완료 → 제출 파일.

DB와 모델은 부르지 않는다. Case는 가짜 객체로, 모델은 document_fixtures의 가짜 응답으로 바꾼다.
"""

import io
from datetime import date, datetime
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.agent.document_tool.documents import DocumentService
from app.agent.document_tool.models import DocumentKind
from app.agent.document_tool.tool import DocumentTool
from app.be.crud import case as case_crud
from app.be.db import get_db
from app.be.dependencies.auth import get_current_member_id
from app.be.routers import document as document_router
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


@pytest.fixture
def api(tmp_path, monkeypatch):
    client_model = DocumentClient()
    cases = {
        1: SimpleNamespace(id=1, created_at=datetime(2026, 11, 3, 9), store_name="봄날개인카페",
                           planned_closure_date=date(2026, 10, 31)),
        2: SimpleNamespace(id=2, created_at=datetime(2026, 11, 3, 10), store_name="다른가게",
                           planned_closure_date=None),
    }
    member = {"id": 1}

    async def fake_tool():
        yield DocumentTool(DocumentService(tmp_path / "vault", client_model, reviewer=client_model,
                                           submission_policy="RRN_BACK_ONLY"))

    def fake_db():
        yield None

    monkeypatch.setattr(case_crud, "get_case_by_member_id", lambda _session, member_id: cases.get(member_id))
    app.dependency_overrides.update({
        get_db: fake_db,
        get_current_member_id: lambda: member["id"],
        document_router.get_document_directory: lambda: tmp_path / "vault",
        document_router.get_document_tool: fake_tool,
    })
    yield TestClient(app), member, client_model
    app.dependency_overrides.clear()


def upload(client, kind, fields):
    return client.post("/cases/documents", files={"file": (f"{kind}.pdf", document_pdf(kind, **fields), "application/pdf")})


def test_missing_transfer_is_reported_then_added_and_zip_downloads(api):
    client, _, _ = api
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
    client, member, _ = api
    uploaded = upload(client, DocumentKind.TRANSFER, TRANSFER).json()["documents"][0]
    assert uploaded["kind"] == "TRANSFER" and uploaded["kind_label"] == "이체확인증"
    assert {f["name"]: f["value"] for f in uploaded["fields"]}["amount"] == "3,300,000원"
    assert "quote" not in uploaded["fields"][0]

    # 요청마다 새로 읽어도(서버를 다시 켠 것과 같다) 저장한 목록이 그대로 나온다
    assert [d["document_id"] for d in client.get("/cases/documents").json()["documents"]] == [uploaded["document_id"]]

    member["id"] = 2
    assert client.get("/cases/documents").json() == {"documents": [], "check": None}
    other = client.post(f"/cases/documents/{uploaded['document_id']}/confirm",
                        json={"kind": "TRANSFER", "confirmed_fields": {"amount": "1원"}})
    assert other.status_code == 422
    assert client.delete(f"/cases/documents/{uploaded['document_id']}").status_code == 422


def test_owner_confirms_uncertain_values_and_can_remove_document(api):
    client, _, client_model = api
    client_model.needs_confirmation = True
    record = upload(client, DocumentKind.TRANSFER, TRANSFER).json()["documents"][0]
    assert record["needs_confirmation"] is True

    confirmed = client.post(f"/cases/documents/{record['document_id']}/confirm", json={
        "kind": "TRANSFER", "confirmed_fields": {**TRANSFER, "amount": "3,000,000원"},
    }).json()["documents"][0]
    assert confirmed["needs_confirmation"] is False
    assert confirmed["confirmed_fields"]["amount"] == "3,000,000원"

    assert client.delete(f"/cases/documents/{record['document_id']}").json()["documents"] == []


def test_case_is_required_and_empty_upload_is_rejected(api):
    client, member, _ = api
    assert client.post("/cases/documents", files={"file": ("empty.pdf", b"", "application/pdf")}).status_code == 422
    member["id"] = 3
    assert client.get("/cases/documents").status_code == 404


# 1: 가입 때 폐업 예정일(2026-10-31)을 정한 Case, 2: "예상 달·아직"을 골라 예정일이 없는 Case
@pytest.mark.parametrize("case_id", [1, 2])
def test_only_owner_confirmed_closure_date_is_checked(api, case_id):
    client, member, _ = api
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
