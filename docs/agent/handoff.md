# Agent 작업 인수인계

> 소유: AI · 작성/점검: 2026-09-21 KST (직전 판 2026-09-20)
> 대상: 현재 작업을 이어받는 개발자·AI. 아래 Git 상태는 작성 시점의 로컬 작업 트리 기준이다.

## 1. 먼저 알아야 할 현재 상태

**Agent 전체와 서비스 DB 저장은 아직 완료되지 않았다.** 코어 실행 구조는 있지만 실제 Case
API → Agent → Review → MySQL 저장 → 재조회 연결은 미검증이다.
실제로 확인한 것은 공식기관·LLM·임베딩 API, Langfuse 관측 저장, MySQL 읽기 전용 조회,
Obsidian 공고 저장·재읽기, 별도 Chroma 색인·검색이다.

| 구분 | 인수인계 상태 |
|---|---|
| AI 내부 코드 완료로 분류한 티켓 | **A1·A2·A3·A5**. 실제 Case 전체 실행 성공을 의미하지 않음 |
| 남은 AI 티켓 | **C4·A4·A6·A7·A8·A9**. 아래 §6의 조건을 충족해야 완료 처리 |
| 공동 협의 | **C1·C5·C6**. 제안 문서는 있지만 외부 계약·저장 방식 공동 확정은 남음 |
| 공식 자료 | 절차 문서 3건, 지원공고 7건. 전부 미검수이며 지원사업 서비스 후보는 0건 |
| A7 | 선택적 Wiki ID·UUID reader 구현. 실제 DB 매핑·사람 검수 후 HIT→비교→Review 확인 필요 |
| A8 | 미검수 공고 7건·35구간을 실제 임베딩 API로 Chroma 저장·검색. 운영 RAG·S3는 미연결 |
| A6 | 2026-09-21에 검수 소진 실패가 `requested_field_paths`를 파생하도록 고침. 외부 실패 응답 형태는 C5 대기 |
| 되살린 검사 | `pytest -m real_data` **77 passed, 541 deselected**. 합성 Case를 만드는 541개는 멈춰 둠 |
| 실제 DB의 마지막 관측 | 2026-09-20 20:52 KST: 11개 테이블, 기준 대비 6개 테이블·8개 컬럼 누락. Case·절차·지원사업·Case 이력 0건 |

티켓별 완료 조건은 [implementation-status.md](./implementation-status.md), 실측과 실패 기록은
[live-verification.md](./live-verification.md)가 상세 기준이다. DB 관측은 당시 연결한 DB의
상태이며 이후 BE 작업이나 다른 서버의 상태를 보장하지 않는다.

## 2. 반드시 유지할 사용자 지시

1. 데이터 기준은 **[docs/schema/schema_table.md](../schema/schema_table.md)** 하나다.
   테이블·컬럼·enum·키·NULL·버전을 AI 편의로 바꾸지 않는다. 필요한 변경은 근거와 영향을
   [be-requests.md](./be-requests.md)에 건의하고 협의한다.
2. AI 담당 코드와 `docs/agent/`에서 작업한다. BE·FE·공유 스키마·의존성 파일을 임의 수정하지 않는다.
   Agent는 SQL·ORM으로 서비스 DB를 직접 읽거나 쓰지 않고 합의된 BE 함수로 연결한다.
3. **더미 데이터·mock·합성 Case 테스트 금지.** 실제 자료·실제 API로 검증한다. 기존 pytest suite에
   합성 데이터가 있으므로 그대로 재실행하지 않는다. 정적 검사·소스 compile·`--help`는 가능하다.
   과거 CLAUDE 문서의 mock 테스트 안내보다 이 세션의 최신 사용자 지시를 우선한다.
4. 실제 Case·DB ID·UUID·사람 검수자·확인 시각·자격조건을 만들어 빈자리를 채우지 않는다.
   수집시각은 사람 검수일·정책 시행일이 아니다. 미검수·불명확한 최신성은 `UNKNOWN`으로 유지한다.
5. 사용자가 갱신한 `.env`·`.env.example`을 보존한다. 키·토큰·DB 주소·계약서·Case 원문을
   문서·로그·PR에 복사하지 않는다. 이번에 갱신한 지식은 공개 공식 공고 자료다.

