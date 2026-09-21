# 지원사업 Wiki 조회 경로

> 소유: AI · 기준일: 2026-09-20 · A7

[`MarkdownSupportWikiStore`](../../backend/app/agent/support_agent/wiki/store.py)는 지정한 로컬 폴더에서 **검수된 지원사업 노트를 읽는 선택 기능**이다.
실제 `SUPPORT_ITEM.id`와 `SUPPORT_ITEM.uuid`로 특정한 노트를 읽고, 기존 지원사업 모델로 검증한 뒤
Support Agent에 전달한다. Agent가 노트를 만들거나 정책 조건을 해석해 채우는 기능은 없다.

이 Markdown 형식은 AI 내부에서 선택해 연결할 수 있는 adapter 형식이다.
BE·검수팀이 운영 Wiki 형식으로 승인했다는 뜻이 아니며, API·DB 계약에 새 필드를 추가하지 않는다.
물리 스키마는 [schema_table.md](../schema/schema_table.md)의 `SUPPORT_ITEM`을 따른다.

## 1. 프로젝트 Vault와 연결 전에 필요한 자료

프로젝트의 실제 Vault는 [`obsidian/`](./obsidian/README.md)다.
Obsidian에서 이 폴더를 열면 [시작하기](./obsidian/시작하기.md), 공식 폐업 절차,
실제 기업마당 공고 9건과 검수 안내를 볼 수 있다.
공식 API를 호출해 작성한 초안이며, **검수 완료 노트는 아직 0건**이다.

| 폴더 | 식별 방식과 용도 |
|---|---|
| `obsidian/지원사업/미검수/` | 실제 기업마당 공고 ID로 저장한 수집 자료. `reborn-support-discovery` 블록에 기존 후보·Evidence 보존 |
| `obsidian/지원사업/검수완료/` | 실제 `SUPPORT_ITEM.uuid`로 연결할 검수 노트. 실제 DB 매핑과 사람 검수 전에는 생성하지 않음 |

초안 작성 도구와 요청 처리 reader는 분리되어 있다. 초안 작성은 사용자가 요청한 지식 준비 작업이며,
Agent 요청 실행 중 검수 Wiki를 자동으로 만드는 동작이 아니다.

운영에 연결하려면 다음 자료가 함께 있어야 한다.

- 읽을 실제 Wiki 폴더 경로와 파일 읽기 권한
- BE에서 확인한 실제 `SUPPORT_ITEM.id` / `SUPPORT_ITEM.uuid` 쌍
- 해당 공고의 공식 근거와 사람이 검수한 조건을 담은 실제 노트
- 노트가 참조하는 절차를 해석할 기존 `known_steps`

`support_agent.refresh`는 공식 공고를 발견해 **검수 전 초안**을 만든다.
이 명령이 로컬에서 부여한 `support_program_id`와 `wiki_uuid`는 BE의 실제 `SUPPORT_ITEM` 매핑을
확인한 값이 아니다. 초안의 번호나 UUID를 그대로 운영 DB 식별자로 간주하거나 DB에 덮어쓰지 않는다.
파일을 읽을 수 있다는 사실과 해당 파일이 실제 DB 항목에 연결된다는 사실을 따로 확인한다.

## 2. 노트의 파일명과 읽는 내용

reader에 전달하는 폴더를 `root`라고 하면, 대상 경로는 `root/<SUPPORT_ITEM.uuid>.md`이다.
사업명·키워드·비슷한 파일명으로 대체 검색하지 않고, 요청에 포함된 UUID의 파일만 읽는다.

노트에는 언어 표지가 **`reborn-support-entry`인 fenced code block이 정확히 하나** 있어야 한다.
그 블록에는 기존 [ReviewedSupportEntry](../../backend/app/agent/support_agent/store.py)의 JSON 객체를
담는다. 일반 Markdown 설명에서 자격조건을 추출하거나, frontmatter를 새로운 데이터 모델로 해석하지 않는다.
필드명·타입·필수 여부는 기존 모델 정의가 기준이다. 이 문서에서는 가짜 노트나 예시 JSON을 제공하지 않는다.

