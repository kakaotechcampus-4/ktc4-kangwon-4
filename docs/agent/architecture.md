# RE:BORN Agent 아키텍처

Agent는 확인된 Case와 근거로 다음 행동을 판단한다. 실행 경로는 LangGraph가 연결하고,
최종 Blocker·Next Action은 Supervisor 한 곳에서 결정한다.
범위와 코드 색인은 [Agent 범위](./README.md)를 따른다.
동작 규칙의 기준은 문서가 아니라 `backend/app/agent/`의 검증자와 prompt다.

## 구성요소

| 구성요소 | 책임 |
|---|---|
| Supervisor Agent | 절차·사실·지원조건을 종합해 Blocker 1개·Next Action 1개 또는 확인 질문과 변경 후보를 만든다 |
| 정보분석 Agent | 비식별 입력에서 근거가 있는 사실·진행·충돌 후보를 추출하고 Case에 맞는 절차를 분석한다 |
| 지원금 Agent | 검수된 지원조건을 Case와 비교하고 관련성·미확인 조건·공식 근거를 반환한다 |
| 절차조회 Tool | 주입된 절차 자료에서 원문·출처·검수 상태를 조회한다. 우선순위나 Next Action을 결정하지 않는다 |
| Review Tool | 초안·변경 후보·근거를 독립 검수해 `PASS` 또는 사유와 재작업 대상이 있는 `REVISE`를 반환한다 |

`AgentGraph`는 실행기이며 별도 Agent가 아니다. 하위 Agent·Tool은 서로 직접 호출하지 않는다.
Review는 검색·초안 수정·저장을 수행하지 않는다.

## MVP 실행 경로

```text
CASE_CREATED | RESULT_SUBMITTED
  → Procedure → Info
      ├─ 확정 사실과 충돌 → CONFLICT
      └─ 충돌 없음 → Support → Supervisor → Review

CONFLICT_CONFIRMED
  → 선택 후보·현재값 검증 → 확인된 fact_overlays
  → Procedure → Info(절차 분석: input=None, fact_overlays)
  → Support → Supervisor → Review

Review
  ├─ PASS → 검수 대상과 일치하는 ReviewProof → REVIEWED_PLAN
  ├─ REVISE → 해당 단계부터 재작업 → Review
  └─ 실패·상한 소진 → SAFE_FAILURE
```

MVP는 위 경로를 사용하며 일반화된 자율 Tool 선택 계획을 추가하지 않는다.
충돌 확인 뒤에도 변경된 사실을 바탕으로 절차·지원조건을 다시 확인한다.
새 사용자 입력이 없는 실행을 위해 발화를 만들지 않는다. Info는 전달된 확인 후보로 절차만 분석한다.
확인된 후보는 Procedure·Info부터 다시 실행하는 재작업에서도 유지하며 LLM이 교체하지 못한다.

## 실행 자료와 수명

BE가 실제 절차 ID 목록·검수 지원 catalog·절차 store를 `build_runtime`에 주입한다.
공용 runtime을 여러 요청에 사용하되 호출 예산·사용량·deadline은 실행마다 분리한다.
환경변수는 [`.env.example`](../../.env.example), 한도·자원 정리는
[`runtime.py`](../../backend/app/agent/runtime.py)를 따른다.

Case snapshot은 한 실행 동안 바꾸지 않는다. 추출·사용자 확인으로 얻은 변경 후보는
`fact_overlays`로 별도 전달하고, 저장 전까지 snapshot의 확정 사실로 덮어쓰지 않는다.
절차·정책 자료는 요청 중 인터넷에서 수집하지 않으며 검수 상태와 최신성을 보존한다.
자료가 없으면 없는 상태를 반환하고 다른 문서·지원사업·조건으로 채우지 않는다.

## 검수와 반환

| 결과 | 규칙 |
|---|---|
| `REVIEWED_PLAN` | 같은 Case·선행 결과·초안을 검수한 PASS와 증명을 반환한다. DB 저장 완료를 뜻하지 않는다 |
| `CONFLICT` | 실행을 멈추고 사용자 선택을 요청한다. 기존 사실을 자동 변경하지 않는다 |
| `SAFE_FAILURE` | 오류·검증 실패·예산 소진을 알리고 검수 전 초안을 반환하지 않는다 |

`NEEDS_MORE_INFO`는 Review를 거치는 정상 판단이다. Blocker와 확인 질문을 반환하며
없는 Next Action이나 확정값을 만들어 넣지 않는다.

초안·선행 결과가 달라지면 이전 Review PASS를 재사용하지 않는다.
허용된 단계부터 재작업하되 `runtime.py`·`llm.py`의 호출·시간·재작업 상한을 넘기지 않는다.

## 상태와 저장 경계

- 사용자 확인은 사실 선택이며 이후 계획의 정확성을 보증하지 않는다. 선택 뒤에도 필수 Review를 적용한다.
- 오래된 충돌 확인은 `STALE_CONFLICT_CONFIRMATION`으로 거부한다.
- ID·타입·근거 참조·digest·허용 상태 전이는 코드로 검증한다.
- 미확인·오래된 근거로 날짜·금액·법률·세무·지원 자격을 단정하지 않는다.
- 공식 절차 문서만으로 사용자의 실제 절차가 완료됐다고 처리하지 않는다.
- Agent는 SQL·ORM으로 Case를 직접 읽거나 쓰지 않는다. BE가 권한·현재값을 확인하고 저장·재조회한다.
- 사용자 원문·근거 본문·비밀값을 trace에 기록하지 않는다.

호출자가 맡는 저장과 충돌 확인 경계는 [실행 경계](./README.md#실행-경계)를 따른다.
절차 실행 가능 판정은 `procedure_tool/rules.py`, 지원조건 비교는 `support_agent/agent.py`가 기준이다.
