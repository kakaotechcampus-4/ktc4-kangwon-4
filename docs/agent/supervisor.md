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

## ACTION의 next_action 규칙

- target은 정확히 하나: `target_kind=PROCEDURE`(Info finding 기반) 또는 `target_kind=SUPPORT_PROGRAM`(Support check 기반). 섞지 않는다
- `questions_for_user`는 비워야 한다 — 확인 질문은 `next_action.questions_to_ask`에 넣는다
- `procedure_plan_constraints`(→ [procedure-tool.md](./procedure-tool.md))를 통과 못 하면 `SupervisorGuardrailError`로 초안 자체를 거부한다

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
