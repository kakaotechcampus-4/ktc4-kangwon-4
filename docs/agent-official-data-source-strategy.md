# RE:BORN 공식 API·크롤링·RAG 데이터 소스 전략

> 상태: **`[OBSERVED_2026-09-15]` 실조사·실호출 + `[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` 생산 전략**
>
> 소유: AI. 인증·개인정보·저장·운영 권한은 BE와 공동 확정
>
> 범위: 임차형 소규모 카페 폐업 Case의 절차와 지원사업. 전 업종 확장 문서가 아님

상태 라벨을 분리해서 읽습니다. `[OBSERVED_2026-09-15]`는 그 날짜에 API 접근·응답만 확인한 실측값이며 생산 연결이나 지속 가용성을 보장하지 않습니다. `[CURRENT_AI]`는 현재 코드가 소비하는 경로, `[PROPOSED_SHARED]`는 공동 승인 전 운영·개인정보 계약, `[TARGET_UNIMPLEMENTED]`는 adapter/pipeline/RAG가 아직 없다는 뜻입니다.

## 1. `[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` 데이터 획득 전략

아래 순서는 **목표 데이터 획득 전략**입니다. 현재 구현 범위는 공식 source registry의 제한적 직접 조회와 기업마당 단일-page discovery이며, 범용 크롤러·영구 corpus·vector RAG는 아직 없습니다.

RE:BORN은 검색 포털을 주 데이터 원천으로 쓰지 않습니다. 목표 우선순위는 다음과 같습니다.

1. 정형 공식 API
2. 코드 리뷰로 승인한 공식 공개 문서의 제한적 직접 조회
3. 적법하게 수집·버전 관리한 공식 원문의 RAG 검색
4. 위 세 경로에서 문서를 찾지 못했을 때만 Kakao 또는 Google을 URL 발견용으로 사용

