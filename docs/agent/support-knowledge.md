# 지원사업 정보를 어디서 읽는가

> 소유: AI · 기준일: 2026-09-20
>
> 이 문서의 책임: 지원사업 후보를 어떻게 찾고, 무엇을 사람이 채워야 서비스되는지.

## 1. 먼저 보는 결론

- **발견은 자동, 승격은 수동입니다.** 기업마당 공식 API로 폐업 지원 공고를 찾아오지만,
  사람이 자격조건을 써 넣기 전까지는 사용자 Case와 비교되지 않습니다.
- 사용자 요청 경로는 **검수된 카탈로그**, 또는 선택적으로 연결한 **검수 Wiki**를 읽습니다.
  인터넷으로 정책 자료를 자동 갱신하지 않습니다.
- 현재 스냅샷에 실제 공고 **7건**이 들어 있고, **검수된 것은 0건**입니다.
- CLI도 실제 검수 **0건을 그대로 사용**합니다. 데모 카탈로그 fallback은 제거했습니다.
- CLI 입력은 실제 Case·절차 registry export이며, DB 조회·저장은 아직 연결되지 않았습니다.
  실행 방법은 [`standalone-runtime.md`](./standalone-runtime.md), 실제 확인 결과는
  [`live-verification.md`](./live-verification.md)에 있습니다.

## 2. 왜 자동으로 승격하지 않나

기업마당 API가 주는 자격 정보는 이런 모양입니다.

```
대상 : 소상공인
기간 : 예산 소진시까지
기간 : 세부사업별 상이
```

문장입니다. 이걸 코드가 날짜나 참/거짓 조건으로 바꾸면 **누가 대상인지 코드가 정하는 것**이
됩니다. 팀 원칙이 그걸 금지합니다.

> `/CLAUDE.md` — 정책 데이터는 팀이 검수한다 / 조회·검증된 지원사업 항목에 없는
> 사업명이나 조건을 생성하는 코드를 두지 않는다

계약도 같은 말을 합니다. `ReviewedSupportProgram.criteria`는 **최소 1개**를 요구하므로,
조건 없는 항목은 애초에 카탈로그가 될 수 없습니다. 그래서 검수 전 항목은 파일에 남아
있기만 하고 Support Agent에 전달되지 않습니다.

## 3. 요청 경로

```
Graph → Support Agent → 검수된 카탈로그(메모리 조회)
                     → 선택적 Wiki ID·UUID 조회(로컬 파일, 읽기 전용)
                     → 설정된 LLM(비교 결과 표현)
```

카탈로그는 프로세스가 뜰 때 한 번 읽습니다. 비교할 검수 항목이 없고 source 누락도 없으면
`NO_CANDIDATE`로 끝나고 Support의 LLM 호출도 하지 않습니다. 요청한 Wiki 자료를 확보하지 못한
경우에는 빈 결과여도 `PARTIAL/SOURCE_UNAVAILABLE`을 남깁니다. 카탈로그 조회 자체에는
네트워크 호출이 없으며, 비교할 항목이 있을 때의 LLM 호출은 별도입니다.

CLI는 `AGENT_SUPPORT_CATALOG_PATH`의 실제 JSON 파일을 읽습니다. 설정이 없으면 패키지의
`backend/app/agent/support_agent/data/reviewed-support.ko-KR.json`을 읽습니다.
파일 누락·손상은 실행 실패이며, 빈 catalog와 구분합니다. 다른 데이터로 대체하지 않습니다.

실제 Case 분석에는 `--request`의 `AgentGraphInput` JSON과 `--procedure-steps`의
`KnownProcedureStep[]` JSON이 모두 필요합니다. 합성 Case를 자동 생성하지 않습니다.
`--max-llm-calls`로 예산을 지정하고 `--output`으로 새 `0600` 결과 파일을 만들 수 있습니다.
CLI 결과 파일은 DB의 `SUPPORT_MATCH`나 판단·근거 테이블에 저장된 결과가 아닙니다.

## 4. 공고를 찾는 법

**요청 경로가 아닙니다.** 사람이 직접 돌립니다.

```bash
PYTHONPATH=backend backend/.venv/bin/python \
  -m app.agent.support_agent.refresh --out /tmp/support.draft.json
```

기업마당 해시태그로 검색합니다. 쓰는 검색어는 `폐업`, `점포철거비`, `폐업+재창업`이고,
제목에 폐업·철거·재기·사업정리 같은 말이 들어간 공고만 남깁니다. 해시태그만 맞고 무관한
공고(백화점 입점모집 등)가 섞이기 때문입니다.

이미 검수한 항목은 **규칙을 그대로 두고 근거만 갱신**합니다. 다시 돌려도 사람이 한 일이
지워지지 않습니다.

## 5. 사람이 채워야 하는 것

항목마다 이렇게 되어 있습니다.

```json
{
  "program_name": "2026년 희망리턴패키지 원스톱폐업지원 소상공인 모집 공고",
  "discovered_target": "소상공인",          // 공고의 말 그대로. 규칙이 아님
  "discovered_period": "세부사업별 상이",    // 공고의 말 그대로. 날짜가 아님
  "reviewed_by": null,                      // ← 공고를 읽은 사람
  "reviewed_at": null,                      // ← 읽은 시각
  "criteria": [],                           // ← 자격조건
  "related_step_codes": []                  // ← 어느 절차 단계의 지원인가
}
```

