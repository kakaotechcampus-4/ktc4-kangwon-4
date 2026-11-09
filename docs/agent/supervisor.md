# Supervisor Agent

최종 판단 지점. 하위 결과(Info·Procedure)를 종합해 전체 Blocker와 **우선 Blocker 1개·다음 행동 또는 확인 질문** 결정.
Case 직접 접근 없이 검증된 `SupervisorAgentInput` 사용.

## 입력 → 출력

`SupervisorAgentInput` → `SupervisorDraft` (`decision` + `mutations` + `grounded_claims`)

## decision_type

| 값 | 조건 | 모양 |
|---|---|---|
| `ACTION` | 근거 있는 행동 가능 | `blocker` 1개, `next_action` 1개, `questions_for_user=[]` |
| `NEEDS_MORE_INFO` | 실제 미확인 정보나 안내로 실행을 지시할 수 없는 원상복구의 새 진행 보고를 기다림 | `blocker` 1개, `next_action=None`, `questions_for_user` 1개 이상, `requires_human=True` |
| `PROCEDURES_COMPLETED` | 적용되는 등록 절차의 완료 근거와 자료·대응표를 확인한 안내 종료 | `blocker=None`, `blockers=[]`, `next_action=None`, `questions_for_user=[]`, `requires_human=False` |

`ACTION`과 `NEEDS_MORE_INFO`는 전체 `blockers`와 그중 선택한 우선 `blocker`를 반환한다.
행동·질문 후보가 없다는 이유만으로 종료하지 않는다.
[`completed_procedure_decision_fields`](../../backend/app/agent/blocker_candidates.py)의 조건을
Supervisor와 Review가 각각 검사하며, 미완료·적용 여부 미확인·자료 설정 오류는 정상 종료로 숨기지 않는다.

`CASE_COMPLETE`는 없다 — schema_table.md의 `DECISION_RECORD.decision_type`에도 없고,
"전체 폐업 완료 자동 판정"은 [Agent MVP 제외 범위](./README.md)다.

## Blocker

사용자에게 보이는 내용은 `description`이다(`schema_table.md`의 `BLOCKER.description`에 대응).
Agent 출력은 판단 근거를 연결하는 `evidence_refs`도 함께 반환한다.
`title`·`blocker_code`는 없다 — 물리 컬럼에 없어서 뺐다.
기존 Blocker 중 현재 조건에서 해소된 항목은 코드가 `resolved_blocker_candidate_ids`로 반환하고 BE가 저장한다.

`ACTION`과 `NEEDS_MORE_INFO`에는 우선 Blocker가 정확히 1개 있고 전체 Blocker는 여러 개일 수 있다. 원상복구 미확인과
공식 절차의 진행 상태·준비사항 확인을 근거 있는 후보로 반환한다. 확인된 사실을 다시
미확인으로 바꾸거나, 후보에 없는 차단 조건을 만들지 않는다. 전체 Case 완료 판정은
범위에서 제외하며 모든 판단·행동의 근거와 필수 Review를 유지한다.

[`blocker_candidates.py`](../../backend/app/agent/blocker_candidates.py)가 확인된 Case 값과
현재 절차 분석에서 기존 근거·적용 조건·선후 관계·완료 여부 검사를 통과한 전체 후보를 만든다.
후보를 임의로 3개에서 자르지 않는다. 각 후보에 허용된 행동 코드·대상을 연결하고 아래 순서로 정렬한다.
Supervisor 모델은 행동 후보와 실제 정보 질문 후보 중 우선 항목을 선택한다. 선택한 후보의
허용된 행동 코드·대상만 사용하며, 목록에 없는 코드·대상은 거절한다.
상태 설명·확인 질문은 후보에서 채우며 Review가 근거·허용 행동·문장을 재검증한다.

