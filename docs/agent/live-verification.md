# 실제 API 호출·DB 조회 검증 기록

> 소유: AI · 확인일: 2026-09-20 KST. §2~3은 최초 20:50–20:54 관측이며 후속 검증은 §7~10에 기록한다.
> 기준: [`schema_table.md`](../schema/schema_table.md). 환경변수 갱신 후 새 프로세스에서 다시 읽었다.

## 1. 현재 결론

**LLM·임베딩·공식기관 API 연결과 Langfuse 기록 저장은 확인했다. 전체 Agent 판단과 Case DB 저장은 미검증이다.**
실제 MySQL은 연결되지만 Case·절차·지원사업 데이터가 없고, 기준 스키마의 일부 구조도 빠져 있다.
현재 작업 브랜치에는 BE API에서 Agent를 호출하고 결과를 저장하는 경로가 연결되지 않았다.

사용자의 더미 데이터 테스트 금지 지시 이후에는 pytest·mock·합성 Case를 실행하지 않았다.
실제 공식 문서를 API 입력으로 사용했으며, 검수자·실제 Case·절차 ID·확인 사실을 만들어 넣지 않았다.
이 문서의 API 호출은 Case 실행을 대신한 결과가 아니라 각 외부 연결의 실제 확인 결과다.
현재까지 추가로 확인한 Vault 생성·재읽기는 §9, Chroma 저장·검색은 §10을 본다.
작업 재개 조건과 임시 자료 보존 범위는 [handoff.md](./handoff.md)에 있다.

## 2. 최초 실제 호출 결과 (후속 Vault·Chroma 확인은 §9~10)

| 대상 | 실제 입력·방법 | 결과 | 확인하지 않은 범위 |
|---|---|---|---|
| 절차 원문 수집 | `app.agent.procedure_tool.refresh`로 생활법령정보 2건·국민연금공단 1건 GET | 모두 HTTP 200, 공식 문서 3건, 2.910초 | 사람 검수, DB 절차 적용 조건·선후 관계 |
| 기업마당 지원공고 | `app.agent.support_agent.refresh` 및 점포철거비 공고 API 직접 조회 | refresh 공고 7건, 0.993초. 별도 상태 확인 HTTP 200, 후보 1건, 0.230초 | 자격 규칙 작성·검수. 실제 서비스 후보는 0건 |
| 공용 LLM 설정 | 방금 받은 국민연금공단 원문에서 문장을 그대로 추출, 실제 `StructuredLLMClient` 호출 | 갱신 후 HTTP 200, 응답 schema 및 원문 부분문자열 검증 통과, 1.752초 | 정보분석·지원금·Review Agent의 실제 Case 실행 |
| Supervisor LLM 설정 | 같은 공식 원문으로 별도 설정의 `StructuredLLMClient` 호출 | HTTP 200, 응답 schema 및 원문 부분문자열 검증 통과, 2.300초 | Supervisor의 Blocker·Next Action 판단 및 Graph 실행 |
| 임베딩 | 방금 받은 공식 식품영업 폐업 문서 발췌 900자, 실제 embedding API 1회 | HTTP 200, 유한한 숫자 벡터 1개·1,536차원, 3.802초 | Chroma 인덱스·검색, S3 원문 연결, A8 완료 |
| Langfuse 인증 | 실제 프로젝트 API 조회 | HTTP 200, 인증 성공, 0.872초 | 비용·Review 반송률 대시보드 |
| Langfuse 기록 저장 | 위 실제 LLM 호출 2건의 metadata를 기존 `LangfuseTraceSink`로 전송 후 observations API 재조회 | HTTP 200, 해당 실행의 공용·Supervisor 관측 각 1건, 두 건 모두 token usage 확인, 재조회 1.364초 | Case 판단·Evidence의 MySQL 저장 |

LLM 호출은 각각 실제 HTTP 시도 1회, retry 0회, timeout 40초로 제한했다.
공용 LLM은 **환경변수 갱신 전 첫 호출에서는 HTTP 200이어도 원문 일치 검증에 실패**했다.
갱신 후에는 원문 공백·문장부호 보존을 명시한 요청으로 재호출했고 통과했다.
설정과 요청 문구가 함께 달라졌으므로 개선 원인을 환경변수 변경 하나로 단정하지 않는다.
두 번의 성공만으로 판단 품질·가용성·가드레일 전체를 보장하지 않는다.