1. `detail_url`의 공고 원문을 읽습니다
2. `criteria`에 자격조건을 씁니다 — 현행 `schema_table.md`의 CASE 필드와 AI 계약에서 허용하는 업종·직원수·임대 형태 등만 사용합니다. 지역 등 없는 필드를 추가해 처리하지 않습니다
3. `related_step_codes`에 해당 절차 단계를 적습니다
4. `reviewed_by`, `reviewed_at`을 채웁니다

**읽어봤지만 조건을 쓸 수 없는 경우도 정상입니다.** `reviewed_by`와 `reviewed_at`을 채우고 `criteria`를
비워 두면 그 항목은 계속 서비스되지 않습니다. 코드가 그렇게 강제합니다.

## 6. 현재 스냅샷 (2026-09-20)

기업마당에서 실제로 찾아온 7건입니다. 전부 미검수입니다.

| # | 공고 | 대상 |
|---|---|---|
| 1 | 2026년 희망리턴패키지 원스톱폐업지원 소상공인 모집 공고 | 소상공인 |
| 2 | [서울] 2026년 새 길 여는 폐업지원 사업 모집 공고 | 소상공인 |
| 3 | [전북] 2026년 폐업 소상공인 사업정리 지원사업 공고 | 소상공인 |
| 4 | [전북] 2026년 새출발 재기지원 (휴·폐업 사업주형) | 소상공인 |
| 5 | [경기] 2026년 소상공인 사업정리 지원사업 모집 공고 | 소상공인 |
| 6 | [제주] 소상공인·자영업자 재기지원사업 희망업체 모집 공고 | 소상공인 |
| 7 | [대전] 소상공인·자영업자 재기지원 (폐업정리) 참여자 모집 공고 | 소상공인 |

1번은 Hero Case가 가리키는 **점포철거비 지원**을 포함합니다. 이 공고를 검수하고 조건·공식 근거·실제
지원사업 ID를 연결하는 것이 선행 작업입니다. 실제 Case 입력과 DB 저장 연결이 완료되기 전에는
공고 검수만으로 대표 시나리오 전체가 동작한다고 볼 수 없습니다.

## 7. Wiki·RAG는 어떻게 되나

A7의 선택적 **읽기 전용 Wiki adapter**를 추가했습니다. `support_agent/wiki/`에서
실제 지원사업 ID·UUID 쌍으로 노트를 읽고 기존 `ReviewedSupportEntry` 조건을 검증합니다.
운영 Wiki의 합의된 형식을 대체하지 않는 AI 내부 선택 형식입니다.
자세한 연결 방법·누락 처리·실자료 요건은 [`support-wiki.md`](./support-wiki.md)에 있습니다.

Wiki를 연결하지 않거나 조회할 참조가 없으면 `NOT_REQUESTED`, 검수 자료를 찾으면 `HIT`,
요청한 자료를 확보하지 못하면 `MISS`와 `PARTIAL/SOURCE_UNAVAILABLE`을 남깁니다.
실제 검수 Wiki와 DB 식별자 매핑이 없어 HIT 실행은 아직 확인하지 못했습니다.

프로젝트 Vault는 [`obsidian/`](./obsidian/README.md)에 만들었습니다. 실제 기업마당 API로
수집한 공고 7건을 미검수 노트로 보존하며, 실제 DB 식별자·검수 조건을 임의로 채우지 않습니다.
이 초안은 사용자 요청의 조건 비교에 자동으로 들어가지 않습니다.

**A8의 미검수 공고 오프라인 색인·검색은 구현하고 실자료로 확인했습니다.**
검수 corpus·S3 원문 확인·Wiki miss의 운영 fallback은 남아 있으며 Graph는 `rag_used=false`입니다.
실행 방법과 한계는 [`support-retrieval.md`](./support-retrieval.md)에 있습니다.
공식 근거 검수와 운영 Wiki 연결의 공동 항목은 [`open-decisions.md`](./open-decisions.md) OD-01에서 추적합니다.

## 8. 현재 검증과 과거 기록

기존 단위 테스트와 과거 CLI smoke에서는 합성 catalog를 사용했습니다. 해당 결과는 코드 개발
이력이며 실제 지원사업 적합성이나 사용자 DB 저장 성공을 입증하지 않습니다.

현재 사용자의 지시에 따라 dummy/mock 테스트를 실행하지 않습니다. CLI 전환은 정적 검사와
`--help`까지만 확인했으며, 별도 A8 검색 CLI는 실제 임베딩 API·Chroma 저장·검색까지 확인했습니다.
실제 API 조회·DB 접속·Case 실행·저장 결과는
[`live-verification.md`](./live-verification.md)에서 각각 구분해 기록합니다.

## 9. 저장소 근거

- 카탈로그 정의와 승격 규칙: `backend/app/agent/support_agent/store.py`
- JSON 구현: `backend/app/agent/support_agent/json_store.py`
- 선택적 Wiki 구현: `backend/app/agent/support_agent/wiki/`
- 오프라인 미검수 공고 색인·검색: `backend/app/agent/support_agent/rag/`
- 공고 발견 명령: `backend/app/agent/support_agent/refresh.py`
- 기업마당 API adapter: `backend/app/agent/support_agent/discovery_tool.py`
- 실제 입력 CLI: `backend/app/agent/cli.py`
- 기존 회귀 테스트(현재 재실행하지 않음): `backend/tests/agent/test_support_store.py`
