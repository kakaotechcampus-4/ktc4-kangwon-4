# 정보조회(Info) Agent

사용자 발화와 절차조회 결과를 분석해 **사실 변경 후보·충돌·미확인 필드·절차 finding**을 만든다.
Case를 직접 수정하지 않는다 — 전부 후보(candidate)로만 반환한다.
모델과 추론 강도는 `INFO_*` 설정을 사용하며, 비우면 공용 설정을 따른다.
Supervisor·Review와 같은 실행별 호출 예산·시간 제한을 공유한다.

## 입력의 두 경로

`InfoAnalysisInput.input`은 `RedactedInput | None`이다.

| 입력 | 동작 |
|---|---|
| 발화 있음 | 발화 근거로 사실·충돌 후보 생성 + 절차 분석 |
| `input=None` | 검증된 확인 후보(`fact_overlays`)만 받고 절차만 재분석. 새 사실·충돌 후보를 만들지 않는다 |

최신 발화는 사실·실행 결과를 추출하는 근거이며, 절차 분석의 범위를 최신 발화에 나온
주제로 제한하지 않는다. 현재 Case·진행 상태·overlay와 조회된 문서 전체를 함께 본다.
현재 자료에 연결된 미완료 절차를 분석에서도 문서별 불확실성에서도 누락하면 해당 절차를
명시해 제한된 재시도를 수행한다. 원상복구가 불필요하거나 완료됐다고 확인된 경우에는
원상복구 세부사항을 다시 요구하지 않는다.
절차별 허용 출처를 전달하고, 다른 절차의 출처를 섞으면 허용 문서를 명시해 재시도한다.
이미 저장된 동일 절차·동일 진행 상태는 새 변경 후보로 다시 만들지 않는다.
요약은 해당 절차의 인용 원문에서 발췌하며, 바꿔 쓰거나 다른 문서의 내용을 섞으면
재시도한다. 날짜·기한을 인용할 때도 대상·조건을 보존하도록 지시한다.
세부 행동·기한도 인용 원문과 일치해야 한다.
원문 일치만으로 Case 적용 조건이 검증된
것은 아니므로 미확인 조건을 단정하지 않고 `requires_confirmation=True`를 유지한다.

## 반환하는 것

`InfoAnalysisResult`: `fact_candidates`(SET/CLEAR), `conflicts`, `missing_fields`,
`procedure_findings`, `question_candidates`, `evidence_records`.

- `missing_fields`: 모르는 필드를 여기로만 표현한다. `blocks`는 `PROCEDURE_LOOKUP` / `SUPPORT_ANALYSIS` / `SUPERVISOR_DECISION` 중 하나 이상
- `procedure_findings`: `requires_confirmation`은 항상 `True`(웹에서 온 finding은 전부 사람 확인 필요). `relevance`는 출처가 `UNKNOWN`/`STALE`이면 `UNDETERMINED`
- 모르는 필드를 다루는 절차 문서가 있으면 `missing_fields`와 함께 `decision_authority=LANDLORD`인 `procedure_finding`도 같이 낸다 — Supervisor가 "임대인에게 확인" ACTION을 만들 근거가 된다

## SET/CLEAR 규칙

- 사용자가 모른다고 한 사실에는 SET/CLEAR를 내지 않는다 — `missing_fields`+질문으로만 표현
- `clear_allowed=false`인 필드는 CLEAR 금지
- `restoration_status`는 `restoration_scope`가 확정된 경우에만 확정한다. 확정된 `restoration_status`를 유지하며 `restoration_scope`만 CLEAR하지 않는다
- 추출한 사실마다 정확한 `source_text` 부분 문자열을 인용해야 한다. 모호하면 질문/missing field로

## 충돌 감지

기존 확정값과 다른 값이 발화에서 나오면 `ConflictCandidate`를 만든다. 충돌 확인의 최신성 검사는
Supervisor가 아니라 [`enrichment.py`](../../backend/app/agent/enrichment.py)가 한다 —
`snapshot_id` + 기존값(타입까지) 일치를 확인한다(낙관적 락 없이 동작).

코드: [`info_agent/agent.py`](../../backend/app/agent/info_agent/agent.py),
프롬프트: [`prompts.py`](../../backend/app/agent/prompts.py)의 `info_messages`,
개인정보 차단: [`projection.py`](../../backend/app/agent/projection.py).
