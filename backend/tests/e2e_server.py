"""브라우저 E2E(frontend/e2e)가 붙는 진짜 BE 서버. 모델은 부르지 않는다.

    E2E_DATABASE_URL=mysql+pymysql://root:pw@127.0.0.1:3306/e2e?charset=utf8mb4 \\
    E2E_TOKEN_FILE=/tmp/reborn-e2e-token.json python tests/e2e_server.py

- 켤 때 E2E_DATABASE_URL의 표를 **전부 지우고** 새로 만든다. 그래서 주소를 꼭 따로 받는다.
  .env의 DATABASE_URL(개발 DB)을 그대로 쓰면 그 DB가 지워진다.
- 판단은 진짜 AI 그래프를 그대로 돌리고, 모델 자리에만 가짜를 끼운다. 가입 첫 판단은 정리본을
  써서 Supervisor 모델만 부르고 검수는 코드로 한다(AI팀 test_first_judgment_reviews_with_code_only…).
  그래서 가짜는 "첫 번째 후보를 고른다"만 하면 되고, 판단 저장·화면 조회는 운영과 같은 길을 탄다.
- 로그인은 우회 API를 만들지 않는다. 회원 한 명을 만들고 그 토큰을 E2E_TOKEN_FILE에 쓴다.
  브라우저 검사가 이걸 sessionStorage에 넣고 시작한다.

pytest가 모으지 않는다(test_로 시작하지 않음). 이름은 다물님 E2E 제안을 따랐다.
"""

import json
import os
import sys
from pathlib import Path
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
from app.be.crud.member import create_member  # noqa: E402
from app.be.db import get_engine, reset_all_tables  # noqa: E402
from app.be.services import auth as auth_service  # noqa: E402
from app.main import app  # noqa: E402


class FirstCandidateModel:
    """Supervisor 자리의 가짜. 받은 Blocker 후보 중 첫 번째와 그 첫 할 일을 고른다."""

    @classmethod
    def from_env(cls, *args, **kwargs):
        return cls()

    async def generate(self, response_model, messages, **kwargs):
        # 가입 첫 판단에서 다른 모델이 불리면 이 E2E가 가정한 길이 아니다. 조용히 넘기지 않는다.
        if kwargs.get("schema_name") != "reborn_supervisor_draft":
            raise AssertionError(f"E2E 가짜 모델은 Supervisor만 받는다: {kwargs.get('schema_name')}")
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
    Path(os.environ["E2E_TOKEN_FILE"]).write_text(json.dumps(_signed_in_member()), encoding="utf-8")
    port = int(os.environ.get("E2E_BE_PORT", "8765"))
    with patch.object(runtime_module.StructuredLLMClient, "from_env", FirstCandidateModel.from_env), \
         patch.object(runtime_module.LangfuseTraceSink, "from_env", lambda *a, **k: None):
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
