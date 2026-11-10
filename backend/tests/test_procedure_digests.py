"""검수 정리본으로 첫 판단의 Info를 모델 없이 만드는지. 모델은 부르지 않는다.

정리본(app/common/procedure-digests.ko-KR.json)은 사람이 검수한 원문의 문장을 그대로 옮긴 것이라,
글자 하나만 달라도 Info 검사(_materialize)가 거절한다. 그래서 파일 자체도 여기서 확인한다.

Review 모델 없이 "코드 검사만" 하는 경로(#203)의 안전 검사 규칙 테스트도 여기 있다(ACTION_PATH 아래).
규칙마다 어느 이슈 코드·위치에서 막았는지 보고, 막혀야 하는 초안과 통과해야 하는 초안을 짝으로 둔다.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import app.agent.runtime as runtime_module
import pytest
from app.agent.action_catalog import ACTION_DEFINITIONS, PROCEDURE_LABELS
from app.agent.info_agent import agent as info_module
from app.agent.info_agent import procedure_digests
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


@pytest.mark.parametrize("scope", ["FULL", "PARTIAL"])
@pytest.mark.parametrize("detail", [None, "카운터"])
def test_restoration_answer_unknown_never_clears_confirmed_values(scope, detail):
    answer = RestorationAnswer(restoration_scope="UNKNOWN", demolition_required="UNKNOWN")
    info, calls = info_result(result_text=answer.to_input_text(), answer=answer,
        confirmed={"restoration_scope": scope, "demolition_required": "REQUIRED",
                   **({"restoration_scope_detail": detail} if detail is not None else {})})
    assert calls == [] and info.fact_candidates == [] and info.conflicts == []
    assert [field for question in info.question_candidates for field in question.resolves_field_paths] == [
        "restoration_scope", "demolition_required",
    ]


@pytest.mark.parametrize("original_scope", ["FULL", "PARTIAL"])
@pytest.mark.parametrize("accepted", [True, False])
@pytest.mark.parametrize("detail", [None, "카운터"])
@pytest.mark.parametrize("lease_status", ["LEASED_PAID", "OWNED"])
def test_scope_conflict_choice_rebuilds_only_the_missing_detail_question(original_scope, accepted, detail, lease_status):
    from app.agent.procedure_tool.cafe import build_cafe_procedure_steps
    from app.common.agent_service import build_conflict_input

    selected_scope = "PARTIAL" if original_scope == "FULL" else "FULL"
    answer = RestorationAnswer(restoration_scope=selected_scope, demolition_required="REQUIRED")
    store = ev.SnapshotStore(REVIEWED)
    registry = build_cafe_procedure_steps({code: i + 1 for i, code in enumerate(PROCEDURE_LABELS)})
    request = ev.attach_fixture_sources(ev.build_graph_input(dict(ev.CASES["benchmark_case1"], lease_status=lease_status),
        result_text=answer.to_input_text(), prior_facts={"restoration_scope": original_scope,
        "demolition_required": "REQUIRED", "restoration_scope_detail": detail}), store)
    request.trigger.restoration_answer = answer
    original = request.model_dump_json()
    captured = {}

    async def stop(supervisor_input):
        captured["info"] = next(source.output for source in supervisor_input.source_results
                                if source.meta.component == "INFO_AGENT")
        raise RuntimeError("stop after info")

    async def run():
        with patch.object(runtime_module.StructuredLLMClient, "from_env", NoModel.from_env), \
             patch.object(ev, "build_registry", lambda store: registry):
            runtime = await runtime_module.build_runtime(known_procedure_steps=ev.build_registry(store),
                procedure_store=store, support_catalog=ev.load_catalog(None))
            try:
                first = await runtime.run_planning(request)
                assert first.outcome_type == "CONFLICT", first
                confirmed = build_conflict_input(case_snapshot=first.conflict_snapshot.model_copy(deep=True),
                    conflicts=first.conflicts, conflict_snapshot=first.conflict_snapshot,
                    retained_info_result=first.retained_info_result,
                    selections=[{"conflict_ref": conflict.conflict_ref, "accepted": accepted} for conflict in first.conflicts],
                    input_event_id="synthetic-detail-confirm", confirmed_at=request.case_snapshot.captured_at)
                before = confirmed.model_dump_json()
                runtime._graph._supervisor.draft = stop
                await runtime.run_planning(confirmed)
                assert confirmed.model_dump_json() == before
            finally:
                await runtime.aclose()

    asyncio.run(run())
    assert request.model_dump_json() == original
    info = captured["info"]
    effective_scope = selected_scope if accepted else original_scope
    expected = ["restoration_scope_detail"] if lease_status != "OWNED" and effective_scope == "PARTIAL" and detail is None else []
    assert [item.field_path for item in info.missing_fields] == expected
    assert [field for question in info.question_candidates for field in question.resolves_field_paths] == expected
    assert all(fact.field_path != "restoration_scope_detail" for fact in info.fact_candidates)


@pytest.mark.parametrize("digests", ["unreviewed", "changed_source"])
def test_restoration_answer_fails_without_calling_a_model_when_digests_are_untrusted(digests):
    if digests == "changed_source":
        data = digest_file() | {"reviewed_by": "test", "reviewed_at": "2026-11-05"}
        digests = data | {"source_hashes": {key: "sha256:" + "0" * 64 for key in data["source_hashes"]}}
    answer = RestorationAnswer(restoration_scope="FULL", demolition_required="REQUIRED")
    info, calls = info_result(result_text=answer.to_input_text(), answer=answer, digests=digests)
    assert info is None and calls == []


@pytest.mark.parametrize("scope,detail", [("FULL", None), ("PARTIAL", None), ("PARTIAL", "카운터")])
def test_restoration_answer_uses_supervisor_and_code_review_without_review_model(scope, detail):
    # 선택형은 모델이 쓴 사실·문장이 없어 Review 모델 없이 코드 검사만 한다(graph review_code_only).
    from pydantic import ValidationError
    from app.agent.schemas import ReviewedPlanOutcome

    calls = []
    answer = RestorationAnswer(restoration_scope=scope, demolition_required="REQUIRED")
    needs_detail = scope == "PARTIAL" and detail is None
    store = ev.SnapshotStore(REVIEWED)
    request = ev.attach_fixture_sources(ev.build_graph_input(ev.CASES["benchmark_case1"],
        result_text=answer.to_input_text(), prior_facts={"restoration_scope_detail": detail}), store)
    request.trigger.restoration_answer = answer

    class SelectionModel(NoModel):
        async def generate(self, response_model, messages, **kwargs):
            name = kwargs["schema_name"]
            calls.append(name)
            assert name not in {"reborn_info_analysis", "reborn_review_output"}, "선택형은 Info·Review 모델을 부르지 않는다"
            contract = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))["contract"]
            if needs_detail:
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
    # "일부"면 구체 범위 질문이 먼저라 Supervisor 모델도 부르지 않는다
    assert calls == ([] if needs_detail else ["reborn_supervisor_draft"])
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    assert outcome.review_subject.trigger.restoration_answer == answer
    if needs_detail:
        decision = outcome.review_subject.supervisor_draft.decision
        assert decision.decision_type == "NEEDS_MORE_INFO" and decision.next_action is None
        assert list(decision.questions_for_user) == ["확인한 원상복구 범위의 구체적인 내용을 알려주세요."]
    else:
        assert outcome.review_subject.supervisor_draft.decision.questions_for_user == []
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


def test_digest_recalculation_keeps_demolition_support_as_preparation_only():
    from app.agent.procedure_tool.cafe import build_cafe_procedure_steps

    registry = build_cafe_procedure_steps({code: i + 1 for i, code in enumerate(PROCEDURE_LABELS)})
    # 지원금 승인을 받은 자료 없이, 실제 카페 절차·검수 원문과 임대인 답변만 사용한다.
    with patch.object(ev, "build_registry", lambda store: registry):
        info, calls = landlord_answer_info()

    assert len(calls) == 1 and calls[0]["schema"] == "InfoFactProviderOutput"
    assert {item.field_path: item.value for item in info.fact_candidates} == {
        "restoration_scope": "PARTIAL", "demolition_required": "REQUIRED",
    }
    finding = next(item for item in info.procedure_findings if item.procedure_step.step_code == "PERFORM_RESTORATION")
    assert any(action.text in records()["DEMOLITION_SUPPORT_2026"]["excerpt"] for action in finding.required_actions)
    assert finding.relevance == "POSSIBLY_RELEVANT"
    assert finding.requires_confirmation is True


def test_landlord_answer_falls_back_to_the_full_analysis_without_a_trusted_digest():
    # 이 가짜 모델은 절차 정리를 내지 않아 전체 분석 검사에 걸려 재시도까지 간다. 모양만 본다
    _, seen = landlord_answer_info(digests="unreviewed")
    assert seen and {call["schema"] for call in seen} == {"InfoProviderOutput"}


@pytest.mark.parametrize("digests", ["reviewed", "unreviewed"])
def test_fact_prompt_keeps_case_context_and_only_omits_procedure_rules_with_digests(digests):
    captured = {}
    analyze = info_module.InfoAnalysisAgent.analyze

    async def capture(agent, request):
        before = request.model_dump_json()
        captured["full"] = agent._prompt_input(request)
        try:
            return await analyze(agent, request)
        finally:
            assert request.model_dump_json() == before

    with patch.object(info_module.InfoAnalysisAgent, "analyze", capture):
        _, calls = landlord_answer_info(digests=digests)
    sent = json.loads(calls[0]["messages"][1]["content"].removeprefix("INPUT_JSON="))
    expected = captured["full"]
    if digests == "reviewed":
        for key in ("procedure_analysis_step_codes", "procedure_evidence_by_step", "procedure_lookup"):
            expected.pop(key)
        keep = {"procedure_step", "step_name", "utterance_aliases", "deprecated_at"}
        expected["known_procedure_steps"] = [
            {key: value for key, value in step.items() if key in keep}
            for step in expected["known_procedure_steps"]
        ]
    assert sent == expected


@pytest.mark.parametrize("status,submitted", [("IN_PROGRESS", True), ("COMPLETED", True)])
def test_fact_prompt_retains_submission_and_completion_reports(status, submitted):
    text = "사업자등록 폐업신고서를 제출했습니다." if status == "IN_PROGRESS" else "사업자등록 폐업신고의 기관 처리 완료를 확인했습니다."
    captured = {}
    analyze = info_module.InfoAnalysisAgent.analyze

    class ReportsProgress(FactModel):
        async def generate(self, response_model, messages, **kwargs):
            out = (await super().generate(response_model, messages, **kwargs)).model_dump(mode="python")
            out["facts"] = []
            out["procedure_observations"] = [{
                "step_code": "FILE_TAX_BUSINESS_CLOSURE", "observed_status": status,
                "source_text": text, "requirements_confirmed": True, "submitted": submitted,
                "requires_confirmation": False, "reason_summary": "사용자의 신고 진행 보고",
            }]
            return response_model.model_validate(out)

    async def capture(agent, request):
        captured["result"] = await analyze(agent, request)
        return captured["result"]

    with patch.object(NoModel, "from_env", classmethod(lambda cls, *a, **k: ReportsProgress())), \
         patch.object(info_module.InfoAnalysisAgent, "analyze", capture):
        info_result(result_text=text)
    [observation] = captured["result"].procedure_progress_observations
    assert observation.procedure_step.step_code == "FILE_TAX_BUSINESS_CLOSURE"
    assert observation.source_span.text == text
    assert observation.observed_status == status and observation.submitted is submitted
    assert observation.requires_confirmation is (status == "COMPLETED")


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


# 아래 테스트는 "반려됐다"만 보지 않고 어느 규칙(코드·위치)에 걸렸는지 본다. 한 초안이 여러 규칙에
# 함께 걸리므로, verdict만 보면 규칙 하나를 지워도 테스트가 계속 통과한다(멘토 리뷰 #187).
ACTION_PATH = "/supervisor_draft/decision/next_action"


def _code_only_issues(request, draft):
    from app.agent.review_tool import ReviewTool
    from test_blocker_candidates import subject

    result = asyncio.run(ReviewTool(NoModel()).review_code_only(subject(request, draft)))
    return {(issue.issue_code, issue.target_path) for issue in result.issues}


def _with_freshness(request, freshness):
    # 근거만 바꾸면 출처 지문이 안 맞아 무결성 검사에서 먼저 막힌다. 처음부터 그 근거였던 것처럼 다시 만든다.
    from test_action_codes import canonical_digest, source

    request = request.model_copy(deep=True)
    lookup, info = request.source_results[0].output, request.source_results[1].output
    for record in [*lookup.evidence_records, *lookup.documents, *request.case_snapshot.evidence_records]:
        record.freshness_status = freshness
    info.based_on_procedure_lookup_digest = canonical_digest(lookup)
    request.source_results[0], request.source_results[1] = source(lookup, "PROCEDURE_TOOL", 5), source(info)
    return request


@pytest.mark.parametrize("freshness", ["STALE", "UNKNOWN"])
def test_code_only_review_blocks_an_execution_action_on_unverified_evidence(freshness):
    from app.agent.schemas import ProcedureProgress
    from app.agent.supervisor import SupervisorAgent
    from test_action_codes import NOW, REF, TAX, StubModel, source, supervisor_request

    request = supervisor_request().model_copy(deep=True)
    finding = request.source_results[1].output.procedure_findings[0]
    finding.requires_confirmation = False
    request.source_results[1] = source(request.source_results[1].output)
    request.case_snapshot.procedure_progress = [ProcedureProgress(procedure_step=finding.procedure_step,
        status="IN_PROGRESS", requirements_confirmed=True, evidence_refs=[REF], updated_at=NOW)]
    draft = asyncio.run(SupervisorAgent(StubModel(action_code=TAX)).draft(request))
    assert draft.decision.next_action.action_code == TAX
    assert _code_only_issues(request, draft) == set()  # 최신 근거면 실행 안내 통과
    assert ("STALE_EVIDENCE", ACTION_PATH) in _code_only_issues(_with_freshness(request, freshness), draft)


@pytest.mark.parametrize("freshness", ["STALE", "UNKNOWN"])
def test_code_only_review_allows_a_confirmation_action_on_unverified_evidence(freshness):
    # 최신인지 모르는 근거라도 "확인해 주세요" 행동은 막지 않는다(실행 지시만 막는다)
    from app.agent.supervisor import SupervisorAgent
    from test_action_codes import StubModel, supervisor_request

    request = _with_freshness(supervisor_request(), freshness)
    draft = asyncio.run(SupervisorAgent(StubModel()).draft(request))
    assert draft.decision.next_action.questions_to_ask
    assert _code_only_issues(request, draft) == set()


@pytest.mark.parametrize("change", [{"questions_to_ask": []}, {"requires_human": False}])
def test_code_only_review_blocks_a_procedure_that_needs_confirmation_without_asking(change):
    from app.agent.supervisor import SupervisorAgent
    from test_action_codes import StubModel, supervisor_request

    request = supervisor_request()
    draft = asyncio.run(SupervisorAgent(StubModel()).draft(request))
    assert _code_only_issues(request, draft) == set()  # 확인 질문이 있으면 통과
    decision = draft.decision
    if "requires_human" in change:
        decision = decision.model_copy(update=change)
    else:
        decision = decision.model_copy(update={"next_action": decision.next_action.model_copy(update=change)})
    draft = draft.model_copy(update={"decision": decision})
    assert ("HUMAN_CONFIRMATION_OMITTED", ACTION_PATH) in _code_only_issues(request, draft)


REASON_PATH = f"{ACTION_PATH}/reason"
OVERCONFIDENT_SUPPORT = "지원 대상입니다. 무조건 받을 수 있어요."


def _confirm_case():
    from app.agent.supervisor import SupervisorAgent
    from test_action_codes import StubModel, supervisor_request

    request = supervisor_request()
    draft = asyncio.run(SupervisorAgent(StubModel()).draft(request))
    assert _code_only_issues(request, draft) == set()  # 바꾸기 전 정상 초안은 통과
    return request, draft


def _with_reason(draft, text):
    action = draft.decision.next_action.model_copy(update={"reason": text})
    return draft.model_copy(update={"decision": draft.decision.model_copy(update={"next_action": action})})


def test_code_only_review_blocks_overconfident_and_ungrounded_support_text():
    request, draft = _confirm_case()
    issues = _code_only_issues(request, _with_reason(draft, OVERCONFIDENT_SUPPORT))
    assert ("OVERCONFIDENT_LANGUAGE", REASON_PATH) in issues  # 화면 문장의 단정 표현
    assert ("UNSUPPORTED_CLAIM", REASON_PATH) in issues  # 지원 자격 문장에 근거 연결 없음


def test_code_only_review_blocks_an_overconfident_grounded_claim():
    # 근거 문장(GroundedClaim)까지 같이 바꾸면 화면 문장 규칙과 같은 위치에 걸린다. 근거가 붙은 반려로 구분한다
    from app.agent.review_tool import ReviewTool
    from test_blocker_candidates import subject

    request, draft = _confirm_case()
    claims = [claim.model_copy(update={"text": OVERCONFIDENT_SUPPORT}) if claim.target_path == REASON_PATH else claim
              for claim in draft.grounded_claims]
    draft = _with_reason(draft, OVERCONFIDENT_SUPPORT).model_copy(update={"grounded_claims": claims})
    result = asyncio.run(ReviewTool(NoModel()).review_code_only(subject(request, draft)))
    assert any(issue.issue_code == "OVERCONFIDENT_LANGUAGE" and issue.target_path == REASON_PATH and issue.evidence_refs
               for issue in result.issues)


def test_code_only_review_requires_an_official_source_for_each_claim():
    from test_action_codes import evidence

    request, draft = _confirm_case()
    request = request.model_copy(deep=True)
    request.case_snapshot.evidence_records.append(evidence(evidence_id="user-1", source_type="USER_INPUT"))
    index = next(i for i, claim in enumerate(draft.grounded_claims) if claim.target_path == REASON_PATH)
    claims = list(draft.grounded_claims)
    claims[index] = claims[index].model_copy(update={"evidence_refs": ["user-1"]})  # 공식 자료 대신 사장님 입력만
    issues = _code_only_issues(request, draft.model_copy(update={"grounded_claims": claims}))
    assert ("MISSING_EVIDENCE", f"/supervisor_draft/grounded_claims/{index}") in issues


@pytest.mark.parametrize("prerequisite_done", [False, True])
def test_code_only_review_blocks_a_procedure_before_its_prerequisite(prerequisite_done):
    from app.agent.schemas import ProcedureProgress
    from test_action_codes import NOW, REF

    request, draft = _confirm_case()
    request = request.model_copy(deep=True)
    step = request.known_procedure_steps[0]
    prerequisite = step.model_copy(deep=True, update={"step_name": "선행 절차", "dependencies": []})
    prerequisite.procedure_step = step.procedure_step.model_copy(update={"procedure_step_id": 2, "step_code": "PRE_STEP"})
    step.dependencies = [{"prerequisite_procedure_step_id": 2, "dependency_type": "SEQUENTIAL"}]
    request.known_procedure_steps.append(prerequisite)
    if prerequisite_done:
        request.case_snapshot.procedure_progress.append(ProcedureProgress(procedure_step=prerequisite.procedure_step,
            status="COMPLETED", requirements_confirmed=True, evidence_refs=[REF], updated_at=NOW))
    blocked = ("PROCEDURE_CONFLICT", f"{ACTION_PATH}/target") in _code_only_issues(request, draft)
    assert blocked is not prerequisite_done


@pytest.mark.parametrize(
    "info_used_model,revision_count,expected",
    [(False, 0, "CODE_ONLY"), (True, 0, "MODEL"), (False, 1, "MODEL")],
)
def test_only_a_first_round_without_model_text_skips_the_review_model(info_used_model, revision_count, expected):
    # 재작업 회차는 Supervisor가 반려를 받고 다시 쓴 초안이라 Review 모델이 본다
    from unittest.mock import AsyncMock
    from uuid import UUID
    from app.agent.graph import AgentGraph
    from app.agent.review_tool import ReviewTool
    from test_action_codes import NOW, StubModel

    used = []

    class Recorder(ReviewTool):
        async def review(self, subject):
            used.append("MODEL")
            return await super().review(subject)

        async def review_code_only(self, subject):
            used.append("CODE_ONLY")
            return await super().review_code_only(subject)

    request, draft = _confirm_case()
    graph = AgentGraph(procedure_tool=AsyncMock(), info_agent=AsyncMock(), support_agent=AsyncMock(),
                       supervisor=AsyncMock(), review_tool=Recorder(StubModel()),
                       known_procedure_steps=request.known_procedure_steps, clock=lambda: NOW)
    asyncio.run(graph._review_node({"run_id": UUID(int=2), "request": request, "source_results": request.source_results,
                                    "current_draft": draft, "info_used_model": info_used_model,
                                    "revision_count": revision_count}))
    assert used == [expected]


def _with_action(draft, **update):
    action = draft.decision.next_action.model_copy(update=update)
    return draft.model_copy(update={"decision": draft.decision.model_copy(update={"next_action": action})})


def _claim_index(draft, path):
    return next(index for index, claim in enumerate(draft.grounded_claims) if claim.target_path == path)


def test_code_only_review_blocks_a_claim_that_no_longer_matches_the_visible_text():
    request, draft = _confirm_case()
    index = _claim_index(draft, REASON_PATH)
    issues = _code_only_issues(request, _with_reason(draft, "근거 문장과 다른 화면 문장입니다."))
    assert ("CONTRACT_VIOLATION", f"/supervisor_draft/grounded_claims/{index}/target_path") in issues


@pytest.mark.parametrize("change", ["information_level", "no_caveat"])
def test_code_only_review_blocks_a_definite_claim_on_unverified_evidence(change):
    # 최신인지 모르는 근거의 문장은 "확인 필요" 수준이고 확인 문구가 있어야 한다(확인 안내 초안 자체는 통과)
    from app.agent.supervisor import SupervisorAgent
    from test_action_codes import StubModel, supervisor_request

    request = _with_freshness(supervisor_request(), "STALE")
    draft = asyncio.run(SupervisorAgent(StubModel()).draft(request))
    index = _claim_index(draft, REASON_PATH)
    claims = list(draft.grounded_claims)
    if change == "information_level":
        claims[index] = claims[index].model_copy(update={"assertion_level": "INFORMATION"})
        expected = ("STALE_EVIDENCE", f"/supervisor_draft/grounded_claims/{index}")
    else:
        text = "사업자 폐업신고 준비사항입니다."
        claims[index] = claims[index].model_copy(update={"text": text})
        draft = _with_reason(draft, text)
        expected = ("STALE_EVIDENCE", REASON_PATH)
    assert expected in _code_only_issues(request, draft.model_copy(update={"grounded_claims": claims}))


def _support_case(check_update=None, duplicate=False):
    # Supervisor는 지원사업 행동을 코드 후보로 내지 않으므로, 절차 확인 초안의 행동만 지원사업으로 바꿔 Review를 시험한다
    from app.agent.supervisor import SupervisorAgent
    from test_action_codes import StubModel, evidence, source, support_sources, supervisor_request

    request = supervisor_request().model_copy(deep=True)
    request.case_snapshot.evidence_records.append(evidence(evidence_id="user-1", source_type="USER_INPUT"))
    output = support_sources()[0].output
    if check_update:
        check = output.support_checks[0]
        output = output.model_copy(update={"support_checks": [type(check).model_validate({**check.model_dump(), **check_update})]})
    request.source_results += [source(output, call_id=call_id) for call_id in ([9, 10] if duplicate else [9])]
    return request, asyncio.run(SupervisorAgent(StubModel()).draft(request))


def _support_action(draft, program_id=1, **update):
    from uuid import UUID
    from app.agent.schemas import SupportActionTarget

    target = SupportActionTarget.model_validate({"target_kind": "SUPPORT_PROGRAM", "support_program": {
        "support_program_id": program_id, "wiki_uuid": UUID(int=6 if program_id == 1 else program_id)}})
    return _with_action(draft, **{
        "action_code": "CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS", "target": target,
        "title": "합성 지원사업 신청 조건을 확인해 주세요.", "reason": "합성 지원사업 조건 확인이 필요합니다.",
        "questions_to_ask": ["합성 지원사업 신청 조건을 확인해 주시겠습니까?"], **update})


@pytest.mark.parametrize("check_update,duplicate,change,expected", [
    ({}, False, {"program_id": 99}, ("CONTRACT_VIOLATION", f"{ACTION_PATH}/target")),  # 분석에 없는 지원사업
    ({}, True, {}, ("CONTRACT_VIOLATION", f"{ACTION_PATH}/target")),  # 같은 지원사업 분석이 둘
    ({"match_status": "NOT_RELEVANT", "criteria": [{"criterion_code": "BUSINESS_TYPE", "case_value": "카페",
      "required_values": ["제조업"], "status": "NOT_MET", "reason_summary": "업종 불일치",
      "evidence_refs": ["synthetic-document"]}]}, False, {}, ("INFEASIBLE_ACTION", ACTION_PATH)),  # 관련 없다고 나온 지원사업
    ({}, False, {"evidence_refs": ["user-1"]}, ("MISSING_EVIDENCE", f"{ACTION_PATH}/evidence_refs")),  # 분석 근거와 연결 없음
    ({}, False, {"title": "합성 지원사업 확인 후 폐업 신고서를 내세요."}, ("PROCEDURE_CONFLICT", f"{ACTION_PATH}/target")),
    ({}, False, {"questions_to_ask": []}, ("HUMAN_CONFIRMATION_OMITTED", ACTION_PATH)),  # 기관 확인 질문 없음
])
def test_code_only_review_blocks_an_unsafe_support_action(check_update, duplicate, change, expected):
    plain_request, plain_draft = _support_case()
    assert expected not in _code_only_issues(plain_request, _support_action(plain_draft))
    request, draft = _support_case(check_update, duplicate)
    assert expected in _code_only_issues(request, _support_action(draft, **change))


def test_code_only_review_blocks_a_procedure_action_without_its_analysis():
    request, draft = _confirm_case()
    request = request.model_copy(deep=True)
    other = request.known_procedure_steps[0].model_copy(deep=True, update={"step_name": "분석 안 된 절차"})
    other.procedure_step = other.procedure_step.model_copy(update={"procedure_step_id": 2, "step_code": "OTHER_STEP"})
    request.known_procedure_steps.append(other)
    from app.agent.supervisor import SupervisorAgent
    from test_action_codes import StubModel

    draft = asyncio.run(SupervisorAgent(StubModel()).draft(request))
    target = draft.decision.next_action.target.model_copy(update={"procedure_step": other.procedure_step})
    assert ("PROCEDURE_CONFLICT", f"{ACTION_PATH}/target") in _code_only_issues(request, _with_action(draft, target=target))


def test_code_only_review_blocks_a_procedure_action_with_evidence_outside_its_analysis():
    from app.agent.supervisor import SupervisorAgent
    from test_action_codes import StubModel, evidence

    request, _ = _confirm_case()
    request = request.model_copy(deep=True)
    request.case_snapshot.evidence_records.append(evidence(evidence_id="user-1", source_type="USER_INPUT"))
    draft = asyncio.run(SupervisorAgent(StubModel()).draft(request))
    issues = _code_only_issues(request, _with_action(draft, evidence_refs=["user-1"]))
    assert ("MISSING_EVIDENCE", f"{ACTION_PATH}/evidence_refs") in issues


def test_code_only_review_blocks_a_procedure_action_that_also_names_a_support_program():
    plain_request, draft = _support_case()
    assert _code_only_issues(plain_request, draft) == set()
    issues = _code_only_issues(plain_request, _with_action(draft, title="합성 지원사업과 함께 폐업 준비사항을 확인하세요."))
    assert ("CONTRACT_VIOLATION", f"{ACTION_PATH}/target") in issues


@pytest.mark.parametrize("detail_state", ["unknown", "held", "conflict"])
def test_a_free_text_reply_with_unknown_detail_still_lets_the_supervisor_choose(detail_state):
    # "구체 범위 먼저" 규칙은 선택형 답변에만 쓴다. 자유글 답변("아직 모름" 포함)은 모델이 고른다(같은 질문 반복 방지).
    calls = []
    store = ev.SnapshotStore(REVIEWED)
    request = ev.attach_fixture_sources(ev.build_graph_input(ev.CASES["benchmark_case1"], result_text=LANDLORD,
        prior_facts={"restoration_scope_detail": "싱크대"} if detail_state == "conflict" else None), store)

    class Model(FactModel):
        async def generate(self, response_model, messages, **kwargs):
            name = kwargs["schema_name"]
            calls.append(name)
            if name == "reborn_review_output":
                return response_model.model_validate({"verdict": "PASS", "issues": [], "missing_evidence": [],
                    "recommended_rework_targets": [], "resolution_reason": "합성 검수"})
            if name == "reborn_supervisor_draft":
                contract = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))["contract"]
                assert any(item["candidate_id"] == "missing:restoration_scope_detail"
                           for item in contract["information_blockers"])
                return response_model.model_validate({"decision_type": "NEEDS_MORE_INFO",
                    "blocker_candidate_id": "missing:restoration_scope_detail", "action_code": None})
            out = (await super().generate(response_model, messages, **kwargs)).model_dump(mode="python")
            out["missing_fields"] = [{"field_path": "restoration_scope_detail", "reason_summary": "세부 대상 미확인",
                                      "blocks": ["SUPERVISOR_DECISION"], "question": "어떤 부분을 원래대로 해야 하나요?"}]
            if detail_state in {"held", "conflict"}:
                out["missing_fields"] = []
                out["facts"].append({"operation": "SET", "field_path": "restoration_scope_detail",
                    "value_type": "STRING", "value": "카운터", "source_text": LANDLORD,
                    "confidence_bps": 7000, "requires_confirmation": detail_state == "held",
                    "reason_summary": "세부 범위 확인 대기"})
            out["completion_status"] = "NEEDS_USER_INPUT" if detail_state == "unknown" else "COMPLETE"
            return response_model.model_validate(out)

    async def run():
        with patch.object(runtime_module.StructuredLLMClient, "from_env", classmethod(lambda cls, *a, **k: Model())):
            runtime = await runtime_module.build_runtime(known_procedure_steps=ev.build_registry(store),
                procedure_store=store, support_catalog=ev.load_catalog(None))
            try:
                return await runtime.run_planning(request)
            finally:
                await runtime.aclose()

    outcome = asyncio.run(run())
    if detail_state == "conflict":
        assert outcome.outcome_type == "CONFLICT", outcome
        [conflict] = outcome.conflicts
        assert (conflict.field_path, conflict.committed_value, conflict.proposed_value) == (
            "restoration_scope_detail", "싱크대", "카운터",
        )
        assert calls == ["reborn_info_analysis"]
        assert next(fact.value for fact in request.case_snapshot.facts if fact.field_path == conflict.field_path) == "싱크대"
        return
    assert "reborn_supervisor_draft" in calls, (calls, outcome)
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    draft = outcome.review_subject.supervisor_draft
    assert list(draft.decision.questions_for_user) == ["확인한 원상복구 범위의 구체적인 내용을 알려주세요."]
    assert all(change.field_path != "restoration_scope_detail" for change in draft.mutations.fact_changes)


@pytest.mark.parametrize("with_retained", [False, True])
def test_conflict_confirmation_fills_info_from_digest_and_keeps_the_review_model(with_retained):
    # 충돌 확인 후 재판단은 새 사실을 꺼내지 않아 Info를 정리본으로 채운다. 보관된 사실은 이전 판단에서
    # Info 모델이 글에서 꺼내 아직 Review를 안 거쳤으므로 Review 모델은 유지한다.
    from datetime import datetime, timezone
    from app.common.agent_service import build_conflict_input

    lines = ["자가가 아니라 무상 임차예요.", "폐업 예정일은 2026-12-20입니다."]
    text = " ".join(lines if with_retained else lines[:1])
    calls = []
    store = ev.SnapshotStore(REVIEWED)
    request = ev.attach_fixture_sources(ev.build_graph_input(ev.CASES["benchmark_case1"], result_text=text), store)

    class Model(NoModel):
        async def generate(self, response_model, messages, **kwargs):
            name = kwargs["schema_name"]
            calls.append(name)
            if name == "reborn_review_output":
                return response_model.model_validate({"verdict": "PASS", "issues": [], "missing_evidence": [],
                    "recommended_rework_targets": [], "resolution_reason": "합성 검수"})
            if name == "reborn_supervisor_draft":
                contract = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))["contract"]
                if contract["blocker_candidates"]:
                    row = contract["blocker_candidates"][0]
                    return response_model.model_validate({"decision_type": "ACTION", "blocker_candidate_id": row["candidate_id"],
                                                          "action_code": row["actions"][0]["action_code"]})
                return response_model.model_validate({"decision_type": "NEEDS_MORE_INFO",
                    "blocker_candidate_id": contract["information_blockers"][0]["candidate_id"], "action_code": None})
            return response_model.model_validate({
                "completion_status": "COMPLETE",
                "facts": [{"operation": "SET", "field_path": field, "value_type": kind, "value": value,
                           "source_text": line, "confidence_bps": 9500, "requires_confirmation": False,
                           "reason_summary": "합성 사용자 진술"}
                          for field, kind, value, line in [("lease_status", "ENUM", "LEASED_FREE", lines[0]),
                                                           ("planned_closure_date", "DATE", "2026-12-20", lines[1])]
                          if line in text],
                "procedure_observations": [], "missing_fields": [], "uncertainties": [],
                **({} if response_model.__name__ == "InfoFactProviderOutput" else {"procedure_findings": []}),
            })

    async def run():
        with patch.object(runtime_module.StructuredLLMClient, "from_env", classmethod(lambda cls, *a, **k: Model())):
            runtime = await runtime_module.build_runtime(known_procedure_steps=ev.build_registry(store),
                procedure_store=store, support_catalog=ev.load_catalog(None))
            try:
                first = await runtime.run_planning(request)
                assert first.outcome_type == "CONFLICT", first
                calls.clear()
                confirmed = build_conflict_input(
                    case_snapshot=first.conflict_snapshot.model_copy(deep=True), conflicts=first.conflicts,
                    conflict_snapshot=first.conflict_snapshot, retained_info_result=first.retained_info_result,
                    selections=[{"conflict_ref": c.conflict_ref, "accepted": True} for c in first.conflicts],
                    input_event_id="owner-confirmation", confirmed_at=datetime.now(timezone.utc))
                return await runtime.run_planning(confirmed)
            finally:
                await runtime.aclose()

    outcome = asyncio.run(run())
    assert outcome.outcome_type == "REVIEWED_PLAN", (outcome.failure_code, getattr(outcome, "failure_message_code", None), calls)
    # Info 모델은 부르지 않는다. 보관된 사실(모델이 꺼내 아직 Review 전)이 있으면 Review 모델을 유지한다
    assert calls == ["reborn_supervisor_draft", "reborn_review_output"] if with_retained else ["reborn_supervisor_draft"]


# ── [했어요] 버튼: 지금 할 일의 답을 모델 해석 없이 코드로 받는다 ──
# 운영에서 "넵 다 확인 완료했어요"·"전/후 사진 찍었어요"가 준비 확인으로 저장되지 않아 같은 안내가
# 반복되거나 판단이 멈췄고(2026-11-07), "식품영업 폐업신고 했어요"도 판단이 멈췄다(11-08).
# 준비 확인은 준비만, 신고 제출은 제출까지, 처리 결과 확인·직접 하는 일은 완료로 그 판단에서 반영한다.

def _action_done_outcome(action_code, prior_facts, *, insured=False, step_code=None, progress=None, prefer=None):
    from app.agent.procedure_tool.cafe import build_cafe_procedure_steps
    from app.agent.schemas import ActionDoneAnswer

    # 테스트용 ev.build_registry에는 선후 규칙이 없다. 운영과 같은 카페 절차 목록으로 돌린다
    registry = build_cafe_procedure_steps({code: i + 1 for i, code in enumerate(PROCEDURE_LABELS)})
    step = next(item.procedure_step for item in registry
                if item.procedure_step.step_code == (step_code or ACTION_DEFINITIONS[action_code].procedure_logical_code))
    answer = ActionDoneAnswer(action_code=action_code, procedure_step_id=step.procedure_step_id)
    store = ev.SnapshotStore(REVIEWED)
    request = ev.attach_fixture_sources(ev.build_graph_input(ev.CASES["benchmark_case1"],
        result_text=answer.to_input_text(), prior_facts=prior_facts), store)
    payload = request.model_dump(mode="json")
    base = next(fact for fact in payload["case_snapshot"]["facts"] if fact["field_path"] == "franchise_status")
    if insured:
        # 준비 데이터는 보험 칸을 옮기지 않는다. 가게 만들기에서 고른 값처럼 확정 사실로 넣는다
        payload["case_snapshot"]["facts"].extend(dict(base, field_path=field, value=True) for field in _INSURED_FIELDS)
    if progress:
        # 지금 할 일이 나오기 직전까지의 진행 상태(상태, 준비 확인, 제출)
        status, prepared, submitted = progress
        payload["case_snapshot"]["procedure_progress"].append({
            "procedure_step": step.model_dump(mode="json"), "status": status, "requirements_confirmed": prepared,
            "submitted": submitted, "evidence_refs": base["evidence_refs"], "updated_at": base["updated_at"],
        })
    request = AgentGraphInput.model_validate(payload)
    request.trigger.action_done = answer
    calls, seen = [], {}
    prefer = prefer or ACTION_DEFINITIONS[action_code].procedure_logical_code

    class SelectionModel(NoModel):
        async def generate(self, response_model, messages, **kwargs):
            calls.append(kwargs["schema_name"])
            contract = json.loads(messages[1]["content"].removeprefix("INPUT_JSON="))["contract"]
            seen["rows"] = {row["candidate_id"]: [action["action_code"] for action in row["actions"]]
                            for row in contract["blocker_candidates"]}
            row = next((row for row in contract["blocker_candidates"]
                        if any(action["action_code"] == prefer for action in row["actions"])),
                       contract["blocker_candidates"][0])
            action = next((item for item in row["actions"] if item["action_code"] == prefer), row["actions"][0])
            return response_model.model_validate({"decision_type": "ACTION", "blocker_candidate_id": row["candidate_id"],
                                                  "action_code": action["action_code"]})

    async def run():
        with patch.object(runtime_module.StructuredLLMClient, "from_env", classmethod(lambda cls, *a, **k: SelectionModel())):
            runtime = await runtime_module.build_runtime(known_procedure_steps=registry,
                procedure_store=store, support_catalog=ev.load_catalog(None))
            try:
                return await runtime.run_planning(request)
            finally:
                await runtime.aclose()

    return asyncio.run(run()), calls, seen.get("rows", {}), answer


def _change(outcome, answer):
    [change] = outcome.review_subject.supervisor_draft.mutations.procedure_progress_changes
    assert change.procedure_step.procedure_step_id == answer.procedure_step_id
    return change.proposed_status, change.proposed_requirements_confirmed, change.proposed_submitted


_SCOPE_CONFIRMED = {"restoration_scope": "FULL", "demolition_required": "REQUIRED"}
_RESTORATION_DONE = {"restoration_scope": "FULL", "demolition_required": "NOT_REQUIRED", "restoration_status": "COMPLETED"}
# 가게 만들기에서 가게 이름으로 낸 보험을 고른 상태. "잘 모르겠어요"는 화면에서 고를 수 없다
_INSURED_FIELDS = ("pension_enrolled", "health_insurance_enrolled",
                   "employment_insurance_enrolled", "industrial_accident_insurance_enrolled")


@pytest.mark.parametrize("action_code,prior_facts,insured", [
    ("CONFIRM_TAX_CLOSURE_REQUIREMENTS", _SCOPE_CONFIRMED, False),
    ("CONFIRM_FOOD_SERVICE_CLOSURE_REQUIREMENTS", _SCOPE_CONFIRMED, False),
    ("CONFIRM_WORKPLACE_INSURANCE_CLOSURE_REQUIREMENTS", _SCOPE_CONFIRMED, True),
    ("CONFIRM_EMPLOYEE_SETTLEMENT_REQUIREMENTS", _SCOPE_CONFIRMED, False),
    ("CONFIRM_EMPLOYEE_INSURANCE_LOSS_REQUIREMENTS", _SCOPE_CONFIRMED, True),
    # 점포 반환은 철거가 끝나야 할 일로 나온다(카페 절차 선후 규칙)
    ("CONFIRM_PREMISES_RETURN_REQUIREMENTS", _RESTORATION_DONE, False),
])
def test_preparation_done_moves_to_execution_in_the_same_judgment(action_code, prior_facts, insured):
    outcome, calls, rows, answer = _action_done_outcome(action_code, prior_facts, insured=insured)
    execution = ACTION_DEFINITIONS[action_code].procedure_logical_code

    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    # 버튼 답은 Info·Review 모델 없이, Supervisor 선택 한 번과 코드 검사로 끝난다
    assert calls == ["reborn_supervisor_draft"]
    # 같은 준비 안내를 다시 고를 수 없고, 그 절차는 실행 행동으로 넘어간다
    assert rows[f"procedure:{answer.procedure_step_id}"] == [execution]
    assert outcome.review_subject.supervisor_draft.decision.next_action.action_code == execution
    # 준비 확인만 남긴다. 제출·완료는 준비 버튼으로 정하지 않는다
    assert _change(outcome, answer) == ("IN_PROGRESS", True, False)
    assert outcome.review_subject.trigger.action_done == answer


def test_preparation_done_for_demolition_saves_preparation_without_ordering_demolition():
    # 철거 준비는 지원금 증빙 안내라 확인해도 철거 실행을 지시하지 않는다(#290). 다른 절차로 넘어간다
    outcome, calls, rows, answer = _action_done_outcome("CONFIRM_RESTORATION_REQUIREMENTS", _SCOPE_CONFIRMED)

    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    assert calls == ["reborn_supervisor_draft"]
    assert f"procedure:{answer.procedure_step_id}" not in rows
    assert _change(outcome, answer) == ("IN_PROGRESS", True, False)


@pytest.mark.parametrize("action_code,insured", [
    ("FILE_TAX_BUSINESS_CLOSURE", False),
    ("FILE_FOOD_SERVICE_CLOSURE", False),
    ("REPORT_WORKPLACE_INSURANCE_CLOSURE", True),
    ("REPORT_EMPLOYEE_INSURANCE_LOSS", True),
])
def test_submission_done_moves_to_the_processing_check_in_the_same_judgment(action_code, insured):
    # 11-08 운영: "식품영업 폐업신고 했어요"를 글로 보내자 Review가 막힌 일 목록을 거절해 판단이 멈췄다
    outcome, calls, rows, answer = _action_done_outcome(
        action_code, _SCOPE_CONFIRMED, insured=insured, progress=("IN_PROGRESS", True, False),
        prefer="CONFIRM_PROCEDURE_COMPLETION")

    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    assert calls == ["reborn_supervisor_draft"]
    # 제출까지만 남기고, 그 절차는 같은 판단에서 기관 처리 결과 확인으로 넘어간다. 완료로 정하지 않는다
    assert _change(outcome, answer) == ("IN_PROGRESS", True, True)
    assert rows[f"procedure:{answer.procedure_step_id}"] == ["CONFIRM_PROCEDURE_COMPLETION"]
    assert outcome.review_subject.supervisor_draft.decision.next_action.action_code == "CONFIRM_PROCEDURE_COMPLETION"


@pytest.mark.parametrize("action_code,step_code,prior_facts,progress", [
    # 처리 결과 확인: 제출한 신고의 기관 처리가 끝났다
    ("CONFIRM_PROCEDURE_COMPLETION", "FILE_FOOD_SERVICE_CLOSURE", _SCOPE_CONFIRMED, ("IN_PROGRESS", True, True)),
    ("CONFIRM_PROCEDURE_COMPLETION", "FILE_TAX_BUSINESS_CLOSURE", _SCOPE_CONFIRMED, ("IN_PROGRESS", True, True)),
    # 직접 하는 일: 점포 반환·직원 정산을 끝냈다
    ("RETURN_PREMISES", None, _RESTORATION_DONE, ("IN_PROGRESS", True, False)),
    ("SETTLE_EMPLOYEE_PAYMENTS", None, _SCOPE_CONFIRMED, ("IN_PROGRESS", True, False)),
])
def test_completion_button_records_completion_without_asking_again(action_code, step_code, prior_facts, progress):
    # 글로 쓴 완료 보고는 "완료로 기록해도 될까요?"를 다시 묻는다. 같은 절차의 완료 버튼은 그 자체가 확인이다
    outcome, calls, rows, answer = _action_done_outcome(
        action_code, prior_facts, step_code=step_code, progress=progress, prefer="__none__")

    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    assert calls == ["reborn_supervisor_draft"]
    status, prepared, submitted = _change(outcome, answer)
    assert (status, prepared) == ("COMPLETED", True)
    # 끝난 절차는 다음 할 일 후보에서 빠지고, 다시 완료를 묻지 않는다
    assert f"procedure:{answer.procedure_step_id}" not in rows
    assert not outcome.review_subject.supervisor_draft.decision.questions_for_user


def test_action_done_for_another_procedure_fails_without_calling_a_model():
    # 서버가 할 일과 절차를 함께 정한다. 둘이 어긋난 답은 저장하지 않고 안전하게 멈춘다
    outcome, calls, _, _ = _action_done_outcome(
        "FILE_FOOD_SERVICE_CLOSURE", _SCOPE_CONFIRMED, step_code="FILE_TAX_BUSINESS_CLOSURE",
        progress=("IN_PROGRESS", True, False))

    assert outcome.outcome_type == "SAFE_FAILURE" and calls == []


def test_action_done_codes_are_every_procedure_action():
    from typing import get_args

    from app.agent.schemas import ActionDoneCode

    # 할 일이 새로 생기면 버튼 대상에도 넣을지 여기서 드러난다. 범위 확인(자체 선택지)·지원사업(MVP 밖)만 뺀다
    procedure_actions = set(ACTION_DEFINITIONS) - {"CONFIRM_RESTORATION_SCOPE", "CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS"}
    assert set(get_args(ActionDoneCode)) == procedure_actions


def test_action_done_requires_its_own_text_only():
    from pydantic import ValidationError

    from app.agent.schemas import ActionDoneAnswer

    answer = ActionDoneAnswer(action_code="FILE_TAX_BUSINESS_CLOSURE", procedure_step_id=1)
    request = ev.build_graph_input(ev.CASES["benchmark_case1"], result_text="넵 다 했어요")
    payload = request.model_dump(mode="json")
    payload["trigger"]["action_done"] = answer.model_dump()
    # 버튼 답에 다른 글을 붙여 모델 해석 없이 들어오게 할 수 없다
    with pytest.raises(ValidationError):
        AgentGraphInput.model_validate(payload)
    payload["trigger"]["input"]["redacted_text"] = answer.to_input_text()
    payload["trigger"]["restoration_answer"] = {"restoration_scope": "FULL", "demolition_required": "REQUIRED"}
    with pytest.raises(ValidationError):
        AgentGraphInput.model_validate(payload)
    del payload["trigger"]["restoration_answer"]
    assert AgentGraphInput.model_validate(payload).trigger.action_done == answer


@pytest.mark.parametrize("code,confirmation", [
    ("RETURN_PREMISES", "CONFIRM_PREMISES_RETURN_REQUIREMENTS"),
    ("SETTLE_EMPLOYEE_PAYMENTS", "CONFIRM_EMPLOYEE_SETTLEMENT_REQUIREMENTS"),
    ("REPORT_EMPLOYEE_INSURANCE_LOSS", "CONFIRM_EMPLOYEE_INSURANCE_LOSS_REQUIREMENTS"),
    ("REPORT_WORKPLACE_INSURANCE_CLOSURE", "CONFIRM_WORKPLACE_INSURANCE_CLOSURE_REQUIREMENTS"),
])
@pytest.mark.parametrize("mode", ["same_judgment", "stored", "held", "completion_report"])
def test_preparation_report_updates_readiness_without_changing_snapshot_status(code, confirmation, mode):
    from uuid import UUID

    from test_action_codes import StubModel, source
    from test_blocker_candidates import ChoiceModel
    from test_info_replanning import Responses

    from app.agent.blocker_candidates import build_blocker_candidates
    from app.agent.procedure_tool.stored_tool import StoredProcedureLookupTool
    from app.agent.review_tool import ReviewTool
    from app.agent.schemas import (
        CASE_FIELD_SPECS,
        CaseFact,
        InfoAnalysisInput,
        ProcedureLookupInput,
        ProcedureProgress,
        ReviewSubject,
        SupervisorAgentInput,
    )
    from app.agent.supervisor.agent import SupervisorAgent

    async def run():
        store = ev.SnapshotStore(REVIEWED)
        registry = ev.build_registry(store, cafe_registry=True)
        text = "해당 절차의 준비사항을 확인했습니다."
        if code == "REPORT_WORKPLACE_INSURANCE_CLOSURE":
            text = (
                "담당 기관에 사업장 보험 탈퇴·소멸 신고 대상과 필요한 서류, 제출 방법을 모두 확인했고 "
                "준비할 자료도 갖췄어요. 아직 탈퇴·소멸 신고서는 제출하지 않았어요."
            )
        if mode == "completion_report":
            text = "해당 절차의 처리를 모두 마쳤습니다."
        payload = ev.CASES["benchmark_case1"] | {"had_employees": True, "pension_enrolled": True,
            "health_insurance_enrolled": True, "employment_insurance_enrolled": True,
            "industrial_accident_insurance_enrolled": True}
        request = ev.attach_fixture_sources(ev.build_graph_input(payload, result_text=text,
            prior_facts={"restoration_scope": "FULL", "demolition_required": "NOT_REQUIRED",
                         "restoration_status": "COMPLETED"}), store)
        snapshot = request.case_snapshot
        ref = snapshot.evidence_records[0].evidence_id
        for key in ["had_employees", "pension_enrolled", "health_insurance_enrolled",
                    "employment_insurance_enrolled", "industrial_accident_insurance_enrolled"]:
            snapshot.facts.append(CaseFact(field_path=key, value_type="BOOLEAN", value=True,
                status="CONFIRMED", evidence_refs=[ref], updated_at=ev.FIXED_TIME))
        step = next(item.procedure_step for item in registry if item.procedure_step.step_code == code)
        snapshot.procedure_progress.append(ProcedureProgress(procedure_step=step, status="IN_PROGRESS",
            requirements_confirmed=mode == "stored", submitted=False, evidence_refs=[ref], updated_at=ev.FIXED_TIME))
        before = snapshot.model_dump_json()
        lookup = await StoredProcedureLookupTool(store).lookup(ProcedureLookupInput(
            lookup_goal="BUSINESS_CLOSURE", procedure_step_codes=[item.procedure_step.step_code for item in registry],
            evidence_records=snapshot.evidence_records, search_queries=["폐업 절차"], as_of=ev.FIXED_TIME.date(),
            locale="ko-KR", source_policy="OFFICIAL_ONLY", max_results_per_query=10,
            based_on_snapshot_id=snapshot.snapshot_id, review_feedback=[]))
        raw = {"completion_status": "COMPLETE", "facts": [], "missing_fields": [], "uncertainties": [],
            "procedure_observations": [{"step_code": code, "observed_status": "COMPLETED" if mode == "completion_report" else "IN_PROGRESS",
                "source_text": text, "requirements_confirmed": True, "submitted": False,
                "requires_confirmation": mode == "held", "reason_summary": "사용자의 절차 진행 보고"}]}
        info = await info_module.InfoAnalysisAgent(Responses(raw), clock=lambda: ev.FIXED_TIME, max_local_attempts=1).analyze(
            InfoAnalysisInput(input=request.trigger.input, case_snapshot=snapshot, allowed_field_paths=list(CASE_FIELD_SPECS),
                known_procedure_steps=registry, source_call_id=UUID(int=40), procedure_lookup_call_id=UUID(int=5),
                procedure_lookup_result=lookup, review_feedback=[]))
        finding = next(item for item in info.procedure_findings if item.procedure_step == step)
        assert finding.current_status == "IN_PROGRESS"
        assert finding.requires_confirmation is (mode in {"held", "completion_report"})
        supervisor_input = SupervisorAgentInput(trigger=request.trigger, case_snapshot=snapshot, known_procedure_steps=registry,
            source_results=[source(lookup, "PROCEDURE_TOOL", 5), source(info, "INFO_AGENT", 40)])
        supervisor = SupervisorAgent(ChoiceModel(), clock=lambda: ev.FIXED_TIME, max_local_attempts=1)
        changes = supervisor._build_mutations(supervisor_input, supervisor_input.source_results, fact_overlays=[])
        rows = build_blocker_candidates(snapshot, registry, supervisor_input.source_results, changes,
                                        supervisor._evidence(supervisor_input.source_results, supervisor_input))
        choice = 0 if mode == "completion_report" else next(i for i, row in enumerate(rows)
            if row["candidate_id"] == f"procedure:{step.procedure_step_id}")
        draft = await SupervisorAgent(ChoiceModel(choice=choice, information=mode == "completion_report"),
                                      clock=lambda: ev.FIXED_TIME, max_local_attempts=1).draft(supervisor_input)
        if mode == "completion_report":
            assert draft.decision.next_action is None
        else:
            assert draft.decision.next_action.action_code == (code if mode in {"same_judgment", "stored"} else confirmation)
        assert len(draft.mutations.procedure_progress_changes) == int(mode == "same_judgment")
        for change in draft.mutations.procedure_progress_changes:
            assert (change.proposed_status, change.proposed_requirements_confirmed, change.proposed_submitted) == ("IN_PROGRESS", True, False)
        subject = ReviewSubject.create(schema_version="agent-io/2.0", review_subject_id=UUID(int=500), review_attempt=1,
            run_id=supervisor_input.source_results[0].meta.run_id, case_id=1, trigger=request.trigger,
            snapshot=snapshot, known_procedure_steps=registry, source_results=supervisor_input.source_results, supervisor_draft=draft)
        assert (await ReviewTool(StubModel()).review(subject)).verdict == "PASS"
        assert snapshot.model_dump_json() == before

    asyncio.run(run())
