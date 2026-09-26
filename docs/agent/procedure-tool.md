# 절차조회(Procedure) Tool

사전에 주입된 검수 스냅샷만 읽는다. 요청 처리 중 인터넷·DB·파일을 읽지 않는다.
적용 여부·우선순위·Next Action은 결정하지 않는다 — Supervisor의 일이다.

## 조회 (`StoredProcedureLookupTool`)

`ProcedureLookupInput`(조회어·기준일) → `ProcedureLookupResult`(문서·Evidence·상태·경고).
읽기는 부분 실패가 없다 — `completion_status`는 `COMPLETE` 아니면 `NO_RESULTS`뿐이다.

| 자료 상태 | freshness |
|---|---|
| `reviewed_by`/`reviewed_at` 둘 다 없음 | `UNKNOWN` |
| 검수 완료 + `review_valid_days` 이내 | `CURRENT` |
| 검수 완료 + 기간 초과 | `STALE` |

(`procedure_tool/store.py`의 `ReviewedProcedureRecord.freshness()`. 두 필드는 항상 같이 채워야 한다 — 하나만 채우면 검증 오류.)

## 실행 가능 판정 (`procedure_tool/rules.py`)

`procedure_constraints(step, snapshot, ...)`가 막는 사유를 반환한다(빈 목록 ≠ 출처 품질 보증):

- `deprecated_at`이 있으면 무조건 막음
- `applicable_business_type`이 `ALL`이 아니고 Case의 `business_type`과 다르면 막음
- 선행 절차(`dependency_type=SEQUENTIAL`)가 `COMPLETED`가 아니면 막음
- `eligibility_conditions`: `has_employee`(직원 수 > 0 비교) 또는 Case 필드 정확 일치만 지원. 그 외 조건 키·미확인 사실은 실행 가능으로 안 침

`procedure_plan_constraints(...)`는 Supervisor의 ACTION target과 진행 변경 후보 전체에 위 규칙을
적용한다. 등록 안 된 ID, 폐기된 절차, 이미 `COMPLETED`인 절차를 next action으로 막는다 —
위반 시 Supervisor는 `SupervisorGuardrailError`로 초안 자체를 버린다.

코드: [`procedure_tool/stored_tool.py`](../../backend/app/agent/procedure_tool/stored_tool.py)(조회),
[`procedure_tool/store.py`](../../backend/app/agent/procedure_tool/store.py)(검수 상태),
[`procedure_tool/rules.py`](../../backend/app/agent/procedure_tool/rules.py)(실행 가능 판정).