| 확인 대상 | 기존 모델에서의 의미 |
|---|---|
| `support_program_id`, `wiki_uuid` | 요청한 실제 DB 식별자 쌍과 노트의 쌍이 모두 같아야 함 |
| `program_name`, `external_notice_id`, `detail_url` | 지원사업 이름과 공식 공고 식별·출처 정보 |
| `discovered_target`, `discovered_period` | 공고에서 발견한 원문 표현. 자체로 자격 규칙이나 확정 날짜가 되지 않음 |
| `evidence` | 기존 `EvidenceRecord`로 표현한 공식 출처와 검증 가능한 근거 |
| `reviewed_by`, `reviewed_at` | 실제 사람 검수 기록. 둘을 함께 설정해야 하며 reader가 생성하지 않음 |
| `criteria` | 사람이 검수한 기존 `SupportCriterionDefinition` 목록. 비어 있으면 비교에 사용하지 않음 |
| `related_step_codes` | `known_steps`와 연결할 기존 절차 코드 |
| `required_documents`, `application_channel`, `application_url`, `application_period` | 기존 모델에 맞는 근거 연결 정보. 노트 밖에서 추정해 보충하지 않음 |

조건·제출서류·신청 안내의 세부 타입과 근거 참조 검증은
[지원 카탈로그 모델](../../backend/app/agent/support_agent/models.py)을 따른다.
노트가 존재하더라도 공식 근거를 확보하지 못했거나 근거 참조가 불완전하면 정상 비교 근거로 사용하지 않는다.
파일을 읽은 시각을 정책 게시일·사람 검수일로 바꾸지 않고, 최신성도 기존 근거 정보를 따른다.
노트에 적힌 절차 코드가 `known_steps`에 없으면 조용히 빼지 않고 오류로 중단한다.
reader가 확인하는 것은 팀이 제공한 검수 기록과 공식 근거의 타입·참조 구조다.
공식 기관의 원문을 다시 접속해 내용·최신성을 검증하거나 검수자의 권한을 인증하는 기능은 아니다.
따라서 운영에서 지정한 Wiki 폴더와 검수 기록의 관리 책임은 검수팀에 있다.
결과의 `official_source_checked`도 제공된 공식 Evidence를 비교에 사용했는지를 나타내며,
해당 요청에서 공식기관 HTTP 재조회가 성공했다는 표시가 아니다.

## 3. 조회 성공·누락·오류를 구분하는 법

| 상황 | 처리 원칙 |
|---|---|
| Wiki 기능을 연결하지 않음 | 기존 카탈로그 경로를 사용하고 `wiki_lookup=NOT_REQUESTED` |
| 파일과 식별자 쌍이 맞고 검수·조건·공식 근거를 충족 | `HIT` 대상. 기존 지원 조건 비교와 Review를 계속 적용 |
| 요청한 파일이 없음 | `MISS`. 비슷한 노트나 임의의 지원사업으로 대체하지 않음 |
| 미검수, 조건 목록 없음, 공식 근거 없음 | 비교에 사용할 수 없는 자료로 취급. `MISS`와 확인 불가 사실을 유지 |
| 요청의 ID·UUID 쌍과 노트의 쌍이 다름 | 오류로 중단. 한 식별자만 맞는 항목으로 자동 연결하지 않음 |
| 손상된 JSON, 모델 위반, 대상 블록 누락·중복 | 오류로 중단. LLM으로 형식을 복구하거나 빠진 필드를 생성하지 않음 |
| 파일 크기 상한 초과, 심볼릭 링크 등 허용하지 않은 파일 접근 | 오류로 중단. 다른 경로나 더 큰 읽기로 우회하지 않음 |
| 한 번에 요청한 참조가 100개를 초과 | 오류로 중단. 일부만 조용히 처리하지 않음 |