현재 지침에서 허용되는 작업과 공동 결정이 필요한 항목을 구분한다. AI 내부의 되돌릴 수 있는
작업을 할 때 매번 허락을 다시 요청할 필요는 없다. 외부 계약을 합의된 것으로 꾸미거나,
문서의 건의 내용을 팀에 실제 전달·승인받았다고 기록하지 않는다.

## 3. 브랜치와 미커밋 변경 보존

| 항목 | 작성 시점 값 |
|---|---|
| 작업 브랜치 | `feature/agent-ssot-runtime-and-conflict-replan` |
| HEAD | `380ffa3` (직전 판은 `4498a47`) |
| 로컬 `develop` / `origin/develop` | 둘 다 `e360ab3`, 서로 차이 0 |
| 최신 develop 포함 | 현재 HEAD가 해당 develop을 포함함 |
| 이전 판의 미커밋 작업 | **커밋 완료.** `4498a47` 위에 13개 커밋(이 문서 갱신 포함) |
| 푸시 | **안 함.** 2026-09-20 기준 PR을 더 올리지 않기로 해 로컬에만 있다 |
| 남은 미커밋 | `.env.example` 하나. **사용자 작업이므로 AI가 건드리지 않는다** |

`develop`은 이전에 `1a11cf1 → e360ab3`로 fast-forward했고 마지막 원격 재확인에서도 같았다.
이어받을 때는 먼저 아래 읽기 전용 확인을 한다. 새 upstream 변경이 있으면 작업 트리를 보존하며
반영한다. `reset --hard`, `clean`, 일괄 checkout으로 현재 결과를 지우지 않는다.

커밋은 소유 범위별로 나눴다. 되돌릴 일이 생기면 통째로 말고 해당 커밋만 본다.
`.env.example`은 어느 커밋에도 들어 있지 않다(확인: `git show --name-only <커밋> | grep '^\.env'`).

```bash
git status --short --branch
git rev-parse --short HEAD
git rev-list --left-right --count develop...origin/develop
git merge-base --is-ancestor develop HEAD
```

이전 판에서 미추적이던 `support_agent/wiki/`, `support_agent/rag/`, `docs/agent/obsidian/`와
새 Agent 문서는 모두 커밋됐다. 앞으로도 `git diff`만으로는 새 파일이 보이지 않으므로
`git status --short`로 미추적 항목을 함께 확인한다.
`.env.example` 수정은 사용자 작업이다. 커밋할 때 `git add .`로 섞지 말고 경로를 지정한다.

## 4. 구현을 이어볼 코드와 문서

| 영역 | 이어볼 위치 | 현재 경계 |
|---|---|---|
| Case 허용 필드·추출 | [schemas.py](../../backend/app/agent/schemas.py), [info_agent/agent.py](../../backend/app/agent/info_agent/agent.py) | 임대 형태·복구 범위를 현행 스키마에 맞춤. 스키마에 없는 Case 필드 제거 |
| Graph·관측 | [graph.py](../../backend/app/agent/graph.py), [tracing.py](../../backend/app/agent/tracing.py) | Review 필수, 실행별 예산·판정 집계. 새 Review 집계의 실제 Case 관측은 미검증 |
| BE 주입·실행 | [runtime.py](../../backend/app/agent/runtime.py), [cli.py](../../backend/app/agent/cli.py) | 실제 요청·절차 registry 필요. 선택 `procedure_store`·`support_wiki` 주입. DB 저장 없음 |
| 실제 문장 가드레일 | [claim_safety.py](../../backend/app/agent/claim_safety.py), [guardrails.py](../../backend/app/agent/guardrails.py) | 금액 뒤 조사 누락 2건 수정, 사업자등록번호 패턴 추가(좁은 형태). 전화번호·이메일·주소는 실측 근거로 의도적 제외 — OD-08 |
| 검수 소진 실패 | [graph.py](../../backend/app/agent/graph.py) | `requested_field_paths`를 source 결과에서 파생. 외부 응답 형태는 C5 대기 |
| 되살린 검사 | [conftest.py](../../backend/tests/conftest.py), [test_real_vault_sources.py](../../backend/tests/agent/test_real_vault_sources.py) | `real_data` marker. 합성 Case를 만드는 541개는 멈춘 상태 |
| A7 | [wiki/](../../backend/app/agent/support_agent/wiki/), [support-wiki.md](./support-wiki.md) | 검수 UUID reader와 미검수 공고 import를 분리. 기존 노트 덮어쓰기·자동 검수 없음 |
| A8 | [rag/](../../backend/app/agent/support_agent/rag/), [support-retrieval.md](./support-retrieval.md) | 공개 API 필드의 오프라인 검색만. 검수 catalog·Case Graph·S3에는 미연결 |
| 공식 폐업 절차 | [official-closure-procedure.md](./official-closure-procedure.md) | 공식 출처·조건·미확인 범위. 팀 검수나 DB 시드 발행을 대신하지 않음 |
| 지식 Vault | [obsidian/README.md](./obsidian/README.md) | `docs/agent/obsidian`을 Vault로 열기. 미검수 7건·검수 완료 0건 |
| 공동 계약 | [be-integration-requirements.md](./be-integration-requirements.md), [open-decisions.md](./open-decisions.md) | 내부 DTO와 외부 API·저장 계약을 구분. 결정 전 제안을 확정 계약으로 사용하지 않음 |

