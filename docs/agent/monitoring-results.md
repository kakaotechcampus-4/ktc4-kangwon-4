# Agent 모니터링과 모델 최적화 기록

2026년 11월 1일 개인 카페 폐업 시안에 맞춘 Agent와 실제 LLM 호출을 검증했고, 11월 2일 Langfuse 모니터링 조회 기능을 추가했다. 같은 입력으로 모델과 추론 강도인 `effort`를 바꿔 품질·토큰·시간·비용을 비교한다. 아래 수치는 합성 입력에 대한 결과이며, 실제 고객 서류의 정확도나 전체 서비스의 응답 속도로 일반화하지 않는다.

## 코드 기준과 변경 범위

- 작업 브랜치: `feature/agent-monitoring-mobile`
- 현재 기준 커밋: `2c6a574140b63cf31635f6e4497e637e84a10cbc` (PR 120 머지). 이전 측정의 기준 `d630255...`는 각 원본 기록에 보존한다.
- [PR 115](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/115)의 실제 변경 커밋 `c958b2201431bc81714100fd9076cb1f06a12708`과 [PR 114](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/114)를 포함한다.
- [PR 118](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/118)과 [PR 120](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/120)의 head가 현재 HEAD의 조상임을 확인했다. 원격 변경은 FE 40개 파일뿐이며 fast-forward로 반영했고, 기존 수정 파일 73개는 바이트가 모두 유지됐다. FE를 별도로 수정하지 않았다.
- 기존 `preserve/readme-and-procedure-store-test` 작업 폴더는 수정 중이던 내용을 보존했다. 최신 기준 작업은 옆의 `ktc4-kangwon-4-agent-monitoring` 폴더에 있다.
- 사용자 요청에 따라 모니터링 구현 #121, 문서 Tool #128, 평가 원본 #130 세 개로 나눴다. 커밋과 PR 제목은 [AI]를 사용하며 리뷰어를 지정하지 않는다.
- FE, `app/be`, `app/common`, DB 스키마와 `CLAUDE.md`는 수정하지 않는다. Agent, 관련 평가·테스트, 환경설정과 이 기록을 변경한다.

## 게시한 PR

