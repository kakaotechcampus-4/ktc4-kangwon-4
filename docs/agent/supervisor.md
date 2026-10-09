# Supervisor Agent

최종 판단 지점. 하위 결과(Info·Procedure)를 종합해 **Blocker 1개·Next Action 1개** 결정.
Case 직접 접근 없이 검증된 `SupervisorAgentInput` 사용.

## 입력 → 출력

`SupervisorAgentInput` → `SupervisorDraft` (`decision` + `mutations` + `grounded_claims`)

## decision_type (2가지뿐)

| 값 | 조건 | 모양 |
|---|---|---|
| `ACTION` | 근거 있는 행동 가능 | `blocker` 1개, `next_action` 1개, `questions_for_user=[]` |
| `NEEDS_MORE_INFO` | 근거 있는 행동 불가 | `blocker`만 있음, `next_action=None`, `questions_for_user` 1개 이상, `requires_human=True` |

`CASE_COMPLETE`는 없다 — schema_table.md의 `DECISION_RECORD.decision_type`에도 없고,
"전체 폐업 완료 자동 판정"은 [Agent MVP 제외 범위](./README.md)다.

## Blocker

사용자에게 보이는 내용은 `description`이다(`schema_table.md`의 `BLOCKER.description`에 대응).
Agent 출력은 판단 근거를 연결하는 `evidence_refs`도 함께 반환한다.
`title`·`blocker_code`는 없다 — 물리 컬럼에 없어서 뺐다.
Blocker 해소(`RESOLVED`) 판정은 Supervisor가 하지 않는다. BE가 다음 판단에서 처리한다.

현재 MVP의 정상 판단에는 Blocker가 항상 정확히 1개 있다. 원상복구 미확인과
공식 절차의 진행 상태·준비사항 확인을 근거 있는 후보로 반환한다. 확인된 사실을 다시
미확인으로 바꾸거나, 후보에 없는 차단 조건을 만들지 않는다. 전체 Case 완료 판정은
범위에서 제외하며 모든 판단·행동의 근거와 필수 Review를 유지한다.

[`blocker_candidates.py`](../../backend/app/agent/blocker_candidates.py)가 확인된 Case 값과
현재 절차 분석에서 기존 근거·적용 조건·선후 관계·완료 여부 검사를 통과한 전체 후보를 만든다.
후보를 임의로 3개에서 자르지 않는다. 각 후보에 허용된 행동 코드·대상을 연결하고 아래 순서로 정렬한다.
Supervisor 모델에는 첫 후보·첫 행동만 선택값으로 제공하며, 다른 유효한 선택이 오더라도
코드가 첫 후보·첫 행동으로 정규화한다. 목록에 없는 코드·대상은 거절한다.
상태 설명·확인 질문도 후보에서 채우며 Review가 같은 우선순위와 문장을 재검증한다.

같은 검증된 Case·자료·Info 분석 결과에서 정상 출력되는 Blocker·행동은 동일하다.
Info 재분석 결과나 Review 통과 여부, 실행 ID·시각까지 같다는 보장은 아니다.
후보가 없으면 Info의 판단 차단 항목 중 실제 미확인 조건 하나를 고정된 필드 순서로 묻는다.
선택 날짜·확정된 사실을 다시 묻거나 근거 없이 안내문 제출을 요구하지 않는다.
지원사업 행동·지원 안내 요청·지원 변경 후보는 MVP 실행에서 생성하지 않는다.
공식 문서는 있지만 절차 대응이 0개이고 행동 후보도 없으면 구성 오류로 종료하며,
사용자 추가 입력으로 해결할 수 있다고 안내하지 않는다.

절차 finding이 `RELEVANT`가 아니면 후보에서 제외한다. 단 확인 행동은 공식 안내가 있고
`requires_confirmation=true`인 `POSSIBLY_RELEVANT`도 남긴다 — 적용 여부의 확인 자체가
다음 행동이기 때문이다. 이때도 그 finding이 참조하는 근거와
상위 근거 전체가 `CURRENT`여야 하며, `UNDETERMINED`는 예외 대상이 아니다.

## ACTION의 next_action 규칙