`support_agent.refresh`가 로컬 수집용으로 부여한 번호·UUID는 BE의 `SUPPORT_ITEM` 식별자가 아니다.
현재 Vault 수집 노트는 실제 외부 공고 ID로 저장하며, 검수 reader는 실제 DB ID·UUID 쌍을 요구한다.
Chroma chunk ID·corpus digest도 DB ID·catalog version을 대신하지 않는다.

## 5. 실행·검증을 다시 시작하는 방법

### 환경과 정적 확인

저장소 루트에서 작업한다. Python·의존성은 기존 `backend/.venv`와 BE가 관리하는 requirements를
사용한다. 환경변수명·기본값은 [standalone-runtime.md](./standalone-runtime.md), 한도는
[runtime-limits.md](./runtime-limits.md)를 본다. 환경 파일 내용을 출력해 확인하지 않는다.
설정은 저장소 루트의 `.env`에서 읽으며 같은 이름의 프로세스 환경변수가 우선한다.
환경 파일을 갱신했다면 기존 실행 프로세스를 재사용하지 말고 새 프로세스에서 확인한다.

```bash
ruff check backend/app/agent
ruff format --check backend/app/agent/support_agent/wiki backend/app/agent/support_agent/rag
git diff --check
PYTHONPATH=backend backend/.venv/bin/python -m app.agent.cli --help
PYTHONPATH=backend backend/.venv/bin/python -m app.agent.support_agent.wiki.import_notices --help
PYTHONPATH=backend backend/.venv/bin/python -m app.agent.support_agent.rag.cli --help

# 합성 Case를 만들지 않는 검사만. 정의는 backend/tests/conftest.py
backend/.venv/bin/python -m pytest backend/tests/agent -m real_data -q
```

`-m real_data` 없이 전체를 돌리지 않는다. 나머지 541개는 합성 Case를 만들며, 통과해도 실제
동작의 증거가 아니다. 지우지 않은 이유는 BE 연결 뒤 실제 입력으로 되살릴 수 있어서다.

당시 Ruff는 `/home/vasebull/.local/bin/ruff`를 사용했다. PATH에 없으면 그 경로를 확인한다.
도움말은 네트워크 호출·Case 실행 검증이 아니다.

### 실제 공고로 A8 재현

