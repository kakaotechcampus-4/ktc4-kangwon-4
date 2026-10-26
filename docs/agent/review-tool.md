# Review Tool

모든 정상 판단을 독립 검수하는 필수 관문. 검색하지 않고 초안을 직접 고치지 않는다 —
반송 사유만 내고, 해당 구성요소가 다시 판단한다.

Runtime의 공용 client로 호출하며, 현재 실제 실행 설정은
`OPENAI_MODEL=gpt-6.1-sol`, `OPENAI_REASONING_EFFORT=xhigh`다.
모델은 환경설정에서 읽으며, Info·Supervisor는 별도 설정을 지정할 수 있다.
Review 독립성은 다른 모델 사용이 아니라 별도 프롬프트·별도 호출로 확보.
Supervisor의 응답이나 대화 이력을 재사용하지 않고 `ReviewSubject`만 입력으로 사용.

## 입력 → 출력

`ReviewSubject`(불변, 초안+근거+snapshot 전부 포함) → `ReviewResult`(`verdict`: `PASS`/`REVISE`).
`PASS`만 `ReviewProof`로 이어져 `REVIEWED_PLAN`이 된다 — 증명은 `subject_digest` 일치까지 재확인한다.

## 두 겹 검사

1. **결정적 검사(코드, 우회 불가)** — `_validate_integrity` 뒤 `_deterministic_safety_review`를 수행한다
   - `_validate_integrity`: subject 자체의 구조적 일관성
   - `_validate_mutation_provenance`: 모든 변경 후보가 실제 하위 결과에서 나왔는지(근거·digest 추적)
   - `_validate_procedure_analysis_provenance`: 절차 finding의 출처 추적
   - `_validate_action_shape`: ACTION/NEEDS_MORE_INFO/COMPLETED 모양 규칙(Blocker/NextAction 존재 여부 등)
   - `procedure_plan_constraints`([procedure-tool.md](./procedure-tool.md))도 여기서 다시 검사
2. **모델 검토** — 무결성 검사를 통과하면 LLM도 검토하며, 최종 결과에는 결정적 검사 사유를 함께 반영한다. 출력 형식 재시도는 첫 시도 포함 기본 2회(`max_output_attempts=2`)

충돌 확인은 `conflict_ref`로 각 충돌과 선택을 연결한다. 수락한 변경의 before는 당시
snapshot과, proposed·operation·근거는 선택한 충돌 후보와 정확히 일치해야 한다.
거절한 값의 반영과 수락한 값의 누락은 반려한다.
전부 거절해도 재판단·Review를 거친다. 이전 단건 수락 형식도 지원한다.

절차 진행 변경은 자연어 보고의 정확한 원문 인용·입력 이벤트·근거를 대조한다.
명시적 `ProcedureProgressReport`는 절차·enum 상태·요건 확인·제출 선택과 정확히 일치해야 한다.
신고 접수와 기관 처리 완료를 구분하며, 선택이 있었다는 이유로 적용 조건·근거 검수를 생략하지 않는다.

## 모델에 전달하는 범위

사용자에게 보이는 전체 문장·전체 Blocker·질문·완료 후 세금 안내와, 선택된 행동·절차 진행
변경에 쓰이는 세부 근거를 검수한다. 해당 문장과 연결된 근거·부모 원문을 유지한다.
모든 finding의 세부사항을 모델에 전달한다. 참조 없는 조회 문서·본문은
생략하되, finding과 연결된 근거·부모 원문은 유지한다.
중복되는 `GroundedClaim.text`도 생략하고, `target_path`의 실제 문장을 대조한다.
배열 위치와 실제 재작업 경로는 보존하며, 원본 DTO 전체의 코드 검증·digest·검수 증명은
바뀌지 않는다. 자료 안전 검사는 생략된 조회 문서의 원문도 검사한다.

## PASS 조건

사용자에게 보이는 모든 주장에 해석 가능한 근거를 연결하고, 미확인 사항을 명시하며,
자격/법률/세무/날짜의 단정을 방지한다.

- `ACTION`: 전체 `blockers`와 그중 우선 `blocker` 1개, 다음 행동 1개를 반환한다.
- `NEEDS_MORE_INFO`: 전체 `blockers`와 우선 `blocker` 1개, 확인 질문을 반환하며 다음 행동은 없다.
- `COMPLETED`: 전체 카페 절차의 적용·완료와 공식 세금 후속 안내를 재검증한다.
  `blocker=null`, `blockers=[]`, `next_action=null`, `questions_for_user=[]`이며,
  근거가 있는 `followup_guidance`를 반환한다.

후보에 존재하는 Blocker의 임의 제거와 후보에 없는 Blocker의 추가는 반려한다.

미확인 여부는 Case와 변경 후보를 대조하고, 단순한 확인 질문에는 추가 근거를 요구하지
않도록 모델에 지시한다. 모델의 반려 사유를 코드로 삭제하거나 PASS로 바꾸지 않는다.
질문 안의 완료·자격 등 사실 주장도 검수하며, schema의 `evidence_refs` 요건을 유지한다.

## 재작업 한도

Graph 기준 `max_review_revisions=2`(최초 검수 포함 최대 3회). 소진하면 `SAFE_FAILURE`로
끝나고 미검수 초안은 절대 노출하지 않는다.

코드: [`review_tool/tool.py`](../../backend/app/agent/review_tool/tool.py),
프롬프트: [`prompts.py`](../../backend/app/agent/prompts.py)의 `review_messages`.
