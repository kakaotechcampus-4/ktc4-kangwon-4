# AI 공식 데이터 조회·크롤링·RAG 구현 계획

> 문서 소유자: AI
>
> 적용 범위: 임차형 소규모 카페 폐업 Case의 절차·사업자 상태·인허가·지원사업 정보
>
> 목적: 현재 구현과 외부 API 실측, 앞으로 구현할 AI 데이터 파이프라인, 공동 결정이 필요한 경계를 한 문서에서 구분한다.

이 문서는 **AI가 공식 데이터를 어떻게 확보하고 검증 가능한 근거로 만들 것인지**를 설명한다. Agent/Tool의 정확한 입출력 필드는 [Agent·Tool 입출력 스키마](./agent-tool-io-schema.md), 호출 구조는 [Agent 아키텍처](./architecture.md), 실행법·환경변수·데이터 모드는 [standalone Runbook](./agent-standalone-runtime-requirements.md), BE가 구현하거나 함께 확정해야 할 인증·Case·저장 계약은 [BE-Agent 연동 요구사항](./be-agent-integration-requirements.md)을 정본으로 한다. 이 문서에는 그 내용을 복제하지 않는다.

## 1. 상태 판정 원칙

| 문서 표기 | 의미 |
|---|---|
| 현재 구현·검증됨 | 현재 저장소에 실행 코드가 있고 자동화 테스트로 경계가 검증된 AI 기능 |
| 2026-09-15 제한 실측 | 해당 날짜에 외부 API·사이트의 HTTP 응답을 직접 확인한 사실. 지속 가용성, 실제 Case 연동, 운영 승인을 뜻하지 않음 |
| AI 후속 구현 | AI 구현 목표지만 현재 코드·저장소·index·실행 연결 중 하나 이상이 없음 |
| 선행 공동 결정 필요 | AI만 정해서는 안 되며 권한·개인정보·운영 계약 결정이 먼저 필요함 |
| 보류 | 현재 카페 폐업 MVP 범위에서 제외했고 일정이 확정되지 않음 |

한 항목에 상태가 둘 이상 적용될 수 있다. 예를 들어 `2026-09-15 제한 실측 · AI 후속 구현`은 외부 endpoint 응답은 확인했지만 adapter나 Graph 연결은 아직 없다는 뜻이다. HTTP 200은 다음을 증명하지 않는다.

- 실제 사용자의 Case를 읽었다는 것
- 해당 Case의 소유권·동의를 확인했다는 것
- 응답을 Agent 입출력 스키마로 변환했다는 것
- 공고의 지원 자격이나 절차의 적용 가능성을 검수했다는 것
- 운영 환경에서 지속적으로 쓸 수 있다는 것

## 2. 결론: 현재 가능한 것과 목표

### 2.1 현재 구현·검증된 범위

1. `ProcedureLookupTool`이 코드 검토된 공식 URL registry를 먼저 조회하고, 공식 원문을 직접 fetch해 `ProcedureSourceDocument`와 `EvidenceRecord`를 만든다.
2. registry로 찾지 못한 질의는 설정된 경우 **Kakao → Google** 순서로 공식 URL 후보만 발견한다. 후보 URL은 공식 도메인 allowlist를 통과하고 원문 fetch가 성공해야 Evidence가 된다.
3. `BizInfoSupportDiscoveryTool`이 기업마당 공식 API를 한 번 bounded 조회해 **검수 전 공고 후보**와 `OFFICIAL_API` Evidence를 만든다.
4. standalone Graph는 합성 Case와 합성 `ReviewedSupportCatalog`를 사용한다. 절차 원문은 인터넷에서 가져올 수 있지만 실제 사용자 Case·실제 지원 catalog 연동은 아니다.

코드 근거:

- 공식 source registry, provider 순서, 원문 fetch와 Evidence 생성: [`backend/app/agent/procedure_tool/tool.py`](../backend/app/agent/procedure_tool/tool.py)
- 공식 도메인·검색 환경설정과 제한: [`backend/app/agent/procedure_tool/models.py`](../backend/app/agent/procedure_tool/models.py)
- 기업마당 raw discovery와 정규화: [`backend/app/agent/support_agent/discovery_tool.py`](../backend/app/agent/support_agent/discovery_tool.py)
- raw 후보와 검수 catalog를 분리한 계약: [`backend/app/agent/support_agent/discovery_models.py`](../backend/app/agent/support_agent/discovery_models.py)
- RAG를 사용하지 않았음을 `rag_used=False`로 출력하는 현재 Support Agent: [`backend/app/agent/support_agent/agent.py`](../backend/app/agent/support_agent/agent.py)
- 합성 Case·catalog를 주입하는 standalone 실행: [`backend/app/agent/cli.py`](../backend/app/agent/cli.py), [`backend/app/agent/fixtures.py`](../backend/app/agent/fixtures.py)
- 네트워크·schema drift·민감정보·공식 도메인 실패 조건 테스트: [`backend/tests/agent/test_procedure_tool.py`](../backend/tests/agent/test_procedure_tool.py), [`backend/tests/agent/test_support_discovery_tool.py`](../backend/tests/agent/test_support_discovery_tool.py)

### 2.2 AI가 이어서 구현할 목표

현재의 제한된 URL fetch와 기업마당 단일-page discovery를 범용 크롤러나 RAG라고 부르지 않는다. 목표는 승인된 공식 원문을 수집하고, 재현 가능한 버전으로 검수·색인한 뒤, Agent가 원문까지 역추적 가능한 Evidence만 사용하는 전체 파이프라인이다.

```text
승인된 공식 API·공식 문서 allowlist
  → bounded crawler / API connector
  → parser · 정규화 · chunking
  → 원문 version · content hash · locator 보존
  → 사람 검수된 procedure corpus / ReviewedSupportCatalog 발행
  → 재현 가능한 index 생성
  → source-policy aware retriever
  → EvidenceRecord 생성·검증
  → Procedure Tool / Info Agent / Support Agent / Graph 연결
```

완료 기준은 “검색 결과가 나왔다”가 아니라 **같은 source version으로 결과를 재현하고, 모든 확정형 claim을 원문 Evidence까지 추적하며, stale·권한 미확인 자료를 안전하게 배제하는 것**이다.

## 3. 데이터 원천 우선순위와 금지 경계

### 3.1 우선순위

| 순위 | 원천 | 용도 | 판정 |
|---:|---|---|---|
| 1 | 정형 공식 API | 사업자 상태·인허가·공고처럼 구조화된 최신 데이터 | 응답 schema와 이용 권한을 검증한 뒤 사용 |
| 2 | 코드 검토된 공식 공개 문서 직접 조회 | 폐업 절차·신고 방법·기관 안내 | allowlist, HTTPS, content type, 크기, redirect를 검증한 뒤 사용 |
| 3 | 검수·버전 관리된 공식 corpus의 RAG | 여러 공식 문서에서 관련 구간 검색 | 원문 hash·locator로 역추적되는 chunk만 사용 |
| 4 | Kakao·Google 검색 | 1~3에서 문서를 찾지 못할 때 공식 URL 발견 | 제목·snippet은 Evidence가 아니며 공식 원문을 다시 fetch해야 함 |

Kakao와 Google은 사실 원천이 아니다. 현재 Google 경로는 Google HTML 검색 결과를 크롤링하는 기능이 아니라 Google Agent Search의 URL discovery fallback이다. 검색 key가 없어도 registry에 등록된 카페 MVP 공식 문서는 직접 조회할 수 있다.

### 3.2 금지·제한

