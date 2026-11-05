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
from app.agent.schemas import AgentGraphInput, RestorationAnswer
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


def info_result(case="benchmark_case1", result_text=None, digests="reviewed", answer=None, confirmed=None):
    """절차 조회·Info까지 실제로 돌리고, Supervisor 입력에서 Info 결과를 꺼낸다."""

    store = ev.SnapshotStore(REVIEWED)
    request = ev.attach_fixture_sources(ev.build_graph_input(ev.CASES[case], result_text=result_text), store)
    payload = request.model_dump(mode="json")
    if answer is not None:
        payload["trigger"]["restoration_answer"] = answer.model_dump()
    if confirmed:
        ref = next(item.evidence_id for item in request.case_snapshot.evidence_records if item.source_type == "USER_INPUT")
        for fact in payload["case_snapshot"]["facts"]:
            if fact["field_path"] in confirmed:
                fact.update(value=confirmed[fact["field_path"]], status="CONFIRMED", evidence_refs=[ref])
    request = AgentGraphInput.model_validate(payload)
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
            if answer is not None:
                analyze = runtime._graph._info_agent.analyze

                async def capture_info(component_input):
                    result = await analyze(component_input)
                    captured["info"] = result
                    return result

                runtime._graph._info_agent.analyze = capture_info

            async def stop(supervisor_input):
                captured["info"] = next(
                    item.output for item in supervisor_input.source_results
                    if type(item.output).__name__ == "InfoAnalysisResult"
                )
                raise RuntimeError("stop after info")

            runtime._graph._supervisor.draft = stop
            before = request.model_dump_json()
            await runtime.run_planning(request)
            assert request.model_dump_json() == before

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


@pytest.mark.parametrize("scope", ["FULL", "PARTIAL", "NOT_REQUIRED", "UNKNOWN"])
@pytest.mark.parametrize("demolition", ["REQUIRED", "NOT_REQUIRED", "UNKNOWN"])
def test_restoration_answer_uses_no_info_model_and_preserves_explicit_values(scope, demolition):
    answer = RestorationAnswer(restoration_scope=scope, demolition_required=demolition)
    info, calls = info_result(result_text=answer.to_input_text(), answer=answer)
    assert calls == []
    expected = {field: value for field, value in answer.model_dump().items() if value != "UNKNOWN"}
    assert {item.field_path: item.value for item in info.fact_candidates} == expected
    missing = set(answer.model_dump()) - expected.keys()
    if scope == "PARTIAL":
        missing.add("restoration_scope_detail")
    assert {item.field_path for item in info.missing_fields} == missing
    assert info.conflicts == []
    assert len(info.procedure_findings) == len(digest_file()["steps"])
    for fact in info.fact_candidates:
        span = fact.source_span
        assert answer.to_input_text()[span.start_offset:span.end_offset] == span.text
        assert fact.source_evidence_refs
    assert "restoration_scope_detail" not in expected


def test_restoration_answer_partial_keeps_the_detail_question_without_inventing_an_answer():
    answer = RestorationAnswer(restoration_scope="PARTIAL", demolition_required="REQUIRED")
    info, calls = info_result(result_text=answer.to_input_text(), answer=answer)
    assert calls == []
    [missing] = info.missing_fields
    assert missing.field_path == "restoration_scope_detail" and list(missing.blocks) == ["SUPERVISOR_DECISION"]
    assert len(info.question_candidates) == 1
    assert [item.value for item in info.fact_candidates] == ["PARTIAL", "REQUIRED"]


def test_restoration_answer_does_not_reask_a_confirmed_scope_detail():
    answer = RestorationAnswer(restoration_scope="PARTIAL", demolition_required="REQUIRED")
    info, calls = info_result(result_text=answer.to_input_text(), answer=answer,
                              confirmed={"restoration_scope_detail": "카운터"})
    assert calls == [] and info.missing_fields == [] and info.question_candidates == []
    assert all(item.field_path != "restoration_scope_detail" for item in info.fact_candidates)


def test_restoration_answer_preserves_old_facts_and_reports_both_conflicts():
    answer = RestorationAnswer(restoration_scope="PARTIAL", demolition_required="NOT_REQUIRED")
    info, calls = info_result(result_text=answer.to_input_text(), answer=answer,
                              confirmed={"restoration_scope": "FULL", "demolition_required": "REQUIRED"})
    assert calls == [] and info.fact_candidates == []
    assert {item.field_path for item in info.conflicts} == {"restoration_scope", "demolition_required"}


def test_restoration_answer_unknown_never_clears_confirmed_values():
    answer = RestorationAnswer(restoration_scope="UNKNOWN", demolition_required="UNKNOWN")
    info, calls = info_result(result_text=answer.to_input_text(), answer=answer,
                              confirmed={"restoration_scope": "FULL", "demolition_required": "REQUIRED"})
    assert calls == [] and info.fact_candidates == [] and info.conflicts == []
    assert len(info.question_candidates) == 2


@pytest.mark.parametrize("digests", ["unreviewed", "changed_source"])
def test_restoration_answer_fails_without_calling_a_model_when_digests_are_untrusted(digests):
    if digests == "changed_source":
        data = digest_file() | {"reviewed_by": "test", "reviewed_at": "2026-11-05"}
        digests = data | {"source_hashes": {key: "sha256:" + "0" * 64 for key in data["source_hashes"]}}
    answer = RestorationAnswer(restoration_scope="FULL", demolition_required="REQUIRED")
    info, calls = info_result(result_text=answer.to_input_text(), answer=answer, digests=digests)
    assert info is None and calls == []