같은 검증된 Case·자료·Info 분석 결과에서는 후보가 같아도 모델이 고르는 유효한 항목은 달라질 수 있다.
질문 후보도 실제 미확인 조건에서만 만들며, 보류된 사실을 확정값으로 사용하지 않는다.
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
- 준비사항 확인 여부와 제출 상태를 구분한다. 저장된 `requirements_confirmed`가 없으면 확인 행동만 허용하고, 제출 보고를 기관 처리 완료로 바꾸지 않는다

## 후보 정렬과 실행 조건

1. 원상복구가 완료되지 않은 임차 점포에서 범위·철거 필요 여부가 미확인 → 임대인 확인
2. 현재 Case에 관련되고 적용 조건을 충족하는 다른 미완료 절차의 `SEQUENTIAL` 선행 절차
3. 진행 중인 절차(`IN_PROGRESS`)
4. 나머지 실행 가능한 폐업 절차

동률은 DB ID나 조회 순서가 아닌 **논리 절차 코드의 알파벳 순**으로 정한다.
이 순서는 모델에 보여줄 후보 정렬이며, 법적 우선순위나 최종 선택을 강제하지 않는다.
모델은 현재 허용된 후보 중 우선 항목을 고른다.

현재 BE는 카페 절차와 적용 조건·선후 관계를 적재해 전달한다.
절차 제약은 후보 생성과 Review에서 검사하므로, 미완료 선행 절차가 막는 실행을 선택할 수 없다.
임대인 확인도 근거·절차 제약 검사를 통과해야 하며, 이미 확인된 항목은 다시 묻지 않는다.
실제 확인할 조건이 있으면 행동 후보와 함께 질문 후보를 선택할 수 있다.

## 모델에게서 쓸 답을 못 받았을 때

통신 장애(`LLMRequestError`)나 응답 형식 불일치(`LLMResponseError`)가 나면
Supervisor는 오류를 Graph에 전달하고 판단은 `SAFE_FAILURE`로 끝난다.
모델 대신 첫 후보로 행동을 만들거나 이전 판단을 새 성공으로 저장하지 않는다.

**다시 부르지 않는다.** `llm.py`가 이미 내부에서 재시도를 끝낸 뒤 이 오류들을 던진다.
여기서 또 부르면 이미 재시도한 호출을 통째로 반복하게 되고, 한 번이 최대 180초라
판단 전체 제한시간(420초)만 쓴다.

모델이 **답은 했는데 틀린** 경우는 여기에 해당하지 않는다. 없는 후보를 지어내거나
절차 제약을 어기면 덮어서 넘기지 않고 실패로 남긴다. 이때는 `max_local_attempts`만큼
다시 묻는다 — 모델에게 무엇이 틀렸는지 알려주면 고쳐 올 수 있기 때문이다.

Info·Review도 제공자 오류는 내부 해석·검수 재작업을 반복하지 않고 Graph에 전달한다.
사용자에게 줄 복구 안내는 실패 종류와 재시도 가능 여부로 정한다.
다만 `max_local_attempts`가 "실패하면 3번 다시 부른다"로 읽히는데 실제로는
모델이 틀린 답을 했을 때만 도는 점은 구분해서 읽어야 한다.

## 미검수 자료의 처리

절차 문서가 미검수(`freshness=UNKNOWN`)면 Info가 `relevance=UNDETERMINED`로 낼 수밖에 없고,
Supervisor는 그 finding으로 ACTION을 만들 수 없다. 근거 있는 다른 행동이 없을 때
실제 확인할 조건이 있어야 `NEEDS_MORE_INFO`를 반환한다. 이를 충족하지 못하면
미검수 초안 없이 실패한다. 검수 완료된 현재 자료의 동작과 구분해야 한다.

코드: [`supervisor/agent.py`](../../backend/app/agent/supervisor/agent.py),
프롬프트: [`prompts.py`](../../backend/app/agent/prompts.py)의 `supervisor_messages`,
스키마: [`schemas.py`](../../backend/app/agent/schemas.py)의 `SupervisorDraft`·`ActionDecisionDraft`·`NeedsMoreInfoDecisionDraft`·`Blocker`.
