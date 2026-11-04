"""검수 정리본으로 첫 판단의 Info를 모델 없이 만드는지. 모델은 부르지 않는다.

정리본(app/common/procedure-digests.ko-KR.json)은 사람이 검수한 원문의 문장을 그대로 옮긴 것이라,
글자 하나만 달라도 Info 검사(_materialize)가 거절한다. 그래서 파일 자체도 여기서 확인한다.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import app.agent.runtime as runtime_module
from app.agent.info_agent import agent as info_module
from app.agent.info_agent import procedure_digests
from app.agent.action_catalog import PROCEDURE_LABELS
from scripts import evaluate_planning as ev

REVIEWED = Path("app/common/reviewed-procedures.ko-KR.json")


def records():
    return {item["record_id"]: item for item in json.loads(REVIEWED.read_text(encoding="utf-8"))["records"]}


def digest_file():
    return json.loads(procedure_digests.DIGEST_PATH.read_text(encoding="utf-8"))


def test_every_digest_sentence_is_copied_from_its_reviewed_source():
    data, source = digest_file(), records()
    for code, step in data["steps"].items():
        for item in [step["summary"], *step["required_actions"]]:
            record = source[item["record_id"]]
            assert code in record["step_codes"]
            assert item["text"] in record["excerpt"], (code, item["text"][:30])
        for item in step["required_documents"]:
            assert item["name"] in source[item["record_id"]]["excerpt"], (code, item["name"])
    # 지문이 검수 원문과 같아야 실행 중 근거와 짝지어진다. 원문을 갱신하면 여기서 정리본도 다시 보게 된다
    assert data["source_hashes"] == {key: source[key]["content_hash"] for key in data["source_hashes"]}


def test_digest_covers_every_cafe_procedure_step():
    # 정리본에 없는 절차가 생기면 첫 판단이 통째로 모델 경로로 돌아가 느려진다
    assert set(PROCEDURE_LABELS) <= set(digest_file()["steps"])


class NoModel:
    """부르면 실패하는 모델. 첫 판단에서 Info 모델을 부르지 않는지 본다."""

    calls: list[str] = []

    @classmethod
    def from_env(cls, *args, **kwargs):
        return cls()

    async def generate(self, *args, **kwargs):
        NoModel.calls.append(kwargs.get("schema_name", "?"))
        raise AssertionError("model called")

    async def aclose(self):
        pass


def info_result(case="benchmark_case1", result_text=None, digests="reviewed"):
    """절차 조회·Info까지 실제로 돌리고, Supervisor 입력에서 Info 결과를 꺼낸다."""

    store = ev.SnapshotStore(REVIEWED)
    request = ev.attach_fixture_sources(ev.build_graph_input(ev.CASES[case], result_text=result_text), store)
    data = {"reviewed": digest_file() | {"reviewed_by": "test", "reviewed_at": "2026-11-05"},
            "unreviewed": None}[digests] if isinstance(digests, str) else digests
    captured, NoModel.calls = {}, []

    async def run():
        with patch.object(runtime_module.StructuredLLMClient, "from_env", NoModel.from_env), \
             patch.object(info_module, "load_digests", lambda: data):
            runtime = await runtime_module.build_runtime(
                known_procedure_steps=ev.build_registry(store), procedure_store=store,
                support_catalog=ev.load_catalog(None),
            )

            async def stop(supervisor_input):
                captured["info"] = next(
                    item.output for item in supervisor_input.source_results
                    if type(item.output).__name__ == "InfoAnalysisResult"
                )
                raise RuntimeError("stop after info")

            runtime._graph._supervisor.draft = stop
            await runtime.run_planning(request)

    asyncio.run(run())
    return captured.get("info"), NoModel.calls


def test_first_judgment_uses_the_digest_instead_of_the_info_model():
    info, calls = info_result()
    assert calls == []
    assert {item.procedure_step.step_code for item in info.procedure_findings} == set(digest_file()["steps"])
    # 원상복구 범위·철거 여부를 모르면 임대인에게 물을 질문 두 개를 낸다(Info 프롬프트 9번 규칙)
    assert [item.text for item in info.question_candidates] == ["원상복구해야 할 범위는 어디까지인가요?", "철거가 필요한가요?"]
    restoration = next(i for i in info.procedure_findings if i.procedure_step.step_code == "CONFIRM_RESTORATION_SCOPE")
    assert restoration.decision_authority == "LANDLORD" and restoration.required_actions


@pytest.mark.parametrize("digests", ["unreviewed", "changed_source"])
def test_falls_back_to_the_info_model_when_the_digest_cannot_be_trusted(digests):
    if digests == "changed_source":
        # 공식 원문이 갱신돼 지문이 달라진 상황. 낡은 정리본을 쓰지 않는다
        data = digest_file() | {"reviewed_by": "test", "reviewed_at": "2026-11-05"}
        digests = data | {"source_hashes": {key: "sha256:" + "0" * 64 for key in data["source_hashes"]}}
    _, calls = info_result(digests=digests)
    assert calls == ["reborn_info_analysis"]


def test_a_result_report_still_reads_the_owner_text_with_the_info_model():
    _, calls = info_result(result_text="임대인이 철거해야 한다고 했어요.")
    assert calls == ["reborn_info_analysis"]
