# Supervisor Agent

최종 판단 지점. 하위 결과(Info·Procedure·Support)를 종합해 **Blocker 1개·Next Action 1개**를
결정한다. Case를 직접 읽거나 쓰지 않고, 검증된 `SupervisorAgentInput`만 받는다.

## 입력 → 출력

`SupervisorAgentInput` → `SupervisorDraft` (`decision` + `mutations` + `grounded_claims`)

## decision_type (2가지뿐)

| 값 | 조건 | 모양 |
|---|---|---|
| `ACTION` | 근거 있는 행동 가능 | `blocker` + `next_action` 둘 다 있음, `questions_for_user=[]` |
| `NEEDS_MORE_INFO` | 근거 있는 행동 불가 | `blocker`만 있음, `next_action=None`, `questions_for_user` 1개 이상, `requires_human=True` |

`CASE_COMPLETE`는 없다 — schema_table.md의 `DECISION_RECORD.decision_type`에도 없고,
"전체 폐업 완료 자동 판정"은 [Agent MVP 제외 범위](./README.md)다.

## Blocker

사용자에게 보이는 내용은 `description`이다(`schema_table.md`의 `BLOCKER.description`에 대응).
Agent 출력은 판단 근거를 연결하는 `evidence_refs`도 함께 반환한다.
`title`·`blocker_code`는 없다 — 물리 컬럼에 없어서 뺐다.
Blocker 해소(`RESOLVED`) 판정은 Supervisor가 하지 않는다. BE가 다음 판단에서 처리한다.

[`blocker_candidates.py`](../../backend/app/agent/blocker_candidates.py)가 확인된 Case 값과
현재 절차·지원 분석에서 최대 3개 후보를 만든다. 기존 업무 순서와 절차 제약을 적용하고,
각 후보에 허용된 행동 코드·대상을 연결한다. Supervisor는 후보와 행동을 선택하며,
선택한 후보의 상태 설명·확인 질문을 코드에서 채운다. 따라서 미확인을 실제 미결정으로
바꾸거나 이미 확인한 항목을 다시 묻는 표현을 모델이 추가하지 않는다.
Review도 같은 후보·상태 문장을 재검증한다. 후보가 없으면 추가 확인 질문을 반환한다.

## ACTION의 next_action 규칙

- target은 정확히 하나: `target_kind=PROCEDURE`(Info finding 기반) 또는 `target_kind=SUPPORT_PROGRAM`(Support check 기반). 섞지 않는다
- `questions_for_user`는 비워야 한다 — 확인 질문은 `next_action.questions_to_ask`에 넣는다
- `procedure_plan_constraints`(→ [procedure-tool.md](./procedure-tool.md))를 통과 못 하면 `SupervisorGuardrailError`로 초안 자체를 거부한다
- `action_code`는 [행동 목록](../../backend/app/agent/action_catalog.py)에 정의한 값만 선택한다. 현재 Info·Support 결과에서 가능한 코드와 target 조합을 Supervisor에 제공하고, 서버와 Review가 다시 검증한다
- 코드는 행동 종류이며 대상 ID나 실행 이력 ID가 아니다. 같은 절차에서도 요건 확인과 신고 진행은 다른 코드다. 제목·이유·질문이 선택한 코드의 의미와 맞는지도 Review가 검사한다
- 원상복구 범위 확인, 세무·식품영업 폐업 및 사업장 보험 탈퇴의 요건 확인/신고, 지원사업 조건 확인을 정의한다. 새 절차는 행동 목록에 명시적으로 등록하며 임의 코드로 대체하지 않는다
- 코드가 고정돼도 판단 내용의 일관성이 보장되는 것은 아니다. 반복 평가에서는 코드·target과 실제 확인 항목을 함께 비교한다

## 업무 순서 (prompts.py의 지시)

1. `demolition_required=REQUIRED` 확정 + `restoration_status≠COMPLETED` → 철거 지원조건 확인 우선
2. 그 외 `restoration_scope`·철거 필요 여부가 미확정 → 임대인 확인을 Info finding 기반으로 우선
3. 근거 있는 행동이 없으면 `NEEDS_MORE_INFO`

이미 확정된 사실은 다시 묻지 않고, `restoration_status=COMPLETED` 뒤 철거 전 행동을 반복하지 않는다.

## 미검수 자료의 처리

절차 문서가 미검수(`freshness=UNKNOWN`)면 Info가 `relevance=UNDETERMINED`로 낼 수밖에 없고,
Supervisor는 그 finding으로 ACTION을 만들 수 없다. 근거 있는 다른 행동이 없으면
`NEEDS_MORE_INFO`를 반환한다. 검수 완료된 현재 자료의 동작과 구분해야 한다.

코드: [`supervisor/agent.py`](../../backend/app/agent/supervisor/agent.py),
프롬프트: [`prompts.py`](../../backend/app/agent/prompts.py)의 `supervisor_messages`,
스키마: [`schemas.py`](../../backend/app/agent/schemas.py)의 `SupervisorDraft`·`ActionDecisionDraft`·`NeedsMoreInfoDecisionDraft`·`Blocker`.
