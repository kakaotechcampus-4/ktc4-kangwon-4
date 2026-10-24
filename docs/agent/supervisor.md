# Supervisor Agent

검증된 `SupervisorAgentInput`에서 전체 Blocker와 우선 해결할 한 가지를 판단한다.
Case·DB를 직접 수정하지 않고 `SupervisorDraft`의 변경 후보를 독립 Review에 보낸다.
계약은 [schemas.py](../../backend/app/agent/schemas.py), 실행은
[supervisor/agent.py](../../backend/app/agent/supervisor/agent.py)가 기준이다.

| 판단 | 반환 |
|---|---|
| ACTION | `blockers` 전체, 우선 `blocker`, `next_action` 하나 |
| NEEDS_MORE_INFO | `blockers` 전체, 우선 `blocker`, 확인 질문. `next_action=null` |
| COMPLETED | `blocker=null`, `blockers=[]`, `next_action=null`, 세금 후속 `followup_guidance` |

[blocker_candidates.py](../../backend/app/agent/blocker_candidates.py)는 근거·적용 조건·선후 관계·완료 상태를 검증해 후보를 만든다.
LLM은 `decision_type`, `blocker_candidate_id`, `action_code`만 반환한다.
설명·질문·대상·근거는 선택된 검증 후보에서 코드가 조립한다.
LLM은 유효 후보 중 우선 항목과 그 후보의 행동을 고르며, 코드가 첫 후보로 바꾸지 않는다.
없는 후보·행동·대상은 거절하고, 제한된 재시도에도 유효한 답을 못 받으면 SAFE_FAILURE로 끝낸다.
모델 오류를 코드가 만든 기본 답으로 대신하지 않는다.

Blocker의 `candidate_id`는 절차 ID 또는 미확인 필드에 연결된다. BE가 이전 활성 ID를
`CaseSnapshot.active_blocker_candidate_ids`에 공급하면, 사실·진행으로 해소가 확인된 항목만
`resolved_blocker_candidate_ids`에 반환한다. 오늘 후보에서 빠졌다는 이유만으로 해소하지 않는다.
기존 BE 저장 코드는 우선 한 개만 저장하므로 전체 목록·해소 상태 저장은 연동 변경이 필요하다.

절차 행동은 요건 확인 → 실행·제출 → 기관 처리 확인을 구분한다.
`requirements_confirmed`와 `submitted`는 사용자 선택 또는 검증된 원문 보고를 근거로 전진하며,
신고 제출과 기관 처리 완료를 구분한다. 자연어 진행 후보도 원문 근거와 Review를 통과해야 하며 모호하면 보류한다. 각 행동은 등록된 절차 하나를 가리킨다.
FE 상태 선택·BE 전달과 검수 후 진행 저장은 아직 연동 작업이 필요하다.

[completion.py](../../backend/app/agent/completion.py)는 카페 전체 8종 절차 등록,
미확인 적용 조건 없음, 적용 대상의 완료, 공식 세금 후속 안내를 검사한다.
일부 절차만 등록됐거나 현재 직원 수로 과거 가입 이력을 추정해야 하는 상태에서는 종료하지 않는다.
완료도 LLM 선택·Review·최종 안전 검사를 거친다. BE의 Case 종료 저장은 별도 연동이다.

문장 의미·과신·고위험 주장 누락은 독립 Review LLM이 검토한다.
타입·enum·인용·근거 계보·신선도·후보·상태·검수 digest 검사는 코드가 강제한다.
지원사업과 자율 Tool 선택은 MVP 실행 범위에 넣지 않는다.