아래는 저장된 실제 공고와 현재 임베딩 API를 쓰는 명령이다. Case나 검수자를 만들지 않는다.
매 실행마다 새 임시 디렉터리를 만들어 기존 인덱스·결과와 충돌하지 않게 한다.
`EMBEDDING_PROXY_URL`·`PROXY_TOKEN`, `OPENAI_EMBEDDING_MODEL` 설정과 설치된 Chroma가 필요하다.
모델 기본값·실행 전제는 [support-retrieval.md](./support-retrieval.md#실행)와 현재 설정 코드를 확인한다.

```bash
REBORN_HANDOFF_RUN_DIR="$(mktemp -d /tmp/reborn-handoff-retrieval-XXXXXX)"
PYTHONPATH=backend backend/.venv/bin/python -m app.agent.support_agent.rag.cli index \
  --vault docs/agent/obsidian \
  --index "$REBORN_HANDOFF_RUN_DIR/index"
PYTHONPATH=backend backend/.venv/bin/python -m app.agent.support_agent.rag.cli search \
  --vault docs/agent/obsidian \
  --index "$REBORN_HANDOFF_RUN_DIR/index" \
  --query '2026년 희망리턴패키지 원스톱폐업지원 소상공인 모집 공고' \
  --limit 5 \
  --output "$REBORN_HANDOFF_RUN_DIR/search.json"
```

성공 기준은 프로세스 종료 코드와 출력의 `INDEXED_UNREVIEWED_DISCOVERY` /
`DISCOVERY_MATCHES`, 원자료 일치, 실제 공고 ID 확인이다. `UNREVIEWED`·`UNKNOWN`,
S3·정책 최신성 확인 false가 유지돼야 한다. 제목 검색 성공을 일반 질문 정확도나 지원 자격으로 해석하지 않는다.
현재 노트·parser version·임베딩 모델 또는 차원이 바뀌면 새 인덱스를 만든다.
기존 인덱스의 digest·모델 metadata를 강제로 바꿔 호환성 검사를 우회하지 않는다.
실패한 색인 경로도 재사용하지 않는다. 실패 원인은 보존하고 새 경로에서 다시 실행한다.

### 실제 Case 실행

BE가 소유권·비식별 처리를 마친 **`AgentGraphInput` JSON + `KnownProcedureStep[]` JSON**을
제공해야 한다. 명령은 [standalone-runtime.md §4](./standalone-runtime.md#4-실행-방법)를 따른다.
없는 파일을 합성 fixture로 채우지 않는다. 검수 완료 Wiki가 0건인 지금은 `--support-wiki` 경로만
추가해도 운영 HIT가 검증되지 않는다. CLI 출력은 DB 저장과 별개다.
Case CLI는 호출 전에 출력 파일을 예약하므로 예외 후 빈 파일이 남을 수 있다.
파일 존재만으로 성공 처리하지 않고 종료 코드와 결과의 `outcome_type`을 확인한다.

## 6. 다음 작업 순서와 완료 증거

| 순서·티켓 | 필요한 입력/협의 | 끝났다고 말할 수 있는 증거 |
|---|---|---|
| 1. C1·C4·B7 | 현행 schema 기준 BE snapshot adapter, 실제 버전·ID·시각·근거, UNKNOWN/NULL·허용 변경 합의 | 실제 소유 Case export가 기존 Agent 입력 검증을 통과. 임의 필드·근거 생성 없음 |
| 2. B4·A4 | 사람이 검수한 절차 자료와 BE 실제 step ID·조건·선후 관계 | 실제 Case의 절차 후보·필요 조건·불가 사유가 출처와 함께 조회됨 |
| 3. A7 | 실제 `SUPPORT_ITEM.id/uuid/external_notice_id` 매핑과 사람 검수 노트 | 실제 Wiki HIT→조건 비교→필수 Review 확인. 선정·지급 확정은 하지 않음 |
| 4. A8 | 실제 `source_file_location`, S3 읽기 설정·원문 version/hash, 검수 corpus 정책 | 객체 bytes·원문 최신성 확인 후 검수 검색과 Wiki 누락 경로 연결. 근거 부족은 불확실성으로 남음 |
| 5. C5·B11·A6 | transaction 소유자, 안전 실패 응답, 저장 함수 | 실제 API에서 결과 입력→Review→Case·판단·Evidence·이력 저장→재조회. 실패 시 합의된 DB 상태 확인 |
| 6. C6·B12 | conflict 참조·만료·1회 소비·현재값 재확인, FE payload | 실제 충돌 선택 뒤 재계획. 사용자 선택 전 쓰기·stale 덮어쓰기 없음 |
| 7. A9 | 실제 Case 실행 관측, 비용 집계 방식 | 실제 호출 수·token·지연·Review 반송·재작업 확인 및 대시보드. 가짜 이벤트 금지 |

1~4는 준비된 자료에 따라 병행할 수 있다. 공동 결정은 OD-01·04·05·11을 중심으로
[미정 사항 대장](./open-decisions.md)에 기록하고 [BE 요청서](./be-requests.md) §7의 구체적인
완료 증거로 닫는다. 다음 구현을 위해 새 테이블이나 자격 컬럼이 필요하다고 미리 가정하지 않는다.

### 알려진 BE 연결 장애

마지막 확인 당시 `origin/feature/case-service`는 `e082b84`이고 `to_agent_case_snapshot()`이
`NotImplementedError`였다. `origin/feature/validator`는 `4b34da2`이며 Agent 전체 실행 route와
저장 루프는 연결되지 않았다. 이후 변경 여부는 코드와 실제 API를 다시 확인해야 한다.

해당 validator 브랜치에는 시작 시 DB 초기화 경로가 관측됐다. 기존 DB에 무심코 서버를 띄워
연결 문제를 우회하지 않는다. migration·seed·통합 위치는 BE와 확인한다.
현재 AI가 확인한 MySQL 누락 상세와 branch별 차이는 [상태 문서 §3](./implementation-status.md#3-be가-만든-것과-아직-연결되지-않은-것)에 있다.

## 7. 실제 검증 증거와 보존 범위

| 당시 실제 확인 | 현재 로컬 증거 위치 | 인수인계 해석 |
|---|---|---|
| 공식 원문·LLM·Langfuse·MySQL | `/tmp/reborn-live-refresh-mvb_sb3n/` | metadata·원문 후보·실측 보고서. Case 전체 실행·DB 쓰기 성공이 아님 |
| 공식 문장 금액 가드레일 | `/tmp/reborn-live-guardrail-lsalqaba/` | 원문과 수정 전후 결과. 두 표현에 대한 확인 |
| Vault 생성·재읽기·기존 파일 보존 | `/tmp/reborn-obsidian-source-mpfa0qrl/` | 실제 discovery JSON 3개, 노트 대조·재실행·게시 결과 |
| 임베딩 모델 표기 실패·진단 | `/tmp/reborn-live-retrieval-8ahpalju/` | 최초 실패를 보존. 성공 인덱스로 사용하지 않음 |
| Chroma 저장·재검색 | `/tmp/reborn-live-retrieval-q6u7plbd/` | `index/corpus.json`, `build-report.json`, `hope-return-search.json`, `retrieval-verification.json` |

`/tmp`는 같은 개발환경에서만 참조할 수 있고 삭제될 수 있다. 영구 저장소나 다른 개발자의
필수 입력 경로로 가정하지 않는다. 주요 결과·실패·한계는 [검증 기록](./live-verification.md)에,
공개 공고의 실제 Candidate·Evidence는 [Vault](./obsidian/README.md)에 남겨 두었다.
임시 인덱스가 사라졌다면 §5의 실제 공고 색인 명령으로 다시 만든다. 임시 검증 보고서가
사라졌다고 같은 결과를 새 관측인 것처럼 작성하지 않는다.
재색인에는 저장소의 Vault 노트를 사용하며 원시 discovery JSON은 필수가 아니다.
당시 인덱스 자체를 보존하려면 `index/corpus.json`, `index/chroma/` 전체와 해당 보고서를 함께
안전한 보관 위치로 옮겨야 한다. 현재 저장소에는 실행 보고서 원본과 Chroma DB를 커밋하지 않았다.

과거 `542 passed`·`609 passed`는 더미 금지 전의 합성 suite 결과다. 이후 코드 변경과 실제
서비스 동작을 보장하지 않는다. 금지 후에는 실제 API·공식 자료·읽기 전용 DB·정적 검사로만 확인했다.
문서 정리 단계에서는 API를 불필요하게 재호출하지 않고 기존 실측 파일과 코드·명령 정의를 대조했다.

## 8. 다음 인수인계 때 갱신할 것

- 현재 브랜치·HEAD·develop 반영 여부와 커밋/푸시 상태를 다시 적는다.
- 실제 완료 증거가 생긴 티켓만 [구현 현황](./implementation-status.md)에서 변경한다.
- 새 실제 실행의 입력 출처·시각·결과·실패·미검증 범위를 [검증 기록](./live-verification.md)에 남긴다.
- 합의가 끝난 항목만 [미정 사항 대장](./open-decisions.md)에서 결정 완료로 옮긴다.
- 실행법·환경설정은 [standalone-runtime.md](./standalone-runtime.md), 한도는
  [runtime-limits.md](./runtime-limits.md)에 갱신하고 문서 링크를 확인한다.
- 검사를 추가하면 `real_data` 기준(실제 Case·사업자·DB 식별자를 만들지 않음)을 지키는지 보고,
  해당하면 marker를 붙인다. 합성 Case가 필요해지면 붙이지 않고 그 이유를 남긴다.
- 파일을 지울 때 그 파일을 가리키는 문서 링크를 함께 정리한다. `fixtures.py`를 지울 때
  문서 3곳이 걸려 있었다.

현재 읽기 시작점은 이 문서, 세부 문서 색인은 [README.md](./README.md)다.
