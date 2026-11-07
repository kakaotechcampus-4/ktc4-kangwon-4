"""브라우저 E2E(frontend/e2e)가 붙는 진짜 BE 서버. 모델은 부르지 않는다.

    E2E_DATABASE_URL=mysql+pymysql://root:pw@127.0.0.1:3306/e2e?charset=utf8mb4 \\
    E2E_TOKEN_FILE=/tmp/reborn-e2e-token.json python tests/e2e_server.py

- 켤 때 E2E_DATABASE_URL의 표를 **전부 지우고** 새로 만든다. 그래서 주소를 꼭 따로 받는다.
  .env의 DATABASE_URL(개발 DB)을 그대로 쓰면 그 DB가 지워진다.
- 판단은 진짜 AI 그래프를 그대로 돌리고, 모델 자리에만 가짜를 끼운다. 가입 첫 판단은 정리본을
  써서 Supervisor 모델만 부르고 검수는 코드로 한다(AI팀 test_first_judgment_reviews_with_code_only…).
  직접 입력·서류는 테스트에 적힌 합성 문장에만 고정 사실·검수 응답을 준다. 충돌 선택 뒤 검수도 대체한다.
  모델 품질을 평가하지 않는다.
  판단 저장·화면 조회는 운영과 같은 길을 탄다.
- 로그인은 우회 API를 만들지 않는다. 독립된 합성 회원과 토큰을 E2E_TOKEN_FILE에 쓴다.
  브라우저 검사가 이걸 sessionStorage에 넣고 시작한다.

pytest가 모으지 않는다(test_로 시작하지 않음). 이름은 다물님 E2E 제안을 따랐다.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

# 설정은 처음 읽을 때 굳는다(get_settings 캐시). app을 불러오기 전에 정해 둔다.
# 프로세스 환경이 .env보다 앞서서, 개발용 .env가 있어도 아래 값이 쓰인다.
if not os.environ.get("E2E_DATABASE_URL") or not os.environ.get("E2E_TOKEN_FILE"):
    sys.exit("E2E_DATABASE_URL·E2E_TOKEN_FILE이 필요합니다. 표를 지우므로 개발 DB 주소를 쓰지 않습니다.")
os.environ.update({
    # dev면 켤 때 표를 다시 지워 아래에서 만든 회원이 사라진다. 표는 여기서 직접 만든다.
    "ENVIRONMENT": "prod",
    "DATABASE_URL": os.environ["E2E_DATABASE_URL"],
    "JWT_SECRET_KEY": "e2e-only-secret-not-used-anywhere-else",
    "KAKAO_CLIENT_ID": "e2e", "KAKAO_CLIENT_SECRET": "e2e", "KAKAO_REDIRECT_URI": "http://localhost/e2e",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402
from sqlmodel import Session  # noqa: E402

import app.agent.runtime as runtime_module  # noqa: E402
from app.agent.document_tool.documents import DocumentService  # noqa: E402
from app.agent.document_tool.safety import ContentSafetyGuard  # noqa: E402
from app.agent.document_tool.safety import SafetyDecision  # noqa: E402
from app.agent.document_tool.tool import DocumentTool  # noqa: E402
from app.agent.llm import LLMRequestError  # noqa: E402
from app.be.crud.member import create_member  # noqa: E402
from app.be.db import get_engine, reset_all_tables  # noqa: E402
from app.be.services import auth as auth_service  # noqa: E402
from app.main import app  # noqa: E402
from app.be.routers import document as document_router  # noqa: E402
from document_fixtures import DocumentClient, document_pdf  # noqa: E402


class DocumentSafetyModel(DocumentClient):
    """합성 표식에만 안전 판정/제공자 장애를 주고, 실제 Guard→HTTP 경로는 유지한다."""

    async def generate(self, model, messages, **kwargs):
        if model is SafetyDecision:
            text = messages[-1]["content"]
            for decision in ("REFUSE", "CRISIS_SUPPORT", "UNAVAILABLE"):
                if f"E2E_SAFETY_{decision}" not in text:
                    continue
                if decision == "UNAVAILABLE":
                    raise LLMRequestError("synthetic provider outage", code="PROVIDER_UNAVAILABLE", retryable=True)
                return SafetyDecision(decision=decision)
        return await super().generate(model, messages, **kwargs)


async def synthetic_documents(directory: Path, *, submission_policy: str):
    client = DocumentSafetyModel()
    client.needs_confirmation = True
    # 실제 라우터가 고른 제출 가림 정책과 도구 종료 경로도 브라우저에서 검증한다.
    return DocumentTool(DocumentService(directory, client,
        reviewer=client, safety=ContentSafetyGuard(client), submission_policy=submission_policy))


def document_files(directory):
    # 텍스트 PDF 합성 자료다. 사진/OCR·실제 모델의 판독 품질을 검증하지 않는다.
    fields = {
        "CONSTRUCTION_STATEMENT": dict(amount="3,300,000원\n주민번호 800101-1234567", supplier="그린철거", buyer="봄날개인카페"),
        "TAX_INVOICE": dict(supply_amount="3,000,000원", tax_amount="300,000원", supplier="그린철거", buyer="봄날개인카페"),
        "BEFORE_PHOTO": {}, "AFTER_PHOTO": {},
        "CLOSURE_CERTIFICATE": dict(closure_date="2026-10-31"),
        "TRANSFER": dict(amount="3,300,000원", sender="김리본", recipient="그린철거"),
    }
    files = {kind: str(Path(directory) / f"{kind}.pdf") for kind in fields}
    for kind, values in fields.items():
        Path(files[kind]).write_bytes(document_pdf(kind, **values))
    return files


def replan_files(directory):
    files = {}
    for name, clause, day in [
        ("LEASE", "카운터만 철거한다.", "2026-11-01"),
        ("SAME_CLAUSE", "카운터만 철거한다.", "2026-11-02"),
        ("CHANGED_CLAUSE", "카운터만 철거한다. 작업 전 보양한다.", "2026-11-03"),
    ]:
        path = Path(directory) / f"{name}.pdf"
        path.write_bytes(document_pdf("LEASE", restoration_clause=clause, date=day))
        files[name] = str(path)
    return files


def document_safety_files(directory):
    files = {}
    for decision in ("REFUSE", "CRISIS_SUPPORT", "UNAVAILABLE"):
        path = Path(directory) / f"safety-{decision}.pdf"
        path.write_bytes(document_pdf("TRANSFER", amount="3,300,000원",
                                      sender=f"E2E_SAFETY_{decision}", recipient="그린철거"))
        files[decision] = str(path)
    return files


class FirstCandidateModel:
    """선택은 첫 후보, 직접 입력 해석은 아래 합성 문장만 받는 모델 대역이다."""

    @classmethod
    def from_env(cls, *args, **kwargs):
        return cls()

    async def generate(self, response_model, messages, **kwargs):
        name = kwargs.get("schema_name")
        if name == "reborn_info_analysis":
            prompt = json.dumps(messages, ensure_ascii=False)
            progress = "원상복구 작업을 시작했습니다." in prompt
            text = "원상복구 작업을 시작했습니다." if progress else "원상복구는 일부이고 카운터만 철거해야 합니다."
            if not progress and "카운터만 철거한다." in prompt:
                text = "카운터만 철거한다."
            if "서류 대기 검증입니다." in prompt:
                # 실제 판단을 기다리는 동안 업로드한다. 제품용 제어 API나 시간 추측 없이
                # 테스트 파일로 모델 대역만 멈춘다. 실패해도 서버가 무한히 기다리지 않는다.
                directory = Path(os.environ["AGENT_DOCUMENT_DIR"])
                (directory / "model-entered").touch()
                async with asyncio.timeout(45):
                    while not (directory / "model-release").exists():
                        await asyncio.sleep(0.05)
            assert text in prompt and "010-1234-5678" not in prompt
            facts = [("restoration_status", "ENUM", "IN_PROGRESS")] if progress else [
                ("restoration_scope", "ENUM", "PARTIAL"), ("demolition_required", "ENUM", "REQUIRED"),
                ("restoration_scope_detail", "STRING", "카운터"),
            ]
            return response_model.model_validate({
                "completion_status": "COMPLETE", "procedure_observations": [],
                "missing_fields": [], "uncertainties": [],
                "facts": [{"operation": "SET", "field_path": field, "value_type": kind,
                           "value": value, "source_text": text, "confidence_bps": 10000,
                           "requires_confirmation": False, "reason_summary": "합성 문장의 고정 답변"}
                          for field, kind, value in facts],
            })
        if name == "reborn_review_output":
            return response_model.model_validate({
                "verdict": "PASS", "issues": [], "missing_evidence": [],
                "recommended_rework_targets": [], "resolution_reason": "합성 문장 검수 응답 대역",
            })
        if name != "reborn_supervisor_draft":
            raise AssertionError(f"지원하지 않는 E2E 모델 호출: {name}")
        contract = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))["contract"]
        first = contract["blocker_candidates"][0]
        return response_model.model_validate({
            "decision_type": "ACTION",
            "blocker_candidate_id": first["candidate_id"],
            "action_code": first["actions"][0]["action_code"],
        })

    async def aclose(self):
        pass


def _signed_in_member() -> dict[str, str]:
    """화면이 로그인한 것처럼 쓸 회원과 토큰. 카카오 로그인 뒤 서버가 하는 일과 같은 값을 만든다."""

    with Session(get_engine()) as session:
        member = create_member(session, oauth_id=f"e2e-{uuid4()}", nickname="E2E 사장님")
        access = auth_service._create_access_token(member.id)
        refresh = auth_service._create_refresh_token(member.id)
        member.refresh_token = refresh
        session.commit()
    return {"access_token": access, "refresh_token": refresh}


def main() -> None:
    reset_all_tables()
    port = int(os.environ.get("E2E_BE_PORT", "8765"))
    with TemporaryDirectory(prefix="reborn-e2e-documents-") as directory, \
         patch.object(runtime_module.StructuredLLMClient, "from_env", FirstCandidateModel.from_env), \
         patch.object(runtime_module.LangfuseTraceSink, "from_env", lambda *a, **k: None), \
         patch.object(document_router, "build_document_tool", synthetic_documents):
        os.environ["AGENT_DOCUMENT_DIR"] = directory
        tokens = {**_signed_in_member(), "restoration_members": [_signed_in_member() for _ in range(6)],
                  "conflict_members": [_signed_in_member() for _ in range(2)],
                  "replan_members": [_signed_in_member() for _ in range(3)],
                  "replan_files": replan_files(directory),
                  "document_member": _signed_in_member(), "document_other_member": _signed_in_member(),
                  "document_safety_members": [_signed_in_member() for _ in range(3)],
                  "document_directory": directory, "document_files": document_files(directory),
                  "document_safety_files": document_safety_files(directory)}
        Path(os.environ["E2E_TOKEN_FILE"]).write_text(json.dumps(tokens), encoding="utf-8")
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