- MVP target은 `target_kind=PROCEDURE`(Info finding 기반) 하나다. 지원 target DTO는 기존 계약에 남지만 현재 실행에서는 선택하지 않는다
- `questions_for_user`는 비워야 한다 — 확인 질문은 `next_action.questions_to_ask`에 넣는다
- `procedure_plan_constraints`(→ [procedure-tool.md](./procedure-tool.md))를 통과 못 하면 `SupervisorGuardrailError`로 초안 자체를 거부한다
- `action_code`는 [행동 목록](../../backend/app/agent/action_catalog.py)에 정의한 값만 선택한다. 현재 Info 결과에서 가능한 코드와 target 조합을 Supervisor에 제공하고, 서버와 Review가 다시 검증한다
- 코드는 행동 종류이며 대상 ID나 실행 이력 ID가 아니다. 같은 절차에서도 요건 확인과 신고 진행은 다른 코드다. 제목·이유·질문이 선택한 코드의 의미와 맞는지도 Review가 검사한다
- 원상복구 범위 확인, 세무·식품영업 폐업 및 사업장 보험 탈퇴의 요건 확인/신고, 지원사업 조건 확인을 정의한다. 지원사업 코드는 MVP 실행에서 제외한다. 새 절차는 행동 목록에 명시적으로 등록하며 임의 코드로 대체하지 않는다
- 현재 `ProcedureFinding.requires_confirmation`은 `Literal[True]`다. 같은 절차의 행동 중 담당자 확인을 먼저 선택한다

## 업무 순서 (코드와 Review에서 적용)

1. 원상복구가 완료되지 않은 임차 점포에서 범위·철거 필요 여부가 미확인 → 임대인 확인
2. 현재 Case에 관련되고 적용 조건을 충족하는 다른 미완료 절차의 `SEQUENTIAL` 선행 절차
3. 진행 중인 절차(`IN_PROGRESS`)
4. 나머지 실행 가능한 폐업 절차

동률은 DB ID나 조회 순서가 아닌 **논리 절차 코드의 알파벳 순**으로 정한다.
실행할 때마다 같은 순서가 나오게 하려는 동률 처리이며, 법적 선후 관계나
급한 정도를 반영한 순서가 아니다. 지금 실제 순서는 식품영업(`FILE_FOOD…`) →
세무서(`FILE_TAX…`) → 4대보험(`REPORT_WORKPLACE…`)이다. 어떤 순서가 맞는지는
PM이 정할 몫이며 [#55](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues/55)에서 다룬다.

**2·3번은 아직 실제 서비스에서 동작하지 않는다.** 선후 관계(`SEQUENTIAL`) 행을
넣는 코드가 저장소에 없고, Case 생성 때 넣는 임시 절차에는 선후 관계도 적용 조건도
없다. 테스트는 그 관계를 직접 끼워 넣어 규칙 자체를 검사한다. 그래서 현재 실제
판단에서는 1번을 뺀 나머지가 사실상 알파벳 순이다.
임대인 확인도 근거·절차 제약 검사를 통과해야 하며, 이미 확인된 항목은 다시 묻지 않는다.
근거 있는 행동이 없고 실제 확인할 조건이 있을 때만 `NEEDS_MORE_INFO`를 반환한다.

## 모델에 닿지 못했을 때

후보 순서는 코드가 정하고 모델에는 1순위 하나만 보기로 준다. 그래서 모델의 답이
최종 결과를 바꾸지 않는다. 공급자 장애(`LLMRequestError`)로 호출이 실패하면 1순위
후보로 ACTION 초안을 그대로 만든다. 답이 이미 손에 있는데 판단 전체를 실패로 끝내면
사장님이 빈손이 되기 때문이다. 호출 한 번이 최대 180초라 다시 부르지 않고 바로 넘어간다.
독립 Review는 그대로 거친다.

모델이 **답은 했는데 틀린** 경우는 여기에 해당하지 않는다. 없는 후보를 지어내거나
절차 제약을 어기면 덮어서 넘기지 않고 실패로 남긴다.

## 미검수 자료의 처리

절차 문서가 미검수(`freshness=UNKNOWN`)면 Info가 `relevance=UNDETERMINED`로 낼 수밖에 없고,
Supervisor는 그 finding으로 ACTION을 만들 수 없다. 근거 있는 다른 행동이 없을 때
실제 확인할 조건이 있어야 `NEEDS_MORE_INFO`를 반환한다. 이를 충족하지 못하면
미검수 초안 없이 실패한다. 검수 완료된 현재 자료의 동작과 구분해야 한다.

코드: [`supervisor/agent.py`](../../backend/app/agent/supervisor/agent.py),
프롬프트: [`prompts.py`](../../backend/app/agent/prompts.py)의 `supervisor_messages`,
스키마: [`schemas.py`](../../backend/app/agent/schemas.py)의 `SupervisorDraft`·`ActionDecisionDraft`·`NeedsMoreInfoDecisionDraft`·`Blocker`.
