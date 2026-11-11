# RE:BORN 리본

> 폐업을 결정한 개인 카페 사장님에게 **지금 할 일 하나**와 **챙길 서류**를 알려주는 폐업 준비 도우미

카카오테크 캠퍼스 4기 강원대 4팀 · 2026.08 ~ 2026.11

**[서비스 열기](https://ktc4-kangwon-4.vercel.app)** · **[시연 영상 (1분 41초)](docs/presentation/reborn-demo.mp4)** · **[발표 자료 (PDF 21쪽)](docs/presentation/reborn-final-presentation.pdf)**

[개발 문서](https://ktc4-kangwon-4.vercel.app/developers/) · [안심가이드](https://ktc4-kangwon-4.vercel.app/safety) · [대표 사용자 흐름](docs/hero-scenario.md)

<table>
  <tr>
    <td><img src="docs/final-guide/images/04-home.png" width="200" alt="홈: 오늘 할 일 하나"></td>
    <td><img src="docs/final-guide/images/39-understood.png" width="200" alt="임대인 답변을 이해한 내용 확인"></td>
    <td><img src="docs/final-guide/images/11-roadmap.png" width="200" alt="5단계 폐업 순서"></td>
    <td><img src="docs/final-guide/images/18-docs-issues.png" width="200" alt="서류 점검에서 빠진 서류 안내"></td>
  </tr>
  <tr>
    <td align="center">오늘 할 일은 하나</td>
    <td align="center">AI가 이해한 내용 확인</td>
    <td align="center">5단계 폐업 순서</td>
    <td align="center">빠진 서류 찾기</td>
  </tr>
</table>

<sub>화면은 로컬에서 미리보기 데이터로 찍은 것입니다. 전체 화면은 <a href="docs/final-guide/설명서.md">서비스 설명서</a>에 있습니다.</sub>

## 어떤 문제를 푸는가

폐업을 결정한 사장님은 임대차, 원상복구, 직원 정산, 폐업 신고, 지원금 서류를 직접 챙겨야 합니다. 안내는 여러 기관과 계약서에 흩어져 있고, 내 가게에 무엇이 해당하는지와 무엇을 먼저 해야 하는지는 스스로 연결해야 합니다. 그래서 안내를 읽어도 다음 행동으로 이어지기 어렵습니다.

중소벤처기업부가 2026년 6월 30일 발표한 조사에서, 최근 1년 안에 폐업하고 정부 사업에 참여한 소상공인 1,500명 중 26.1%가 폐업에 시간이 걸린 항목으로 "폐업 절차 파악"을 꼽았습니다.

리본은 이 연결을 대신합니다. 가게 상황을 버튼으로 받고, 지금 할 일 하나를 정해 주고, 사장님이 실제로 하고 온 결과를 받아 다음 할 일을 다시 정합니다.

- **핵심 대상:** 40~50대 비프랜차이즈 개인 카페 사장님. 가게를 빌려 쓰는 경우가 대표 흐름입니다.
- **하지 않는 일:** 지원금 자격을 확정하지 않고, 기관에 대신 신청하거나 제출하지 않습니다.

## 핵심 기능

| 기능 | 설명 |
|---|---|
| 상황 진단 | 임차 여부, 직원, 원상복구 조항, 폐업 시기를 버튼으로 받습니다. 모르는 것은 "모름"으로 남깁니다 |
| 오늘 할 일 하나 | 지금 진행을 막고 있는 것 하나와 그것을 풀 행동 하나만 보여줍니다 |
| 결과 입력과 재판단 | 임대인 답변처럼 하고 온 결과를 알려주면 AI가 이해한 내용을 보여주고, 다음 할 일을 다시 정합니다 |
| 기록 충돌 확인 | 새 입력이 기존 기록과 다르면 자동으로 덮어쓰지 않고 사장님께 되묻습니다 |
| 5단계 로드맵 | 폐업 준비부터 세금 마무리까지 26개 할 일의 진행 상태를 한 화면에서 봅니다 |
| 서류 점검과 제출 준비 | 철거비 정산 서류를 올리면 종류를 나누고, 빠진 서류와 금액 불일치를 찾고, 제출용 ZIP을 만듭니다 |

## 시스템 구조

```mermaid
flowchart LR
  U["사장님<br/>모바일 브라우저"] --> FE["화면<br/>React · Vercel"]
  FE -- "/api" --> CD
  subgraph EC2["AWS EC2"]
    CD["Caddy<br/>HTTPS"] --> BE["FastAPI"]
    BE --> AG["Agent<br/>LangGraph"]
    BE --> DB[("MySQL 8.0")]
    BE --> VOL[("서류 저장소")]
  end
  BE --- KA["카카오 로그인"]
  AG -- "httpx" --> LLM["LLM<br/>OpenAI 호환 주소"]
  AG -. "실행 기록만" .-> LF["Langfuse"]
```

화면은 판단하지 않고 입력 전달과 결과 표시만 합니다. Agent는 DB를 직접 읽거나 쓰지 않고, 저장과 권한 확인은 BE가 맡습니다.

### 판단 한 번이 지나가는 길

```mermaid
flowchart LR
  IN["가게 등록<br/>결과 입력"] --> P["절차조회 Tool"] --> I["정보분석 Agent"]
  I -- "기존 기록과 다름" --> C["사장님께 되묻기"]
  C -- "사장님 선택" --> P
  I -- "충돌 없음" --> S["Supervisor Agent"] --> R{"Review Tool"}
  R -- "통과" --> OK["다음 할 일<br/>저장 · 표시"]
  R -- "반려: 해당 단계부터 다시<br/>최대 2번" --> S
  R -- "실패 · 한도 초과" --> F["안전 실패<br/>검수 전 초안은 보여주지 않음"]
```

| 구성요소 | 맡은 일 |
|---|---|
| 절차조회 Tool | 사람이 검수한 폐업 절차 자료에서 원문과 출처를 찾습니다. 순서나 할 일을 정하지 않습니다 |
| 정보분석 Agent | 사장님 글에 실제로 있는 값만 꺼내고, 기존 기록과 다른 점을 찾습니다 |
| Supervisor Agent | 다음 할 일을 정하는 유일한 곳입니다. 코드가 만든 후보 중에서 고릅니다 |
| Review Tool | 모든 판단을 내보내기 전에 따로 검사합니다. 직접 고치지 않고 반려 사유만 돌려줍니다 |

자세한 구조는 [Agent 아키텍처](docs/agent/architecture.md), DB는 [ERD](docs/schema/ERD.png)에 있습니다.

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 화면 | React 19, TypeScript, Vite, Tailwind CSS, React Router, Zustand |
| 서버 | Python 3.12, FastAPI, SQLModel, MySQL 8.0, PyJWT, 카카오 로그인 |
| AI | LangGraph(실행 순서), Pydantic(입출력 검증), httpx(모델 호출), PyMuPDF(서류 읽기), Langfuse(실행 기록) |
| 테스트 | pytest, testcontainers(MySQL), Vitest, Testing Library, Playwright |
| 배포 | Vercel(화면), AWS EC2 + Docker Compose + Caddy(서버), GitHub Actions |

설치만 되어 있고 쓰지 않는 패키지까지 구분한 목록은 [기술 스택 문서](docs/tech-stack.md)에 있습니다.

## 왜 이렇게 만들었나

| 결정 | 다른 선택지 | 이렇게 한 이유 |
|---|---|---|
| 다음 할 일은 Supervisor 한 곳에서만 정한다 | Agent 여러 개가 각자 판단 | Agent가 늘면 모델 호출, 대기 시간, 비용, 원인 추적이 모두 어려워집니다 |
| 화면에 나가는 문장은 사람이 검수한 절차 자료에서 코드가 가져온다 | 모델이 문장을 새로 작성 | 금액, 기한, 자격을 근거 없이 단정하는 문장이 나갈 길을 줄입니다. 모델은 후보 중에서 고르기만 합니다 |
| 검수를 코드 검사와 모델 검토 두 겹으로 둔다 | 모든 판단을 모델이 검수 | 모델이 쓴 내용이 들어가는 판단만 모델이 검수합니다. 나머지는 코드 검사로 충분하고 훨씬 빠릅니다 |
| 절차 자료는 사람이 검수해서 넣는다 | 요청할 때마다 인터넷 검색 | 출처와 검수 상태, 최신 여부를 지킬 수 있습니다. 자료가 없으면 없다고 답합니다 |
| 입력은 버튼 위주, 글은 임대인 답변 한 곳만 | 처음부터 자유롭게 글로 입력 | 글 해석에 드는 시간과 오해를 줄입니다. 글로 받은 내용은 "이렇게 이해했어요"로 확인받습니다 |
| 기존 기록과 다르면 사장님이 고른다 | 새 값으로 자동 덮어쓰기 | 잘못 이해한 값이 사실로 굳는 것을 막습니다 |
| 배포는 사람이 버튼으로 실행한다 | develop에 합쳐질 때마다 자동 배포 | 서버가 재시작되면 진행 중이던 판단이 실패로 바뀝니다. 시연과 QA 도중 재시작을 피합니다 |

왜 AI가 필요했는지, 어디까지 AI에 맡기고 어디서 사람에게 묻는지, 그 대가가 무엇인지는 [왜 이렇게 설계했나](docs/agent/why-this-design.md)에 문제부터 순서대로 정리했습니다.

## 문제 해결 기록

### 1. 첫 할 일을 받는 데 2분이 걸렸다

- **문제:** 시연에서 첫 할 일이 나오기까지 5분 30초가 걸린 적이 있었습니다. 서버 기록 9건의 중간값은 180.5초였고, 그 시간의 83%를 정보분석 Agent가 썼습니다.
- **원인:** 첫 판단의 입력은 버튼 값뿐이라 글에서 꺼낼 내용이 없는데도 모델을 불렀습니다. 모델은 매번 같은 절차 원문 8건을 다시 읽고 정리하고 있었습니다.
- **시도 1, 실패:** 모델만 바꿔 봤습니다. 304초 뒤 실패해서 채택하지 않았고, "모델 교체가 아니라 하는 일을 줄여야 한다"는 근거가 됐습니다.
- **시도 2:** 절차 원문을 사람이 검수한 정리본으로 미리 만들어 두고 첫 판단의 정보분석에서는 모델을 부르지 않게 했습니다([#189](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/189)). 이어서 원상복구 답변을 선택형으로 받고([#197](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/197)), 모델이 쓴 내용이 없는 판단은 코드 검사만 하게 했습니다([#203](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/203)).
- **결과:** 같은 입력을 같은 구간에서 3번씩 쟀습니다.

  | 같은 첫 판단 | 평균 시간 | 모델 호출(3회 합계) | 정상 완료 |
  |---|---:|---:|---:|
  | 바꾸기 전 | 120.3초 | 9번 | 2/3 |
  | 바꾼 뒤 | 3.0초 | 3번 | 3/3 |

  정해진 다음 할 일은 전후가 같았습니다. 화면에 다음 할 일이 보이기까지는 중간값 3.2초였습니다(10회).
- **배운 점:** 처음에는 서버 기록 180초와 로컬 3초를 나란히 놓고 "3분에서 3초"라고 썼습니다. 멘토 리뷰에서 측정 대상이 같은지 확인하라는 지적을 받았고, 같은 입력과 같은 구간끼리 다시 쟀습니다. 위 수치는 3회짜리 표본이라 서비스 전체의 속도로 일반화하지 않습니다.
- **남은 것:** 글로 쓴 답변은 모델이 읽어야 해서 중간값 36.6초가 걸립니다.

### 2. 규칙을 지워도 테스트가 통과했다

- **문제:** 모델 검수를 줄이면 코드 검사가 그만큼 믿을 만해야 합니다. 멘토 리뷰에 따라 검수 규칙을 한 곳씩 꺼 보고 테스트를 돌렸더니 24곳 중 3곳만 테스트가 실패했습니다.
- **원인:** 기존 테스트는 "반려됐는가"만 확인했습니다. 위험한 초안 하나는 규칙 여러 개에 동시에 걸려서, 규칙 하나를 지워도 다른 규칙 때문에 계속 반려됐습니다.
- **해결:** "막혀야 하는 초안"과 "조건 하나만 바꿔 통과해야 하는 초안"을 짝으로 두고, 반려 여부가 아니라 어느 규칙이 막았는지를 확인하게 했습니다([#220](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/220)).
- **결과:** 테스트가 지키는 규칙이 3/24에서 22/24로 늘었습니다. 남은 2곳은 입력 형식 검사가 먼저 막아서 만들 수 없는 경우입니다.

### 3. 대표 시나리오에 실제 사례가 없었다

- **문제:** 처음 대표 장면은 "인수자를 기다리는 중에 임대인이 말을 바꾼다"였습니다. 사례를 찾아보니 이 장면을 뒷받침하는 실제 사례를 확인하지 못했습니다.
- **해결:** 실제로 반복되는 모습인 "원상복구 범위가 처음에는 정해지지 않고 임대인 요구가 조금씩 늘어난다"로 대표 장면을 바꿨습니다. 공고 원문도 다시 읽어 절차 순서를 고쳤습니다. 점포철거비는 철거 전에 신청해 1차 적격심사를 받는 것이 기본 흐름이고, 영업 마무리가 철거보다 먼저입니다.
- **결과:** 근거를 확인하지 못한 장면은 보조로 내리고, 서류 점검과 5단계 로드맵을 중심에 두었습니다. 바뀐 내용은 [대표 사용자 흐름 9~10절](docs/hero-scenario.md)에 남겼습니다.

## 검증

| 무엇을 | 결과 |
|---|---|
| 자동 검사 | PR에서 [BE·Agent](.github/workflows/be-agent-ci.yml), [화면](.github/workflows/frontend-ci.yml), [브라우저 E2E](.github/workflows/e2e.yml) 검사가 돕니다. 11월 7일 기록 기준 BE 1,098개, 화면 658개 통과 |
| 실제 모델 평가 (11/7) | 미리 정답을 정해 둔 24건 중 22건 통과, 1건 실행 실패, 1건 기대값과 불일치. 결과에 맞춰 정답을 고치지 않았습니다 |
| 운영 서버 확인 (11/9) | 개인 카페 1건을 끝까지 진행. 판단 21건 모두 성공, 서류 6종 점검과 ZIP 내려받기 확인 |
| 비용 (11/9) | 위 1건에 모델 36번 호출, 약 230원(사용량 기준 추정) |
| 폭주 방지 | 판단 한 번에 모델 호출 40번, 실행 7분을 넘으면 멈춥니다 |

평가 입력은 실제 고객 자료가 아니라 만들어 낸 사례입니다. 조건과 한계는 [모니터링 기록](docs/agent/monitoring-results.md)에 그대로 적었습니다. 개인정보와 근거 없는 단정을 막는 장치는 [가드레일 문서](docs/agent/guardrails.md)에 있습니다.

## 로컬 실행

필요한 것: Node.js 20.19 이상, Python 3.12, Docker

```bash
# 1. DB (개발용 MySQL만 뜹니다)
docker compose up -d db

# 2. 서버
cd backend
pip install -r requirements.txt
python scripts/setup_agent_ocr.py      # 서류 기능을 쓸 때만
uvicorn app.main:app --reload          # http://localhost:8000

# 3. 화면 (새 터미널)
cd frontend
npm ci
npm run dev                            # http://localhost:5173
```

- 환경변수는 [`.env.example`](.env.example)(AI 연결)과 [`backend/.env.example`](backend/.env.example)(인증·DB)을 복사해 채웁니다. 화면을 로컬 서버에 붙이는 방법은 [Frontend README](frontend/README.md)에 있습니다.
- **`ENVIRONMENT=dev`는 서버를 켤 때마다 DB 표를 초기화합니다.** 개발 전용 DB에서만 씁니다.
- 실제 모델을 부르는 평가는 돈이 듭니다. 1건을 먼저 돌려 금액을 확인한 뒤 실행합니다.
- 운영 서버 배포는 [배포 문서](docs/deploy.md)를 따릅니다.

## 폴더 구조

```text
backend/app/agent/     판단 로직 (Supervisor, 정보분석, 절차조회, Review, 서류 Tool)
backend/app/be/        API, DB 모델, 인증
backend/app/common/    BE와 Agent가 주고받는 데이터 모양, 검수한 절차 자료
backend/sql/           운영 DB에 넣는 SQL
backend/tests/         서버·Agent 테스트
frontend/src/          화면
frontend/e2e/          브라우저 E2E 테스트
frontend/public/       안심가이드·개발 문서 (정적 HTML이 원본)
docs/                  구조, 배포, 평가 기록, 발표 자료
```

## 한계와 다음 과제

- 비프랜차이즈 개인 카페만 지원합니다. 프랜차이즈 카페와 일반 음식점은 "지원 준비 중"으로 안내합니다.
- 지원금 Agent는 구현되어 있지만 지금 판단 경로에서는 부르지 않습니다.
- 40~50대 사장님을 대상으로 한 인터뷰와 사용성 확인은 아직 하지 못했습니다. 큰 글자와 버튼, 한 번에 하나의 할 일은 설계 의도이고 효과를 확인한 것은 아닙니다.
- 글로 쓴 답변의 판단 시간(중간값 36.6초)을 더 줄여야 합니다.
- 실제 고객 서류로 서류 분류의 정확도를 확인하지 못했습니다.

## 팀

| 이름 | GitHub | 파트 |
|---|---|---|
| 최다물 | [@healthy27](https://github.com/healthy27) | PM · AI |
| 정승준 | [@tokengeoji](https://github.com/tokengeoji) | AI |
| 이현종 | [@leehyunjong12](https://github.com/leehyunjong12) | BE |
| 정현석 | [@Louie-03](https://github.com/Louie-03) | BE |
| 박시우 | [@blackwellSW](https://github.com/blackwellSW) | FE |

**일하는 방식**

- 한 번에 기능 하나씩, 대신 화면부터 서버, AI까지 다 이어지게 만들었습니다.
- 파트끼리 주고받는 데이터 모양은 문서가 아니라 코드(FastAPI, 파이썬 클래스)로 정했습니다.
- PR에는 왜 이 구조를 골랐는지와 고르지 않은 방법을 적고, 리뷰어를 2명 이상 지정하는 것을 원칙으로 했습니다. 합쳐진 PR은 265개입니다.
- AI 도구를 함께 썼습니다. 기준은 하나였습니다. **담당자가 남에게 설명할 수 없는 코드는 올리지 않는다.** 팀 규칙은 [CLAUDE.md](CLAUDE.md)와 [Git 컨벤션](docs/git-convention.md)에 있습니다.

## 문서 더 보기

- [최종 발표 자료 PDF](docs/presentation/reborn-final-presentation.pdf) · [시연 영상](docs/presentation/reborn-demo.mp4): 2026년 11월 11일 발표본
- [개발 문서 사이트](https://ktc4-kangwon-4.vercel.app/developers/): 서비스 흐름, 화면, API, 테스트
- [리본 안심가이드](https://ktc4-kangwon-4.vercel.app/safety): 서류 보호와 AI 검수 설명
- [서비스 전체 설명서 PDF](docs/final-guide/리본_서비스_전체_설명서.pdf): 11월 7일 기준 보관본
- [Agent 문서](docs/agent/README.md) · [대표 사용자 흐름](docs/hero-scenario.md) · [배포](docs/deploy.md) · [기술 스택](docs/tech-stack.md)