LLM 및 Langfuse에 실제 사업자·계약서·Case 정보를 보내지 않았다. LLM/embedding 입력은 공개된
공식 원문이며, Langfuse에는 실제 호출의 모델·상태·지연·token 수 등 metadata만 보냈다.
재조회도 input/output 필드를 요청하지 않았다. 원문 후보의 미검수 상태를 변경하지 않았다.

## 3. 환경변수 갱신 후 실제 MySQL

2026-09-20 **20:52:07 KST**에 새로 읽은 `DATABASE_URL`로 접속했다.
MySQL **8.0.46**, 실제 테이블 **11개**이며 metadata와 다음 건수만 읽었다.

| 실제 테이블 | 행 수 |
|---|---:|
| `case` | 0 |
| `procedure_step` | 0 |
| `support_item` | 0 |
| `case_history` | 0 |

기준 스키마 대비 없는 테이블 6개:

- `case_field_history`
- `conflict_reference`
- `decision_record`
- `evidence`
- `evidence_lineage`
- `support_match`

없는 컬럼 8개:

| 테이블 | 컬럼 |
|---|---|
| `case` | `case_version` |
| `procedure_step` | `step_name`, `utterance_aliases`, `registry_version`, `deprecated_at`, `replaced_by_procedure_step_id` |
| `support_item` | `catalog_version`, `external_notice_id` |

enum도 차이가 있다. 실제 `case.restoration_status`에는 기준의 `UNKNOWN`이 없고,
`support_item_application.application_status`에는 이전의
`NOT_CHECKED/ELIGIBLE/NOT_ELIGIBLE`이 남아 있다. 물리 기준을 실제 DB에 맞춰 낮추지 않고,
현행 `schema_table.md`에 맞추는 BE migration·통합 작업으로 건의한다.

DB 조회는 읽기 전용 transaction과 metadata/count로 수행했다. migration·초기화·쓰기·더미 시드는
실행하지 않았다. 연결된 DB에 대한 확인이며 다른 서버의 DB까지 조사했다는 뜻은 아니다.

## 4. 전체 실행·저장이 막힌 지점

현재 환경에서 BE API 주소·Case 지정 설정은 없고 로컬 8000·8080 포트도 연결되지 않는다.
현재 DB의 Case도 0건이므로 실제 Case 요청 JSON을 export할 수 없었다.

`origin/feature/case-service`의 `to_agent_case_snapshot()`은 아직 `NotImplementedError`다.
`origin/feature/validator`에는 DB를 초기화하는 시작 경로가 있어 기존 DB에 실행하지 않았다.
BE 브랜치를 AI가 임의 병합하거나 DB 초기화로 연동 문제를 우회하지 않았다.

아직 실행·검증하지 못한 것은 다음과 같다.

- 실제 Case → 정보분석 → Supervisor → 필수 Review → 가드레일 전체 경로
- 실제 절차 시드의 필요 조건·선후 관계 조회와 지원금 자격 규칙 비교
- Review 통과 결과의 Case·판단·Evidence·History 원자 저장과 재조회
- 충돌 선택·version 충돌·재계획 실패 때 실제 API 응답과 DB 상태
- 검수 Wiki HIT→조건 비교→Review, 검수 corpus의 운영 RAG 연결, S3 원문 최신성 확인

미검수 공고의 별도 Chroma 저장·검색은 이후 §10에서 확인했다. 운영 Graph 연결과 구분한다.

다음 입력은 **실행 중인 BE API와 실제 Case 식별자**, 또는 **소유권·비식별 처리를 마친 실제
`AgentGraphInput` 및 `KnownProcedureStep[]` export 파일**이다. export만 있으면 Agent 실행은
가능하지만 DB 저장은 BE 저장 함수·API 연결 후 확인해야 한다.
필요한 BE 작업과 협의 항목은 [`be-requests.md`](./be-requests.md),
번호별 상태는 [`implementation-status.md`](./implementation-status.md)에 구분했다.

## 5. 실제 입력을 위한 변경

`backend/app/agent/cli.py`에서 합성 Case와 demo 지원사업 fallback을 제거했다.
실제 요청 파일과 절차 registry 파일을 필수로 받고, 검수된 지원사업이 0건이면 그대로 유지한다.
파일 누락·손상은 실패 처리한다. 결과는 `--output`으로 기존 파일을 덮어쓰지 않는 `0600` 파일에
저장할 수 있다. 입력당 4 MiB 제한과 실행별 호출·시간 상한을 적용한다.

