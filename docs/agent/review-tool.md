# Review Tool

모든 정상 판단을 독립 검수하는 필수 관문. 검색하지 않고 초안을 직접 고치지 않는다 —
반송 사유만 내고, 해당 구성요소가 다시 판단한다.

모델 검토는 공용 설정을 사용한다. [운영 예시](../../.env.prod.example)는 Review에
Sol `xhigh`, Info에 Sol `high`, Supervisor에 별도 Luna 6 `high`를 지정한다.
실제 선택은 [`runtime.py`](../../backend/app/agent/runtime.py)와 환경설정을 따른다.
모델 검토의 독립성은 별도 프롬프트·별도 호출로 확보한다.
Supervisor의 응답이나 대화 이력을 재사용하지 않고 `ReviewSubject`만 입력으로 사용.

## 입력 → 출력

`ReviewSubject`(불변, 초안+근거+snapshot 전부 포함) → `ReviewResult`(`verdict`: `PASS`/`REVISE`).
`PASS`만 `ReviewProof`로 이어져 `REVIEWED_PLAN`이 된다 — 증명은 `subject_digest` 일치까지 재확인한다.

## 두 겹 검사

1. **결정적 검사(코드, 우회 불가)** — `_validate_integrity` 뒤 `_deterministic_safety_review`를 수행한다
   - `_validate_integrity`: subject 자체의 구조적 일관성
   - `_validate_mutation_provenance`: 변경 후보의 출처·근거·digest를 검사한다. 절차 완료는 `completion_confirmed`로 별도 확인 또는 같은 절차의 고정 완료 버튼을 검사한다. 충돌 확인에서 채택한 원상복구 완료는 `confirmed_restoration_progress`가 원래 충돌·현재 절차·근거의 일치를 확인한 변경만 인정한다
   - `_validate_procedure_analysis_provenance`: 절차 finding의 출처 추적
   - `_validate_action_shape`: ACTION/NEEDS_MORE_INFO 모양 규칙(Blocker/NextAction 존재 여부 등)
   - `procedure_plan_constraints`([procedure-tool.md](./procedure-tool.md))도 여기서 다시 검사
2. **모델 검토** — Info가 모델을 사용하지 않은 첫 회차(`revision_count=0`)는 `review_code_only`로 코드 검사만 한다. 첫 판단·원상복구 선택형 답변·`action_done` 버튼·충돌 확인 뒤 판단이 이 조건에 해당할 수 있다. 그 밖에는 LLM도 검토하며, 최종 결과에는 결정적 검사 사유를 함께 반영한다. 모델 응답 검증은 기본 첫 시도 포함 최대 2회(`max_output_attempts`)

## PASS 조건

사용자에게 보이는 모든 주장에 해석 가능한 근거, 미확인 사항 명시,
현재 MVP의 ACTION은 action 정확히 1개·blocker 정확히 1개, 자격/법률/세무/날짜의 단정 방지.
후보에 존재하는 Blocker의 임의 제거와 후보에 없는 Blocker의 추가는 반려.
`NEEDS_MORE_INFO`의 Blocker 1개·확인 질문 필수 조건 유지.

미확인 여부는 Case와 변경 후보를 대조하고, 단순한 확인 질문에는 추가 근거를 요구하지
않도록 모델에 지시한다. 모델의 반려 사유를 코드로 삭제하거나 PASS로 바꾸지 않는다.
질문 안의 완료·자격 등 사실 주장도 검수하며, schema의 `evidence_refs` 요건을 유지한다.

## 재작업 한도

Graph 기준 `max_review_revisions=2`(최초 검수 포함 최대 3회). 소진하면 `SAFE_FAILURE`로
끝나고 미검수 초안은 절대 노출하지 않는다.

코드: [`review_tool/tool.py`](../../backend/app/agent/review_tool/tool.py),
프롬프트: [`prompts.py`](../../backend/app/agent/prompts.py)의 `review_messages`.
