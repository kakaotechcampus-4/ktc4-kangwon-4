# 절차조회(Procedure) Tool

BE가 Case snapshot에 담아 준 공식 근거를 사전에 읽은 승인 목록과 대조한다.
Tool 조회 중 인터넷·DB·파일을 읽지 않는다. 빈 승인 목록을 받은 runtime은 조립할 때
동봉 JSON을 검수·검색 메타정보로 읽지만, DB 근거가 없으면 JSON 원문으로 대체하지 않는다.
적용 여부·우선순위·Next Action은 결정하지 않는다 — Supervisor의 일이다.

## 조회 (`StoredProcedureLookupTool`)

`ProcedureLookupInput`(Case의 공식 Evidence·조회어·기준일) →
`ProcedureLookupResult`(문서·Evidence·상태·경고).
`evidence_records`는 기본값 없는 필수 필드다. Tool 직접 호출 시에도 전달해야 하며 빈 목록은 허용한다.
정상 반환의 `completion_status`는 `COMPLETE` 아니면 `NO_RESULTS`이며,
원문 불일치나 검수 상태 오류는 Graph가 `SAFE_FAILURE`로 처리한다.

- 승인 목록과 URL·버전이 같은 DB 자료의 발췌·해시가 일치해야 한다. 같은 URL·버전의
  중복 자료나 원문·해시 불일치는 `PROCEDURE_SOURCE_MISMATCH` 오류다.
- 현재 승인 버전의 DB 자료가 없으면 조회 대상에서 제외한다. 각 조회어별로 일치하는 문서가 없으면
  경고하며, 개별 자료 누락마다 경고하지는 않는다. 이전 버전의 DB 근거를 현재 버전으로 바꾸거나,
  없는 원문을 파일에서 채우지 않는다.
- 제목·기관명·검색어·절차 코드는 승인 목록에서, 발췌·출처·해시·시각은 DB 근거에서 읽는다.
  검색과 URL 중복 제거 후에도 DB `evidence_id`와 Evidence 내용은 그대로 유지한다.
- runtime이 전달한 대응표로 문서의 `step_codes`를 실제 DB 코드로 변환한다.
  대응이 없는 코드는 제외하되 문서와 근거는 유지한다. 빈 대응표는 `step_codes=[]`가 된다.
  Tool을 직접 호출하며 대응표를 생략한 경우에만 기존 승인 목록의 코드를 그대로 사용한다.

근거 키는 이름만 보고 바꾸지 않는다. Agent의 `evidence_refs`는 문자열인
`Evidence.evidence_id`를 참조한다. 반면 DB 관계 모델 `EvidenceLineage.evidence_id`와
`parent_evidence_id`는 숫자 PK인 `Evidence.id`를 참조한다. 이 모델과 생성 CRUD는 이미 있지만,
현재 BE snapshot 변환은 `parent_evidence_refs=[]`로 고정하므로 파생 관계 조회는 아직 연결되지 않았다.

#53 적재 코드의 `source_version`은 승인 JSON의 `snapshot_version`이며 공식기관 문서의 판본을
뜻하지 않는다. `source_ref`는 공식 URL이고, `locator`에도 현재 같은 URL을 넣는다. 따라서
`locator`가 발췌의 페이지·문단 위치를 제공한다고 볼 수 없으며 Tool의 승인 자료 대조에도 쓰지 않는다.
`retrieved_at`은 자료 수집 시각으로, 사람의 `reviewed_at`이나 DB 행 생성 시각과 구분한다.

| 승인 목록과 DB 상태 | 처리 |
|---|---|
| DB 자료와 대응하는 승인 목록에 검수 정보 없음 | `PROCEDURE_REVIEW_REQUIRED` 오류 |
| 검수 유효기간 초과인데 DB는 `CURRENT` | 같은 오류로 차단, 자료 갱신 필요 |
| 검수 유효기간 내이고 DB도 `CURRENT` | `CURRENT` 그대로 반환 |
| 검수 정보가 있고 DB는 `STALE` 또는 `UNKNOWN` | DB 상태와 근거를 그대로 반환하고 경고 |

검수 유효기간은 `ReviewedProcedureRecord.freshness()`로 요청 기준일에 대해 검사한다.
DB 상태를 Tool 안에서 `CURRENT`로 올리거나, 같은 근거 ID에 다른 상태를 덮어쓰지 않는다.
`reviewed_by`와 `reviewed_at`은 둘 다 있어야 하며 하나만 있으면 승인 목록 검증 오류다.

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