변경 CLI에는 실제 Case를 아직 투입하지 못했다. 확인한 것은 Ruff·소스 compile·`--help`이며,
실제 Graph 실행·저장 성공으로 표시하지 않는다. 실행 방법은
[`standalone-runtime.md`](./standalone-runtime.md)에 있다.

## 6. 로컬 확인 자료

다음 파일은 `/tmp/reborn-live-refresh-mvb_sb3n/`에 있다. 디렉터리 권한은 `0700`,
JSON 파일은 `0600`이며 비밀값·DB host·사용자 Case 본문을 기록하지 않았다.
임시 자료이므로 배포 산출물이나 영구 감사 저장소로 사용하지 않는다.

- `summary.json`: 공식 절차·지원공고 실제 refresh 결과
- `procedures.draft.json`, `support.draft.json`: 실제 수집 원문 후보, 전부 미검수
- `support.status-verification.json`: 기업마당 실제 HTTP 상태
- `llm-api-report.json`: 환경변수 갱신 전 실제 LLM 호출, 원문 일치 실패 포함
- `llm-updated-env-report.json`: 갱신 후 실제 LLM 호출과 검증 결과
- `embedding-langfuse-live-summary.json`: 임베딩·Langfuse 인증 결과
- `langfuse-saved-observations-summary.json`: 실제 LLM 관측 2건 저장 재조회
- `db-verification.json`: 갱신된 설정의 실제 DB metadata·건수

## 7. 후속 작업 — 실제 금액 표현과 Review 관측

사용자의 다음 단계 진행 요청 후 `git fetch origin`으로 다시 확인했다. BE 브랜치 HEAD는
변경되지 않았고, Case adapter의 `NotImplementedError`와 Agent/Case API·migration·seed 부재도
그대로였다. 따라서 BE·DB를 임의 변경하지 않고 AI 내부 작업을 진행했다.

**금액 가드레일:** [중소벤처기업부 공식 보도자료](https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1058272&cbIdx=86)를
직접 GET해 HTTP 200을 확인했다. 실제 본문의 `30만원을`, `77.7억원을`은 기존 금액 정규식에서
미탐지됐다. `claim_safety.py`의 금액 뒤 경계를 한국어 조사까지 인식하도록 수정한 후,
받은 원문에서 그대로 뽑은 두 표현 모두 `AMOUNT` 및 공식 근거 필수로 분류됨을 확인했다.
과거 보도자료를 문법 검증에 사용한 것이며 현행 지원 한도·자격 정보로 사용하거나 catalog에 넣지 않았다.

공식 발췌를 변조하거나 Case를 만들지 않았다. 실제 원문 발췌로 기존 미탐지 회귀 기대값도
교체했지만 pytest·mock·합성 fixture suite는 실행하지 않았다.
21:02:34 KST 확인 자료는 `/tmp/reborn-live-guardrail-lsalqaba/after.json`이며,
동일 디렉터리에 `source.txt`, `before.json`을 보관했다(디렉터리 `0700`, 파일 `0600`).
이 결과는 두 실제 표현에 대한 분류 확인이며 출력·개인정보 가드레일 전체 검증이 아니다.

**A9 관측:** `graph.py`·`tracing.py`에 Review 판정과 실행별 판정 수·반송 수·실제로 시작한
재작업 라운드 수를 추가했다. 원문이나 키를 포함하지 않는 선택 metadata다.
집계 의미는 [`runtime-limits.md`](./runtime-limits.md) §3에 정리했다.
실제 Case가 없으므로 이 변경은 정적 검사만 수행했으며, 만들어낸 Review 이벤트를
Langfuse로 보내거나 실제 반송률을 측정했다고 주장하지 않는다.

## 8. develop 최신화 후 A7 연결

`git fetch origin develop:develop`로 로컬 `develop`을 `1a11cf1`에서 원격 최신 `e360ab3`까지
fast-forward했다. `git merge --ff-only develop`은 현재 기능 브랜치가 이미 해당 변경을 포함한다고
확인했다. 양쪽 develop 차이는 0이며 기존 수정과 사용자의 환경변수 파일을 보존했다.
BE의 별도 feature 브랜치를 임의 병합하거나 DB migration을 실행하지 않았다.

