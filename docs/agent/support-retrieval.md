# 미검수 공식 공고 검색 인덱스

> 소유: AI · 2026-09-20 · A8 부분 구현

실제 Obsidian 공고 노트를 임베딩하고 Chroma에 저장한 뒤, 검색된 문구를 원자료와 대조하는
**오프라인 검색 명령**이다. 운영 Support Agent의 Wiki miss 처리와 S3 원문 조회는 아직 연결하지 않았다.
미검수 자료를 `ReviewedSupportCatalog`로 바꾸거나 Case 자격 판단에 주입하지 않는다.

## 현재 데이터 경로

1. `지원사업/미검수/`의 실제 노트를 기존 `read_discovery_note()`로 읽는다.
2. 공고명·API 요약·대상·신청 기간·신청 방법을 원래 필드의 문자 구간으로 나눈다.
3. 기존 환경변수의 임베딩 API로 벡터를 생성하고 별도 Chroma 컬렉션에 저장한다.
4. 원자료·구간·모델·차원·digest를 `corpus.json`에 기록한다.
5. 검색할 때 현재 Vault를 다시 읽어 corpus digest를 확인한 후 query embedding으로 검색한다.
6. 검색 결과의 chunk ID를 검증하고, 결과 문구와 출처는 재검증한 원자료에서 조립한다.

컬렉션은 `reborn_support_discovery_v1`, 상태는 항상 `UNREVIEWED`다.
chunk ID와 corpus digest는 로컬 검색 자료 식별자이며 `SUPPORT_ITEM.id/uuid/catalog_version`을
대신하지 않는다. Chroma의 SQLite 파일도 서비스 MySQL 테이블이 아니다.
DB 스키마·공유 DTO에 새 필드를 추가하지 않았다.

`parser_version=bizinfo-api-fields-v1`은 API 제공 필드의 구간 분리 방식이다.
PDF를 파싱하거나 원공고 전체를 다운로드했다는 뜻이 아니다. 각 결과는 원래 공고 ID·공식 URL·기관,
필드명·시작/끝 위치·근거 ID·source version·정규화 hash·수집시각을 보존한다.
`source_note_integrity_checked=true`는 로컬 노트와 색인 출처가 일치한다는 뜻이다.
`s3_original_checked=false`, `policy_freshness_checked=false`, `freshness_status=UNKNOWN`을 유지한다.

## 실행

저장소 루트에서 실행한다. 기존 `EMBEDDING_PROXY_URL`, `PROXY_TOKEN`, `OPENAI_EMBEDDING_MODEL`을
사용하며 새 환경변수나 의존성 pin을 추가하지 않았다. 현재 설치된 Chroma를 사용한다.
`--index`는 부모 폴더가 존재하는 **새 디렉터리 경로**여야 한다.

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.agent.support_agent.rag.cli index \
  --vault docs/agent/obsidian \
  --index /tmp/reborn-support-index
```

실제 공고 제목으로 검색하려면 다음과 같이 실행한다. query에는 공개 공고 문구만 사용하고
Case 원문·사업자 식별정보·주소·토큰을 입력하지 않는다.

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.agent.support_agent.rag.cli search \
  --vault docs/agent/obsidian \
  --index /tmp/reborn-support-index \
  --query '2026년 희망리턴패키지 원스톱폐업지원 소상공인 모집 공고' \
  --limit 5 \
  --output /tmp/reborn-support-search.json
```

`--notice-id`를 추가하면 해당 실제 공고 ID 안에서 검색한다. 결과 파일은 새 파일만 허용한다.
명령의 표준 출력은 건수·상태이고, 공개 문구와 출처를 담은 결과 파일은 `0600`이다.
색인 디렉터리는 `0700`으로 생성한다. 기존 자료를 바꾸거나 증분 갱신하지 않는다.
노트 내용·근거가 변경되면 새 경로에 재색인해야 한다.

기존 파일·컬렉션 덮어쓰기, 모델·차원·digest 불일치, 잘못된 source span, 손상된 자료,
허용하지 않는 경로는 실패 처리한다. 신규 manifest는 모든 벡터 저장이 끝난 뒤 게시한다.
실패한 색인 디렉터리는 유효 manifest가 없으면 검색할 수 없으며 자동 복구하거나 검수 완료로 승격하지 않는다.

호출·데이터 상한과 시간 제한의 정확한 의미는 [실행 한도](./runtime-limits.md) §6을 따른다.
Chroma 기본 임베딩 함수와 자동 모델 다운로드를 사용하지 않고 telemetry를 끈다.
cosine 및 필터 설정은 [Chroma 컬렉션 설정](https://docs.trychroma.com/docs/collections/configure),
[metadata 필터](https://docs.trychroma.com/docs/querying-collections/metadata-filtering)와 대조했다.

## 실제 확인 결과와 한계

실제 기업마당 공고 **7건 → 35개 구간, 2,305자 → 1,536차원 벡터**를 저장했다.
공고 제목 7개를 실제 API로 임베딩해 검색했을 때 7개 모두 해당 공고가 1순위였다.
공고별 필터, source span·Evidence 참조, 별도 프로세스 CLI에서 인덱스를 다시 여는 동작도 확인했다.
이는 정확한 공고 제목을 이용한 동작 확인이며 일반 질문의 의미 검색 정확도·recall 평가가 아니다.

첫 실제 호출에서는 요청 모델 `openai/text-embedding-3-small`과 응답 모델
`text-embedding-3-small`의 표기 차이로 응답 검증이 실패했다.
실제 확인한 이 두 표기만 허용하고 요청·응답 모델명을 manifest에 함께 기록하도록 수정했다.
다른 모델의 임의 치환이나 namespace 전체 제거는 하지 않는다.

**S3·검수 corpus·운영 RAG는 남았다.** 실제 `SUPPORT_ITEM.source_file_location` 매핑,
객체 읽기 설정과 원문 version/hash가 필요하다. API 정규화 데이터 hash를 S3 객체 bytes의 hash로
간주해서는 안 된다. 사람 검수와 실제 DB 매핑 후 검수 corpus용 경로를 분리해 연결하고,
Wiki 누락·자료 부족·stale·조회 실패를 운영 Support Agent의 불확실성으로 전달해야 한다.
현재 Graph의 `rag_used=false`는 그대로이며 이 오프라인 명령 실행으로 바꾸지 않는다.

검증 기록은 [실제 호출·저장 확인](./live-verification.md) §10, 코드 위치는
[`support_agent/rag/`](../../backend/app/agent/support_agent/rag/)다.
