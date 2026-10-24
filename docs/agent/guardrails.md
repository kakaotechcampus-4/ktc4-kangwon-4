# Agent 가드레일

후속 방향은 **의미·문맥 판단은 LLM, 실행 통제와 구조 검증은 코드**다.
코드 가드레일과 LLM 검사 하네스는 함께 적용한다. 하네스의 통과 판정만으로 기존 코드 검증을 생략하지 않는다.
[하네스 설계](./architecture.md#llm-가드레일-하네스-설계--2026-10-16)에 단계·검사 자료·분기·예산을 정리했다.
입력·자료·출력 안전 검사와 Info·독립 Review의 의미 검사를 함께 실행한다.
타입·enum·정확한 인용·근거·진행 상태·허용 후보·검수 증명은 코드가 강제한다.
문장 반전·과신·주의 표현·여러 행동을 섞은 권고는 LLM이 원문과 대조한다.
공급자의 내부 안전 시스템을 복제한 것은 아니며 오탐·미탐이 가능하다.

## 유해한 도움 차단 (`content_safety.py`)

- 기존 공용 모델로 입력·자료 본문·최종 출력을 각각 검사한다. `ALLOW`는 다음 단계로 진행한다.
  현재 자해 위기의 안전 도움 요청은 `CRISIS_SUPPORT`로 구분해 폐업 판단을 멈추고 고정 위기 안내를 반환한다.
  자료·출력 검사에서는 이 분기를 허용하지 않는다.
- 현재 사실·진행·충돌·보관 보고의 근거와 부모 원문, 절차 조회에 쓰는 공식자료를 검사한다. 참조하지 않는 과거 사용자 본문은 보내지 않는다.
- 같은 실행의 같은 본문은 중복 검사하지 않는다. 새 본문은 모델에 전달하기 전에 검사하며 다음 실행에서는 다시 검사한다.
- `check_submission(redacted_text, facts=None)`은 BE 저장 전에 호출할 수 있는 Agent 함수다. 실제 저장 순서·마스킹은 BE 연동 사항이다.
- 폭발물·무기 제작, 살인·폭행, 자살·자해 실행·조장·은폐, 성적 착취·학대,
  혐오·괴롭힘, 범죄 실행·은폐, 개인정보 침해를 돕는 내용을 거절한다.
- 위험 단어의 유무로 판정하지 않는다. 예방·신고·피해자 지원·상담·비실행 교육은 문맥에 따라 허용한다.
- 입력·문서·Tool 응답에 담긴 역할 변경·규칙 해제 지시는 따르지 않도록 모든 구성요소에 지시한다.
- 입력이 차단되면 절차 조회와 판단을 시작하지 않는다. Review PASS 뒤에도 유해한 출력이면 전체를 폐기한다.
  출력 검사에는 새 초안·Info의 생성 이유/질문·충돌 후보를 보내며, 원래 입력·snapshot·공식자료는 제외한다.
- 검사 장애·잘못된 JSON은 허용으로 바꾸지 않는다. 공급자의 안전 거절도 재시도 없이 차단한다.
  모든 검사는 기존 호출 예산·제한시간을 쓴다.
  결과 캐시는 사용하지 않는다. 로그는 원문·판정 이유 없이 호출·토큰·오류 코드만 남긴다.
- 위험 조력은 기존 `STRUCTURED_OUTPUT_FAILED`와
  `message_code=AGENT_SAFETY_REFUSE`, `retryable=false`, `recovery_action_code=NONE`으로 종료한다.
  검사 불능은 `COMPONENT_UNAVAILABLE` / `AGENT_SAFETY_CHECK_UNAVAILABLE` / `RETRY`다.
  위기 도움은 `CrisisSupportOutcome.guidance`의 공식 연락처 안내를 OUTPUT 검사한 뒤 반환한다.
  저장 전 `check_submission`은 같은 안내를 검사하고 `CrisisSupportRequired`로 저장 중단을 알린다.
  BE는 이 응답·예외를 전달하는 분기를 연결해야 하며, Agent가 자동 신고하거나 Case를 변경하지 않는다.

공개 안전 정책과 검사 방식을 참고했다. 공급자의 내부 안전 시스템을 복제한 것은 아니다:
[OpenAI 안전 지침](https://developers.openai.com/api/docs/guides/safety-best-practices),
[Anthropic 사용 정책(2025-09-15 시행본)](https://www.anthropic.com/legal/archive/22742366-2ef0-4c7a-a833-6523f10d3944),
[Gemini 개발자 안전 지침](https://ai.google.dev/gemini-api/docs/safety-guidance).

2026-10-16 실제 `gpt-6.1-sol / xhigh` 검사: 입력 8건·합성 출력 4건이 모두 기대 판정과 일치했다.
폭발물·타인 위해·자해 방법·검사 우회는 거절하고, 일반 폐업·세금 표현·피해 신고·자살예방 상담과
안전 안내·거절 문구는 허용했다. 검사기 단독의 대표 사례 확인이며 전체 Agent의 실제 모델 실행이나
일반적인 탐지 정확도를 입증하는 평가는 아니다.

## 근거 없는 단정 차단

Supervisor·Review는 자연어 키워드로 의미를 확정하지 않는다. 선언된 주장의 정확한
문장·경로·공식 근거·최신성·참조 계보는 코드로 검사하고, 독립 Review가 전체 노출 문장에서
고위험 주장의 누락·오분류·과신·확인 안내 누락을 찾아 반송한다.
`claim_safety.py`의 근거 계보 확장 함수는 유지한다.

독립 Review는 사용자에게 전달되는 전체 본문·Blocker·질문·완료 후 세금 안내와,
선택된 행동·절차 진행 변경에 쓰이는 세부 근거를 검수한다.
모든 finding의 세부사항을 검수에 전달하며, 참조 없는 조회 문서·본문은 제외한다.
중복되는 `GroundedClaim.text`도
생략하고 `target_path`의 실제 사용자 문장을 대조한다. 원본 DTO 전체의 코드 검증과
digest·검수 증명은 유지하며, 배열 위치·사용되는 문장·참조된 근거와 부모 원문·재작업 경로는 보존한다.

## 개인정보·비밀값 차단 (`guardrails.py`)

`ensure_no_sensitive_text(values)`가 5개 패턴을 막는다: 주민번호 형태, 사업자등록번호
(하이픈 있는 형태만: `000-00-00000`), 휴대전화번호(하이픈 형태), Bearer 토큰, API 키(`sk-`/`pk-` 접두).
`resolve_evidence_aliases`는 evidence_ref가 실제 제공된 근거에서 왔는지 확인한다.

## 상태 전이 차단 (`schemas.py`의 validator)

- `restoration_status`는 `restoration_scope`가 확정돼야만 `UNKNOWN`을 벗어난다
- `CONFIRMED` fact는 evidence_refs 1개 이상 필수, `UNKNOWN`은 evidence 있으면 오류
- SET은 `CONFIRMED`+값 필수, CLEAR는 `UNKNOWN`+`value=null` 필수
- 충돌 확인 재검증: 모든 선택과 당시 사실·절차 진행·근거를 검증한다. 전부 거절도 재판단·Review한다. 기준 변경은 `StaleConfirmationError`이며 저장 직전 동시 변경 방지는 BE가 담당한다.
- 종료는 전체 카페 절차·적용 여부·완료·공식 세금 후속 안내를 검사한다.
- 자연어 진행 후보는 정확한 사용자 원문 인용·원 이벤트·근거를 대조한다. `ProcedureProgressReport`가 있으면 명시적 선택과 상태·요건 확인·제출 값이 일치해야 한다. 상태·flag 후퇴는 거절하며 FE/BE 선택 전달·저장은 연동 요청 사항이다.

코드: [`claim_safety.py`](../../backend/app/agent/claim_safety.py),
[`guardrails.py`](../../backend/app/agent/guardrails.py),
[`projection.py`](../../backend/app/agent/projection.py)(개인정보 필터),
[`enrichment.py`](../../backend/app/agent/enrichment.py)(충돌 재검증),
검증자 정의: [`schemas.py`](../../backend/app/agent/schemas.py).