A7의 ID·UUID exact lookup을 `support_agent/wiki/`, `SupportAgent`, `build_runtime`,
CLI의 `--support-wiki`에 선택적으로 연결했다. 조회한 파일·식별자·기존 검수 조건·공식 근거를
확인하고, 자료가 없으면 기존 catalog의 규칙으로 대체하지 않는다. 일부 누락도 `PARTIAL`로 남기며,
조회 자체에 남은 실행 시간을 적용한다. 파일은 읽기 전용이고 노트·검수자를 자동 생성하지 않는다.

**이 단계 당시에는 실제 Wiki 폴더·검수 노트와 BE ID·UUID 매핑이 없었다.** 이후 사용자 요청으로
§9의 프로젝트 Vault를 만들었으며, 사람 검수·DB 매핑은 현재도 남아 있다. 공식 API 공고 7건은
미검수이며 수집기 내부 식별자는 DB 매핑이 아니다. 따라서 HIT/MISS를 만들기 위한 더미 노트를
생성하거나 pytest·mock으로 실동작을 대체하지 않았다. 신규 경로는 Ruff·소스 compile·실제 CLI
`--help`와 독립 코드 검토 범위로 확인하며, 실제 Wiki→비교→Review 실행은 미검증으로 유지한다.
노트 연결 요건과 현재 제한은 [`support-wiki.md`](./support-wiki.md)에 있다.

## 9. 실제 공고로 프로젝트 Obsidian Vault 생성

사용자가 기존 Wiki가 없다고 알려주고 프로젝트에 생성하도록 요청했다.
[`obsidian/`](./obsidian/README.md)에 Vault 설정, 시작 문서, 공식 폐업 절차 진입점,
공고 목록과 검수 안내를 추가했다. 데스크톱 Obsidian UI를 실행해 확인한 것은 아니다.

2026-09-20 **22:02:30 KST**에 기업마당 API를 새로 실제 호출했다.

| 검색어 | HTTP | 응답 후보 수 | API 결과의 `truncated` |
|---|---|---|---|
| 폐업 | 200 | 8 | true |
| 점포철거비 | 200 | 1 | false |
| 폐업 + 재창업 | 200 | 8 | true |

17건의 출현 중 기존 폐업 관련 제목 필터로 3건을 제외하고, 공고 ID로 중복을 제거한
**7개 실제 공고**를 `지원사업/미검수/<공고 ID>.md`로 생성했다.
`support_agent.refresh`가 생성한 로컬 번호·UUID를 가져오지 않았고, DB ID·UUID·검수자·
자격조건을 새로 만들지 않았다. 노트의 최신성은 모두 `UNKNOWN`, 검수 완료는 0건이다.
API 필드를 정규화한 데이터와 그 hash이며, 공고 본문·PDF 전체를 수집한 결과는 아니다.

실제 동작 확인:

- 작성한 7개 노트를 `read_discovery_note()`로 다시 읽어 원본 Candidate와 Evidence가 모두 같은지 확인했다.
- 동일한 실제 수집 결과로 다시 실행해 `created=0`, `unchanged=7`, `skipped=7`, `filtered_out=3`을 확인했다.
  중복 공고의 수집 시각이 달라 `skipped`가 발생하며, 기존 7개 파일의 SHA-256은 모두 그대로였다.
- 신규 노트 7개의 파일 권한은 `0600`이었다. 코드 검사에는 Ruff와 소스 compile을 사용했다.
- 저장 도중 불완전한 최종 파일이 남지 않도록 임시파일 완성 후 게시하도록 보완했다.
  동일한 실제 API 자료로 별도 임시 폴더에 7건을 새로 저장하고 재실행해 원자료·프로젝트 노트와
  모두 일치하며 임시파일이 남지 않는 것을 확인했다. 디스크 장애 주입 검증은 하지 않았다.
- 더미 노트·합성 Case·가짜 검수자를 만들지 않았고 pytest·mock·DB 쓰기를 실행하지 않았다.

확인 자료는 `/tmp/reborn-obsidian-source-mpfa0qrl/`의 `discovery-1.json`부터 `discovery-3.json`,
`summary.json`, `vault-verification.json`, `atomic-publication-verification.json`에 있다
(디렉터리 `0700`, 파일 `0600`).
실제 공고와 근거는 프로젝트 노트에도 보존되어 있다.

**실제 공고를 저장하고 다시 읽는 동작은 확인했다.** 사람 검수와 BE 실제 ID·UUID 매핑이
없으므로 운영 Wiki HIT, Case 조건 비교·Review 및 BE 테이블 저장 완료를 뜻하지 않는다.

## 10. A8 오프라인 Chroma 색인·검색

