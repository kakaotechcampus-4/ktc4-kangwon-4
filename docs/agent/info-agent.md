# 정보조회(Info) Agent

사용자 발화와 절차조회 결과를 분석해 **사실 변경 후보·충돌·미확인 필드·절차 finding**을 만든다.
Case를 직접 수정하지 않는다 — 전부 후보(candidate)로만 반환한다.
모델과 추론 강도는 `INFO_*` 설정을 사용하며, 비우면 공용 설정을 따른다.
Supervisor·Review와 같은 실행별 호출 예산·시간 제한을 공유한다.
최신 입력의 사실은 LLM으로 추출하고, 절차 진행은 사용자가 명시적으로 선택한 `procedure_reports`에서 구성한다. 이 단계에는 공식 문서 본문을 보내지 않는다.
검증된 변경으로 계산한 현재 상태에서 필요한 절차를 한 개씩, 동시에 최대 두 개 상세 분석한다.
상세 단계는 사실·진행을 다시 추출하지 않는다. 일부 호출이 실패하면 부분 결과를 반환하지 않는다.

## 입력의 두 경로

`InfoAnalysisInput.input`은 `RedactedInput | None`이다.

| 입력 | 동작 |
|---|---|
| 발화 또는 절차 선택 있음 | 발화에서 사실·충돌 후보를 추출하고, 선택한 절차 상태로 진행 후보를 구성한 뒤 절차 분석 |
| `input=None` | 채택한 `fact_overlays`와 원 입력에서 보존한 비충돌 사실·진행을 함께 검수한다. 전부 기존값 유지도 허용하며 원문에서 다시 추출하지 않는다 |

자유문장은 사실·질문 문맥이며 절차 진행·완료를 단독으로 확정하는 근거로 쓰지 않는다.
`RedactedInput.procedure_reports`의 상태·요건 확인·제출 선택을 코드가 검증한다.
이 A안의 Agent 입력 처리는 구현됐고 FE/BE 전달·저장과 실제 모델 재검증은 남아 있다. 최신 발화는 사실 추출의 근거이며, 절차 분석의 범위를 최신 발화에 나온
주제로 제한하지 않는다. 현재 Case·진행 상태·overlay와 전체 등록 절차로 상세 분석 대상을 계산한다.
현재 확인·실행 가능한 절차와 이번 진행 변경의 근거가 필요한 절차를 포함한다.
이미 완료된 세무 절차는 적용 대상 전체가 끝나 후속 안내를 반환할 수 있을 때 추가한다.
이번 입력에 새 세무 진행 보고가 있으면 전체 종료 전에도 해당 보고를 검수한다.
현재 snapshot과 pending 변경의 상태·값을 합친 뒤 CONFIRMED인 사실만 사용한다.
`restoration_scope`가 FULL/PARTIAL/NOT_REQUIRED이고 `demolition_required`가 REQUIRED/NOT_REQUIRED로
확인됐으면 범위확인 상세를 다시 요청하지 않는다. 하나가 미확인·CLEAR이면 두 사실만으로 완료를 추정하지 않는다.
새 범위 진행 관찰은 여전히 finding으로 검수하며 기존 `restoration_status=COMPLETED` 경로를 유지한다.
선행 절차가 막혀 있어도 사용자가 선택한 다른 절차의 진행 보고를 버리지 않는다. 상세 분석 대상이
finding과 문서별 불확실성에서 모두 빠지면 제한된 재시도를 수행한다. 진행 변경 대상에는 finding이 필요하다.
아직 막힌 절차도 등록 목록·전체 추적·추가 질문에서는 유지한다. 원상복구가 불필요하거나 완료됐다고 확인된 경우에는
원상복구 세부사항을 다시 요구하지 않는다.
절차별 허용 출처를 전달하고, 다른 절차의 출처를 섞으면 허용 문서를 명시해 재시도한다.
이미 저장된 동일 절차·동일 진행 상태는 새 변경 후보로 다시 만들지 않는다.
요약은 해당 절차의 인용 원문에서 발췌하며, 바꿔 쓰거나 다른 문서의 내용을 섞으면
재시도한다. 날짜·기한을 인용할 때도 대상·조건을 보존하도록 지시한다.
세부 행동·기한도 인용 원문과 일치해야 한다.
원문 일치만으로 Case 적용 조건이 검증된
것은 아니다. `requires_confirmation`은 사용자가 선택한 요건 준비 여부와 기존 상태에서 코드가 계산한다.
상세 분석 대상 중 요건·준비가 아직 확인되지 않은 절차도 finding 또는 uncertainty로 남기되 선택적인 세부 안내는
`required_actions=[]`, `required_documents=[]`, `application_channel=null`, `application_url=null`,
`deadline=null`로 둔다. 준비가 확인된 절차는 지금 실행할 행동 한 문장과 근거만 우선 반환한다.

