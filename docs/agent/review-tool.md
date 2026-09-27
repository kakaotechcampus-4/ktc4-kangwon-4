# Review Tool

모든 정상 판단을 독립 검수하는 필수 관문. 검색하지 않고 초안을 직접 고치지 않는다 —
반송 사유만 내고, 해당 구성요소가 다시 판단한다.

Supervisor와 같은 설정의 클라이언트를 사용하되, 별도 프롬프트·별도 호출로 검수한다.
Supervisor의 응답이나 대화 이력을 재사용하지 않고 `ReviewSubject`만 받는다.

## 입력 → 출력

`ReviewSubject`(불변, 초안+근거+snapshot 전부 포함) → `ReviewResult`(`verdict`: `PASS`/`REVISE`).
`PASS`만 `ReviewProof`로 이어져 `REVIEWED_PLAN`이 된다 — 증명은 `subject_digest` 일치까지 재확인한다.

## 두 겹 검사

1. **결정적 검사(코드, 우회 불가)** — `_validate_integrity` 뒤 `_deterministic_safety_review`를 수행한다
   - `_validate_integrity`: subject 자체의 구조적 일관성
   - `_validate_mutation_provenance`: 모든 변경 후보가 실제 하위 결과에서 나왔는지(근거·digest 추적)
   - `_validate_procedure_analysis_provenance`: 절차 finding의 출처 추적
   - `_validate_action_shape`: ACTION/NEEDS_MORE_INFO 모양 규칙(Blocker/NextAction 존재 여부 등)
   - `procedure_plan_constraints`([procedure-tool.md](./procedure-tool.md))도 여기서 다시 검사
2. **모델 검토** — 무결성 검사를 통과하면 LLM도 검토하며, 최종 결과에는 결정적 검사 사유를 함께 반영한다. 첫 시도 포함 최대 2회(`max_output_attempts`)

## PASS 조건

사용자에게 보이는 모든 주장에 해석 가능한 근거, 미확인 사항은 명시적으로 남음,
ACTION은 blocker·action 정확히 1개씩, 자격/법률/세무/날짜 주장이 과신하지 않음.

미확인 여부는 Case와 변경 후보를 대조하고, 단순한 확인 질문에는 추가 근거를 요구하지
않도록 모델에 지시한다. 모델의 반려 사유를 코드로 삭제하거나 PASS로 바꾸지 않는다.
질문 안의 완료·자격 등 사실 주장도 검수하며, schema의 `evidence_refs` 요건을 유지한다.

## 재작업 한도

Graph 기준 `max_review_revisions=2`(최초 검수 포함 최대 3회). 소진하면 `SAFE_FAILURE`로
끝나고 미검수 초안은 절대 노출하지 않는다.

코드: [`review_tool/tool.py`](../../backend/app/agent/review_tool/tool.py),
프롬프트: [`prompts.py`](../../backend/app/agent/prompts.py)의 `review_messages`.