실제 Vault의 미검수 공고 7건을 그대로 읽어 **35개 API 필드 구간, 총 2,305자**로 구성했다.
합성 문서·Case·검수자를 추가하지 않았고 각 구간은 실제 필드의 정확한 문자 위치를 가진다.

첫 임베딩 API 호출은 HTTP 200 응답의 모델명이 요청과 달라 검증에서 거부됐다.
추가 실제 호출로 요청 `openai/text-embedding-3-small`, 응답 `text-embedding-3-small`,
1,536차원 유한수 벡터임을 확인했다. 이 실제 alias 쌍만 허용하고 다른 모델은 정확 일치를
유지하도록 수정했다. 이때의 실패·진단 자료는 `/tmp/reborn-live-retrieval-8ahpalju/`에 있다.

수정 후 실제 실행 결과:

| 확인 항목 | 결과 |
|---|---|
| 임베딩 생성 | 32개·3개 두 요청 성공, 응답은 모두 HTTP 200 검증 통과 |
| Chroma 저장 | `reborn_support_discovery_v1`에 35개 벡터·API 문구·출처 metadata 저장 |
| 별도 프로세스 조회 | 실제 `rag.cli search`에서 기존 인덱스를 다시 열어 검색 결과 5개 저장 |
| 실제 제목 7개 검색 | 별도 실제 임베딩 요청으로 7개 query 벡터 생성, 각각 해당 공고가 1순위 |
| 공고별 필터 | 각 실제 공고 ID로 필터링해 해당 공고의 5개 구간만 반환됨 확인 |
| 검색 근거 대조 | 반환한 모든 구간의 텍스트·원필드 위치·Evidence 참조가 실제 원자료와 일치 |
| 유지한 상태 | `UNREVIEWED`, `UNKNOWN`, S3·정책 최신성 확인 false |

수정 후 검증에서 임베딩 API 성공 호출은 색인 2회, 별도 CLI 검색 1회, 제목 7개 배치 1회다.
이는 **정확한 제목을 이용한 작은 실제 자료 동작 확인**이며 일반 질문의 검색 품질·recall,
이전 공고의 false positive, 법률·지원자격 판단 품질을 평가한 결과는 아니다.

성공 자료는 `/tmp/reborn-live-retrieval-q6u7plbd/`에 있다.

- `index/`: 실제 Chroma 영속 자료와 출처·구간·요청/응답 모델·차원의 `corpus.json`
- `build-report.json`: 색인 건수·차원·실제 요청 수
- `hope-return-search.json`: 별도 프로세스 CLI 검색 결과와 공식 출처
- `retrieval-verification.json`: 7개 실제 제목 검색·필터·출처 대조 결과

새 manifest·검색 결과는 기존 파일을 덮어쓰지 않고 완성 후 게시한다. 동기 연산 뒤에도
deadline을 검사해 시간 초과 자료를 성공 결과로 게시하지 않도록 했다.
Chroma의 동기 I/O 강제 종료나 네트워크 장애 주입은 검증하지 않았다.
Ruff·format·소스 compile·CLI 도움말을 확인했고 pytest·mock·더미 테스트는 실행하지 않았다.

현재 S3 설정과 실제 객체 매핑, 사람 검수·BE ID/UUID 매핑이 없다. 따라서 검수 corpus·S3
원문 확인·Wiki miss의 운영 fallback은 미완료이며 Graph의 `rag_used=false`를 유지한다.
서비스 MySQL 테이블·BE·FE는 수정하지 않았다. 실제 실행 방법과 경계는
[`support-retrieval.md`](./support-retrieval.md)에 정리했다.

## 11. 2026-09-21 미커밋 작업 보존과 AI 단독 마감

### 실제로 한 것

BE 연결 상태는 이 날 다시 확인하지 않았다. 외부 API·DB·LLM 호출도 하지 않았다.
이번 작업은 **네트워크를 부르지 않는 범위**에서만 진행했다.

| 대상 | 확인 방법 | 결과 |
|---|---|---|
| 미커밋 작업 보존 | 소유 범위별로 나눠 8개 커밋 | `.env.example`은 모든 커밋에서 제외. 신규 코드 1,927줄과 Vault 15개 파일 포함 |
| 정적 검사 | `ruff check backend/app/agent`, `ruff format --check`, `git diff --check` | 통과 |
| CLI 기동 | `cli`, `rag.cli`, `wiki.import_notices`의 `--help` | 3개 모두 정상 종료 |
| 되살린 검사 | `pytest backend/tests/agent -m real_data -q` | **77 passed, 541 deselected** |
| 사업자등록번호 패턴 오탐 | 저장소 공식 자료 전수 스캔 | 좁은 패턴 0건 / 넓은 패턴 11건(전부 근거 digest·공식 URL id) |