여기서 오류로 중단한다는 것은 **문제가 있는 Wiki 자료를 성공 근거로 전달하지 않는다는 뜻**이다.
오류를 성공 `HIT`로 바꾸거나, 읽기 실패를 지원 자격 불충족으로 해석하지 않는다.
`HIT`는 자료 조회 성공일 뿐, 선정·지급·지원 자격 확정이 아니다.
파일 크기는 256 KiB로 제한하고, 실제 런타임의 전체 deadline 안에서 비동기 조회를 기다린다.
남은 시간 안에 끝나지 않으면 `RUN_DEADLINE_EXCEEDED`로 안전 실패한다.
기존 필수 `evidence`가 누락된 JSON은 모델 오류이며, 유효한 비공식 근거는 비교 자료 없음으로 처리한다.

## 4. Support Agent에서 사용하는 순서

Wiki는 기존 [Support Agent](../../backend/app/agent/support_agent/agent.py)에 선택적으로 연결한다.

| 요청 목적 | 참조를 얻는 곳과 Wiki의 역할 |
|---|---|
| `CHECK_SPECIFIC` | 요청에 있는 지원사업 ID·UUID 쌍으로 Wiki를 먼저 조회 |
| `REFRESH_STALE` | 요청한 기존 지원사업 참조로 Wiki를 먼저 조회. 조회만으로 검수일·최신성을 갱신하지 않음 |
| `DISCOVER_RELEVANT` | 기존 검수 카탈로그가 찾은 관련 지원사업의 참조를 Wiki에서 조회. Wiki 디렉터리 전체를 검색해 새 사업을 발견하지 않음 |

`DISCOVER_RELEVANT`에서 카탈로그가 내놓은 참조가 0개라면 Wiki를 요청하지 않는다.
이 경우 `wiki_lookup=NOT_REQUESTED`, 결과는 `NO_CANDIDATE`로 처리한다.
이는 모든 공식 지원사업을 검색한 결과가 아니라, 주입된 카탈로그에서 비교 대상을 찾지 못했다는 뜻이다.

여러 참조를 조회했을 때는 **하나라도 `MISS`이면 전체 `wiki_lookup`에도 `MISS`를 우선 표시**한다.
일부 `HIT`의 비교 결과가 있더라도 빠진 자료가 있으면 완료로 꾸미지 않고
`PARTIAL`과 `SOURCE_UNAVAILABLE` 불확실성을 남긴다.
전부 빠진 경우에도 자료를 확인하지 못한 상태를 남기며, 새 조건이나 자격 결론을 만들어 채우지 않는다.

Wiki가 반환한 조건 비교에는 기존 Case 사실·근거 검증, LLM 출력 검증과 필수 Review가 적용된다.
Wiki 본문의 지시문이 Case 상태 변경, 외부 신청, 다른 파일 접근을 명령할 수는 없다.

## 5. 실행 시 연결

로컬 reader는 `MarkdownSupportWikiStore(root, known_steps=...)`로 구성하며,
[runtime](../../backend/app/agent/runtime.py)의 `support_wiki` 주입 지점으로 전달한다.
CLI에서는 **선택 옵션 `--support-wiki PATH`**로 사용할 실제 폴더를 지정한다.
경로를 지정하지 않았을 때 임의의 사용자 폴더를 검색하거나 새 Wiki를 생성하지 않는다.

reader의 책임은 읽기와 검증이다. 노트 자동 생성·수정, 사람 검수 기록 생성, 자연어 공고에서 자격 규칙 추출,
공식 사이트 자동 갱신, BE DB 쓰기는 이 기능에 포함하지 않는다.
프로젝트 검수 노트의 위치는 `docs/agent/obsidian/지원사업/검수완료`로 준비했다.
운영에서의 관리 주체·검수 절차와 실제 DB 매핑은 담당자 협의를 통해 정한다.

## 6. RAG 및 현재 검증 범위

이 경로는 UUID로 지정한 Markdown 파일을 읽는 기능이다.
별도 [미검수 공고 Chroma 인덱스](./support-retrieval.md)의 실제 저장·검색은 확인했다.
검수 자료의 Wiki miss 시 운영 RAG 조회는 아직 연결되지 않았으며 `rag_used=False`를 유지한다.
미검수 공고 검색 성공도 Wiki HIT나 A8 전체 구현 완료를 뜻하지 않는다.