검색 결과의 제목과 snippet은 근거가 아닙니다. 검색으로 발견한 경우에도 HTTPS·공식기관 allowlist를 검증한 뒤 원문을 직접 조회해야 `EvidenceRecord`가 됩니다. 네이버 검색 API는 2026-09-07 시행 약관에서 검색 결과를 AI 모델·서비스의 입력이나 개발에 사용하는 행위를 금지하므로 사용하지 않습니다([네이버 개발자센터 공지](https://developers.naver.com/notice/article/33400)).

### 1.1 `[OBSERVED_2026-09-15]` 현재 credential·접근 확인 사실

아래는 §2의 날짜 한정 실측을 요약한 것이며 생산 사용 승인이나 지속 가용성 확정이 아닙니다.

- `BIZINFO_API_KEY`: 기업마당 지원사업 API가 HTTP 200으로 동작합니다.
- `DATA_GO_KR_SERVICE_KEY`: 합성 비실사용 번호로 국세청 사업자등록 상태 API의 key/access가 HTTP 200임을 확인했습니다. 실제 사용자 상태를 조회한 것은 아닙니다.
- 같은 공공데이터 키로 행안부 휴게음식점 `15154921`과 일반음식점 `15154916` 모두 실제 목록 응답이 HTTP 200임을 확인했습니다. 승인 직후엔 일반음식점 쪽만 전파 지연으로 잠시 HTTP 403이었으나 2026-09-15 재재확인 시 정상화됐습니다.
- credential 없는 공식 공개 문서: 찾기쉬운 생활법령의 사업자·커피전문점 폐업 안내와 국민연금공단의 사업장 탈퇴 안내를 직접 조회할 수 있습니다.

다만 현재 standalone 전체 Graph의 Case와 지원사업 catalog는 합성 fixture입니다. “공식 절차 원문을 실제로 조회한다”와 “실제 사용자 Case를 저장하고 실제 지원 자격을 판정한다”는 서로 다른 완료 조건입니다. 후자는 BE 인증·소유권·개인정보 경계와 검수된 지원 catalog가 필요합니다.

## 2. `[OBSERVED_2026-09-15]` 실제 접근 시험 결과

비밀값은 출력·문서화하지 않았습니다. 같은 이름의 공공데이터 키라도 서비스별 활용신청이 별도라는 점을 반영해 결과를 해석합니다.

| 데이터 원천 | 실측 응답 | 현재 코드 연결 | 생산 판정 |
|---|---:|---|---|
| 기업마당 직접 API | HTTP 200, JSON `jsonArray` 확인 | `[CURRENT_AI]` 독립 discovery adapter | raw 후보까지만 가능. catalog 승격·Graph 연결은 미구현 |
| 국세청 사업자등록 상태 API `15081808` | 합성 비실사용 번호로 HTTP 200 | 미연결 | key/access만 확인. 실제 사용자 상태 미조회, resolver 계약 필요 |
| 행안부 휴게음식점 API `15154921` | HTTP 200, 목록 응답 확인 | 미연결 | dataset 접근만 확인. 인증된 Case exact 조회 adapter 필요 |
| 행안부 일반음식점 API `15154916` | 승인 전파 뒤 HTTP 200, 목록 응답 확인 | 미연결 | dataset 접근만 확인. 인증된 Case exact 조회 adapter 필요 |
| 행안부 제과점 API `15155252` | HTTP 403, code 30; 활용신청 없음 | 미연결 | 필요 시 활용신청 제안 |
| 공공데이터포털 기업마당 API `15157820` | HTTP 403, code 30 | 미연결 | 활용신청 제안 |
| K-Startup API `15125364` | HTTP 403, code 30 | 미연결 | 활용신청 제안 |
| 정부24 혜택 API `15113968` | HTTP 401 | 미연결 | 활용신청·승인 상태 확인 필요 |
| 찾기쉬운 생활법령 2개 문서 | HTTP 200, 본문 추출 성공 | `[CURRENT_AI]` Procedure registry | 실제 공식 원문 조회 경로 |
| 국민연금공단 사업장 탈퇴 안내 | HTTP 200, 본문 추출 성공 | `[CURRENT_AI]` Procedure registry | 직원 신호가 있는 합성 Case의 원문 조회 경로 |

`SERVICE_KEY_IS_NOT_REGISTERED_ERROR`는 기존 키 전체를 교체해야 한다는 뜻으로 해석하지 않습니다. 같은 키로 국세청 API가 성공했기 때문에 먼저 공공데이터포털에서 필요한 데이터셋별 활용신청을 해야 합니다.

## 3. API별 실측·현재 코드·도입 제안

각 하위 절의 상태 라벨이 기준입니다. 날짜 한정 접근 결과와 아직 승인되지 않은 도입안을 같은 구현 상태로 보지 않습니다.

### 3.1 `[OBSERVED_2026-09-15][PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` 사업자 상태 — 국세청 API

- 공식 안내: [국세청 사업자등록정보 진위확인 및 상태조회 서비스](https://www.data.go.kr/data/15081808/openapi.do)
- 상태 endpoint: `POST https://api.odcloud.kr/api/nts-businessman/v1/status`
- 인증: 기존 `DATA_GO_KR_SERVICE_KEY`
- 주요 결과: 사업자 상태·상태코드, 폐업일, 과세유형과 변경일
- 현재 상태: 합성 비실사용 번호로 HTTP 200과 key/access만 확인. runtime adapter와 실제 Case 조회는 미구현

이 API는 사용자의 사업장이 실제로 계속사업자인지 폐업자인지를 검증하는 API이지, 폐업 절차를 설명하는 API가 아닙니다. 호출에는 사업자등록번호가 필요합니다. 현재 `CaseSnapshot`과 BE 개인정보 계약에 해당 필드가 없으므로 Graph에 연결돼 있지 않습니다. `[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` 사업자등록번호를 자연어 prompt, 검색 query, Langfuse 원문 또는 저장소 fixture에 넣지 않고, 인증된 BE가 사용자 동의와 접근권한을 확인한 뒤 결정적 resolver에 전달하는 경계를 제안합니다.

### 3.2 `[OBSERVED_2026-09-15][PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` 카페·음식점 인허가 상태 — 행정안전부 API

카페 Case의 영업신고 상태와 관할기관은 검색보다 행안부 인허가 API가 정확합니다.

| 업종 | 공식 API | endpoint | 필요성 |
|---|---|---|---|
| 휴게음식점 | [ID 15154921](https://www.data.go.kr/data/15154921/openapi.do) | `GET https://apis.data.go.kr/1741000/rest_cafes/info`, `/history` | `[PROPOSED_SHARED]` 카페 1차 MVP 도입 후보 |
| 일반음식점 | [ID 15154916](https://www.data.go.kr/data/15154916/openapi.do) | `GET https://apis.data.go.kr/1741000/general_restaurants/info`, `/history` | `[PROPOSED_SHARED]` 주류·식사 판매 카페 도입 후보 |
| 제과점 | [ID 15155252](https://www.data.go.kr/data/15155252/openapi.do) | `GET https://apis.data.go.kr/1741000/bakeries/info`, `/history` | 제과점 신고를 겸한 경우 선택 |

핵심 응답은 관리번호, 사업장명, 영업·상세 상태, 인허가일, 폐업일, 도로명주소, 업태, 관할기관 코드와 데이터 수정시각입니다. `[OBSERVED_2026-09-15]` `15154921`(휴게음식점)과 `15154916`(일반음식점)은 목록 API의 HTTP 200 접근만 확인했습니다(§2 표 참고). 이는 실제 Case exact 조회나 생산 사용 가능 판정이 아닙니다. 제과점(`15155252`)은 같은 날짜 마이페이지 활용신청 현황에 없어 미신청 상태였습니다.

`[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` 위 두 서비스를 실제 Case에 연결한다면 BE가 인증·동의를 확인한 사업장 식별정보를 resolver 경계에서 취급하고, Agent에는 최소 상태와 Evidence 참조만 전달하는 계약을 공동 승인해야 합니다.

### 3.3 `[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` 법령·서식 — 국가법령정보 공동활용 API

- 신청 안내: [국가법령정보 공동활용](https://open.law.go.kr/LSO/information/guide.do)
- API 설명: [Open API 사용방법](https://open.law.go.kr/LSO/openApi/openApiManual.do)
- 인증: 회원가입·활용신청 후 발급되는 `OC`
- 용도: 현행 법령·조문·시행일, 부칙, 별표·서식, 자치법규 확인

법령 API는 기한과 서식의 법적 근거를 버전과 시행일에 묶는 생산 후보입니다. 현재 실제 운영용 `OC`와 resolver가 없습니다. 고정 registry만 쓰는 현재 MVP에는 필요하지 않지만 법령·조문·서식 resolver 도입을 공동 승인한다면 `LAW_API_OC`를 받아야 합니다. 샘플 인증값은 연결 형식 시험에만 사용할 수 있고 운영 근거로 쓰지 않는 안이며, 법령정보 자체를 최종 유권해석으로 취급하지 않습니다.

### 3.4 `[CURRENT_AI][OBSERVED_2026-09-15]` raw 지원사업 후보 발견 / `[TARGET_UNIMPLEMENTED]` catalog pipeline

- 공식 문서: [기업마당 지원사업정보 API](https://www.bizinfo.go.kr/apiDetail.do?id=bizinfoApi)
- endpoint: `GET https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do`
- 인증: 기존 `BIZINFO_API_KEY`
- 주요 입력: `crtfcKey`, `dataType=json`, `hashtags`, `pageUnit`, `pageIndex`
- 실제 응답 root: `jsonArray`

응답에는 공고 ID·명칭·상세 URL, 주관·수행기관, 사업 요약, 지원대상 문구, 신청기간 문구, 신청방법, 접수 URL, 생성·수정시각과 첨부 참조가 포함됩니다. 2026-09-15 실제 호출에서는 `PBLN_000000000117676`인 “2026년 희망리턴패키지 원스톱폐업지원 소상공인 모집 공고”를 포함한 폐업 관련 공고를 확인했습니다([공식 상세 페이지](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000117676)).

이 API 결과는 후보 발견과 공식 API Evidence에는 쓸 수 있지만 곧바로 `ReviewedSupportCatalog`가 될 수 없습니다. `세부사업별 상이`, `예산 소진시까지` 같은 문구를 임의 날짜로 바꾸면 안 되고, 첨부 공고문의 조건·제외대상·서류를 검수해야 합니다. 따라서 구현 경계는 다음과 같습니다.

```text
Bizinfo 공식 API
  → strict raw candidate + OFFICIAL_API Evidence
  ── [CURRENT_AI] 현재 adapter 구현 경계 ──
  ── [TARGET_UNIMPLEMENTED] 아래부터 생산 ingestion 목표 ──
  → 상세·첨부 원문 확보 및 hash/version 보존
  → 조건·서류 구조화 초안
  → 코드 검증 + 사람 검수
  → immutable ReviewedSupportCatalog
  → Support Agent read-only 비교
```

현재 adapter는 2026-09-15에 관찰한 `jsonArray`/`pblancId` shape를 strict하게 받고 schema drift 시 fail closed합니다. 한 번의 `pageIndex=1` 요청에서 최대 100건까지만 반환하며 pagination, 전체 공고 동기화, 자동 재시도, 상세·첨부 수집, RAG fallback은 구현하지 않았습니다.

### 3.5 `[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` 지원사업 보강 API

| API | 공식 문서 | 기대 장점 | 제안 상태 |
|---|---|---|---|
| 공공데이터포털 기업마당 | [ID 15157820](https://www.data.go.kr/data/15157820/openapi.do) | 공고 ID·등록/수정일 기반 증분 수집 | 활용신청 필요. 제3유형 변경금지 조건도 검토 |
| 정부24 혜택 | [ID 15113968](https://www.data.go.kr/data/15113968/openapi.do) | 지원대상·선정기준·내용·신청방법·서류·법령 제공 | 활용신청 필요. `JA1103`은 후보 필터일 뿐 자격 확정값이 아님 |
| K-Startup | [ID 15125364](https://www.data.go.kr/data/15125364/openapi.do) | 재도전·재창업 공고와 접수기간·대상·제외대상 보강 | 활용신청 필요. 마감 공고 제외 검증 필수 |
| 중소벤처24 | [지원사업정보 API 안내](https://portal.smes.go.kr/home/cs/opndata/UI_USR_L_210/supportBusinessInfoApi) | 업력·매출·지역·업종·금액·재창업 여부 등 가장 풍부 | 별도 `SMES_API_TOKEN`, 승인·IP 조건 확인 필요 |

`[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` 이 API들을 도입하면 같은 사업을 중복 반환할 수 있으므로 제목 문자열이 아니라 외부 공고 ID, 공식 URL, 수정시각과 원문 hash로 병합하는 규칙을 제안합니다.

### 3.6 현재 금지 경계와 추가 데이터 원천 제안

- `[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` [식품안전나라 Open API](https://www.foodsafetykorea.go.kr/api/main.do)는 인허가·폐업 보강 데이터가 있으나 별도 키와 공식 서비스 시간이 있어 야간 수집 보조 경로 후보입니다.
- `[PROPOSED_SHARED]` [Work24 Open API](https://www.work24.go.kr/cm/e/a/0110/selectOpenApiIntro.do)는 채용·훈련 중심이어서 사업장 보험상실 절차의 주 데이터 원천에서 제외하는 안입니다.
- `[CURRENT_AI]` 현재 Agent에는 정부24·홈택스·4대사회보험정보연계센터의 실제 신고를 실행하는 기능이나 credential이 없습니다. `[PROPOSED_SHARED]` 생산에서도 본인인증·개인정보가 필요한 신고는 사용자 행위로 두고 Agent는 방법과 링크만 안내하는 경계를 제안합니다.

## 4. `[CURRENT_AI]` credential 없는 절차조회

현재 `ProcedureLookupTool`은 코드 리뷰된 공식 출처 registry를 1순위로 사용합니다.

| Case 신호 | 직접 조회 문서 | 이유 |
|---|---|---|
| 사업자·세무 폐업 | [찾기쉬운 생활법령의 휴업·폐업신고](https://www.easylaw.go.kr/CSP/CnpClsMain.laf?ccfNo=2&cciNo=1&cnpClsNo=2&csmSeq=25&popMenu=ov) | 신고 대상·방법과 법령 연결을 공개 콘텐츠에서 확인 |
| 카페·휴게음식점 | [커피전문점 폐업 신고](https://www.easylaw.go.kr/CSP/CnpClsMainBtr.laf?ccfNo=5&cciNo=1&cnpClsNo=1&csmSeq=706&popMenu=ov) | 제품 대상인 커피전문점의 영업신고·사업자등록 폐업을 함께 설명 |
| 직원·4대보험 | [국민연금 사업장 탈퇴 안내](https://www.nps.or.kr/pnsinfo/ntpsklg/getOHAF0006M0.do?menuId=MN24001107&tab=tab10) | 폐업 사업장의 탈퇴 대상·신고자·기한·서류를 공식 기관이 제공 |

찾기쉬운 생활법령은 [저작권 정책](https://www.easylaw.go.kr/CSP/AboutCopyright.laf?topMenu=introUl3)에 따라 출처와 원문 URL을 보존해 활용할 수 있는 경로가 비교적 명확합니다. 모든 excerpt는 `freshness_status=UNKNOWN`으로 시작하며, 페이지 안에서 발행·검토일을 별도 검증하는 resolver가 생기기 전에는 기한·서류를 확정형으로 만들지 않습니다.

국민연금공단 페이지는 현재 최소 본문을 요청시 직접 읽는 경로로만 사용합니다. 재사용·장기 저장 조건을 별도로 확정하지 않았으므로 출처와 링크를 유지한 직접 조회는 허용하되, 원문 전체의 영구 저장·RAG corpus 편입은 이용조건 확인 전까지 제외합니다.

정부24 HTML은 일부 공개 페이지가 기술적으로 열리더라도 구 도메인의 [robots.txt](https://www.gov.kr/robots.txt), 현행 Plus 정부24의 [robots.txt](https://plus.gov.kr/robots.txt), [저작권 정책](https://plus.gov.kr/portal/scrtycntr/prtcplcy/)을 함께 고려하면 대량 수집·원문 영구 저장의 이용 경계가 불명확합니다. 그래서 고정 registry와 RAG 수집원에서는 제외하고 공식 API 또는 재사용 조건이 명확한 문서를 사용합니다. `robots.txt` 허용은 저작권 허락이 아니며, 공공누리 표시는 자동수집 허락과도 별개입니다.

## 5. `[CURRENT_AI]` 현재 검색 fallback 위치

직접 registry가 질의를 처리하지 못하면 선택적으로 다음 순서로 URL만 발견합니다.

```text
OFFICIAL_SOURCE_REGISTRY
  → Kakao Daum 웹문서 검색
  → Google Agent Search searchLite
  → HTTPS·공식 domain 검증
  → 원문 직접 fetch
```

Kakao와 Google key가 없어도 현재 카페 MVP의 세 고정 절차는 조회됩니다. 검색 provider는 새 공식 문서를 발견하는 보조 수단이므로 필수가 아닙니다. Google HTML SERP scraping, 검색결과 snippet의 Evidence 승격, Naver 검색 결과의 AI 입력은 허용하지 않습니다.

## 6. `[TARGET_UNIMPLEMENTED]` 크롤링·RAG 도입 기준

RAG는 현재 구현돼 있지 않습니다. 도입할 경우 인터넷에서 자료를 가져오는 API로 취급하지 않고, 먼저 허용된 공식 API나 공식 문서를 수집한 뒤 원문을 검색 가능하게 색인해야 한다는 acceptance criteria입니다.

각 원문과 chunk에는 최소한 다음 metadata를 보존합니다.

- 기관명과 원문 URL
- API·직접 조회 등 수집 방식
- 외부 문서·공고 ID
- 공공누리/저작권 유형과 이용 검토 상태
- 게시일·개정일·시행일·수집일을 서로 구분한 값
- 전체 원문 content hash와 source version
- parser 버전과 chunk가 가리키는 원문 locator

수집 허용 범위는 다음처럼 운영합니다.

- 우선: 국가법령정보 공식 API, 찾기쉬운 생활법령, 이용조건이 확인된 data.go.kr API
- 조건부: 자료별 공공누리 유형이 확인된 국세청·소상공인 관련 콘텐츠
- 제외: 정부24 대량 HTML, SEMAS 본사이트, 홈택스·4insure·소상공인24의 로그인/검색/마이페이지, 개인정보·사용자 제출 문서

RAG 검색 결과도 원문 Evidence를 대신하지 않습니다. 답변에 쓰는 claim은 원문 ID·hash·locator까지 역추적돼야 하며, stale 또는 license 미확인 문서는 확정 판단에 쓰지 않습니다.

## 7. `[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` 역할별 준비 요청

아래는 구현 지시나 합의 완료 목록이 아니라 담당자별 검토·승인 요청입니다.

| 준비 항목 | 현재 근거 | 제안 소유자 | 확정 필요 주체 |
|---|---|---|---|
| 휴게음식점 `15154921`·일반음식점 `15154916` read-only adapter | `[OBSERVED_2026-09-15]` 목록 HTTP 200만 확인 | AI | AI·BE |
| 인증된 식별정보 resolver, 동의·암호화·마스킹·감사 | 현재 코드·계약 없음 | BE | BE·보안/PM |
| `LAW_API_OC` 신청과 법령·서식 resolver | 운영 key·adapter 없음; registry-only에는 불필요 | AI/운영 | AI·BE |
| `15157820`·`15113968`·`15125364` 활용신청 | 미승인 또는 접근 실패 실측 | 운영/BE | PM·운영 |
| 중소벤처24·식품안전나라 선택 보강 | token/key와 adapter 없음 | AI/운영 | PM·AI |
| 공식 원문 저장·검수·catalog version 발행 | 현재 raw discovery 뒤 pipeline 없음 | AI·데이터 운영 | AI·BE·PM |

`[CURRENT_AI]` 기존 `BIZINFO_API_KEY`는 독립 discovery adapter가 소비합니다. `[OBSERVED_2026-09-15]` 기존 `DATA_GO_KR_SERVICE_KEY`는 일부 API 접근이 확인됐지만 현재 Agent Graph가 소비하지 않습니다. 어떤 추가 서비스 권한을 신청하고 생산 resolver를 열지는 위 표에 따라 별도 승인해야 하며 Kakao·Google·Naver 검색 key는 필수 준비물이 아닙니다.

## 8. 현재 사실과 미구현 목표

| 항목 | 상태 라벨 | 근거 또는 남은 것 |
|---|---|---|
| 공식 절차 직접 조회 | `[CURRENT_AI][OBSERVED_2026-09-15]` | 코드 구현과 허용 문서 실호출 확인 |
| 검색 없는 카페 핵심 절차 조회 | `[CURRENT_AI]` | 고정 official registry 경로 |
| 기업마당 실제 공고 discovery | `[CURRENT_AI][OBSERVED_2026-09-15]` | 기존 key로 raw 후보 API 접근; 자격 판정 아님 |
| 실제 사업자 상태 확인 | `[TARGET_UNIMPLEMENTED]` | key 접근만 관찰; 인증된 사업자번호 전달 계약 없음 |
| 행안부 인허가 dataset 접근 | `[OBSERVED_2026-09-15]` | 두 목록 API HTTP 200; 실제 Case 조회·adapter는 미구현 |
| 실제 사용자 카페 인허가 확인 | `[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` | 인증·소유권·동의가 결합된 exact resolver 필요 |
| 법령 API 보강 | `[TARGET_UNIMPLEMENTED]` | 운영용 `LAW_API_OC`와 resolver 없음 |
| 실제 지원 자격 비교 | `[TARGET_UNIMPLEMENTED]` | raw 공고를 검수 catalog로 승격하는 pipeline 없음 |
| 실제 사용자 Case read/write | `[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` | BE 인증·소유권·DB 계약 없음 |
| 공식 원문 RAG | `[TARGET_UNIMPLEMENTED]` | 수집 허용목록·저장소·parser·검수 pipeline 없음 |

### API 장애 시 fallback의 현재와 목표

| 상황 | 현재 동작 | 안전한 다음 구현 |
|---|---|---|
| Kakao/Google key 없음·검색 장애 | 고정 official registry가 먼저 동작하므로 카페 핵심 3개 문서는 계속 조회 | registry coverage와 version 검증 확대 |
| registry URL 원문 fetch 실패 | snippet으로 대체하지 않고 `PARTIAL`/warning; 같은 질의 재검색은 아직 없음 | 다음 승인 provider 재검색과 cache 재검증을 bounded하게 구현 |
| 기업마당 API 장애·schema drift | 안전한 오류로 종료; 포털 HTML을 자동 크롤링하지 않음 | 승인된 이전 catalog를 stale로 표시하거나 운영 재수집 |
| 정형 API가 제공되지 않는 공식 자료 | 현재는 코드 검토된 고정 URL만 직접 조회 | 이용조건·robots·공공누리 검토 → versioned 수집 → parser 검수 → RAG 색인 |

크롤링이나 RAG는 API 오류를 숨기기 위한 무조건 fallback이 아닙니다. 취득 권한이 확인된 공식 원문, 출처·hash·시행일 metadata, 삭제/재검증 정책, 저장소와 vector index가 모두 준비된 corpus에만 적용합니다.

따라서 `[CURRENT_AI]` 현재 실제로 되는 것은 공식 절차 원문 조회와 기업마당 공고 후보 조회입니다. `[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` 실제 사용자 Case의 상태·인허가·지원 자격을 운영하려면 위 활용신청과 공동 BE 경계를 먼저 승인하고 구현해야 합니다.