### 코드에서 고친 것

- **검수 소진 실패가 다음 행동을 못 내던 문제**(A6): `requested_field_paths`가 빈 목록으로
  고정돼 있었다. 실패 시점의 source 결과에서 막혀 있던 Case 필드를 파생하도록 바꿨다.
  Review 결과에서는 파생하지 않는다 — `ReviewIssue.target_path`는 초안 내부 JSON Pointer이고
  이 필드는 Case 필드 키여서 대응 관계가 없다. 스키마 필드 추가나 `message_code` 변경은
  하지 않았다(C5 협의 대상).
- **사업자등록번호 가드레일**: 하이픈만 인정하는 좁은 패턴을 추가했다. 넓히지 않은 근거는
  위 표의 실측이며 [`open-decisions.md`](./open-decisions.md) OD-08에 남겼다.
- **죽은 코드 제거**: `fixtures.py` 289줄. 합성 Case·지원사업을 만드는 모듈인데 CLI의 더미
  대체를 없애면서 호출자가 0곳이 됐다. 이 파일을 가리키던 문서 링크 3곳도 정리했다.
- **끝난 일이 남은 일처럼 보이던 메모**: `llm.py`의 실행별 예산 분리 TODO. `call_budget_scope`와
  `ScopedCallBudget`으로 이미 해결돼 있었다.

### 검증하지 못한 것 (그대로 유지)

- 실제 Case → 정보분석 → Supervisor → 필수 Review → 가드레일 전체 경로
- A6 파생 결과의 실제 Case 관측. `source_results`가 없는 예외 경로가 기존과 같이 빈 목록을
  내는 것만 확인했다
- Review 결과의 Case·판단·Evidence·History 저장과 재조회
- Wiki HIT → 조건 비교 → Review. 검수완료 노트는 여전히 0건이다
- 실제 반송률·비용 집계. 가짜 Review 이벤트를 만들지 않았다

`real_data` 통과는 위 표의 범위만 뜻한다. 실제 Case 실행 성공이나 DB 저장 성공으로 옮겨
적지 않는다. 멈춰 둔 541개는 합성 Case를 만들기 때문이며, BE 연결 뒤 실제 입력으로
되살릴 수 있도록 지우지 않았다.

## 12. 2026-09-21 실제 API 재수집

사용자 지시로 "API로 받아올 수 있는 것은 받아온다"를 실행했다. 외부 공식 API를 실제로
호출했고, 서비스 DB에는 쓰지 않았다. 검수 상태는 하나도 올리지 않았다.

### 지원사업 공고 — 기업마당 공개 API

| 항목 | 결과 |
|---|---|
| 요청 | 검색어 10세트, **모두 HTTP 200** |
| 원시 후보 | 36건(중복 포함) |
| 보존 | **9건** (기존 7 + 신규 2). 제목 필터와 외부 공고 ID 중복 제거 후 |
| 신규 | `PBLN_000000000117673` 희망리턴패키지 특화취업지원, `PBLN_000000000126649` [강원] 재기 지원사업 |
| Vault | created 2, filtered_out 5, skipped 29, unchanged 0 — 기존 7건 노트는 그대로 |
| 검수 | 9건 전부 미검수. 검수완료 0건, 서비스 후보 0건 |

검색어를 3개에서 10개로 늘렸다. 늘린 7개는 지어낸 말이 아니라 **이미 수집한 공고가 자기
payload에 달고 있는 해시태그**다(`사업정리`, `폐업소상공인`, `폐업예정소상공인`, `폐업정리`,
`점포철거`, `원상복구`, `희망리턴패키지`).

처음에는 검색어당 8건만 요청해 `폐업` 11건 중 8건, `폐업 + 재창업` 13건 중 8건만 받고
있었다. API가 알려준 실제 보유 건수(`provider_total_count`)를 보고 요청 건수를 20으로 올려
재호출했고, **열 검색어 모두 `truncated=false`** 가 됐다. 이 검색어들로 API가 가진 공고는
남김없이 받은 상태다. 페이지 넘기기는 여전히 미구현이며, 지금은 필요하지 않다.

