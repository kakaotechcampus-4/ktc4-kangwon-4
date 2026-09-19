# Case Service (B7)

> 소유: BE
> 작성일: 2026-09-19
> 상태: 스코프 내 구현 완료 · AI 연동 어댑터는 보류
> 코드: [`backend/app/be/services/case_service.py`](../backend/app/be/services/case_service.py), [`backend/app/be/crud/case.py`](../backend/app/be/crud/case.py)
> 티켓: B7 — Case Service, 조회·쓰기 단일 경로 + CaseSnapshot 조립

이 문서는 B7에서 만든 Case Service가 뭘 하고 뭘 안 하는지, 어떤 결정을 거쳐 이 모양이 됐는지,
다음에 뭘 채워야 하는지를 코드를 안 읽고도 알 수 있게 정리합니다.

## B7이 하는 일 (한 줄)

**Case에 접근하는 문을 하나로 만든다** — 소유권 검증을 포함한 조회 단일 경로, 필드 변경 단일 경로,
Agent에게 넘길 스냅샷 조립. `docs/architecture.md`가 말하는 "Agent와 Tool은 DB를 직접 변경하지
않는다" 불변식을 실제로 강제하는 지점입니다.

## 포함된 것

| 함수 | 역할 |
|---|---|
| `get_case_for_member` | 소유권 조건(`case_id` + `member_id`) 포함 단일 조회. 다른 코드는 이 함수를 거치지 않고 `Case`를 직접 select하지 않는다 |
| `assemble_case_snapshot` | 한 시점 기준 Case 상태(사실·절차 진행·활성 Blocker·최근 이력)를 고정한 BE 내부 스냅샷(`InternalCaseSnapshot`) 조립 |
| `apply_case_field_changes` | Case 필드를 바꾸는 단일 경로. 다른 코드는 `Case` 컬럼을 직접 assign하지 않는다 |
| `to_agent_case_snapshot` | AI `CaseSnapshot`으로의 변환 — **보류, `NotImplementedError`** (이유는 아래 "열린 이슈 1") |

`CaseNotFoundError`는 소유하지 않았거나 존재하지 않는 Case를 같은 예외 하나로 표현합니다.
라우터는 이걸 항상 404로만 변환해야 합니다 — 소유권 없음과 존재하지 않음을 구분해서 응답하면
Case 존재 여부가 노출됩니다 (B6 결정 사항).

## 포함 안 된 것 (다른 티켓 범위)

- 상태 전이 유효성 검증 → **B10**
- 충돌 자동 덮어쓰기 방지의 실제 CAS 로직 → **B10/B12**, `CONFLICT_REFERENCE` 테이블 필요
- Agent 실행 orchestration (Supervisor 호출 등) → **B11**
- JWT 인증·소유권 판별 자체 → **B6**. 이 서비스는 이미 검증된 `member_id`를 받는다고 가정

`apply_case_field_changes`는 변경을 **반영만** 합니다. 그 변경이 유효한 상태 전이인지, 기존 값과
충돌하는지는 호출자(B10 이후)가 먼저 검증해서 넘겨야 합니다.

## 진행하며 확정된 결정 (2026-09-19)

| 항목 | 결정 |
|---|---|
| enum 기준 | `docs/schema/schema_table.md`(DB) 값을 그대로 사용 |
| 신규 테이블(`case_version`, `CASE_FIELD_HISTORY`, `EVIDENCE` 등) | 이번 PR에 미포함 — 다른 팀원이 별도로 모델 추가 예정. 코드엔 TODO로 의존성만 표시 |
| 코드 위치 | `app/be/{crud,routers,schemas,services}` — 미병합 `feature/login` 브랜치 컨벤션을 따름 |
| history 개수 | `DEFAULT_HISTORY_WINDOW = 20` (임시값, PM 확인 전) |
| Alembic | 이번 범위에서 제외 — 배포 과정에서 별도로 처리 예정 |

## 열린 이슈 (해결 안 됨 — AI/DB 팀 확인 필요)

모든 이슈를 같은 급으로 두지 않습니다. **B7 코드가 실제로 막힌 것**과 **스키마엔 있지만
다른 티켓 소관이라 B7과 무관한 것**을 구분합니다.

### A. B7 함수가 지금 직접 막혀 있는 것

1. **`CASE.case_version` 없음** — `assemble_case_snapshot`(`case_version`이 항상 `None`
   반환)과 `apply_case_field_changes`(버전 증가 로직이 주석 처리 상태) 둘 다 직접 영향받습니다.
   B7이 원래 하려던 동시성 보호(CAS)를 지금 못 합니다. 컬럼이 생기면 두 지점의 TODO를 지웁니다.

