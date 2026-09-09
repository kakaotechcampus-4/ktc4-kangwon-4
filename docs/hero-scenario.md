# RE:BORN Hero Scenario

> 사용자 시나리오 및 Hero Loop 상세 흐름. 이 문서는 `docs/data-model.md`(enum), `docs/architecture.md`(Agent 노드), `docs/interface-spec.md`(엔드포인트/JSON)에서 이미 확정된 이름만 사용합니다 — 새 용어를 여기서 만들지 않습니다.

## 1. 한 줄 소개

폐업 지원, 조건이 하나 바뀔 때마다 다음 할 일을 다시 계산해주는 Agent.

## 2. 타깃 페르소나

폐업 의사는 이미 확정했지만 임대차·원상복구·철거·지원·세무 조건을 스스로 조율해야 하는 **1~5인 비프랜차이즈 소규모 카페 사업자** (임차형).

## 3. 대표 Hero Case

> 폐업 의사가 확정된 1인 카페 사업자가 "계약은 9월 말까지이고 인수자를 기다리는 중"이라고 입력한다. 이후 임대인이 "원상복구와 철거가 필요하다"고 알려오면, 기존 Case와 충돌·영향 범위를 확인하고 철거 전 점포철거비 지원조건 확인을 다음 행동으로 다시 계산한다.

## 4. Hero Loop — 7단계

| 단계 | 시스템이 해야 할 일 |
|---|---|
| 1. 입력 | 사용자가 자연어로 현재 상황을 입력한다. |
| 2. 사실 추출 | 문장에 있는 값만 추출하고 사용자 발화/문서 추출 출처 태그를 붙인다 (정보분석 Agent → `FactCandidate`). |
| 3. Case 인식 | 폐업 의사·계약 종료일·양도·원상복구·철거·지원·세무 상태를 표시하고 Blocker를 찾는다. |
| 4. 계획 | Next Action 1개, 이유, 상대방에게 물을 질문을 제시한다 (Rule 엔진 → Supervisor). |
| 5. 현실 실행 | 사용자가 임대인 연락·업체 문의·서류 확인을 직접 수행한다. |
| 6. 결과 입력 | 사용자가 실행 결과를 한 줄로 입력한다 (`POST /cases/{caseId}/results`). |
| 7. 검증·재계획 | 충돌이면 되묻고(`CONFLICT`), 확인된 결과로 Case와 영향받는 절차(`case_step_progress`)를 갱신한 뒤 Next Action 1개를 다시 제시한다. |

이 표는 `/CLAUDE.md`의 축약된 Hero Loop("Case 생성 → Blocker 1개 판단 → Next Action 1개 제시 → 사용자 실행 → 결과 입력 → Case 상태 변경 → 재계획 → 반복")의 상세판입니다 — 서로 다른 정의가 아니라 같은 루프를 더 잘게 쪼갠 것입니다.

## 5. Turn-by-turn 워크스루 (첫 E2E 슬라이스)

### Turn 1 — Case 생성

```
입력: 카페 운영 중, 임차, 폐업 의사 확정
→ restoration_status = UNKNOWN, demolition_required = UNKNOWN
→ Blocker: "원상복구·철거 범위가 확인되지 않았습니다."
→ Next Action: "임대인에게 원상복구 범위와 철거 필요 여부를 확인하세요."
```

### Turn 2 — 결과 입력 → 재계획

```
사용자 입력: "임대인에게 확인했는데 철거가 필요하다고 합니다."
→ 정보분석 Agent: FactCandidate(demolition_required=REQUIRED, source_span="철거가 필요하다고 합니다")
→ Validator: 기존 값과 충돌 없음 → Case UPDATE (demolitionRequired: UNKNOWN → REQUIRED)
→ Rule 엔진 재평가: Blocker = "철거 전 지원 조건·증빙 확인 필요"
→ Next Action = "공식 점포철거비 지원 조건과 신청 전 필요 서류를 확인하세요."
→ 지원금 Agent: Wiki 조회 → SupportCheckResult(support_item_id=점포철거비, match_status=NEEDS_CONFIRMATION)
   → support_amount.review_status = REVIEW_REQUIRED 상태이므로 구체 금액은 "검토 대상"으로만 안내 (R7 실제 사례)
```