중복 제거 후 고유 13건 중 제목 필터를 통과한 9건을 보존했다. 제외된 4건은 재창업 지원,
폐업 예방, 통합 안내, 그리고 영세개인사업자 체납액 징수특례다. 마지막 건은 폐업 절차와
닿아 있으나 지원사업이 아니라 세무 제도라 **사람이 판단할 안건**으로 목록 문서에 남겼다.
AI가 제목 필터를 임의로 넓히지 않았다.

### 수집이 끊기던 원인과 수정

`폐업소상공인`·`폐업예정소상공인`·`희망리턴패키지` 세 검색어가 `BIZINFO_URL_INVALID`로
매번 실패하고 있었다. 실제 응답을 받아 한 건씩 정규화를 재현해 원인을 특정했다.

- 원인: `PBLN_000000000117673`의 신청 홈페이지 주소가 `https://www.sbiz24.kr/#/pbanc/591`
  형태인데, 주소 검사가 `#`(fragment)를 무조건 거부했다. 소상공인24의 정상 주소다.
- 영향: 그 한 건 때문에 검색어 전체가 죽었다.
- 수정: **기관 자체 신청 주소에 한해** `#`를 허용하고 값을 그대로 보존한다. `#`를 잘라내면
  사용자를 공고가 아니라 사이트 첫 화면으로 보내게 된다. 기업마당 자체 주소는 형식이 정해져
  있으므로 그대로 엄격하게 둔다. 검사가 어댑터와 모델 두 겹이라 양쪽을 맞췄다.
- 수정 후 재호출: 실패 0건, 9건 수집. 해당 주소가 노트에 그대로 보존된 것을 확인했다.

### 절차 원문 — 찾기쉬운 생활법령정보·국민연금공단

3건 → **4건**. 신규는 `LEASE_RESTORATION_SCOPE`(임차인의 권리·의무)이며, 절차 노트가
"`CONFIRM_RESTORATION_SCOPE` — 해당 공식 원문 레코드 없음"이라고 적어 둔 자리를 메운다.
받아온 본문에 "임차인은 차임지급의무, 임차물반환의무, 원상회복의무 등의 의무를 집니다"가
들어 있다.

**재수집에서 관측한 원문 변화** — 기존 스냅샷은 2026-09-19 수집분이다.

| record_id | 09-19 발췌 | 09-21 발췌 | content_hash |
|---|---:|---:|---|
| `TAX_BUSINESS_CLOSURE` | 1,996 | 2,425 | 같음 |
| `FOOD_SERVICE_CLOSURE` | 1,136 | 1,873 | **다름** |
| `WORKPLACE_INSURANCE_CLOSURE` | 406 | 4,000 | **다름** |
| `LEASE_RESTORATION_SCOPE` | — | 3,529 | 신규 |

이틀 만에 2건의 원문이 달라졌고, 국민연금은 이전 수집이 본문을 거의 못 가져온 상태였다.
`content_hash`는 원문 전체의 해시이고 발췌는 질의에 맞는 구간이라 둘은 따로 움직인다.
이 관측은 [`open-decisions.md`](./open-decisions.md) OD-02(절차 스냅샷 갱신 주기)에 근거로 남겼다.

4건 전부 `reviewed_by`/`reviewed_at`이 null이다. 갱신 명령이 검수 상태를 올리지 못하도록
코드가 강제한다.

### 확인하지 않은 것

- 공고 본문·첨부파일(HWP/PDF)은 **받지 않았다.** 파일명과 URL은 API 응답에 이미 있지만
  바이트를 내려받는 경로는 구현하지 않았다. 보존·재배포 승인이 미결이다.
- 받아온 자료의 **내용이 맞는지**는 판단하지 않았다. 검수는 사람 몫이다.
- 지원 자격·금액·기한을 읽어 조건으로 만들지 않았다. 서비스 후보는 여전히 0건이다.
- 실제 Case 실행·DB 저장은 이번에도 하지 않았다. 여전히 미검증이다.

## 13. 2026-09-21 Agent 전체 경로 첫 실행

**처음으로 Graph를 끝까지 돌렸다.** `REVIEWED_PLAN`까지 도달했고 Review가 PASS를 냈다.

### 입력이 무엇이었나 (중요)

실제 Case는 여전히 없다. DB의 `case`는 0행이고 BE Case API는 develop에 병합되지 않았다.
그래서 **Case 골격은 만든 값**이고, 그 위에서 도는 **지식은 전부 실제 자료**다.