## 반환하는 것

`InfoAnalysisResult`: `fact_candidates`(SET/CLEAR), `conflicts`, `missing_fields`,
`procedure_findings`, `question_candidates`, `evidence_records`.

- `missing_fields`: 모르는 필드를 여기로만 표현한다. `blocks`는 `PROCEDURE_LOOKUP` / `SUPPORT_ANALYSIS` / `SUPERVISOR_DECISION` 중 하나 이상
- `procedure_findings`: 요건 확인·실행·제출·처리 완료를 구분한다. 자료 조회만으로 요건이 확인됐다고 추정하지 않는다. `relevance`는 출처가 `UNKNOWN`/`STALE`이면 `UNDETERMINED`
- `procedure_progress_observations`: 원 `ProcedureProgressReport`와 동일한 절차·상태·요건 확인·제출 값을 코드가 구성한다. 자유문장만으로 만든 진행 관찰은 거절한다. Review는 선택값·원 이벤트·구조화 근거를 다시 대조한다.
- 세무 finding의 `followup_guidance`: 사업자 폐업신고가 이미 완료됐거나 이번 명시적 완료 선택으로 완료되는 경우에만 공식 자료에서 후속 일정·문의처를 연속 발췌한다. 다른 절차나 미완료 신고에는 만들지 않으며 세금 신고 완료는 추적하지 않는다.
- 모르는 필드를 다루는 절차 문서가 있으면 `missing_fields`와 함께 `decision_authority=LANDLORD`인 `procedure_finding`도 같이 낸다 — Supervisor가 "임대인에게 확인" ACTION을 만들 근거가 된다

## SET/CLEAR 규칙

- 사용자가 모른다고 한 사실에는 SET/CLEAR를 내지 않는다 — `missing_fields`+질문으로만 표현
- `clear_allowed=false`인 필드는 CLEAR 금지
- `restoration_status`는 `restoration_scope`가 확정된 경우에만 확정한다. 확정된 `restoration_status`를 유지하며 `restoration_scope`만 CLEAR하지 않는다
- 추출한 사실마다 정확한 `source_text` 부분 문자열을 인용해야 한다. 모호하면 질문/missing field로

## 충돌 감지

기존 확정값과 다른 값이 발화에서 나오면 `ConflictCandidate`를 만든다. 충돌 확인의 최신성 검사는
Supervisor가 아니라 [`enrichment.py`](../../backend/app/agent/enrichment.py)가 한다 —
복수 선택 전체와 당시 사실·절차 진행·근거를 현재 상태와 대조한다. 날짜의 JSON 왕복을 허용하고 bool과 int는 구분한다. BE는 저장 직전에도 상태를 재검사한다.

코드: [`info_agent/agent.py`](../../backend/app/agent/info_agent/agent.py),
프롬프트: [`prompts.py`](../../backend/app/agent/prompts.py)의 `info_messages`,
개인정보 차단: [`projection.py`](../../backend/app/agent/projection.py).

충돌 결과의 `pending_input`은 원 입력·원 Info 호출 ID·비충돌 사실·진행 보고와 전체 집합 digest를 담는다.
확인 시 같은 원 근거·후보 ID를 보존하고 새 Info 호출·현재 절차 조회로 재검증한다.
검수 전 Case 값을 바꾸지 않으며 보존 보고의 누락·변조·불가능한 진행도 거절한다.
입출력 계약은 [`schemas.py`](../../backend/app/agent/schemas.py), 실제 모델 검증 범위는
[`README.md`](./README.md)를 따른다. 신규 충돌 저장·확인 연결은 BE 후속 작업이다.
