"""검수 정리본으로 첫 판단의 Info를 모델 없이 만드는지. 모델은 부르지 않는다.

정리본(app/common/procedure-digests.ko-KR.json)은 사람이 검수한 원문의 문장을 그대로 옮긴 것이라,
글자 하나만 달라도 Info 검사(_materialize)가 거절한다. 그래서 파일 자체도 여기서 확인한다.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import app.agent.runtime as runtime_module
import pytest
from app.agent.action_catalog import PROCEDURE_LABELS
from app.agent.info_agent import agent as info_module
from app.agent.info_agent import procedure_digests
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


@pytest.mark.parametrize("lease_status", ["OWNED", "LEASED_PAID", "LEASED_FREE"])
def test_restoration_questions_follow_the_actual_cafe_applicability(lease_status):
    from app.agent.procedure_tool.cafe import build_cafe_procedure_steps

    registry = build_cafe_procedure_steps({code: i + 1 for i, code in enumerate(PROCEDURE_LABELS)})
    case = dict(ev.CASES["benchmark_case1"], lease_status=lease_status)
    with patch.dict(ev.CASES, {"lease_review": case}), \
         patch.object(ev, "build_registry", lambda store: registry):
        info, calls = info_result(case="lease_review")
    assert calls == []
    expected = [] if lease_status == "OWNED" else ["restoration_scope", "demolition_required"]
    assert [item.field_path for item in info.missing_fields] == expected
    assert [path for question in info.question_candidates for path in question.resolves_field_paths] == expected


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


# ── Turn 2: 사장님 글이 있으면 모델은 값만 꺼내고, 절차 정리는 정리본이 채운다(A-2) ──

LANDLORD = "카운터랑 싱크대는 빼고, 간판도 떼야 한대요. 바닥 타일은 그대로 둬도 된대요."


class FactModel(NoModel):
    """임대인 답변에서 범위·철거 여부만 꺼내 돌려주는 모델. 무엇을 받았는지 남긴다."""

    seen: list[dict] = []

    async def generate(self, response_model, messages, **kwargs):
        if kwargs.get("schema_name") != "reborn_info_analysis":
            raise AssertionError("only Info is under test")
        FactModel.seen.append({"schema": response_model.__name__, "messages": messages})
        fact = {"operation": "SET", "value_type": "ENUM", "source_text": "카운터랑 싱크대는 빼고, 간판도 떼야 한대요.",
                "confidence_bps": 9000, "requires_confirmation": False, "reason_summary": "임대인 답변"}
        return response_model.model_validate({
            "completion_status": "COMPLETE",
            "facts": [fact | {"field_path": "restoration_scope", "value": "PARTIAL"},
                      fact | {"field_path": "demolition_required", "value": "REQUIRED"}],
            "procedure_observations": [], "missing_fields": [], "uncertainties": [],
            **({} if response_model.__name__ == "InfoFactProviderOutput" else {"procedure_findings": []}),
        })


def landlord_answer_info(digests="reviewed"):
    FactModel.seen = []
    with patch.object(NoModel, "from_env", classmethod(lambda cls, *a, **k: FactModel())):
        info, _ = info_result(result_text=LANDLORD, digests=digests)
    return info, FactModel.seen


def test_landlord_answer_sends_only_the_owner_text_to_the_model():
    info, seen = landlord_answer_info()
    [call] = seen
    assert call["schema"] == "InfoFactProviderOutput"
    prompt = json.dumps(call["messages"], ensure_ascii=False)
    # 절차 원문을 보내지 않는다. 임대차 반환 원문 한 문장이 프롬프트에 없어야 한다
    assert "임차인은 임대차계약이 종료하면" not in prompt and LANDLORD in prompt
    assert {item.field_path for item in info.fact_candidates} == {"restoration_scope", "demolition_required"}
    assert {item.procedure_step.step_code for item in info.procedure_findings} == set(digest_file()["steps"])
    # 방금 답으로 정해진 범위·철거 여부는 다시 묻지 않는다
    assert info.question_candidates == []


def test_landlord_answer_falls_back_to_the_full_analysis_without_a_trusted_digest():
    # 이 가짜 모델은 절차 정리를 내지 않아 전체 분석 검사에 걸려 재시도까지 간다. 모양만 본다
    _, seen = landlord_answer_info(digests="unreviewed")
    assert seen and {call["schema"] for call in seen} == {"InfoProviderOutput"}


def test_landlord_answer_asks_back_only_restoration_fields():
    # 실측에서 값 꺼내기 모델이 보험 가입 이력·폐업일·원상복구 진행 상태까지 "모름"으로 되물었고, Review가 그 질문을
    # blocker에도 요구해 3번 모두 반려했다. 임대인 답변 단계에서는 원상복구 칸만 되묻는다
    class AsksEverything(FactModel):
        async def generate(self, response_model, messages, **kwargs):
            out = (await super().generate(response_model, messages, **kwargs)).model_dump(mode="python")
            ask = {"reason_summary": "확인 필요", "blocks": ["SUPERVISOR_DECISION"], "question": "확인해 주세요."}
            out["missing_fields"] = [ask | {"field_path": field} for field in (
                "restoration_status", "planned_closure_date", "pension_enrolled", "restoration_scope_detail")]
            out["completion_status"] = "NEEDS_USER_INPUT"
            return response_model.model_validate(out)

    with patch.object(NoModel, "from_env", classmethod(lambda cls, *a, **k: AsksEverything())):
        info, _ = info_result(result_text=LANDLORD)
    assert [item.field_path for item in info.missing_fields] == ["restoration_scope_detail"]


def test_asked_back_restoration_fields_become_question_blockers():
    # G17 실측: 값 꺼내기 모델이 되묻는 칸을 PROCEDURE_LOOKUP으로 적어 확인 질문 blocker가 안 생겼고, Review가 반려했다
    class LooksUpProcedure(FactModel):
        async def generate(self, response_model, messages, **kwargs):
            out = (await super().generate(response_model, messages, **kwargs)).model_dump(mode="python")
            out["missing_fields"] = [{"field_path": "restoration_scope_detail", "reason_summary": "세부 대상 미확인",
                                      "blocks": ["PROCEDURE_LOOKUP"], "question": "어떤 부분을 원래대로 해야 하나요?"}]
            out["completion_status"] = "NEEDS_USER_INPUT"
            return response_model.model_validate(out)

    with patch.object(NoModel, "from_env", classmethod(lambda cls, *a, **k: LooksUpProcedure())):
        info, _ = info_result(result_text=LANDLORD)
    [missing] = info.missing_fields
    assert missing.field_path == "restoration_scope_detail" and list(missing.blocks) == ["SUPERVISOR_DECISION"]


def test_a_runaway_fact_answer_is_cut_early_and_asked_again():
    # G01 실측: 값 꺼내기 출력이 16,000토큰 상한까지 반복되다 잘려 판단이 실패했다(101초).
    # 값 꺼내기는 상한을 4,000으로 낮춰 일찍 끊고, 같은 요청을 한 번 더 보낸다
    from app.agent.llm import LLMResponseError

    class RunsAwayOnce(FactModel):
        limits: list = []

        async def generate(self, response_model, messages, **kwargs):
            RunsAwayOnce.limits.append(kwargs.get("max_completion_tokens"))
            if len(RunsAwayOnce.limits) == 1:
                raise LLMResponseError("cut", code="OUTPUT_TOKEN_LIMIT", retryable=False, attempts=1)
            return await super().generate(response_model, messages, **kwargs)

    RunsAwayOnce.limits = []
    with patch.object(NoModel, "from_env", classmethod(lambda cls, *a, **k: RunsAwayOnce())):
        info, _ = info_result(result_text=LANDLORD)
    assert RunsAwayOnce.limits == [4000, 4000]
    assert {item.field_path for item in info.fact_candidates} == {"restoration_scope", "demolition_required"}


def test_review_sees_each_reviewed_source_text_once():
    # 같은 검수 원문이 Case 근거·절차 조회 근거·절차 문서 본문으로 세 번 들어가 Review 입력의 약 40%였다.
    # 모델에 보내는 입력에는 snapshot 쪽 한 벌만 남기고, 나머지 자리는 null로 둔다
    seen = {}

    class CaptureReview(FactModel):
        async def generate(self, response_model, messages, **kwargs):
            name = kwargs.get("schema_name")
            if name == "reborn_info_analysis":
                return await super().generate(response_model, messages, **kwargs)
            if name == "reborn_review_output":
                seen["review"] = messages
                return response_model.model_validate({"verdict": "PASS", "issues": [], "missing_evidence": [],
                                                      "recommended_rework_targets": [], "resolution_reason": "stub"})
            rows = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))["contract"]["blocker_candidates"]
            return response_model.model_validate({"decision_type": "ACTION", "blocker_candidate_id": rows[0]["candidate_id"],
                                                  "action_code": rows[0]["actions"][0]["action_code"]})

    store = ev.SnapshotStore(REVIEWED)
    request = ev.attach_fixture_sources(ev.build_graph_input(ev.CASES["benchmark_case1"], result_text=LANDLORD), store)
    reviewed = digest_file() | {"reviewed_by": "test", "reviewed_at": "2026-11-05"}

    async def run():
        with patch.object(runtime_module.StructuredLLMClient, "from_env", classmethod(lambda cls, *a, **k: CaptureReview())), \
             patch.object(info_module, "load_digests", lambda: reviewed):
            runtime = await runtime_module.build_runtime(
                known_procedure_steps=ev.build_registry(store), procedure_store=store, support_catalog=ev.load_catalog(None),
            )
            return await runtime.run_planning(request)

    assert asyncio.run(run()).outcome_type == "REVIEWED_PLAN"
    sent = json.loads(seen["review"][1]["content"].removeprefix("INPUT_JSON="))
    blob = json.dumps(sent, ensure_ascii=False)
    for record in records().values():
        first_line = json.dumps(record["excerpt"][:40], ensure_ascii=False)[1:-1]
        assert blob.count(first_line) <= 1, record["record_id"]
    procedure = next(item["output"] for item in sent["source_results"] if item["meta"]["component"] == "PROCEDURE_TOOL")
    assert procedure["documents"] and all(document["excerpt"] is None for document in procedure["documents"])
    assert any(item and item.get("excerpt") for item in sent["snapshot"]["evidence_records"])


@pytest.mark.parametrize("mode", ["confirmed", "held", "conflict"])
def test_new_employment_history_enables_prepared_settlement_only_after_guards(mode):
    from types import SimpleNamespace

    from app.agent.action_catalog import build_action_candidates
    from app.agent.procedure_tool.cafe import build_cafe_procedure_steps
    from app.agent.schemas import CaseFact, ProcedureProgress

    store = ev.SnapshotStore(REVIEWED)
    registry = build_cafe_procedure_steps({code: i + 1 for i, code in enumerate(PROCEDURE_LABELS)})
    text = "직원을 고용한 적이 있습니다."
    request = ev.attach_fixture_sources(ev.build_graph_input(ev.CASES["solo_dated"], result_text=text), store)
    snapshot = request.case_snapshot
    refs = [snapshot.evidence_records[0].evidence_id]
    settlement = next(step.procedure_step for step in registry if step.procedure_step.step_code == "SETTLE_EMPLOYEE_PAYMENTS")
    snapshot.procedure_progress.append(ProcedureProgress(
        procedure_step=settlement, status="IN_PROGRESS", requirements_confirmed=True,
        evidence_refs=refs, updated_at=snapshot.captured_at,
    ))
    if mode == "conflict":
        snapshot.facts.append(CaseFact(
            field_path="had_employees", value_type="BOOLEAN", value=False, status="CONFIRMED",
            evidence_refs=refs, updated_at=snapshot.captured_at,
        ))

    class EmploymentModel(NoModel):
        async def generate(self, response_model, messages, **kwargs):
            return response_model.model_validate({
                "completion_status": "COMPLETE", "facts": [{
                    "operation": "SET", "field_path": "had_employees", "value_type": "BOOLEAN", "value": True,
                    "source_text": text, "confidence_bps": 9000, "requires_confirmation": mode == "held",
                    "reason_summary": "사용자가 고용 이력을 보고했습니다.",
                }], "procedure_observations": [], "missing_fields": [], "uncertainties": [],
            })

    captured = {}
    analyze = info_module.InfoAnalysisAgent.analyze

    async def capture(agent, value):
        captured["info"] = await analyze(agent, value)
        return captured["info"]

    with patch.object(ev, "build_graph_input", lambda *a, **k: request), \
         patch.object(ev, "build_registry", lambda store: registry), \
         patch.object(NoModel, "from_env", classmethod(lambda cls, *a, **k: EmploymentModel())), \
         patch.object(info_module.InfoAnalysisAgent, "analyze", capture):
        info_result(result_text=text)
    info = captured["info"]
    evidence = {item.evidence_id: item for item in [*snapshot.evidence_records, *info.evidence_records]}
    actions = build_action_candidates(
        [SimpleNamespace(output=info)], evidence, {step.procedure_step.step_code: step.procedure_step for step in registry},
        procedure_progress=snapshot.procedure_progress,
    )
    assert ("SETTLE_EMPLOYEE_PAYMENTS" in {action["action_code"] for action in actions}) == (mode == "confirmed")
    assert bool(info.conflicts) == (mode == "conflict")
    if mode != "conflict":
        assert next(fact for fact in info.fact_candidates if fact.field_path == "had_employees").requires_confirmation == (mode == "held")
