# RE:BORN 공식 API·크롤링·RAG 데이터 소스 전략

> 상태: 2026-09-15 실조사·실호출 기준
>
> 소유: AI. 인증·개인정보·저장·운영 권한은 BE와 공동 확정
>
> 범위: 임차형 소규모 카페 폐업 Case의 절차와 지원사업. 전 업종 확장 문서가 아님

## 1. 결론

아래 순서는 **목표 데이터 획득 전략**입니다. 현재 구현 범위는 공식 source registry의 제한적 직접 조회와 기업마당 단일-page discovery이며, 범용 크롤러·영구 corpus·vector RAG는 아직 없습니다.

RE:BORN은 검색 포털을 주 데이터 원천으로 쓰지 않습니다. 목표 우선순위는 다음과 같습니다.

1. 정형 공식 API
2. 코드 리뷰로 승인한 공식 공개 문서의 제한적 직접 조회
3. 적법하게 수집·버전 관리한 공식 원문의 RAG 검색
4. 위 세 경로에서 문서를 찾지 못했을 때만 Kakao 또는 Google을 URL 발견용으로 사용

검색 결과의 제목과 snippet은 근거가 아닙니다. 검색으로 발견한 경우에도 HTTPS·공식기관 allowlist를 검증한 뒤 원문을 직접 조회해야 `EvidenceRecord`가 됩니다. 네이버 검색 API는 2026-09-07 시행 약관에서 검색 결과를 AI 모델·서비스의 입력이나 개발에 사용하는 행위를 금지하므로 사용하지 않습니다([네이버 개발자센터 공지](https://developers.naver.com/notice/article/33400)).

현재 credential·접근 가능성을 확인한 것은 다음 네 경로입니다.

- `BIZINFO_API_KEY`: 기업마당 지원사업 API가 HTTP 200으로 동작합니다.
- `DATA_GO_KR_SERVICE_KEY`: 합성 비실사용 번호로 국세청 사업자등록 상태 API의 key/access가 HTTP 200임을 확인했습니다. 실제 사용자 상태를 조회한 것은 아닙니다.
- 같은 공공데이터 키로 행안부 휴게음식점 `15154921`과 일반음식점 `15154916` 모두 실제 목록 응답이 HTTP 200임을 확인했습니다. 승인 직후엔 일반음식점 쪽만 전파 지연으로 잠시 HTTP 403이었으나 2026-09-15 재재확인 시 정상화됐습니다.
- credential 없는 공식 공개 문서: 찾기쉬운 생활법령의 사업자·커피전문점 폐업 안내와 국민연금공단의 사업장 탈퇴 안내를 직접 조회할 수 있습니다.

다만 현재 standalone 전체 Graph의 Case와 지원사업 catalog는 합성 fixture입니다. “공식 절차 원문을 실제로 조회한다”와 “실제 사용자 Case를 저장하고 실제 지원 자격을 판정한다”는 서로 다른 완료 조건입니다. 후자는 BE 인증·소유권·개인정보 경계와 검수된 지원 catalog가 필요합니다.

## 2. 실제 접근 시험 결과

비밀값은 출력·문서화하지 않았습니다. 같은 이름의 공공데이터 키라도 서비스별 활용신청이 별도라는 점을 반영해 결과를 해석합니다.

| 데이터 원천 | 실제 결과 | 판정 |
|---|---:|---|
| 기업마당 직접 API | HTTP 200, JSON `jsonArray` 확인 | 기존 키로 즉시 사용 가능 |
| 국세청 사업자등록 상태 API `15081808` | 합성 비실사용 번호로 HTTP 200 | 기존 키와 이 서비스 접근만 확인; 실제 사용자 상태 미조회 |
| 행안부 휴게음식점 API `15154921` | 2026-09-15 재확인: HTTP 200, `rest_cafes/info` 실제 사업장 레코드 반환(예: "카페봄봄제주연동점", 영업상태 등, 전국 646,714건) | 활용신청 승인 완료, 실사용 가능 |
| 행안부 일반음식점 API `15154916` | 2026-09-15 재확인: 승인 직후 한때 `general_restaurants/info` HTTP 403(`SERVICE_KEY_IS_NOT_REGISTERED_ERROR`)이었으나, 재재확인 시 HTTP 200으로 실제 사업장 레코드 반환(예: "낭불갈비", 전국 2,297,081건) | 활용신청 승인·전파 완료, 실사용 가능 |
| 행안부 제과점 API `15155252` | HTTP 403, code 30. 2026-09-15 마이페이지 활용신청 현황에도 없음(미신청) | 제과업을 함께 다룰 때 선택 신청 |
| 공공데이터포털 기업마당 API `15157820` | HTTP 403, code 30 | 이 서비스 활용신청 필요 |
| K-Startup API `15125364` | HTTP 403, code 30 | 이 서비스 활용신청 필요 |
| 정부24 혜택 API `15113968` | HTTP 401 | 해당 서비스 활용신청·승인 상태 확인 필요 |
| 찾기쉬운 생활법령 2개 문서 | HTTP 200, 본문 추출 성공 | 절차조회 Tool의 credential 없는 1순위 |
| 국민연금공단 사업장 탈퇴 안내 | HTTP 200, 본문 추출 성공 | 직원이 있는 Case의 제한적 직접 조회 가능 |

`SERVICE_KEY_IS_NOT_REGISTERED_ERROR`는 기존 키 전체를 교체해야 한다는 뜻으로 해석하지 않습니다. 같은 키로 국세청 API가 성공했기 때문에 먼저 공공데이터포털에서 필요한 데이터셋별 활용신청을 해야 합니다.

## 3. API별 역할과 도입 판단

### 3.1 사업자 상태 — 국세청 API

- 공식 안내: [국세청 사업자등록정보 진위확인 및 상태조회 서비스](https://www.data.go.kr/data/15081808/openapi.do)
- 상태 endpoint: `POST https://api.odcloud.kr/api/nts-businessman/v1/status`
- 인증: 기존 `DATA_GO_KR_SERVICE_KEY`
- 주요 결과: 사업자 상태·상태코드, 폐업일, 과세유형과 변경일
- 현재 상태: 합성 비실사용 번호로 HTTP 200과 key/access만 확인. runtime adapter와 실제 Case 조회는 미구현

이 API는 사용자의 사업장이 실제로 계속사업자인지 폐업자인지를 검증하는 API이지, 폐업 절차를 설명하는 API가 아닙니다. 호출에는 사업자등록번호가 필요합니다. 사업자등록번호를 자연어 prompt, 검색 query, Langfuse 원문 또는 저장소 fixture에 넣지 않고, 인증된 BE가 사용자 동의와 접근권한을 확인한 뒤 결정적 Tool에 전달해야 합니다. 현재 `CaseSnapshot`과 BE 개인정보 계약에 해당 필드가 없으므로 Graph에 바로 연결하지 않습니다.

### 3.2 카페·음식점 인허가 상태 — 행정안전부 API

카페 Case의 영업신고 상태와 관할기관은 검색보다 행안부 인허가 API가 정확합니다.

| 업종 | 공식 API | endpoint | 필요성 |
|---|---|---|---|
| 휴게음식점 | [ID 15154921](https://www.data.go.kr/data/15154921/openapi.do) | `GET https://apis.data.go.kr/1741000/rest_cafes/info`, `/history` | 카페 1차 MVP 필수 |
| 일반음식점 | [ID 15154916](https://www.data.go.kr/data/15154916/openapi.do) | `GET https://apis.data.go.kr/1741000/general_restaurants/info`, `/history` | 주류·식사 판매 카페를 위해 필수 |
| 제과점 | [ID 15155252](https://www.data.go.kr/data/15155252/openapi.do) | `GET https://apis.data.go.kr/1741000/bakeries/info`, `/history` | 제과점 신고를 겸한 경우 선택 |

핵심 응답은 관리번호, 사업장명, 영업·상세 상태, 인허가일, 폐업일, 도로명주소, 업태, 관할기관 코드와 데이터 수정시각입니다. 2026-09-15 재확인 결과 `15154921`(휴게음식점)과 `15154916`(일반음식점) 모두 실호출 HTTP 200으로 사용 가능합니다(§2 표 참고). 제과점(`15155252`)은 2026-09-15 마이페이지 활용신청 현황에 없어 아직 신청조차 안 된 상태입니다. 승인·실호출이 모두 확인된 두 서비스부터 BE가 보유한 인증된 사업장 식별정보로 조회하고, Agent에는 최소한의 상태와 Evidence 참조만 전달해야 합니다.

### 3.3 법령·서식 — 국가법령정보 공동활용 API

- 신청 안내: [국가법령정보 공동활용](https://open.law.go.kr/LSO/information/guide.do)
- API 설명: [Open API 사용방법](https://open.law.go.kr/LSO/openApi/openApiManual.do)
- 인증: 회원가입·활용신청 후 발급되는 `OC`
- 용도: 현행 법령·조문·시행일, 부칙, 별표·서식, 자치법규 확인

법령 API는 기한과 서식의 법적 근거를 버전과 시행일에 묶을 수 있어 장기적으로 Procedure Evidence의 가장 안정적인 원천입니다. 현재 실제 운영용 `OC`가 없습니다. 고정 registry만 쓰는 현재 MVP에는 필요하지 않지만 법령·조문·서식 resolver를 도입할 때는 `LAW_API_OC`를 받아야 합니다. 샘플 인증값은 연결 형식 시험에만 사용할 수 있고 운영 근거로 쓰지 않습니다. 법령정보는 유권해석 자체가 아니므로 Agent는 최종 법률 판단을 확정하지 않습니다.

### 3.4 지원사업 후보 발견 — 기업마당 API

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
  → 상세·첨부 원문 확보 및 hash/version 보존
  → 조건·서류 구조화 초안
  → 코드 검증 + 사람 검수
  → immutable ReviewedSupportCatalog
  → Support Agent read-only 비교
```

현재 adapter는 2026-09-15에 관찰한 `jsonArray`/`pblancId` shape를 strict하게 받고 schema drift 시 fail closed합니다. 한 번의 `pageIndex=1` 요청에서 최대 100건까지만 반환하며 pagination, 전체 공고 동기화, 자동 재시도, 상세·첨부 수집, RAG fallback은 구현하지 않았습니다.

### 3.5 지원사업 보강 API

| API | 공식 문서 | 장점 | 현재 조치 |
|---|---|---|---|
| 공공데이터포털 기업마당 | [ID 15157820](https://www.data.go.kr/data/15157820/openapi.do) | 공고 ID·등록/수정일 기반 증분 수집 | 활용신청 필요. 제3유형 변경금지 조건도 검토 |
| 정부24 혜택 | [ID 15113968](https://www.data.go.kr/data/15113968/openapi.do) | 지원대상·선정기준·내용·신청방법·서류·법령 제공 | 활용신청 필요. `JA1103`은 후보 필터일 뿐 자격 확정값이 아님 |
| K-Startup | [ID 15125364](https://www.data.go.kr/data/15125364/openapi.do) | 재도전·재창업 공고와 접수기간·대상·제외대상 보강 | 활용신청 필요. 마감 공고 제외 검증 필수 |
| 중소벤처24 | [지원사업정보 API 안내](https://portal.smes.go.kr/home/cs/opndata/UI_USR_L_210/supportBusinessInfoApi) | 업력·매출·지역·업종·금액·재창업 여부 등 가장 풍부 | 별도 `SMES_API_TOKEN`, 승인·IP 조건 확인 필요 |

이 API들은 같은 사업을 중복 반환할 수 있습니다. 제목 문자열이 아니라 외부 공고 ID, 공식 URL, 수정시각과 원문 hash로 병합합니다.

### 3.6 식품안전나라·Work24·신고 사이트

- [식품안전나라 Open API](https://www.foodsafetykorea.go.kr/api/main.do)는 인허가·폐업 보강 데이터가 있으나 별도 키와 공식 서비스 시간이 있어 실시간 주 경로보다 야간 수집 보조 경로에 적합합니다.
- [Work24 Open API](https://www.work24.go.kr/cm/e/a/0110/selectOpenApiIntro.do)는 채용·훈련 중심이어서 사업장 보험상실 절차의 주 데이터 원천으로 쓰지 않습니다.
- 정부24·홈택스·4대사회보험정보연계센터의 실제 신고 기능은 본인인증·공동인증서와 개인정보가 필요한 사용자 행위입니다. Agent는 방법과 링크를 안내할 뿐 신고를 대신 실행하지 않습니다.

## 4. credential 없는 절차조회

현재 `ProcedureLookupTool`은 코드 리뷰된 공식 출처 registry를 1순위로 사용합니다.

| Case 신호 | 직접 조회 문서 | 이유 |
|---|---|---|
| 사업자·세무 폐업 | [찾기쉬운 생활법령의 휴업·폐업신고](https://www.easylaw.go.kr/CSP/CnpClsMain.laf?ccfNo=2&cciNo=1&cnpClsNo=2&csmSeq=25&popMenu=ov) | 신고 대상·방법과 법령 연결을 공개 콘텐츠에서 확인 |
| 카페·휴게음식점 | [커피전문점 폐업 신고](https://www.easylaw.go.kr/CSP/CnpClsMainBtr.laf?ccfNo=5&cciNo=1&cnpClsNo=1&csmSeq=706&popMenu=ov) | 제품 대상인 커피전문점의 영업신고·사업자등록 폐업을 함께 설명 |
| 직원·4대보험 | [국민연금 사업장 탈퇴 안내](https://www.nps.or.kr/pnsinfo/ntpsklg/getOHAF0006M0.do?menuId=MN24001107&tab=tab10) | 폐업 사업장의 탈퇴 대상·신고자·기한·서류를 공식 기관이 제공 |

찾기쉬운 생활법령은 [저작권 정책](https://www.easylaw.go.kr/CSP/AboutCopyright.laf?topMenu=introUl3)에 따라 출처와 원문 URL을 보존해 활용할 수 있는 경로가 비교적 명확합니다. 모든 excerpt는 `freshness_status=UNKNOWN`으로 시작하며, 페이지 안에서 발행·검토일을 별도 검증하는 resolver가 생기기 전에는 기한·서류를 확정형으로 만들지 않습니다.

국민연금공단 페이지는 현재 최소 본문을 요청시 직접 읽는 경로로만 사용합니다. 재사용·장기 저장 조건을 별도로 확정하지 않았으므로 출처와 링크를 유지한 직접 조회는 허용하되, 원문 전체의 영구 저장·RAG corpus 편입은 이용조건 확인 전까지 제외합니다.

정부24 HTML은 일부 공개 페이지가 기술적으로 열리더라도 구 도메인의 [robots.txt](https://www.gov.kr/robots.txt), 현행 Plus 정부24의 [robots.txt](https://plus.gov.kr/robots.txt), [저작권 정책](https://plus.gov.kr/portal/scrtycntr/prtcplcy/)을 함께 고려하면 대량 수집·원문 영구 저장의 이용 경계가 불명확합니다. 그래서 고정 registry와 RAG 수집원에서는 제외하고 공식 API 또는 재사용 조건이 명확한 문서를 사용합니다. `robots.txt` 허용은 저작권 허락이 아니며, 공공누리 표시는 자동수집 허락과도 별개입니다.

## 5. 검색 API의 정확한 위치

직접 registry가 질의를 처리하지 못하면 선택적으로 다음 순서로 URL만 발견합니다.

```text
OFFICIAL_SOURCE_REGISTRY
  → Kakao Daum 웹문서 검색
  → Google Agent Search searchLite
  → HTTPS·공식 domain 검증
  → 원문 직접 fetch
```

Kakao와 Google key가 없어도 현재 카페 MVP의 세 고정 절차는 조회됩니다. 검색 provider는 새 공식 문서를 발견하는 보조 수단이므로 필수가 아닙니다. Google HTML SERP scraping, 검색결과 snippet의 Evidence 승격, Naver 검색 결과의 AI 입력은 허용하지 않습니다.

## 6. 크롤링과 RAG 정책

RAG는 인터넷에서 자료를 가져오는 API가 아닙니다. 먼저 허용된 공식 API나 공식 문서를 수집하고, 그 원문을 검색 가능하게 색인하는 단계입니다.

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

## 7. 사용자에게 필요한 준비

### 실제 카페 인허가 연동에 필요한 권한 확인과 구현

1. 휴게음식점 API `15154921` — 2026-09-15 승인·실호출 확인 완료, read-only adapter 구현 필요
2. 일반음식점 API `15154916` — 승인 직후의 HTTP 403은 전파 뒤 해소되었고 2026-09-15 HTTP 200 재확인 완료, read-only adapter 구현 필요

법령·서식 resolver까지 도입할 때는 국가법령정보 공동활용 신청 후 운영용 `LAW_API_OC`도 필요합니다. 현재 고정 registry만 실행할 때는 필수가 아닙니다.

### 지원사업 정확도를 높일 때 필요한 신청

1. 공공데이터포털 `15157820`, `15113968`, `15125364` 활용신청
2. 더 정교한 구조화 조건이 필요하면 중소벤처24 `SMES_API_TOKEN` 신청
3. 식품안전나라를 야간 보조 수집원으로 쓸 경우 별도 API key 신청

### 키가 아니라 BE 계약이 필요한 값

- 사업자등록번호와 인허가 관리번호의 저장 위치·암호화·마스킹·동의 방식
- 인증된 Case에서만 위 식별자를 Tool에 전달하는 read-only resolver
- 외부 API에 어떤 필드를 언제 보냈는지 남기는 감사 기록
- 공식 원문 저장·검수·버전 승격 절차

기존 `BIZINFO_API_KEY`와 `DATA_GO_KR_SERVICE_KEY`는 폐기하지 않습니다. 전자는 즉시 지원 공고 discovery에 사용하고, 후자는 국세청 상태조회에 사용하면서 필요한 공공데이터 서비스 권한을 추가합니다. Kakao·Google·Naver 검색 key는 필수 준비물이 아닙니다.

## 8. 완료 기준과 현재 남은 제한

| 항목 | 현재 상태 |
|---|---|
| 공식 절차 직접 조회 | 구현·실호출 성공 |
| 검색 없는 카페 핵심 절차 조회 | 가능 |
| 기업마당 실제 공고 discovery | 기존 key로 API 접근 성공 |
| 실제 사업자 상태 확인 | API key는 동작하지만 인증된 사업자번호 전달 계약 미구현 |
| 실제 카페 인허가 확인 | 휴게음식점(`15154921`)·일반음식점(`15154916`) 둘 다 승인·실호출 성공. 조회 adapter는 아직 미구현 |
| 법령 API 보강 | 운영용 `LAW_API_OC` 미발급 |
| 실제 지원 자격 비교 | raw 공고를 검수 catalog로 승격하는 ingestion/review 단계 미구현 |
| 실제 사용자 Case read/write | BE 인증·소유권·DB 계약 미구현 |
| 공식 원문 RAG | 수집 허용목록·저장소·parser·검수 pipeline 미구현 |

### API 장애 시 fallback의 현재와 목표

| 상황 | 현재 동작 | 안전한 다음 구현 |
|---|---|---|
| Kakao/Google key 없음·검색 장애 | 고정 official registry가 먼저 동작하므로 카페 핵심 3개 문서는 계속 조회 | registry coverage와 version 검증 확대 |
| registry URL 원문 fetch 실패 | snippet으로 대체하지 않고 `PARTIAL`/warning; 같은 질의 재검색은 아직 없음 | 다음 승인 provider 재검색과 cache 재검증을 bounded하게 구현 |
| 기업마당 API 장애·schema drift | 안전한 오류로 종료; 포털 HTML을 자동 크롤링하지 않음 | 승인된 이전 catalog를 stale로 표시하거나 운영 재수집 |
| 정형 API가 제공되지 않는 공식 자료 | 현재는 코드 검토된 고정 URL만 직접 조회 | 이용조건·robots·공공누리 검토 → versioned 수집 → parser 검수 → RAG 색인 |

크롤링이나 RAG는 API 오류를 숨기기 위한 무조건 fallback이 아닙니다. 취득 권한이 확인된 공식 원문, 출처·hash·시행일 metadata, 삭제/재검증 정책, 저장소와 vector index가 모두 준비된 corpus에만 적용합니다.

따라서 현재 실제로 되는 것은 공식 절차 원문 조회와 기업마당 공고 후보 조회입니다. 실제 사용자 Case를 대상으로 한 상태 확인·인허가 확인·지원 자격 비교까지 정상 운영하려면 위 활용신청과 BE 경계가 추가로 필요합니다.