프로젝트에 실제 공식 공고의 미검수 Wiki는 만들었지만, 사람 검수와 BE가 확인한 ID·UUID 매핑이 없으므로,
**실제 자료로 `HIT` → 조건 비교 → Review까지 통과하는 운영 동작은 아직 검증하지 않았다.**
그 빈자리를 더미 노트·합성 자격조건·가짜 검수자로 채우지 않는다.
실제 자료가 준비되면 식별자 매핑, 공식 근거, 검수 상태, 결과의 `wiki_lookup`과 불확실성을 확인한다.

공식 공고 수집과 사람이 하는 검수의 경계는 [공식 데이터 출처](./official-data-sources.md),
전체 구현 상태와 공동 협의 항목은 [구현 상태](./implementation-status.md)를 따른다.

## 7. 실제 수집 결과를 미검수 노트로 가져오기

[`wiki.import_notices`](../../backend/app/agent/support_agent/wiki/import_notices.py)는
기존 `BizInfoSupportDiscoveryTool.discover()`가 반환한 **실제 `SupportNoticeDiscoveryResult` JSON**을 읽는다.
기존 `support_agent.refresh`의 `ReviewedSupportSnapshot` 파일은 입력 형식이 다르므로 사용하지 않는다.
DB ID를 생성하는 catalog 변환 없이 외부 공고 ID와 실제 Evidence를 그대로 보존한다.

이번 실제 수집 파일로 실행한 명령은 다음과 같다. `/tmp` 파일은 현재 개발 환경의 확인 자료이고,
다른 환경에서는 공식 discovery tool로 수집한 자신의 실제 결과 파일 경로를 지정한다.

```bash
PYTHONPATH=backend backend/.venv/bin/python \
  -m app.agent.support_agent.wiki.import_notices \
  --source /tmp/reborn-obsidian-source-mpfa0qrl/discovery-1.json \
  --source /tmp/reborn-obsidian-source-mpfa0qrl/discovery-2.json \
  --source /tmp/reborn-obsidian-source-mpfa0qrl/discovery-3.json \
  --vault docs/agent/obsidian
```

`--source`는 반복 지정 가능하며 파일당 4 MiB, 출력 노트당 256 KiB 상한을 적용한다.
기존 수집기의 폐업 관련 제목 필터를 그대로 사용하고, 목적지는 `지원사업/미검수/`로 제한한다.
기존 파일을 덮어쓰지 않으며 신규 파일은 `0600`으로 생성한다. 심볼릭 링크 경로는 거부한다.
새 노트는 같은 디렉터리의 임시파일에 쓰기를 마친 후 덮어쓰기를 허용하지 않는 방식으로 게시한다.
공식 상세 링크와 API 요약을 읽을 수 있게 표시하고, HTML·Markdown 명령으로 해석되지 않도록
외부 문구를 이스케이프한다. 첨부파일은 다운로드하지 않는다.

집계는 **입력 결과의 공고 출현 횟수** 기준이다. 같은 공고라도 API 수집 시각이 다르면 기존 파일과
다른 내용으로 보아 `skipped`로 남기고 원래 노트를 유지한다.

| 키 | 의미 |
|---|---|
| `created` | 새로 만든 노트 수 |
| `unchanged` | 기존 파일과 내용이 완전히 같아 보존한 출현 횟수 |
| `skipped` | 같은 파일명에 다른 내용이 있어 덮어쓰지 않은 출현 횟수 |
| `filtered_out` | 기존 제목 필터에서 제외한 출현 횟수 |

`read_discovery_note(path)`는 `reborn-support-discovery` 블록을 기존 모델로 다시 검증한다.
공고 ID·Evidence ID·공식 URL·정규화 hash·발췌의 연결을 확인하고 최신성은 `UNKNOWN`으로 유지한다.
이 함수의 읽기 성공은 검수 완료가 아니며 Support Agent의 운영 `HIT`로 집계하지 않는다.