| PR | 범위 | 대상 브랜치 |
| --- | --- | --- |
| [#121](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/121) | 추적·조회·모델/effort·비용 계산·입력 보호·실행/테스트·측정 결과와 분석 | develop |
| [#128](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/128) | 문서 Tool 계약·로컬 처리·추출·확인·6단계 점검·ZIP·일괄 실행 | feature/agent-observability (#121) |
| [#130](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/130) | 평가 JSON/CSV·합성 입력·검증 로그 원본 51개 | develop |

JSON·CSV는 실제 고객 제출 서류 원본이 아니라 합성 평가 입력과 호출·관측 기록이다. 생성한 PDF/PNG·가림 PDF·ZIP과 내려받은 공식 빈 양식은 기존 eval-runs에 보존하며 Git에 새로 올리지 않는다. 모니터링 결과·분석은 #121에, 요청별 원본은 #130에 둬 구현과 결과를 함께 검토하고 원본은 따로 대조한다.

문서 Tool은 모니터링의 공통 LLM client·계산을 사용하므로 #121 병합 후 #128의 base를 develop으로 바꾸면 된다. 기록 PR은 독립적으로 검토할 수 있다. 모니터링 테스트는 원본 JSON 없이 기존 합성 입력 생성 함수를 사용한다. 실제 평가를 재현할 때는 기록 PR의 데이터 또는 `--inputs`로 지정한 데이터를 사용한다.

## 정확도 우선 재검증과 문서 모델 승격

초기 Luna6 high 스캔 실패 후 낮은 effort 비교만 중단하고 사용자 확인을 전제로 기본값을 유지한 것은 정확도 기준이 부족했다. 기존 OCR 텍스트로 Luna6 xhigh와 Sol xhigh를 각각 실제 호출했지만 세금계산서의 필수 값이 여전히 누락됐다. 원문 OCR부터 이름·날짜가 빠지고 금액이 잘못 읽힌 것이 원인이었다. DPI/전체 페이지 OCR·best 언어파일·분할 OCR도 일관되게 해결하지 못했다.

기존 client가 지원하는 이미지 입력으로, 식별번호를 가린 별도 사본을 Sol xhigh가 판독하도록 문서 Tool을 보완했다. 독립 Review도 같은 가림 이미지와 값을 대조한다. 모델용 사본은 주민번호 전체와 로컬에서 탐지한 식별번호를 가리고, 제출 파일의 가림 정책과 구분한다. 판독 실패 시 불완전한 로컬 OCR로 조용히 돌아가지 않는다. 현재 문서 추출·이미지 판독·Review는 모두 gpt-6.1-sol xhigh다. 기존 Info high와 Supervisor Luna6 high는 유지한다.

| 실제 실행 | 요청 | 총 토큰 | 추정 비용 | 시간 | 자동 필수 값 |
| --- | ---: | ---: | ---: | ---: | --- |
| 기존 OCR + Luna6 xhigh, 세금계산서1개 |3|2,601|8.300748원|18.856초|실패|
| 기존 OCR + Sol xhigh, 같은1개 |3|2,532|15.955380원|14.400초|실패|
| 가림 이미지 판독 Sol xhigh, 같은1개 |4|6,790|31.031910원|18.311초|통과|
| Sol xhigh 일반 PDF7개 |15|12,178|65.698290원|57.458초|통과|
| Sol xhigh 스캔7개 반복1 |20|33,554|153.833886원|99.983초|통과|
| Sol xhigh 스캔7개 반복2 |20|34,185|140.972439원|108.116초|통과|
| Sol xhigh 스캔7개 반복3 |20|34,237|142.215207원|116.719초|통과|

스캔 각 실행에서5개 서류의 필수 값14개가 일치했다(3회42개 검사 통과). 사진2개는 종류 힌트를 준 합성 자리표시자다. 사용자 값 수정은0건이며 확인은 안전장치로 유지한다. 각 실행에서 이체확인증 누락·추가 파일만 분석·같은 파일 재업로드0호출·ZIP9항목을 확인했다. 실제 고객 서류 정확도로 일반화하지 않는다.

스캔 실행당 평균은33,992토큰·145.673844원·108.273초다. 초기42.667962원 실행은 자동 필수 값 검증에 실패했으므로 이 비용 차이를 같은 품질의 최적화 비교로 보지 않는다. 이번에는 정확도를 우선해 강한 모델과 이미지 판독의 추가 비용을 수용했다. 더 낮은 모델/effort는 이 품질 기준을 통과한 뒤 비교한다.

통장 이미지 기능 파일럿1회까지 포함한 이번 추가 검증 전체는86회·128,020토큰·추정565.818285원이다. 성공뿐 아니라 기존 OCR 실패와 중간 파일럿을 포함했다. 실제 모델과 별도로 자동 테스트622개가30.68초에 통과했고, 모델용 이미지에서 주민번호 앞/뒤 모두 판독되지 않는 것을 오프라인으로 확인했다. 새 API 키나 이미지 처리 의존성은 추가하지 않았다.

[실제 요청별 사용량·실패·필드별 결과·코드 지문 원본](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-02-document-quality.json)은 #130, 문서 구현과 상세 결과는 #128에서 확인한다. 아래 이전 측정은 당시의 결과로 보존한다.

## 현재 담당 범위와 구현

사용자의 최신 지시 **“일단 구현하고 pr올리자 구현해”**, **“Agent 기능과 호출 계약을 완성해 PR (기존 범위 유지)”**에 따라 문서 Tool를 구현했다. 이전 PM 대기 지시는 이 요청으로 변경됐다. FE 서류함은 빈 화면이고 BE 업로드·목록 API는 아직 없으므로 앱 연결 완료를 주장하지 않는다. 아래 Python 계약을 BE에서 호출하고 반환된 상태를 저장하는 부분이 다음 연동 작업이다.

[document_tool](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/document-agent-runtime/backend/app/agent/document_tool/tool.py)는 추출·확인·점검·ZIP만 담당한다. [models.py](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/document-agent-runtime/backend/app/agent/document_tool/models.py)의 `DocumentContext`가 호출 계약이며 DB·인증·HTTP 서버를 추가하지 않았다. 기존 LangGraph의 상황 진단·결과 입력·Supervisor·Review 계약은 유지한다. 과거 모바일 전체 흐름 초안은 로컬에 보존하고 이번 게시 코드에 포함하지 않는다. 아래 모바일 측정은 그 초안의 **과거 평가 이력**이다.

- PDF·PNG·JPG/JPEG: 파일당 20MB·30쪽, 일괄 20개·50MB 제한. 한국어/영어 OCR과 식별번호 가림은 로컬에서 수행한다.
- LLM은 가림 처리한 텍스트에서 종류·값·페이지·정확한 인용을 추출한다. 인용과 값이 원문에 없으면 코드에서 차단한다. 안전 검사와 독립 Review는 Sol xhigh이며 최대 3회 재작업만 허용한다.
- OCR을 쓴 서류와 철거 전후 사진은 반드시 소유자 확인을 요구한다. `confirm_document`의 확인값은 `confirmed_fields`에 따로 저장하고 OCR 추출값·인용은 그대로 보존한다.
- 시안의 정산 6종은 공사내역서, 세금계산서, 철거 전·후 사진, 이체확인증, 폐업사실증명원, 통장 사본이다. 사진 두 장을 합쳐 한 종류로 세므로 파일은 7개다. 실제 공고별 요건은 별도 확인 대상이다.
- 6단계 코드 점검으로 누락, 총액·공급가액/세액, 거래처·신청인·수취인·예금주·공급받는 자, 상호·폐업일, 동일 전후 사진과 미확인을 찾는다. 문제가 남으면 ZIP 생성을 막는다.
- 같은 파일 재업로드는 추가 LLM 호출이 없다. 정책·모델·effort 변경 시 재분석하고 같은 문서 ID를 교체한다. 기존 정책 파일의 내보내기·파일 변조를 차단한다.
- 일괄 처리 전체에 호출 40회·420초 예산을 공유한다. 중단 시 `DocumentBatchError.partial_case`와 `failed_file_index`로 완료한 파일을 유지한다.

### 초기 문서 Tool의 실제 호출 결과와 실패 기록 (2026-11-02)

종류 힌트를 함께 준 합성 파일 7개로 이체확인증 누락 → 추가 파일만 분석 → 같은 파일 재업로드 → 소유자 확인 → 6단계 점검 → ZIP 생성을 확인했다. 사진은 실제 매장 사진이 아닌 서로 다른 이미지 자리표시자다. 스캔 확인값은 생성 시 알고 있는 정답을 소유자가 입력하는 방식이며 모델이 맞혔다고 계산하지 않는다.

| 실행 | 실제 HTTP 요청 | 총 토큰 | 추정 비용 | 처리 시간 | 자동 필드 정확 | 확인 후 전체 흐름 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Sol xhigh 세금계산서 파일럿 1개 | 3 | 2,612 | 13.925520원 | 12.363초 | 통과 | 파일럿 범위만 통과 |
| Luna 6 high 최초 PDF 7개 | 15 | 12,331 | 45.641316원 | 58.390초 | 통과 | 통과 |
| Luna 6 high 최종 PDF 7개 | 15 | 12,393 | 42.897543원 | 59.335초 | 통과 | 통과 |
| Luna 6 high 최종 스캔 7개 | 17 | 12,531 | 42.667962원 | 65.856초 | **실패** | 명시적 값 확인 후 통과 |

최종 PDF는 사진 전후만 확인했으며 값 수정은 없었다. 스캔은 공사내역서·세금계산서·폐업사실증명원·통장 사본·이체확인증의 값을 소유자가 확인/수정했다. **high 자동 정확도 실패로 medium/low를 실행하지 않았다.** 이 당시 설정은 사용자 확인을 전제로 high였으며, 이후 위의 정확도 검증을 거쳐 Sol xhigh로 승격했다. 이전 단순 문서 low 비교값을 현재 운영 기본값으로 적용하지 않는다.

이번 요청의 실제 호출은 합계 **50회·39,867토큰·145.132341원**이다. 파일럿과 중간 실행도 포함했다. 최종 두 실행은 같은 런타임 코드 지문을 사용했다. 두 ZIP 모두 9개 항목(가림 PDF 7개·점검 JSON·안내 PDF), PDF 열기·ZIP 무결성·6단계 완료·합성 주민번호 뒤쪽 OCR 불가를 별도 확인했다. 같은 파일 재업로드는 두 실행 모두 0회 호출이었다. 합성 서류 결과이며 실제 고객 정확도는 검증하지 않았다.

[요청별 사용량·코드 지문·산출물 검사](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-02-document-implementation.json)에 성공·실패를 함께 보존한다. 이전 로컬 보관분과 합친 범위는 **967회·확인된 2,164,685토큰·단가 확인 소계 7,025.941381원·비용 미확인 19회**다. Langfuse 24시간 조회와는 다른 집계 범위이므로 더하지 않는다.

### BE에서 호출할 Python 계약

```python
from pathlib import Path
from app.agent.document_tool.tool import build_document_tool
from app.agent.document_tool.models import DocumentContext, DocumentKind

agent = await build_document_tool(Path("private-vault"), submission_policy="RRN_BACK_ONLY")
try:
    context = DocumentContext(applicant_name="확인한 신청인", business_name="확인한 상호")
    context = await agent.add_documents(context, [("서류.pdf", uploaded_bytes, None)])
    # 필요 시 원본을 보여주고 실제 사용자 확인을 받은 다음에만 호출한다.
    # context = agent.confirm_document(context, document_id, DocumentKind.TAX_INVOICE,
    #     confirmed_fields={"amount": "사용자가 확인한 금액", ...})
    context = agent.check_documents(context)
    if context.document_check.status == "COMPLETE":
        package = agent.prepare_settlement(context)
    serialized = context.model_dump_json()  # BE가 Case별로 저장/복원
finally:
    await agent.aclose()
```

각 함수는 받은 Context를 직접 변경하지 않고 새 Context를 반환한다. 현재 기존 LangGraph가 이 Tool을 호출하는 연결은 없으며 별도 연동 작업이 필요하다. `confirm_document`는 문서 종류와 확인한 필드 전체를 받으며 사진 확인은 `{}`를 사용한다. 신청인·상호·폐업일과 필수 서류가 부족하면 `ISSUES`로 남는다. BE는 사용자/Case 권한, 파일 저장 위치 접근 통제, 업로드와 목록 API, 확인 화면, 상태 저장과 삭제를 담당한다. 개인정보 가림 정책은 제출 기관의 실제 요구에 맞춰 명시적으로 선택해야 한다.

## Langfuse에서 기록하는 값

실제 HTTP 요청마다 generation을 만들고 실행·구성요소 아래에 연결한다. 모델명, 요청 effort, 입력·출력 토큰, 제공자가 반환한 캐시·추론 토큰, 지연 시간, 재시도와 실패 코드를 남긴다. 상위 실행의 합계를 별도 토큰 사용량으로 다시 기록하지 않는다.

캐시 입력은 입력 토큰의 일부이고 추론 토큰은 출력 토큰의 일부다. Langfuse에서는 겹치지 않는 항목으로 나눠 합계가 중복되지 않게 한다. API가 사용량을 반환하지 않으면 `None`으로 남기며 0으로 간주하지 않는다. 추적 서비스의 장애는 Agent의 결과나 취소 처리를 바꾸지 않는다.

프롬프트, 모델의 답변 원문, 업로드 문서와 API 키는 추적에 넣지 않는다. 실제 조회에서 토큰과 상위 실행 연결을 확인했고 입력·출력 원문이 없는 것도 확인했다. 원화 비용은 아래 단가로 평가 JSON에서 계산한다. Langfuse의 기본 비용 필드에 원화를 달러로 넣지 않는다.

## 2026-11-02 모니터링 기능

공통 LLM client와 기존 Langfuse 추적을 사용하며, 실행은 `RUN → INFO_AGENT/SUPERVISOR/REVIEW_TOOL → LLM generation`으로 연결된다. generation 메타데이터에 구성요소, 요청·응답 모델, effort, 제공자 원본 토큰 수와 사용량 확인 여부를 추가했다. Langfuse 모델 매개변수에도 effort를 기록한다. 동시 요청의 구성요소가 섞이지 않는지 자동 테스트로 확인했다.

[모니터링 조회 코드](../../backend/scripts/monitor_agent.py)는 [Langfuse 공식 Observations API v2](https://langfuse.com/docs/api-and-data-platform/features/public-api)의 시간 범위·cursor 페이지 조회를 사용한다. 집계 요청에는 입력·출력 필드를 포함하지 않는다. 기존 `.env`의 Langfuse 키와 원화 단가를 그대로 읽으며 새 의존성이나 설정값은 필요하지 않다.

- 구성요소·모델·effort별 요청 수, 입력·출력·캐시·추론 토큰, 평균·중앙·최대 요청 처리 시간, 처리 실패·재시도·오류 코드와 원화 추정 비용을 집계한다.
- 실행 결과와 Review 반려·재작업 횟수는 별도로 제공한다. 실행 합계를 generation 토큰에 다시 더하지 않는다.
- 사용량이나 단가가 없으면 전체 비용을 `null`로 두고, 계산 가능한 비용 소계와 미확인 건수를 함께 표시한다. `failed_http_attempts`는 요청 처리 실패를 뜻하며 HTTP 200 뒤의 응답 검증 실패와 취소도 포함한다.
- 조회 상한에 도달하면 `truncated=true`를 표시한다. 미완성 조회를 전체 기록으로 제시하지 않는다. 조회 실패는 본문·키를 출력하지 않고 오류 종류와 HTTP 상태만 알린다.

실행은 현재 작업 폴더 `ktc4-kangwon-4-agent-monitoring`에서 한다. 조회 자체는 LLM을 호출하지 않는다. 출력 파일은 덮어쓰지 않으므로 새 경로를 사용한다.

```bash
PYTHONPATH=backend python backend/scripts/monitor_agent.py --hours 24 --output eval-runs/monitoring-new.json
# 특정 실행만 확인할 때는 --trace-id <Langfuse의 trace ID>를 추가한다.
```

[실제 검증 trace](https://cloud.langfuse.com/project/cmu706yag0007ad0c288phjhc/traces/583c4863adca25097042ac4b1710de0b)에서 Info Sol `high`의 **1회 호출·4,580토큰·추정 15.6492원**을 조회했고 제공자 사용량과 일치했다. 구성요소 부모 연결, 모델·effort, 원본 토큰 메타데이터와 입력·출력 원문 부재도 실제 조회로 확인했다. 이 실행은 Info 1건이며 전체 그래프나 서류 검증으로 확대 해석하지 않는다.

24시간 조회는 관측 1,445건 중 Agent 요청 927회, 처리 실패 5회, 사용량 미확인 3회, 비용 미확인 21회를 집계했다. 계산 가능한 비용의 소계는 7,028.5650원이며 전체 비용은 미확인이다. 로컬 완료 보고서와 달리 이 조회에는 연결 확인·중단 요청도 들어가므로 두 범위의 합계를 더하거나 억지로 맞추지 않는다.

모니터링 관련 테스트 19개와, 격리된 MySQL을 포함한 전체 **623개 테스트가 39.61초로 통과**했다. Ruff와 diff 검사를 통과했다. [코드 지문·실제 호출·Langfuse 조회·자동 테스트 기록](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-02-monitoring.json)에 결과를 보존한다.

사용자 요청 변경 당시 진행 중이던 Info `xhigh` 파일럿 1건은 Review 첫 통과로 종료했고 추가 비교는 중단했다. 이번의 실제 요청은 파일럿 3회와 모니터링 검증 1회를 합쳐 4회·61,273토큰·237.4504원이다. 모델 역할 설정은 유지했다. 이전 로컬 보관분과 합친 범위는 917회·확인된 2,124,818토큰·단가 확인 소계 6,880.8090원·비용 미확인 19회다. 입력이 달라 이번 두 실행으로 모델 절감률을 계산하지 않는다.

## Serverless 단가와 계산 기준

사용자가 제공한 [엘리스 Serverless 요금](https://kakaotechcampus.elice.io/cloud/mlapi/model-libraries?visibility=public&serverless=true)을 사용한다. 단위는 원/100만 토큰이다.

| 모델 | 일반 입력 | 캐시 입력 | 출력 |
| --- | ---: | ---: | ---: |
| `gpt-6.1-sol` | 2,835 | 141 | 14,175 |
| `gpt-6-luna` | 141 | 14 | 708 |
| `claude-haiku-5-5` | 141 | 14 | 708 |
| `gemini-3.1-flash-lite` | 354 | 35 | 2,126 |

호출 비용은 `((입력−캐시 입력)×일반 입력 단가 + 캐시 입력×캐시 단가 + 출력×출력 단가) / 1,000,000`으로 계산한다. 추론 토큰을 출력 비용에 다시 더하지 않는다. 실패한 요청과 재시도도 합산하고 성공한 처리 건수로 나눠 비교한다. 제공자의 실제 청구서를 대조한 금액이 아닌 사용량 기반 추정치다.

기존 Luna 엔드포인트는 `gpt-5.6-luna`만 노출했다. 이 모델에 `gpt-6-luna` 단가를 대입하지 않았다. 별도 `LUNA6_` 설정과 엔드포인트에서 `gpt-6-luna` 지원을 확인했다.

## 문서 모델 비교 결과

동일한 합성 공사내역서·세금계산서·이체확인증 3개를 사용한다. 종류를 미리 알려주지 않고 분류·값 추출·독립 검수까지 수행한다. 한 실행의 정상 LLM 호출은 9회다. 같은 파일 재업로드는 추가 호출이 0회인지 확인한다. 안전 검사와 독립 Review는 강한 모델로 유지하고 문서 추출 모델과 effort만 바꾼다.

| 비교 | 기준과 반복 후보 | 평균 토큰 | 평균 추정 비용 | 평균 처리 시간 | 최종 반복 성공 |
| --- | --- | ---: | ---: | ---: | ---: |
| Luna 6 기준 | Sol `xhigh` | 7,178.67 | 36.8928원 | 30.278초 | 3/3 |
| Luna 6 후보 | Luna 6 `low` | 6,859.00 | 18.9195원 | 25.949초 | 3/3 |
| Gemini 기준 | Sol `xhigh` | 7,113.00 | 35.9620원 | 28.170초 | 3/3 |
| Gemini 후보 | Flash Lite `low` | 6,389.00 | 20.5758원 | 22.272초 | 3/3 |

Luna 6 비교에서는 토큰 4.45%, 추정 비용 48.72%, 처리 시간 14.30%가 감소했다. Gemini 비교에서는 각각 10.18%, 42.79%, 20.94%가 감소했다. 두 비교는 각자의 기준 실행을 포함하며, 서로 다른 시점의 수치를 모델의 일반적인 우열로 해석하지 않는다.

시간은 서류 3개 처리, 동일 파일 재업로드 확인, 클라이언트 종료와 추적 전송까지 포함한다. 모델별 토큰화 방식과 제공자 캐시 사용량도 원본에 남긴다. 캐시 할인을 제외한 비용도 함께 보존한다. Haiku는 연결·구조화 출력 테스트는 통과했으나 이 문서 평가의 독립 검수에서 거절되어 채택 후보에서 제외했다.

- [기존 4개 모델과 effort 비교 원본](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-model-comparison.json)
- [Luna 6 단계별 비교와 반복 검증](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-luna6-comparison.json)
- [이전 브랜치의 예비 실행과 실패 기록](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-preliminary.json)

### 문서 추출 후보의 전체 단계 기록

아래는 초기 독립 초안의 합성 문서 3개 처리 결과다. 각 실행은 안전 검사·문서 추출·독립 Review를 포함하며 정상 호출은 9회다. `info-high/medium/low`라는 원본 그룹명은 문서 추출에 INFO_ 모델 설정을 사용했다는 뜻이며, 폐업 판단 Info Agent의 통합 평가와는 다른 작업이다. 각 행의 수치는 실행당 평균이고 실패 비용도 남긴다.

첫 비교의 기준 Sol과 후보들:

| 모델 | effort | 성공/실행 | 평균 입력 토큰 | 평균 출력 토큰 | 평균 총 토큰 | 평균 추정 비용 | 평균 시간 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-6.1-sol` | `xhigh` | 3/3 | 5,720.00 | 1,393.00 | 7,113.00 | 35.9620원 | 28.170초 |
| `gpt-6.1-sol` | `high` | 1/1 | 5,720.00 | 1,123.00 | 6,843.00 | 32.1347원 | 25.167초 |
| `gpt-6.1-sol` | `medium` | 1/1 | 5,720.00 | 915.00 | 6,635.00 | 29.1863원 | 22.521초 |
| `gpt-6.1-sol` | `low` | 1/1 | 5,720.00 | 935.00 | 6,655.00 | 29.4698원 | 21.759초 |
| `gpt-5.6-luna` | `high` | 1/1 | 5,720.00 | 1,219.00 | 6,939.00 | 미확인 | 25.009초 |
| `gpt-5.6-luna` | `medium` | 1/1 | 5,720.00 | 1,207.00 | 6,927.00 | 미확인 | 24.358초 |
| `gpt-5.6-luna` | `low` | 1/1 | 5,720.00 | 1,003.00 | 6,723.00 | 미확인 | 22.666초 |
| `claude-haiku-5-5` | `high` | 0/1 | 9,363.00 | 1,555.00 | 10,918.00 | 22.1722원 | 23.995초 |
| `claude-haiku-5-5` | `medium` | 0/1 | 8,816.00 | 1,645.00 | 10,461.00 | 23.0933원 | 23.992초 |
| `claude-haiku-5-5` | `low` | 0/1 | 8,816.00 | 1,495.00 | 10,311.00 | 21.2768원 | 22.639초 |
| `gemini-3.1-flash-lite` | `high` | 1/1 | 4,857.00 | 5,211.00 | 10,068.00 | 28.8070원 | 29.052초 |
| `gemini-3.1-flash-lite` | `medium` | 1/1 | 4,857.00 | 2,951.00 | 7,808.00 | 23.1347원 | 30.746초 |
| `gemini-3.1-flash-lite` | `low` | 1/1 | 4,883.00 | 1,649.00 | 6,532.00 | 20.9224원 | 22.053초 |
| `gemini-3.1-flash-lite` | `low` | 3/3 | 4,857.00 | 1,532.00 | 6,389.00 | 20.5758원 | 22.272초 |

Haiku의 medium/low는 높은 effort 실패 시 중단하라는 기준을 받기 전에 실행한 이력이다. 원본 보존용이며 채택 근거에서 제외한다. 해당 기준 이후 같은 실패 작업의 낮은 effort를 새로 실행하지 않는다. 구형 Luna 5.6에는 Luna 6 단가를 대입하지 않았다.

Luna 6를 별도 endpoint로 연결한 뒤 같은 입력으로 새 기준 실행을 포함해 비교한 결과:

| 모델 | effort | 성공/실행 | 평균 입력 토큰 | 평균 출력 토큰 | 평균 총 토큰 | 평균 추정 비용 | 평균 시간 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-6.1-sol` | `xhigh` | 3/3 | 5,720.00 | 1,458.67 | 7,178.67 | 36.8928원 | 30.278초 |
| `gpt-6-luna` | `high` | 1/1 | 5,720.00 | 1,141.00 | 6,861.00 | 18.1219원 | 28.110초 |
| `gpt-6-luna` | `medium` | 1/1 | 5,720.00 | 1,218.00 | 6,938.00 | 18.9171원 | 25.621초 |
| `gpt-6-luna` | `low` | 1/1 | 5,720.00 | 1,030.00 | 6,750.00 | 17.2487원 | 24.319초 |
| `gpt-6-luna` | `low` | 3/3 | 5,720.00 | 1,139.00 | 6,859.00 | 18.9195원 | 25.949초 |

위 두 비교는 각각의 기준 실행과 코드 지문을 가진다. 서로 다른 시점의 수치로 모델의 일반적인 우열이나 서비스 전체 절감률을 계산하지 않는다. Luna 6 low는 단순 합성 문서의 초기 후보이며, 당시 문서 Tool은 스캔 high 실패를 반영해 확인을 전제로 high를 썼으며, 현재는 위 검증을 통과한 Sol xhigh를 사용한다.

## Supervisor 모델 비교 결과

기존 Supervisor와 독립 Review를 함께 실제 호출했다. 원상복구 미확인, 확인된 복구 범위, 철거 불필요, 실행 가능한 절차 없이 정보가 부족한 상황의 4종을 각각 3회 반복했다. 기준과 최종 후보는 모두 12/12 성공했고, 행동 코드 또는 확인 질문이 일치했으며 Review 재작업은 없었다.

| 설정 | 평균 토큰 | 캐시 반영 추정 비용 | 캐시 할인 제외 비용 | 평균 처리 시간 |
| --- | ---: | ---: | ---: | ---: |
| Sol `xhigh` | 8,344.50 | 22.7241원 | 38.4629원 | 23.501초 |
| Luna 6 `high` | 8,229.50 | 17.2245원 | 29.3221원 | 22.983초 |

토큰은 1.38%, 캐시 반영 추정 비용은 24.20%, 캐시 할인을 제외한 비용은 23.77% 감소했다. 시간 차이는 2.21%로 작아 일반적인 속도 향상을 입증하는 수치로 보지 않는다. 후보를 고를 때 캐시가 이미 채워진 효과가 모델 선택을 바꾸지 않도록 캐시 할인 제외 비용을 사용했다.

Sol과 Luna 6 모두 `high → medium → low`로 비교했다. 한 문항에서 낮은 effort보다 Luna 6 `high`의 비용이 낮았고, 이 설정을 전체 4종·3회에 재검증했다. 초기 단순 합성 서류의 후보값은 `low`, Supervisor의 적용값은 `high`다. 이후 스캔 전체 흐름에서는 `high`도 실패했으므로 문서 `low`를 전체 서류의 최종 설정으로 확정하지 않는다. 독립 Review·안전 검사는 Sol `xhigh`를 유지한다. Info는 아래 최종 검증을 거쳐 Sol `high`로 낮췄다.

기준 12회 중 동일 입력·동일 모델·동일 Agent 코드로 이미 통과한 9회는 기록을 재사용했다. 입력과 코드의 지문을 검사하고 원본 보고서 지문을 각 행에 남겼다. 최종 비교 보고서는 논리적 실행 30회지만, 이번 실행에서 새로 발생한 HTTP 요청은 42회이며 재사용한 비용을 새 지출에 중복 합산하지 않는다.

- [전체 Supervisor 비교와 실제 요청 사용량](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-supervisor-comparison.json)
- [기준 실행 재사용 근거](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-supervisor-baseline-checkpoint.json)

### Supervisor effort별 선별과 반복 검증 원본 집계

다음 수치는 Supervisor와 공용 Sol xhigh 독립 Review의 2회 요청을 합친 실행당 평균이다. high/medium/low 선별은 한 문항·각 1회이며, 최종 후보는 4종·각 3회로 확대했다. 기준 12회 중 코드·입력이 같은 이전 성공 기록 9회를 재사용했고 새 지출 집계에서는 제외했다.

| 모델 | effort | 성공/실행 | 평균 입력 토큰 | 평균 출력 토큰 | 평균 총 토큰 | 평균 추정 비용 | 평균 시간 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-6.1-sol` | `xhigh` | 12/12 | 7,038.83 | 1,305.67 | 8,344.50 | 22.7241원 | 23.501초 |
| `gpt-6.1-sol` | `high` | 1/1 | 8,129.00 | 2,082.00 | 10,211.00 | 39.8666원 | 29.912초 |
| `gpt-6.1-sol` | `medium` | 1/1 | 8,129.00 | 907.00 | 9,036.00 | 23.2110원 | 19.894초 |
| `gpt-6.1-sol` | `low` | 1/1 | 8,129.00 | 904.00 | 9,033.00 | 23.1685원 | 16.615초 |
| `gpt-6-luna` | `high` | 1/1 | 8,129.00 | 1,031.00 | 9,160.00 | 13.5466원 | 18.880초 |
| `gpt-6-luna` | `medium` | 1/1 | 8,129.00 | 1,011.00 | 9,140.00 | 13.7076원 | 18.932초 |
| `gpt-6-luna` | `low` | 1/1 | 8,129.00 | 1,095.00 | 9,224.00 | 15.0599원 | 18.353초 |
| `gpt-6-luna` | `high` | 12/12 | 6,942.92 | 1,286.58 | 8,229.50 | 17.2245원 | 22.983초 |

Luna 6 high의 선별 비용은 13.5466원, medium은 13.7076원, low는 15.0599원이었다. 낮은 effort가 더 낮은 전체 비용을 보장하지 않았다. 캐시 할인 제외 비용으로 후보를 고른 뒤 high를 전체 12건에 반복 검증했다. 입력·출력에는 독립 Review도 포함되므로 모델 자체의 단독 토큰 수로 해석하지 않는다.

## 적용한 환경설정

실제 `.env`와 `.env.example`에 아래 선택을 반영했다. 기존 작업 폴더의 `.env`를 새 worktree에서도 연결해 읽으므로 API 키를 다시 복사할 필요가 없다. 모델 선택은 새 worktree의 구현을 기준으로 한다.

| 역할 | 모델 | effort | 설정 |
| --- | --- | --- | --- |
| 문서 판독·추출 — OCR/사진 사용자 확인 필수 | `gpt-6.1-sol` | `xhigh` | `AGENT_DOCUMENT_MODEL_PREFIX=INFO_`, `AGENT_DOCUMENT_REASONING_EFFORT=xhigh` |
| 기존 Supervisor | `gpt-6-luna` | `high` | `AGENT_SUPERVISOR_MODEL_PREFIX=LUNA6_`, `LUNA6_REASONING_EFFORT=high` |
| 기존 정보 분석 | `gpt-6.1-sol` | `high` | `AGENT_INFO_MODEL_PREFIX=INFO_`, `INFO_REASONING_EFFORT=high` |
| 독립 Review·안전 검사·기존 지원금 분석 | `gpt-6.1-sol` | `xhigh` | 공용 `OPENAI_MODEL`, `OPENAI_REASONING_EFFORT` |

[환경설정 실제 로딩 검사](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-final-config.json)에서 factory가 만든 각 client의 모델과 effort를 확인했다. 공용 설정은 `xhigh`를 유지한다. 초기 문서 기본값 high는 위 정확도 재검증 뒤 Sol xhigh로 승격했고 `.env`와 `.env.example`에 반영했다. 과거 `low` 기록은 이전 비교 이력으로만 보존한다. 모든 평가 키와 Langfuse 키는 `.env`에만 남긴다.

## 사실 추출과 충돌 확인

임대인 답변 9종을 13회 실행했다. 부분 철거와 전체 철거 문장은 각각 3회 반복했다. 복구 불필요, 답변 대기, 부정문, 모순된 답변, 다시 연락하라는 답변, 기존 사실과의 충돌, 지시 우회 문장을 포함했다. 기존 Info `xhigh`와 최종 `high` 모두 각각 13/13 기대한 처리를 통과했고, 이 문장 평가의 Review 재작업과 HTTP 재시도는 0회였다.

확인 전 사실 유지, 변경 거절, 변경 확인을 모두 검사한다. 현재 판단할 수 없는 답변에는 확인 질문을 남긴다. 지시 우회 요청은 안전 검사에서 차단한다.

- [합성 문장과 기대값](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-landlord-cases.json)
- [실제 호출 결과와 사용량](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-landlord-results.json)
- [최종 Info high의 같은 문장 검증](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-landlord-info-high.json)
- [기존 Info 계약의 충돌 검증: high](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-existing-info-high.json)

Info `high`의 문장 평가는 실제 37회 호출·26,052토큰·추정 142.8500원이었다. 기존 Info 계약에서도 원상복구 범위·철거 필요 여부를 자동 변경하지 않고 충돌 후보로 보류하는 것을 실제 호출로 확인했다. 현재 설정은 품질 검증을 통과했지만, Info의 최적 effort를 확정하는 같은 버전의 반복 성능 비교는 후속 TODO다.

## 과거 모바일 초안·기존 그래프 동작과 자동 테스트

이번 게시에 포함하지 않는 로컬 모바일 초안은 문서 Luna 6 `low`, Supervisor Luna 6 `high`, Info Sol `high`, Review·안전 검사 Sol `xhigh`로 실제 실행했다. 임대인 답변 확인, 신청·승인 보고, 서류 13개 처리, 이체확인증 누락 검출, 추가 서류만 분석, 제출 ZIP 생성, 점포 반환, 부가세 자료 준비와 폐업 완료까지 통과했다. 사진 대신 글자로 표시한 합성 PDF 두 개는 모델이 확인을 요청했으며, 평가에서 소유자가 종류를 확인하는 동작을 명시적으로 수행했다.

최종 실행은 HTTP 요청 **50회**, **34,881토큰**, 추정 **116.3028원**, **150.061초**였다. 다음 할 일 생성에서 Review가 한 차례 REVISE했고, 정해진 재작업 범위 안에서 통과했다. HTTP 재시도는 0회였다. 이전 Info `xhigh` 실행은 48회·33,373토큰·110.2392원·137.965초였으며 별도 보존했다. 최종 전체 흐름이 모든 지표에서 개선됐다고 주장하지 않는다. 모델 비교용 반복 실험과 목적이 다르므로 이 두 실행으로 절감률을 계산하지 않는다.

ZIP에는 정산 서류 PDF 7개, 제출 안내 PDF, 점검 JSON이 들어 있고 ZIP 무결성과 모든 PDF 열기를 별도로 확인했다. 합성 이체확인증의 주민번호 뒤쪽 가림과 준비 요약의 한글 표시도 렌더링해 확인했다.

기존 LangGraph도 공식 자료 8개를 주입해 최종 설정으로 실행했다. **Info → Supervisor → 독립 Review의 실제 3회 호출**, **68,468토큰**, **207.8816원**, **83.033초**로 임대인에게 원상복구 범위·철거 필요 여부를 확인하는 행동을 반환했다. Review는 첫 검수에 PASS였다. 이 자료는 평가용 자동 대조 자료이며 사람이 검수한 운영 자료라고 주장하지 않는다. 최종 수정 뒤 전체 그래프 실험은 1회이며, 통합 반복 평가와 전체 분기 검증은 미완료다.

최초 정리 시 자동 테스트는 595개 통과했다. 이번 재개 후 PR 120 입력 보호와 비용·캐시·effort 중단 검증을 포함한 전체 테스트는 격리된 MySQL을 사용하는 테스트까지 **615개, 43.35초로 통과**했다. 모델 응답을 대체하는 자동 테스트와 실제 API 호출 결과는 별도로 기록한다. 문서 대조·가림·파일 변경 검출·상태 전이·충돌·실패 시 차단은 자동 테스트에서 확인한다.

당시 로컬 초안까지 포함한 LLM 호출 지점 10곳 모두 실제 성공 응답을 확인했다. 기존 Info·Supervisor·Review·Support, 모바일 사실 추출·다음 행동·Review, 문서 추출·Review·안전 검사다. Procedure 조회, 문서 금액·명의 대조, 가림과 ZIP은 LLM을 사용하지 않는 코드다. 기존 Support는 MVP 그래프에서 실행되지 않으므로 합성 catalog로 별도 호출했으며 실제 지원사업 전체의 자격 정확도를 검증한 것은 아니다.

Langfuse에서 최근 generation 300건의 토큰과 부모 연결을 조회했다. 55건은 캐시 입력이 0보다 컸으며, 프롬프트·응답 원문은 모두 없었다. 예를 들어 캐시 입력 3,756 + 일반 입력 3 + 추론 출력 325 + 일반 출력 78 = 총 4,162로 제공자 사용량과 같은 방식으로 합산된다. 이 조회에는 평가 중 실패 기록도 포함되며 전체가 성공했다는 뜻은 아니다.

- [모바일 전체 실행](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-full-flow.json)
- [이전 Info xhigh 전체 실행](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-full-flow-info-xhigh.json)
- [최종 기존 LangGraph 실제 실행](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-graph-final.json)
- [ZIP·PDF 파일 지문과 검사](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-artifacts.json)
- [최종 자동 테스트](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-tests-final.json)
- [Langfuse 조회 결과](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-langfuse.json)
- [LLM 호출 지점별 실제 검증 근거](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-llm-coverage.json)
- [실행별 비교 CSV](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-trials.csv)

### 전체 그래프 1건의 역할별 실제 사용량

공식 자료 8개를 사용한 이 실행은 평가용 자동 대조 자료와 합성 Case를 사용했다. 각 역할의 1회 요청 합계이며 통합 반복 성능 비교는 아니다.

| 역할 | 모델 / effort | 입력 토큰 | 출력 토큰 | 총 토큰 | 캐시 반영 추정 비용 |
| --- | --- | ---: | ---: | ---: | ---: |
| Info | `gpt-6.1-sol` / `high` | 11,690 | 6,059 | 17,749 | 110.7246원 |
| Supervisor | `gpt-6-luna` / `high` | 17,905 | 116 | 18,021 | 2.6067원 |
| Review | `gpt-6.1-sol` / `xhigh` | 31,794 | 904 | 32,698 | 94.5503원 |

이 사례의 비용은 Info와 Review에 집중됐다. Supervisor 비교의 24.20% 절감은 Supervisor+Review 평가 범위의 결과이며 전체 서비스 비용이 같은 비율로 줄었다는 근거가 아니다. 근거를 보존하면서 Info·Review에 전달하는 내용의 중복을 줄이는 작업은 후속 TODO다.

## 실패와 중단 기록

실패한 실행도 보존한다. 성공한 실행만 남겨 비용이나 정확도가 좋아 보이게 만들지 않는다.

- Haiku 스트림의 마지막 사용량 청크를 처리하지 못한 오류를 수정했다. 종료 뒤 실제 내용이 더 오는 응답은 계속 거절한다.
- 오늘 할 일의 근거 ID가 허용값과 달라 실패하던 문제는 요청 스키마의 enum으로 제한했다. 독립 검수를 생략하지 않았다.
- 합성 사진 PDF를 실제 사진으로 단정하지 않은 결과는 사용자 종류 확인을 요구하는 정상 보류로 처리한다. 최초 전체 흐름 평가는 이 확인 단계를 누락해 중단됐으며 기록을 보존했다.
- 기존 Info의 충돌 결과를 일반 변경 후보로만 찾던 평가 조건을 고쳤다. 기존 사실과의 충돌이 보류되는 실제 계약을 검사한다.
- 직원 수 누락과 실행 가능한 세무 확인 행동이 함께 있는 입력을 무조건 질문으로 기대한 평가 조건을 고쳤다. 실행 가능한 후보가 없는 누락 상황을 별도로 구성한다.
- 최초 기존 LangGraph 비교는 구현 범위가 확장되면서 중단했다. 완료한 최적화 수치에 포함하지 않으며, 일부 사용량이 없는 요청은 미확인으로 보존한다.
- 기존 전체 그래프의 평가 도구가 여러 자료에서 같은 절차 코드·이름을 중복 생성하던 문제를 수정했다.
- 공식 자료 8개 분석의 스트리밍 응답이 1MB 제한을 넘는 실제 실패를 확인해 `.env`와 예제의 한도를 8MB로 조정했다. 사용량을 받지 못한 최초 실패의 비용은 미확인이다.
- Review는 선택 입력인 예정 폐업일을 필수 blocker로 요구하고, 코드가 별개로 허용한 절차 확인·사용자 질문 후보를 중복으로 반려했다. Luna와 기준 Sol 모두 같은 오류로 재검수 3회를 소모했다. 기존 코드와 테스트의 계약을 프롬프트 다섯 문장으로 설명했고, 같은 검수 대상의 실제 Review가 PASS했으며 새 전체 실행도 통과했다. 후보·근거·위험 주장에 관한 코드 검증은 유지했다.
- 검수 결과를 수집하지 않은 평가의 재작업 횟수를 0으로 보고하지 않도록 `None`으로 처리한다.

## 지금까지의 분석

문서 비교는 같은 합성 서류·같은 독립 검수·각 3회 반복으로 확인한 절감 결과다. Supervisor 비교의 4종·3회 결과와 최종 공식 자료 8개 통합 1회는 범위가 다르다. 실제 호출 지점 10곳을 통과한 것과 모든 운영 상황을 검증한 것은 구분한다.

기존 전체 그래프의 최종 입력 토큰은 Info 11,690, Supervisor 17,905, Review 31,794였다. 긴 docstring보다 공식 자료와 근거 묶음이 주된 토큰 비용이다. 추가 최적화는 근거를 유지하면서 구성요소별 전달 내용을 줄일 수 있는지 먼저 검토한다. 현재는 입력 구조를 새로 바꾸지 않았다. 이번 문서 Tool는 계약·진입점·추출·대조·안전 검사로 나누고 프롬프트는 추출·독립 검수·안전 검사 위치에 모은다.

재개 후 비용 함수는 요청·응답 모델 버전이 다르면 비용을 미확인으로 처리하도록 보완했다. 같은 버전의 제공자 접두어만 정규화한다. 문서 초안의 재업로드 캐시는 안전 정책 코드·모델·effort가 바뀌면 재검사한다. 두 변경은 회귀 테스트를 통과했다. 이후 이번 서류 구현에서 기존 정책의 내보내기 차단과 동일 문서 ID 교체를 구현하고 회귀 테스트로 확인했다.

[분석 원본](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-analysis.json)은 로컬 `results.json` 기록의 호출·토큰·비용을 대조하고, 기준 실행 재사용 9행을 중복 지출에서 제외한다. 단가 없는 구형 Luna와 사용량을 받지 못한 실패가 있어 확인 가능한 비용의 소계만 제공하며 전체 청구 금액으로 표시하지 않는다. [코드·입력·산출물 지문](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-final-manifest.json)과 [변경 범위 확인](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-scope-check.json)도 남겼다.

이 집계 범위에는 HTTP 호출 750회, 확인된 토큰 1,496,620개가 기록돼 있다. 단가와 사용량이 확인된 비용 소계는 4,853.8890원이다. 구형 Luna 18회와 응답 크기 초과 1회는 비용 미확인이다. 초기 중단 실행·연결 확인 등 모든 과거 API 활동을 포함하는 총액은 아니다.

## 재개 후 검증과 분석

[재개 결과·사용량 원본](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-resumed-results.json)에 성공과 실패를 모두 합쳤다. 이전 평가 파일은 덮어쓰지 않았다. 재개 보고서 16개는 실제 HTTP 호출 163회, 566,925토큰, 추정 1,789.4697원이며 사용량 미확인은 없다. 이전 보관분과 합친 기록 범위는 913회·확인된 2,063,545토큰·가격 확인 소계 6,643.3586원이다. 기존의 비용 미확인 19회는 그대로 남는다. 서로 다른 입력의 합계이므로 전체 정확도·절감률로 계산하지 않으며 청구서 총액도 아니다.

PR 120이 보내는 `[리본이 물어본 것] … / [사장님 답] …` 형식은 질문을 문맥으로만 사용한다. Info의 근거 인용을 답변 구간으로 제한했고, 같은 문구가 질문에 먼저 나와도 실제 답변의 위치를 사용한다. 질문만 인용한 사실·완료 보고는 재작업하거나 차단한다. 프롬프트에는 짧은 설명 한 문장만 더했다. 관련 자동 테스트 7개와 기존 Info 테스트를 합쳐 91개가 통과했다.

최종 코드의 실제 Sol `high` 검증은 직원 수·프랜차이즈의 짧은 답변 연결, 질문을 완료 사실로 바꾸지 않기, 기존 직원 수와 충돌한 답변 보류의 **3건 모두 통과**했다. 3회 호출·13,471토큰·44.6909원, 합산 35.386초였다. Info만 호출한 검사이므로 독립 Review와 앱 E2E를 통과한 수치로 표시하지 않는다. 팀 댓글의 별도 12건 검증은 우리 호출 수에 합산하지 않았다. 평가 입력에서 필수 사실을 누락했던 최초 준비 오류는 모델 호출 전 발생했으며 0회로 별도 보존했다.

### effort를 낮추는 중단 기준

**같은 모델·같은 작업에서 높은 effort가 통과할 때만 다음 낮은 effort를 실행한다. 실패하면 그 아래는 실행하지 않는다.** 평가 도구와 자동 테스트에 이 기준을 반영했다.

팀 검수 표시가 있는 기존 공식 자료 4개를 변경 없이 사용하고 평가일을 2026-11-01로 지정해 전체 그래프를 실행했다. 날짜 검사와 독립 Review는 생략하지 않았다.

| Info effort | 전체 결과 | 실제 호출 | 토큰 | 추정 비용 | 처리 시간 |
| --- | --- | ---: | ---: | ---: | ---: |
| `xhigh` | PASS, Review 첫 통과 | 3 | 55,016 | 209.9841원 | 105.667초 |
| `high` | PASS, Review 재작업 2회 | 7 | 139,782 | 419.9444원 | 197.431초 |
| `medium` | SAFE_FAILURE, Review 3회 반려 | 7 | 133,621 | 402.3108원 | 213.107초 |
| `low` | medium 실패로 채택·추가 검증 제외 | — | — | — | — |

중단 기준을 받기 전에 끝난 low 실험 원본은 보존하되 채택 근거에서 제외했다. Info는 `high`를 유지한다. high의 최종 통과만으로 비용 개선을 주장할 수 없으며, 이 통합 입력 1건에서는 xhigh가 더 적은 재작업과 비용으로 끝났다. 같은 코드의 반복 비교 전에는 Info 최적화 완료로 표시하지 않는다. high의 최종 다음 행동은 보험 확인이었으므로 모든 통합 사례가 임대인 확인을 골랐다고 주장하지 않는다.

### 과거 서류 자료 탐색과 중단 이력

로컬·저장소·제공 시안에서 실제 비식별 고객 제출 서류를 찾지 못했다. 합성 자료는 표 PDF 13종과 기울인 스캔 PNG 13종으로 만들었고 합성·제출 불가 표시, 입력 해시, OCR·가림 결과를 보존했다. 사진은 실제 매장 사진이 아닌 글자 자리표시자다. [국세청 양식](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7780&mi=2447)의 HWPX 2개와 [법제처 사회보험 빈 PDF 양식](https://www.law.go.kr/LSW/flDownload.do?bylClsCd=110202&flSeq=160222035&gubun=)도 내려받았다. 새 자료는 사람 검수를 완료한 운영 근거가 아니다. HWPX는 지원하지 않는 형식으로 모델 호출 전에 거절하며, 관련 없는 빈 보험 양식도 정산 서류로 저장하지 않고 거절했다.

문서 Luna 6 `high`, Info `high`로 합성 표 PDF의 전체 흐름은 13서류·48회 호출·36,919토큰·136.4116원·166.752초로 통과했다. 같은 설정의 스캔은 25회·20,722토큰·79.9079원·115.595초에서 멈췄다. 공사내역서·세금계산서에 사용자 확인이 필요했는데 평가 흐름은 사진 확인만 허용해 AssertionError로 중단했다. OCR과 금액 추출까지 통과한 것으로 해석하지 않는다. **high 묶음 실패로 medium·low는 실행하지 않았다.** 성공한 단일 폐업사실증명원 단계 비교를 스캔 전체 흐름의 성공으로 대체하지 않는다.

이후 사용자가 서류 구현과 PR 게시를 요청해 사용자 확인 계약, 최신 정책 확인, 동일 문서 교체, Review 최대 3회와 공통 예산·기한을 독립 문서 Tool로 완성했다. 앞 절의 11월 2일 결과가 현재 구현의 검증이며 이 중단 기록은 덮어쓰지 않는다.

## 최종 게시 코드 검사

로컬 모바일 초안을 제외한 Git tree를 별도 worktree로 만들고 실제 `.env` 없이 모의 BE 설정으로 검사했다. MySQL 통합을 포함한 **619개 테스트가 35.98초에 통과**했다. 추가한 서류 차단 조건과 평가 도구의 개별 회귀 44개도 5.32초에 통과했다. 변경한 Python 파일의 Ruff 검사와 FE/BE/common/규칙 파일 미변경·실제 환경 키 미포함을 확인했다. CSV 원본의 CRLF는 지문 보존을 위해 유지하고 그 기준으로 diff 검사를 통과했다. pytest는 실제 모델을 호출하지 않는다. 위 수치는 이름 변경 전 런타임의 검증이다. 이번 PR 재정리에서 DocumentAgent를 DocumentTool로 이름·경로만 변경했고 평가 원본의 당시 코드 지문은 그대로 보존했다. 이름 변경 후 자동 테스트는 별도 확인한다. 추가 실제 LLM 호출은 하지 않는다.

이번 3개 PR 재정리 후에는 평가 원본 디렉터리가 없는 모니터링 Git tree에서 **581개 테스트가 17.45초**, 문서 Tool 포함 Git tree에서 MySQL 통합까지 **619개가 34.00초**에 통과했다. 개별 변경 회귀34개도4.57초에 통과했다. 모니터링18파일·6커밋, 문서 Tool14파일·4커밋, 평가 원본50파일로 겹침 없이 나눴다. 기능 PR에는 docs/agent/evaluations가 없으며 원본 기록은 별도 PR에 그대로 보존한다. 새 커밋과 열린 PR 제목은 [AI]이며 리뷰어를 요청하지 않았다. Ruff·키 미포함·수정 범위·CSV CRLF 기준 diff 검사를 통과했다.

## TODO와 후속 계획

- [x] Langfuse 역할·모델·effort·실제 토큰 추적과 기간별 집계, 실제 조회 대조.
- [x] PR 115·118·120 기준 반영과 PR 120 질문/답변 근거 구간 보호.
- [x] 서류 추출·사용자 확인·6단계 대조·재점검·ZIP의 Agent 계약과 구현.
- [x] 정책 변경 후 기존 ZIP 차단, 같은 문서 재분석 시 교체, 변조 차단.
- [x] 높은 effort 실패 시 낮은 단계 중단과 실패·미확인 비용 보존.
- [ ] 최종 Info xhigh/high를 동일 공식 자료·코드의 여러 입력·각 3회로 비교. medium 실패 뒤 low는 제외한다.
- [ ] 합성 스캔 Sol xhigh 필수 값3회 통과를 기준으로 실제 자료 범위를 확대한다. 이후 후보 모델/effort는 같은 품질 기준을 통과해야 비교에 포함한다.
- [ ] 실제 비식별 고객 서류·촬영 사진·최신 공고 제출 요건과 가림 범위를 팀이 검수.
- [ ] FE/BE 담당자가 업로드·목록·확인·삭제·다운로드 API와 권한·DB·화면을 연결한 뒤 앱 E2E 검증.
- [ ] [미머지 PR 119](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/119)의 진단 항목 연동을 담당자와 합의. 미질문 값을 false로 확정하지 않는다.
- [ ] 세 PR의 팀 검토와 병합. 리뷰 대상은 사용자가 지정하며 이번 작업에서 임의로 리뷰 요청하지 않는다. 자동 병합하지 않는다.
- [ ] 연결 가능한 Discord 도구가 준비되면 미확인 팀 논의를 대조. 현재 확인 완료로 표시하지 않는다.

먼저 게시한 모니터링으로 실제 비용·실패 분포를 확인하고 Info 근거 묶음의 중복을 검토한다. 서류 자동 추출 개선과 API·화면 연동은 별도 작업으로 진행한다. 원래 작업 폴더의 브랜치와 미완료 변경은 그대로 보존했다.

## 재현 방법

Python 3.12와 기존 의존성에 문서 Tool의 고정 버전 의존성만 추가한다. 모델 키는 `.env`에만 채운다.

```bash
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
pip install -r backend/app/agent/document_tool/requirements.txt
python backend/scripts/setup_agent_ocr.py
cd backend
python -m pytest -q tests
```

실제 모델 평가 전에 예상 호출·금액을 계산하고 1건 파일럿을 실행한다. 아래 평가 도구는 실제 모델을 호출한다. 출력 디렉터리는 새 경로여야 한다. 스캔 high 실패가 미해결인 현재 medium/low를 실행하지 않는다.

```bash
PYTHONPATH=backend python backend/scripts/evaluate_documents.py --model-prefix INFO_ --effort xhigh --pilot --output eval-runs/doc-pilot-new
PYTHONPATH=backend python backend/scripts/evaluate_documents.py --effort high --layout simple --output eval-runs/doc-pdf-new
PYTHONPATH=backend python backend/scripts/evaluate_documents.py --effort high --layout scan --output eval-runs/doc-scan-new
PYTHONPATH=backend python backend/scripts/evaluate_agent_roles.py --compare-supervisor --output eval-runs/supervisor-new
```

과거 로컬 모바일 초안의 평가 스크립트는 이번 게시에 포함하지 않는다. 그 측정은 [코드·입력 지문](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/feature/agent-evaluation-artifacts/docs/agent/evaluations/2026-11-01-final-manifest.json)과 원본 요청별 사용량으로 식별하며, 현재 문서 전용 측정과 같은 코드의 직접 비교로 취급하지 않는다. 합성 PDF·가림 PDF·ZIP은 원래 작업 폴더 `eval-runs/agent-optimization-20261101/`와 `eval-runs/agent-optimization-20261102/document-implementation/`에 보존한다. 원본 업로드와 키는 저장소에 추가하지 않는다.

## 적용 경계

일반 식별번호 패턴은 로컬에서 가린다. 이름과 상세 주소는 호출자가 제공하는 비식별 입력과 `private_values` 설정의 책임 범위를 확인해야 한다. OCR이 모든 실제 서류를 완벽하게 읽거나 모든 개인정보를 자동 식별한다고 보장하지 않는다.

제출 파일의 가림 기준은 호출자가 `RRN_BACK_ONLY` 또는 `ALL_IDENTIFIERS`로 명시한다. 평가에서는 합성 서류에만 주민번호 뒤쪽 가림 기준을 사용한다. 사진 전후, 판독 불가 내용과 불일치는 임의로 확정하지 않는다.

정책·지원 자격 안내는 팀이 검수한 자료가 별도로 필요하다. 합성 자료와 자동 대조 자료를 사람 검수가 끝난 공식 자료로 바꾸지 않는다. [PR 115 최신 리뷰](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/115#pullrequestreview-5723065761)의 BE 주소 식별자와 원문 보관 정책, 실제 알림 발송 및 새 화면 API 연결은 이번 Agent 변경과 구분한다.