### Turn 3 — 충돌 분기 (illustrative)

```
기존: demolition_required = NOT_REQUIRED
신규 입력: "다시 확인했는데 철거해야 한대요."
→ result: CONFLICT → Case 미변경 → 사용자 확인 UI
→ 사용자가 새 값 확인 → POST /cases/{caseId}/results/confirm
→ Case UPDATE + 정정 History INSERT → 재계획
```

## 6. Golden Case — 최소 7개

| # | 시나리오 | 검증하는 것 |
|---|---|---|
| 1 | 폐업 의사 확정 + 임차 + 원상복구 미확인 | 최초 Case 생성 + 첫 Blocker/Next Action |
| 2 | 임대인 확인 결과로 `demolition_required: UNKNOWN → REQUIRED` | `FactCandidate` → `UPDATED` → 재계획 |
| 3 | 기존 `NOT_REQUIRED`와 새 `REQUIRED`의 충돌 | `CONFLICT` → `/results/confirm` 흐름 |
| 4 | 입력만으로 철거 여부를 확정할 수 없음 | `NEEDS_MORE_INFO`, 추가 질문 생성 |
| 5 | 지원사업 원문이 오래됨 | `STALE_SUPPORT_DATA`, 확정 문구 금지 |
| 6 | Case UPDATE 성공 후 Replan 실패 | `REPLAN_FAILED`, 이전 판단을 새 버전인 것처럼 보여주지 않음 |
| 7 | 사용자가 지원사업을 실제 신청 vs 단순 조회 | `SupportCheckResult`(조회) ≠ `subsidy_application`(신청) 자동 생성 안 함 |

## 7. 성공지표

| 지표 | 측정 방법 |
|---|---|
| 세션당 Loop 2회전 이상 | `REPLAN_COMPLETED` 이벤트 수로 집계 (`docs/data-model.md` §4.1) |
| Next Action 실행 가능성 | 사용자가 누구에게 무엇을 확인할지 자기 말로 재설명 가능한지 |
| 의미 있는 State Transition | 승인된 `changed_fields`가 실제 Case UPDATE로 이어졌는지 |
| Next Action 적절성 | 재계획 후 이전 Action과 다른, 지금 상황에 맞는 Action이 나왔는지 |
| 지원사업 관련성 | Case와 공식 조건의 연결 이유를 설명할 수 있는지 |
| 명백히 틀린 Next Action | Golden Case·전문가 검토에서 0건 |
| 확정적 위험 답변 | 법률·세무·지원 자격 단정 0건 |
| 전문용어 혼란 | 세션당 사용자 되물음 2회 이하 |

## 8. 스코프 리마인더 (인라인)

- Turn 1에서 폐업 예정일은 사용자가 입력한 값을 그대로 사용합니다 — **AI는 최적 폐업일을 추천하지 않습니다.**
- Turn 2의 `SupportCheckResult`는 지원 자격을 확정하지 않습니다 — "검토 대상"/"추가 확인 필요"로만 표현합니다.
- Turn 3의 충돌은 자동으로 어느 한쪽을 선택하지 않습니다 — 항상 사용자 확인을 거칩니다.

전체 스코프 제외 목록은 `/CLAUDE.md` "하지 않는 것"을 참고하세요 (여기서 반복하지 않음).

---

## 출처

| 섹션 | 원본 |
|---|---|
| §1~3 한 줄 소개, 페르소나, 대표 Case | `RE_BORN_테크스펙_회의준비_승준.md` §2, §4 |
| §4 Hero Loop 7단계 표 | `RE_BORN_테크스펙_회의준비_승준.md` §4 |
| §5 Turn-by-turn 워크스루 | `BE_AI_역할분담_및_연동스펙.md` §10.3 (11단계 E2E) + `RE_BORN_AI리드_설계안.md` §4.2 (worked examples) 결합 |
| §6 Golden Case 7종 | `todo.md` §3 / `RE_BORN_AI리드_설계안.md` §11 |
| §7 성공지표 | `agent설계.md` §1 / `RE_BORN_AI리드_설계안.md` §10.3 |
| §8 스코프 리마인더 | `/CLAUDE.md` "하지 않는 것" |