@pytest.mark.parametrize("scope", ["FULL", "PARTIAL"])
def test_restoration_answer_uses_supervisor_and_code_review_without_review_model(scope):
    # 선택형은 모델이 쓴 사실·문장이 없어 Review 모델 없이 코드 검사만 한다(graph review_code_only).
    from pydantic import ValidationError
    from app.agent.schemas import ReviewedPlanOutcome

    calls = []
    answer = RestorationAnswer(restoration_scope=scope, demolition_required="REQUIRED")
    store = ev.SnapshotStore(REVIEWED)
    request = ev.attach_fixture_sources(ev.build_graph_input(ev.CASES["benchmark_case1"],
                                        result_text=answer.to_input_text()), store)
    request.trigger.restoration_answer = answer

    class SelectionModel(NoModel):
        async def generate(self, response_model, messages, **kwargs):
            name = kwargs["schema_name"]
            calls.append(name)
            assert name not in {"reborn_info_analysis", "reborn_review_output"}, "선택형은 Info·Review 모델을 부르지 않는다"
            contract = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))["contract"]
            if scope == "PARTIAL":
                assert any(item["candidate_id"] == "missing:restoration_scope_detail"
                           for item in contract["information_blockers"])
                return response_model.model_validate({"decision_type": "NEEDS_MORE_INFO",
                    "blocker_candidate_id": "missing:restoration_scope_detail", "action_code": None})
            rows = contract["blocker_candidates"]
            return response_model.model_validate({"decision_type": "ACTION", "blocker_candidate_id": rows[0]["candidate_id"],
                                                  "action_code": rows[0]["actions"][0]["action_code"]})

    async def run():
        with patch.object(runtime_module.StructuredLLMClient, "from_env", classmethod(lambda cls, *a, **k: SelectionModel())):
            runtime = await runtime_module.build_runtime(known_procedure_steps=ev.build_registry(store),
                procedure_store=store, support_catalog=ev.load_catalog(None))
            try:
                return await runtime.run_planning(request)
            finally:
                await runtime.aclose()

    outcome = asyncio.run(run())
    assert calls == ["reborn_supervisor_draft"]
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    assert outcome.review_subject.trigger.restoration_answer == answer
    if scope == "PARTIAL":
        decision = outcome.review_subject.supervisor_draft.decision
        assert decision.decision_type == "NEEDS_MORE_INFO" and decision.next_action is None
        assert list(decision.questions_for_user) == ["확인한 원상복구 범위의 구체적인 내용을 알려주세요."]
    tampered = outcome.model_dump(mode="json")
    # 원문까지 함께 바꿔도 이미 받은 검수 증거와 묶인 선택값은 바꿀 수 없다.
    trigger = tampered["review_subject"]["trigger"]
    changed = "FULL" if scope == "PARTIAL" else "PARTIAL"
    trigger["restoration_answer"]["restoration_scope"] = changed
    trigger["input"]["redacted_text"] = RestorationAnswer(restoration_scope=changed, demolition_required="REQUIRED").to_input_text()
    with pytest.raises(ValidationError):
        ReviewedPlanOutcome.model_validate(tampered)


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


# ── 모델이 쓴 사실·문장이 없는 판단은 Review 모델 없이 코드 검사만 한다 ──

def test_first_judgment_reviews_with_code_only_and_marks_the_trace():
    calls, events = [], []
    store = ev.SnapshotStore(REVIEWED)
    request = ev.attach_fixture_sources(ev.build_graph_input(ev.CASES["benchmark_case1"]), store)

    class FirstModel(NoModel):
        async def generate(self, response_model, messages, **kwargs):
            calls.append(kwargs["schema_name"])
            assert kwargs["schema_name"] == "reborn_supervisor_draft", "첫 판단은 Supervisor만 부른다"
            rows = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))["contract"]["blocker_candidates"]
            return response_model.model_validate({"decision_type": "ACTION", "blocker_candidate_id": rows[0]["candidate_id"],
                                                  "action_code": rows[0]["actions"][0]["action_code"]})

    class Sink:
        def emit(self, event):
            events.append(event)

    async def run():
        with patch.object(runtime_module.StructuredLLMClient, "from_env", classmethod(lambda cls, *a, **k: FirstModel())), \
             patch.object(runtime_module.LangfuseTraceSink, "from_env", lambda: Sink()):
            runtime = await runtime_module.build_runtime(known_procedure_steps=ev.build_registry(store),
                procedure_store=store, support_catalog=ev.load_catalog(None))
            try:
                return await runtime.run_planning(request)
            finally:
                await runtime.aclose()

    outcome = asyncio.run(run())
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    assert calls == ["reborn_supervisor_draft"]
    assert [event.review_mode for event in events if event.component == "REVIEW_TOOL"] == ["CODE_ONLY"]


def test_code_only_review_still_blocks_a_draft_outside_the_reviewed_candidates():
    from app.agent.review_tool import ReviewTool
    from app.agent.supervisor import SupervisorAgent
    from test_action_codes import StubModel, supervisor_request
    from test_blocker_candidates import subject

    class NoCalls:
        async def generate(self, *args, **kwargs):
            raise AssertionError("코드 검사만 해야 한다")

    request = supervisor_request()
    draft = asyncio.run(SupervisorAgent(StubModel()).draft(request))
    action = draft.decision.next_action.model_copy(update={"title": "오늘 바로 폐업 신고서를 제출하세요."})
    draft = draft.model_copy(update={"decision": draft.decision.model_copy(update={"next_action": action})})
    result = asyncio.run(ReviewTool(NoCalls()).review_code_only(subject(request, draft)))
    assert result.verdict == "REVISE"