| 입력 | 출처 |
|---|---|
| 절차 단계 4개 | 실제 수집한 절차 스냅샷의 `step_code`. `procedure_step_id`는 **실제 DB 값이 아니다**(DB는 0행) |
| 절차 원문 | 2026-09-21 실제 수집분 4건 |
| 지원사업 catalog | 실제 수집 9건. 전부 미검수라 서비스 후보 0건(`0 reviewed / 9 pending`) |
| Case 사실·근거 | **비어 있음.** 새로 만든 Case로 두었다 |
| 사용자 발화 | **만든 문장.** 카페 정리, 원상복구 요구, 직원 2명 |
| `case_version` | `null` — 팀 확인으로 이 컬럼은 구현하지 않는다 |

만든 값은 Case 골격과 발화 두 가지뿐이고, 판단에 쓰인 지식은 실제다. 이 실행은 **경로가
도는지**를 본 것이지 판단 품질을 평가한 것이 아니다.

### 무엇이 나왔나

성공한 실행의 판단은 `NEEDS_MORE_INFO`였다.

```
blocker_code : MISSING_PLANNED_CLOSURE_DATE
title        : 폐업 예정일 확인 필요
description  : 정확한 폐업 예정일이 없어 폐업 절차 확인이 진행되지 않았습니다.
evidence_refs: procedure:reviewed:ee62f36e-...
```

Review는 첫 시도에 PASS했고 `subject_digest`가 일치했다. source 결과 3건(정보분석·절차조회·
지원금)이 모두 실행됐다.

### 찾아낸 결함 두 개와 수정

**1. 업종을 영원히 추출할 수 없었다.** `_FACT_VALUE_CUES`에 `(BUSINESS_TYPE, "CAFE")`가
있었는데 `"CAFE"`라는 정규값은 스키마 어디에도 없다 — `schema_table.md`는 VARCHAR에 예시가
한글 "카페"이고 실제 DB도 `varchar(50)`이다. 모델이 무슨 값을 내든 원문의 "카페"가 그 유령
값에 매칭돼 거부됐고, 올바른 STRING 분기에 도달하지 못했다. 항목을 지웠다.

**2. 재시도가 거부 사유를 알려주지 않았다.** 가드레일은 옳게 막고 있었다 — "임대차 계약
기간이 아직 남았는데"에는 유상/무상이 없으므로 `lease_status=LEASED_PAID`는 거부가 맞다.
문제는 fact 하나가 거부되면 draft 전체가 버려지는데 재시도 프롬프트가 일반 문구만 줘서
모델이 세 번 다 같은 값을 냈다는 점이다. 거부된 **필드 이름만**(값·원문 제외) 다음 시도에
전달하도록 고쳤다.

### 실측

| 구간 | 정보분석 통과 | `REVIEWED_PLAN` |
|---|---|---|
| 수정 전 | 9회 중 1회 | 1회 |
| 수정 후 | 4회 중 4회 | 3회 |

실행 시간은 29~97초. 남은 1회는 `REVIEW_RETRY_EXHAUSTED`이며 정보분석은 통과했다.

### A6 파생의 실전 확인

그 `REVIEW_RETRY_EXHAUSTED` 실행에서 2026-09-21에 만든 파생이 실제로 동작했다.

```
recovery_action_code   : RESUBMIT_INPUT
requested_field_paths  : ['lease_status', 'restoration_status',
                          'restoration_scope', 'planned_closure_date']
```

이전에는 각각 `NONE`과 `[]`였다. 정적 확인만 했던 변경이 실제 실행에서 확인됐고, 순서도
`CASE_FIELD_SPECS` 기준으로 정렬됐다.

### 여전히 확인하지 못한 것

- **실제 Case.** 위 Case 골격과 발화는 만든 값이다. BE Case API와 snapshot adapter가 있어야
  진짜 입력으로 다시 돌릴 수 있다.
- **DB 저장·재조회.** CLI는 저장하지 않는다. `EVIDENCE` 등은 아직 실제 DB에 없다.
- **추출 품질.** 통과한 실행에서도 모델은 "작은 카페", "직원 2명"을 뽑지 않고 아무 사실도
  제안하지 않았다. 안전한 쪽이지만 Case가 채워지지 않는다.
- **지원금 경로의 실질.** 검수 완료가 0건이라 비교할 대상이 없다.
- **충돌·재계획 경로.** 이번 trigger는 `CASE_CREATED` 하나다.
