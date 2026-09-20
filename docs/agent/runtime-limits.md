# Agent 실행 한도와 실측 기록

> 소유: AI · 기준일: 2026-09-20
>
> 이 문서의 책임: 한 번의 실행이 **얼마나 쓰고 얼마나 걸리는지**의 단일 출처.
> 다른 문서는 숫자를 반복하지 않고 여기를 가리킵니다.

## 1. 지금 값

| 한도 | 값 | 환경변수 | 넘으면 |
|---|---|---|---|
| 실행당 LLM 호출 총 횟수 | **40** | `AGENT_MAX_LLM_CALLS_PER_RUN` | `SAFE_FAILURE` / `LOOP_LIMIT_REACHED` |
| 실행 전체 시간 | **60초** | `AGENT_RUN_DEADLINE_SECONDS` | `SAFE_FAILURE` / `RUN_DEADLINE_EXCEEDED` |
| 호출 하나의 시간 | 45초 | `AGENT_LLM_TIMEOUT_SECONDS` | 재시도 후 실패 |

둘은 서로 다른 것을 막습니다. **호출 수는 비용을, 시간은 사용자가 기다리는 길이를** 막습니다.
하나가 다른 하나를 대신하지 못해서 둘 다 둡니다.

호출 하나의 시간은 전체 상한보다 **작아야** 합니다. 같거나 크면 호출 한 번이 전체 예산을
통째로 써버립니다. 실제로 이 저장소의 `.env`가 한동안 60초/60초였습니다.

### 어떻게 세는가

- 호출 수는 **실제 HTTP 호출**을 셉니다. 재시도도 1회로 칩니다 — 재시도에도 돈이 나가니까요.
- 실행이 시작될 때 그 실행 몫의 카운터가 새로 생깁니다. 동시에 두 요청이 들어와도 섞이지 않습니다
  (`run_scope.py`, `llm.py`의 `call_budget_scope`).
- 시간은 monotonic 기준입니다. 실행 도중 시계가 조정돼도 상한이 늘거나 줄지 않습니다.
- 남은 시간이 없으면 **예산을 쓰기 전에** 멈춥니다. 끝낼 수 없는 호출에 돈을 쓰지 않습니다.

## 2. 실측 (2026-09-19 ~ 09-20)

조건: `openai/gpt-4.1-mini` 공용 + Supervisor 전용 endpoint 분리, 합성 Case fixture,
절차는 검수 스냅샷 조회. 총 8회.

| 회차 | 상한 | 결과 | 소요 | LLM 호출 |
|---|---|---|---|---|
| 1 | 300초 | `REVIEWED_PLAN` | 64.5초 | 9회 |
| 2 | 300초 | `SAFE_FAILURE` (`STRUCTURED_OUTPUT_FAILED`, 정보분석) | 15.4초 | 3회 |
| 3 | 300초 | `REVIEWED_PLAN` | 52.3초 | 7회 |
| 4 | 60초 | `SAFE_FAILURE` (`RUN_DEADLINE_EXCEEDED`, Supervisor 단계) | 60초 | — |
| 5 | 60초 | `SAFE_FAILURE` (`STRUCTURED_OUTPUT_FAILED`, 정보분석) | — | — |
| 6 | 60초 | `REVIEWED_PLAN` | 45초 | — |
| 7 | 60초 | `REVIEWED_PLAN` | 29초 | — |
| 8 | 60초 | `SAFE_FAILURE` (`STRUCTURED_OUTPUT_FAILED`, 정보분석) | 25초 | — |

구성요소별(1회차):

| 구성요소 | 소요 |
|---|---|
| 절차조회 | **1밀리초** |
| 정보분석 | 31.5초 |
| 지원금 | 2.8초 |
| Supervisor | 24.1초 |
| Review | 6.1초 |

### 2026-09-20 근거 참조 수정 이후

정보분석과 Supervisor가 근거를 **짧은 손잡이**로 고르게 바꾼 뒤 다시 measured.

| 구간 | 결과 |
|---|---|
| 정보분석 단독 10회 | **10회 모두 성공.** UUID 필사 오류 0건 (이전에는 이게 최다 실패 원인) |
| 전체 실행 7회 | 성공 4 / `REVIEW_RETRY_EXHAUSTED` 3 |
| 전체 실행 소요 | 42~75초, LLM 호출 7~15회 |

### 여기서 읽을 것

**호출 예산 40은 여전히 넉넉합니다.** 최악의 경우(Review 재작업 3회)에도 15회입니다.

**병목이 옮겨갔습니다.** 정보분석은 이제 거의 실패하지 않습니다. 대신 Review가
Supervisor 초안을 반려해 재작업을 돌리고, 그 재작업이 시간을 크게 늘립니다.
재작업이 도는 실행은 70~75초로 **60초 상한을 넘깁니다.** 상한은 팀 결정대로
60초를 유지하므로, 이런 실행은 `RUN_DEADLINE_EXCEEDED`로 안전 종료됩니다.

**Review 반려는 해결했습니다.** `NEEDS_MORE_INFO` 결정의 Blocker를 근거 요구
대상에서 제외한 뒤 5회 실행에서 `REVIEW_RETRY_EXHAUSTED`가 0건입니다.

**남은 실패는 정보분석이 근거 ID를 지어내는 것입니다.** UUID 필사 오류는 사라졌지만
모델이 `fixture:case:profile`, `INPUT_JSON` 같은 그럴듯한 문자열을 근거로 씁니다.
프롬프트에 보이는 식별자는 무엇이든 인용 후보가 됩니다 —
[`open-decisions.md`](./open-decisions.md) OD-11.

**절차조회는 계속 1밀리초 이하입니다.**

## 3. 다시 재는 방법

실행마다 trace에 `RUN` 이벤트가 1건 남습니다. 여기에 그 실행이 **실제로 쓴 호출 수**와
**총 소요 시간**, 종료 사유가 들어 있습니다.

구성요소별 이벤트로는 이걸 알 수 없습니다. 구성요소 한 번이 여러 번의 HTTP 호출을
덮을 수 있어서, 이벤트 수가 곧 호출 수가 아니기 때문입니다.

Langfuse credential이 설정돼 있으면 거기로 갑니다. 없으면 아무 데도 보내지 않습니다.
로컬에서 그냥 재보려면 `MemoryTraceSink`를 넣어 돌리면 됩니다.

## 4. 값을 바꿀 때

- **근거 없이 바꾸지 않습니다.** 위 표에 회차를 추가하고 나서 바꿉니다.
- 내릴 때는 정상 요청이 막히지 않는지부터 봅니다. 재시도도 예산을 쓰기 때문에
  실패가 잦은 구간에서는 같은 요청이 예산을 더 씁니다.
- 바꾼 값은 `.env.example`과 이 문서 §1에 함께 반영합니다.

## 5. 근거

- 한도 구현: `backend/app/agent/run_scope.py`, `backend/app/agent/llm.py`, `backend/app/agent/runtime.py`
- 노드별 확인과 실행 기록: `backend/app/agent/graph.py`
- 회귀 테스트: `backend/tests/agent/test_runtime.py`, `backend/tests/agent/test_graph.py`