- 현재 정책: Naver 검색 API 결과를 Agent·RAG 입력으로 사용하지 않는다. 2026-09-07 시행 약관 공지가 검색 결과를 AI 모델·서비스의 입력 또는 개발에 사용하는 행위를 금지하므로 provider 후보에서 제외했다([네이버 개발자센터 공지](https://developers.naver.com/notice/article/33400)).
- 현재 정책: 검색 결과 제목·snippet, 비공식 블로그, 카페, 광고 페이지를 근거로 승격하지 않는다.
- 현재 정책: allowlist 밖 URL, HTTP URL, 비공식 redirect, 허용하지 않은 content type, 제한보다 큰 응답은 fetch하지 않거나 Evidence로 만들지 않는다.
- AI 후속 구현: **승인된 정부·공식 출처별 bounded crawler는 반드시 구현한다.** 다만 임의 URL을 무차별 순회하는 인터넷 전체 크롤링은 금지하고, 출처별 이용조건·robots·공공누리·보존 조건을 승인한 범위만 수집한다.
- 선행 공동 결정 필요: 사업자등록번호·주소 등 사용자 식별정보를 검색 query, LLM prompt, trace, fixture 또는 공개 API URL에 직접 넣지 않는다. 인증·동의·마스킹·보존 계약을 먼저 확정한다.
- 보류: 정부24·홈택스·4대사회보험정보연계센터의 실제 신고 대행은 현재 범위가 아니다. Agent는 검증된 방법과 공식 링크만 안내한다.

## 4. 현재 구현된 조회 경계

### 4.1 절차 원문 조회

현재 source registry에는 세 종류의 공식 안내가 있다.

| Case 신호 | 공식 원문 | 현재 처리 |
|---|---|---|
| 사업자·세무 폐업 | [찾기쉬운 생활법령: 휴업·폐업신고](https://www.easylaw.go.kr/CSP/CnpClsMain.laf?ccfNo=2&cciNo=1&cnpClsNo=2&csmSeq=25&popMenu=ov) | registry match 후 직접 fetch |
| 카페·음식점 | [찾기쉬운 생활법령: 커피전문점 폐업 신고](https://www.easylaw.go.kr/CSP/CnpClsMainBtr.laf?ccfNo=5&cciNo=1&cnpClsNo=1&csmSeq=706&popMenu=ov) | registry match 후 직접 fetch |
| 직원·4대보험 | [국민연금공단: 사업장 탈퇴 안내](https://www.nps.or.kr/pnsinfo/ntpsklg/getOHAF0006M0.do?menuId=MN24001107&tab=tab10) | registry match 후 직접 fetch |

원문 fetch가 성공하면 URL, 수집시각, excerpt, content hash를 보존한다. 현재 페이지 발행일·검토일을 판별하는 resolver가 없으므로 `freshness_status=UNKNOWN`이다. 따라서 기한·서류를 확정형으로 사용하려면 Info Agent가 Evidence와 불확실성을 함께 처리해야 한다.

이 구현은 세 도메인(`law.go.kr`, `easylaw.go.kr`, `nps.or.kr`)과 등록된 문서 중심의 제한 조회다. 전체 폐업 절차 문서를 수집하거나 주기적으로 최신성을 확인하는 crawler가 아니다.

### 4.2 지원사업 raw 후보 discovery

`BizInfoSupportDiscoveryTool`은 [기업마당 지원사업정보 API](https://www.bizinfo.go.kr/apiDetail.do?id=bizinfoApi)의 고정 endpoint를 사용한다.

- 입력: 제한된 keyword 목록과 최대 결과 수
- 처리: 한 번의 `pageIndex=1` 요청, strict JSON shape 검증, 공식 상세 URL 검증, 민감 query redaction
- 출력: `SupportNoticeCandidate`, `EvidenceRecord`, 결과 수·중복 수·`truncated` summary
- 하지 않는 일: 전체 페이지 동기화, 상세·첨부 원문 수집, 지원 조건 해석, eligibility 판정, 사람 검수, Graph 연결

후보는 곧바로 `ReviewedSupportCatalog`가 될 수 없다. 공고의 “세부사업별 상이”, “예산 소진 시까지” 같은 문구를 임의의 날짜나 Boolean 자격값으로 바꾸면 오판이 생기기 때문이다. 상세 공고와 첨부의 조건·제외대상·신청서류를 구조화하고 검수한 version만 Support Agent가 읽어야 한다.

### 4.3 현재 Graph와 데이터의 관계

| 데이터 | standalone Graph에서 사용 | 실제 데이터 여부 |
|---|---:|---|
| Case snapshot | 사용 | 합성 fixture |
| `ReviewedSupportCatalog` | 사용 | 합성 fixture |
| 공식 절차 원문 | 사용 | 요청 시 인터넷 직접 fetch |
| 기업마당 raw 후보 | 미사용 | 독립 adapter에서 실제 API 조회 가능 |
| 사업자 상태·인허가 | 미사용 | adapter 없음 |
| RAG corpus·index·retriever | 미사용 | 구현 없음 |

따라서 현재 standalone 실행 성공은 “Agent 흐름과 실제 절차 원문 fetch가 동작한다”는 뜻이며 “실제 사용자 Case와 실제 지원 자격이 연동됐다”는 뜻이 아니다.

## 5. 2026-09-15 외부 API·사이트 제한 실측

아래 표는 2026-09-15 당시의 접근 시험 기록이다. 비밀값은 출력하거나 문서화하지 않았다. 재실행 일자와 결과를 남기지 않은 채 현재 운영 상태로 확대 해석하지 않는다.

| 원천 | 그날 확인한 사실 | 코드/Case 연결 판정 |
|---|---|---|
| 기업마당 직접 API | HTTP 200, JSON `jsonArray` 및 폐업 관련 공고 후보 확인 | 독립 discovery adapter만 구현됨. catalog·Graph에는 미연결 |
| 국세청 사업자등록 상태 API `15081808` | 합성 비실사용 번호로 HTTP 200 | 접근만 확인; adapter는 AI 후속 구현. 실제 사용자 조회 아님 |
| 행안부 휴게음식점 API `15154921` | 목록 endpoint HTTP 200 | 접근만 확인; 실제 Case exact 조회·adapter는 AI 후속 구현 |
| 행안부 일반음식점 API `15154916` | 승인 전파 후 목록 endpoint HTTP 200 | 접근만 확인; 실제 Case exact 조회·adapter는 AI 후속 구현 |
| 행안부 제과점 API `15155252` | HTTP 403, code 30 | 활용신청 없음; 현재 보류 |
| 공공데이터포털 기업마당 API `15157820` | HTTP 403, code 30 | 활용신청 필요. 보강원 후보 |
| K-Startup API `15125364` | HTTP 403, code 30 | 활용신청 필요. 보강원 후보 |
| 정부24 혜택 API `15113968` | HTTP 401 | 활용신청·승인 상태 확인 필요. 보강원 후보 |
| 찾기쉬운 생활법령 2개 문서 | HTTP 200, 본문 추출 성공 | 현재 Procedure registry 경로에 연결됨 |
| 국민연금공단 사업장 탈퇴 안내 | HTTP 200, 본문 추출 성공 | 현재 Procedure registry 경로에 연결됨 |

공공데이터포털의 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`는 보유한 key 전체가 고장 났다는 뜻으로 단정하지 않는다. 같은 key로 성공한 서비스가 있으므로 서비스별 활용신청·승인·전파 상태부터 확인한다.

기업마당 실측에서는 공고 ID `PBLN_000000000117676`인 “2026년 희망리턴패키지 원스톱폐업지원 소상공인 모집 공고”를 확인했다([공식 상세](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000117676)). 이것은 해당 공고의 존재를 확인한 것이며 특정 사용자의 자격 충족을 확인한 것이 아니다.

## 6. 데이터 원천별 도입 계획

| 원천 | 목적 | 현재 상태 | 다음 AI 작업 | 선행 결정·준비 |
|---|---|---|---|---|
| 기업마당 직접 API | 지원 공고 후보 발견 | raw adapter 구현·검증됨; 실행 흐름 미연결 | pagination, 상세·첨부 수집, versioning, 검수 queue | 보존·검수·발행 정책 |
| 국세청 `15081808` | 사업자 영업·폐업 상태 확인 | 2026-09-15 접근만 확인; adapter 미구현 | 최소 응답 adapter와 Evidence 변환 | 선행 공동 결정: 인증된 사업자번호 resolver |
| 행안부 `15154921`, `15154916` | 카페 영업신고·폐업·관할기관 확인 | 2026-09-15 접근만 확인; adapter 미구현 | 업종별 exact 조회 adapter와 정규화 | 선행 공동 결정: 매칭 key, 동의, 오매칭 처리 |
| 국가법령정보 공동활용 API | 조문·시행일·서식 보강 | AI 후속 구현 | 신청 후 resolver·version 검증 | 운영 `LAW_API_OC`, 이용 범위 승인 |
| 기업마당 `15157820` | 수정일 기반 증분 수집 보강 | AI 후속 구현 | 승인 뒤 schema spike | 활용신청, 제3유형 변경금지 검토 |
| 정부24 혜택 `15113968` | 대상·선정기준·서류 보강 | AI 후속 구현 | 승인 뒤 후보 connector 평가 | 활용신청, 자격 판정 기준 검수 |
| K-Startup `15125364` | 재도전·재창업 공고 보강 | AI 후속 구현 | 승인 뒤 후보 connector 평가 | 활용신청, 마감·제외대상 검증 |
| 중소벤처24 | 업력·매출·지역 등 지원조건 보강 | AI 후속 구현 | API 계약·sample 조사 | `SMES_API_TOKEN`, 승인·IP 조건 |
| 식품안전나라 | 식품업 인허가 보조 | 보류 | MVP 정확도 gap 발생 시 재평가 | 별도 key, 서비스 시간·중복성 검토 |
| Work24 | 채용·훈련 정보 | 보류 | 사업장 보험상실 절차의 주 원천이 아니므로 현재 도입하지 않음 | 제품 범위 변경 시 재평가 |

공식 문서 링크:

- [국세청 사업자등록정보 진위확인 및 상태조회 `15081808`](https://www.data.go.kr/data/15081808/openapi.do)
- [행안부 휴게음식점 `15154921`](https://www.data.go.kr/data/15154921/openapi.do), [일반음식점 `15154916`](https://www.data.go.kr/data/15154916/openapi.do), [제과점 `15155252`](https://www.data.go.kr/data/15155252/openapi.do)
- [국가법령정보 공동활용 안내](https://open.law.go.kr/LSO/information/guide.do)
- [공공데이터포털 기업마당 `15157820`](https://www.data.go.kr/data/15157820/openapi.do), [정부24 혜택 `15113968`](https://www.data.go.kr/data/15113968/openapi.do), [K-Startup `15125364`](https://www.data.go.kr/data/15125364/openapi.do)
- [중소벤처24 지원사업정보 API](https://portal.smes.go.kr/home/cs/opndata/UI_USR_L_210/supportBusinessInfoApi)

## 7. AI 후속 목표: 크롤링·RAG 구현 단계

아래 단계는 순서를 갖는다. 앞 단계 acceptance criterion을 충족하지 못하면 다음 단계에서 운영 데이터로 사용하지 않는다.

| 단계 | Owner | 선행조건 | 산출물 | Acceptance criterion |
|---:|---|---|---|---|
| 0. 출처 등록·정책 심사 | AI + PM/보안/데이터 운영 | 공식 기관, 이용조건, robots, 공공누리, 수집 목적 확인 | versioned source registry, 허용 경로·주기·보존·삭제 정책 | 모든 source가 소유기관·공식 URL·허용 근거·검토일·재검토일을 가지며 미승인 source는 fetch 불가 |
| 1. connector/crawler | AI | 0단계 승인, 필요한 API key·rate limit | 출처별 bounded connector, retry/timeout/size/redirect 정책, raw manifest | allowlist 밖 통신 0건, secret log 0건, rate limit 준수, 부분 실패를 typed result로 기록 |
| 2. parser·정규화·chunking | AI | raw 원문과 지원 content type 확정 | source별 parser, normalized document, 의미 단위 chunk, parser version | fixture와 실문서 golden test 통과, 표·기한·서류 locator 보존, parser drift 시 fail closed |
| 3. version·hash·provenance | AI | canonical URL/외부 ID와 parser 출력 | raw hash, normalized hash, source version, 수집·게시·개정·시행일, parent lineage | 동일 원문 재수집은 동일 digest, 변경 원문은 새 version, 모든 chunk가 원문 locator로 역추적 가능 |
| 4. 검수 corpus/catalog 발행 | AI + 데이터 운영/PM | 2·3단계 완료, 검수 기준과 권한 확정 | immutable procedure corpus version, immutable `ReviewedSupportCatalog` version, 승인/반려 기록 | 미검수 자료는 운영 조회에서 제외, 지원 조건·제외대상·서류 coverage 검수, 발행 version 재현 가능 |
| 5. index 생성 | AI | 승인된 corpus/catalog version | index manifest, embedding model/version, chunk↔source mapping | 같은 corpus+설정에서 동일 manifest 생성, 삭제·교체 source가 index에서 제거됨, 고아 chunk 0건 |
| 6. retriever | AI | versioned index, freshness·license metadata | official-only retriever, metadata filter, top-k/score 정책 | 승인 평가셋에서 필수 source Recall@5 ≥ 0.95, Evidence Precision@5 ≥ 0.98, 비공식·금지 source 선택 0건 |
| 7. Evidence·Agent 연결 | AI | retriever 평가 통과, 현재 Agent schema와 호환 | retriever result→`EvidenceRecord` adapter, Procedure/Info/Support/Graph wiring | 확정형 claim 100%가 source_ref+version+locator+hash로 추적되고 Evidence 없는 mutation은 Review에서 거부 |
| 8. 운영 검증·갱신 | AI + 데이터 운영 + BE | 저장·스케줄·관측 계약 확정 | 증분 수집 job, stale 경보, rollback, 품질 dashboard | 갱신 SLA 준수, schema/source drift 경보, 이전 catalog/index로 rollback 가능, Case 결과에서 사용 version 감사 가능 |

### 7.1 procedure corpus 규칙

- 절차 문서는 법적 시행일, 기관 검토일, 수집일을 하나의 `updated_at`으로 합치지 않는다.
- 법령·공식 안내의 서로 다른 표현을 LLM이 임의 병합하지 않는다. 원문별 version과 충돌을 보존하고 Info Agent가 불확실성을 출력한다.
- 국민연금공단 등 재사용·장기 저장 조건이 아직 확정되지 않은 원문은 직접 조회까지만 허용하고 corpus 편입을 막는다.
- 정부24 HTML은 공개 접근 가능 여부와 별개로 대량 수집·영구 저장 조건이 명확해질 때까지 corpus에서 제외한다. `robots.txt` 허용은 저작권 허락과 동일하지 않다.

### 7.2 support catalog 규칙

- 외부 공고 ID, 공식 URL, 원문 수정시각과 hash로 중복을 병합한다. 제목 문자열만으로 병합하지 않는다.
- 공고 종료, 예산 소진, 지역·업종·업력·매출·고용·중복수혜·제외대상을 구조화한다.
- raw API 후보와 검수 catalog를 같은 타입·테이블·index namespace로 취급하지 않는다.
- Support Agent는 검수된 catalog를 read-only로 비교하며, RAG 유사도만으로 `ELIGIBLE`을 만들지 않는다.

### 7.3 RAG 품질·안전 기준

- 검색 결과는 원문 Evidence의 대체물이 아니다.
- 답변에 사용한 chunk는 기관명, canonical URL, 외부 ID, source version, content hash, locator, parser version, 수집일을 가져야 한다.
- `UNKNOWN` 또는 `STALE` freshness, 이용조건 미확인, parse 실패 문서는 확정형 기한·서류·자격 판정에서 제외한다.
- retrieval 평가는 문서 검색 recall뿐 아니라 잘못된 기관·이전 version·비공식 자료를 선택하는 false-positive도 측정한다.
- API 장애 시 무조건 웹 크롤링으로 우회하지 않는다. 마지막으로 검수된 version을 stale 표시해 사용할지 fail closed할지는 데이터 종류별 정책으로 정한다.

## 8. AI 구현 전에 공동으로 확정할 항목

아래는 AI 구현 의지가 없어서 미구현인 것이 아니라, 잘못 결정하면 개인정보 노출·Case 오매칭·무근거 판정이 생기기 때문에 공동 결정이 먼저 필요한 항목이다. 상세 질문과 acceptance criterion은 [BE-Agent 연동 요구사항](./be-agent-integration-requirements.md)을 따른다.

| 결정 | 필요한 이유 | 결정 전 AI 경계 |
|---|---|---|
| 인증된 Case snapshot 전달과 소유권 확인 | 실제 사용자와 합성 fixture를 구분하고 타인 Case 조회를 차단 | fixture 외 실제 Case를 조회하지 않음 |
| 사업자등록번호·주소 resolver 경계 | NTS·인허가 exact 조회에 식별정보가 필요 | 자연어 prompt·검색 query에 식별정보를 넣지 않음 |
| 동의·암호화·마스킹·audit·retention | 개인정보가 log, trace, Evidence에 복제될 수 있음 | 원문 식별정보 저장·trace 전송 금지 |
| corpus/catalog 저장소와 발행 권한 | 미검수 데이터를 운영 판정에 섞지 않기 위해 필요 | raw discovery 결과를 Support Agent에 주입하지 않음 |
| source별 수집·보존·삭제 승인 | 공개 URL도 대량 수집·재배포 권한을 자동 보장하지 않음 | 승인 source만 직접 조회, 영구 corpus 미구축 |
| catalog/index version을 Case 결과에 기록하는 방식 | 나중에 같은 판단을 재현하고 정정하기 위해 필요 | standalone 결과를 운영 DB에 저장하지 않음 |

## 9. 구현 완료 정의

다음 조건을 모두 만족해야 “실제 공식 데이터 기반 Agent가 동작한다”고 표현한다.

- 실제 사용자 Case는 BE가 인증·소유권·동의 확인 후 최소 snapshot으로 제공한다.
- 필요한 NTS·인허가 resolver는 식별정보를 LLM·검색·trace에 노출하지 않고 결정적으로 조회한다.
- 절차 원문은 승인 source registry 또는 승인 corpus에서 가져오며 source version과 locator가 남는다.
- 지원사업은 raw 후보가 아니라 발행된 `ReviewedSupportCatalog` version으로 비교한다.
- corpus→index→retriever→Evidence→Graph 경로가 구현되고 자동화 평가를 통과한다.
- HTTP 200, 검색 성공, Graph 성공, Case 연동 성공을 각각 별도 지표와 검증 결과로 기록한다.
- stale·schema drift·upstream 장애·근거 부족 시 확정형 답을 만들지 않고 안전한 부분 결과 또는 실패를 반환한다.

현재 판정은 다음과 같다.

| 범위 | 판정 |
|---|---|
| 공식 절차 원문 제한 조회 | 현재 구현·검증됨 |
| 기업마당 raw 공고 후보 discovery | 구현·검증됐지만 현재 Graph 미연결 |
| 실제 Case·실제 검수 catalog를 사용한 전체 Graph | 선행 공동 결정 필요 · AI 후속 구현 |
| 승인된 공식 원문 crawler·parser·versioned corpus | AI 후속 구현 |
| index·retriever·Evidence·Graph RAG 연결 | AI 후속 구현 |

즉, 크롤링·RAG는 폐기한 아이디어가 아니라 **AI 구현 목표**다. 다만 현재의 세 URL fetch나 단일 기업마당 API 호출을 RAG라고 과장하지 않고, 위 단계와 acceptance criterion을 충족하는 시점에만 구현 완료로 전환한다.
