# Guardrail (코드 차단)

LLM 출력·근거·상태 전이를 결정적 코드로 막는 곳. 프롬프트 지시와 달리 우회 불가능하다.

## 근거 없는 단정 차단 (`claim_safety.py`)

`high_risk_metadata(text, ...)`가 위험 유형을 감지하면 `REQUIRED_CLAIM_SOURCES`
(`OFFICIAL_DOCUMENT` / `OFFICIAL_API`만 인정)로만 뒷받침돼야 한다.

| `ClaimType` | 감지 |
|---|---|
| `AMOUNT` | 금액 뒤 조사(을/를/은/는/이/가 등) 포함 숫자+원/만원/억원 |
| `DATE_OR_DEADLINE` | 날짜·기한 표현 |
| `LEGAL` | "법적으로"·"위법"·"소송" 등 |
| `TAX` | "세법상"·"부가세"·"종합소득세" 등 |
| `SUPPORT_PROGRAM` / `ELIGIBILITY` | 지원사업·자격 언급 |

`is_overconfident(text)`: "지원 가능"·"수령 확정" 등 과신 표현 차단
(CLAUDE.md: "추천"·"지원 가능" 대신 "검토 대상"·"추가 확인 필요").

## 개인정보·비밀값 차단 (`guardrails.py`)

`ensure_no_sensitive_text(values)`가 4개 패턴을 막는다: 주민번호 형태, 사업자등록번호
(하이픈 있는 형태만: `000-00-00000`), Bearer 토큰, API 키(`sk-`/`pk-` 접두).
`resolve_evidence_aliases`는 evidence_ref가 실제 제공된 근거에서 왔는지 확인한다.

## 상태 전이 차단 (`schemas.py`의 validator)

- `restoration_status`는 `restoration_scope`가 확정돼야만 `UNKNOWN`을 벗어난다
- `CONFIRMED` fact는 evidence_refs 1개 이상 필수, `UNKNOWN`은 evidence 있으면 오류
- SET은 `CONFIRMED`+값 필수, CLEAR는 `UNKNOWN`+`value=null` 필수
- 충돌 확인 재검증: `snapshot_id` + 기존값(타입까지) 불일치 시 `StaleConfirmationError`
  (`enrichment.py`) — 낙관적 락(`case_version`) 없이 이 두 가지로 덮어쓰기를 막는다

코드: [`claim_safety.py`](../../backend/app/agent/claim_safety.py),
[`guardrails.py`](../../backend/app/agent/guardrails.py),
[`projection.py`](../../backend/app/agent/projection.py)(개인정보 필터),
[`enrichment.py`](../../backend/app/agent/enrichment.py)(충돌 재검증),
검증자 정의: [`schemas.py`](../../backend/app/agent/schemas.py).