2. **`lease_status` / `restoration_scope` 값이 DB와 AI 코드에서 다른 사실을 가리킴** —
   DB(`schema_table.md`): `lease_status` = 임대 조건(`LEASED_PAID`/`LEASED_FREE`/`OWNED`),
   `restoration_scope` = 복구 범위(`UNKNOWN`/`PARTIAL`/`FULL`/`NOT_REQUIRED`). AI 코드
   (`backend/app/agent/schemas.py`의 `CASE_FIELD_SPECS`): `lease_status` = 해지 통보 진행
   단계(`ACTIVE`/`TERMINATION_NOTIFIED`/`TERMINATED`/`OWNED`), `restoration_scope` = 복구
   비용 부담 주체(`AGREEMENT_REQUIRED`/`TENANT_ALL`/`LANDLORD_ALL`/`SHARED`/`NOT_REQUIRED`).
   이름은 같지만 다른 사실이라 값 하나가 다른 값 하나로 안 옮겨갑니다. DB 값을 그대로 AI에
   넘기면 AI 코드가 `ValueError`로 거부합니다. `to_agent_case_snapshot`이 `NotImplementedError`인
   이유입니다. AI 리드가 `CASE_FIELD_SPECS`를 갱신하거나 매핑을 승인해야 풀립니다.

3. **`entity_type` / `building_use_type` / `previous_support_history` — DB에 컬럼 없음** —
   AI `CaseFieldKey`가 이 3개 필드를 쓰는데 `schema_table.md`·SQLModel 어디에도 없습니다.
   `to_agent_case_snapshot` 완성을 막는 요인 중 하나입니다. DB에 새 컬럼을 추가할지, AI가
   이 필드 없이 판단하도록 할지 결정 필요.

### B. B7 완성(2단계 CaseSnapshot)엔 필요하지만, A가 먼저 안 풀려서 지금 순서가 안 온 것

`SharedCaseSnapshotDTO`(`be-agent-integration-requirements.md` §5.2) 기준으로 완성형
CaseSnapshot의 필수 필드라, "무관"이 아니라 "A가 풀린 다음에 바로 막힐 것"입니다.

4. **`EVIDENCE` / `EVIDENCE_LINEAGE` 없음** — 완성형 스냅샷의 `evidenceRecords`를 채우려면
   필요. A-2·A-3가 먼저 안 풀려서 순번이 아직 안 왔을 뿐, `to_agent_case_snapshot`을 실제로
   끝내려면 결국 필요합니다.
5. **`DECISION_RECORD` 없음** — 완성형 스냅샷의 `latestDecision`(최근 판단 결과)을 채우려면
   필요. 마찬가지로 순번 대기 중이며, B11이 아니라 B7의 완성 조건에도 포함됩니다.

### C. CaseSnapshot 조립과 무관 — 별도 기능·다른 티켓 소관

이 2개는 CaseSnapshot 안에 들어가는 내용이 아니라 별개 기능입니다. B7이 지금 만든 함수는
아무것도 쓰지 않고, CaseSnapshot이 완성돼도 필요해지지 않습니다.

6. **`CONFLICT_REFERENCE`** — 충돌 확인(`/results/confirm`) 전용, B12 소관.
7. **`CASE_FIELD_HISTORY`** — 쓰기 감사 이력(변경 전/후 기록)이지 스냅샷에 들어가는 값이
   아닙니다. `apply_case_field_changes`에 TODO로 걸어뒀지만, 이걸 B7(쓰기 단일 경로)이
   채울지 이후 Guardrail·트랜잭션 티켓(B10/B11)이 채울지는 아직 안 정해졌습니다.

## 다음에 할 일

1. `CASE.case_version`이 머지되면 `case_service.py`의 두 TODO 지점(A-1)을 채운다.
2. AI 쪽이 `CASE_FIELD_SPECS`를 schema_table.md 기준으로 갱신하거나 매핑을 승인하면(A-2),
   DB에 없는 3개 필드 처리 방향이 정해지면(A-3) `to_agent_case_snapshot` 1차 구현을 진행한다.
3. `EVIDENCE`/`EVIDENCE_LINEAGE`(B-4), `DECISION_RECORD`(B-5)가 머지되면 `to_agent_case_snapshot`을
   완성한다 — 이게 끝나야 B7이 원래 목표한 "AI가 실제로 쓰는 CaseSnapshot"까지 완료된 것.
4. `CASE_FIELD_HISTORY`(C-7)를 B7이 채울지 다른 티켓이 채울지 정한다.
5. B10(상태 전이 Guardrail), B11(핵심 루프)이 이 서비스 함수들을 호출하도록 연결한다 — 이때
   `CONFLICT_REFERENCE`(C-6)가 B12에서 필요해진다.
