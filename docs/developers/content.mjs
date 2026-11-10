export const implementationRevision = '6cb52843e911bf29bd85a5b3b6ca1690a0572b10';

// 문서 설명 원본. API 필드·타입·요청 예제는 generated/contracts.json에서 가져온다.
export const groups = [
  { title: '시작하기', items: [['guide/overview', '서비스 이해하기'], ['guide/quickstart', '개발 환경'], ['guide/ui-ux', '화면과 UX'], ['guide/tech-spec', '테크스펙']] },
  { title: '가게 상태와 판단', items: [['case', '상황 진단과 Case'], ['results', '결과 알려주기'], ['conflicts', '충돌 확인'], ['roadmap', '폐업 로드맵'], ['logs', '작업 기록'], ['account/common', '내 정보와 로그아웃']] },
  { title: '서류', items: [['documents', '서류함과 정산 점검']] },
  { title: '카카오 연동', items: [['auth', '카카오 로그인']] },
  { title: 'AI와 운영', items: [['agent/architecture', 'AI 실행 구조'], ['agent/guardrails', '근거와 검수'], ['operations', '실패와 복구']] },
  { title: '참고 정보', items: [['reference/errors', '에러 코드'], ['reference/tests', '테스트 케이스'], ['reference/schemas', '타입과 필드'], ['reference/glossary', '용어집'], ['reference/changes', '변경 이력'], ['reference/maintenance', '문서 갱신']] },
];

export const pages = [];
function doc(id, title, description, sections, sources = [], extra = {}) {
  pages.push({ id, title, description, sections, sources, ...extra });
}
const section = (id, title, text, rest = {}) => ({ id, title, text: Array.isArray(text) ? text : [text], ...rest });
const note = (title, text, tone = 'info') => ({ title, text, tone });
const tests = (...rows) => rows.map(([name, expected]) => ({ name, expected }));

doc('guide/overview', '서비스 이해하기', '폐업을 결정한 40~50대 개인 카페 사장님의 다음 행동과 필요한 서류를 정리합니다.', [
  section('purpose', '리본이 해결하는 문제', '폐업을 결정한 사장님은 임대차·원상복구·직원 정산·신고에 흩어진 안내를 내 가게에 적용해, 무엇을 먼저 실행하고 어떤 결과와 서류를 남길지 직접 연결해야 합니다. 리본은 한 가게의 확인된 상태와 진행을 Case로 모으고, 지금 먼저 확인할 행동과 이유를 안내합니다. 실행 결과를 알려주면 다음 행동을 다시 검토합니다.'),
  section('audience', '핵심 대상과 제공 범위', '핵심 설계 대상은 폐업 절차와 서류를 직접 챙기는 40~50대 비프랜차이즈 개인 카페 사장님입니다. 연령은 제품 설계의 초점이며 가입 제한이 아닙니다. 현재 로드맵은 개인 카페를 지원하며 프랜차이즈 카페와 일반 음식점은 지원 준비 중으로 안내합니다. 기관 신청·제출, 임대인 연락, 실제 철거는 사장님이 직접 수행합니다.', { note: note('지원사업 정보', '현재 MVP는 지원금 자격·금액·접수 가능 여부를 자동 확정하지 않습니다. Support Agent 구현은 남아 있지만 현재 Graph에서는 호출하지 않습니다.') }),
  section('target-design', '대상과 화면 설계를 함께 설명하기', '40~50대 사장님이 폐업 절차를 읽고 실행하는 부담을 줄이고자 Pretendard, 홈 할 일 제목 26px, 주요 버튼 글자 18~19px·높이 56~60px, 질문을 나눠 보여주는 배치와 선택형 입력을 적용했습니다. 현재 행동과 전체 로드맵을 분리하고, 할 일의 성격에 맞는 준비·제출·처리 완료 버튼과 원상복구 진행 상태 버튼을 제공합니다. 선택형 범위의 모름과 직접 입력도 구분합니다. 최초 진단의 과거 고용·보험 이력 질문은 현재 예·아니요로 받습니다.', { images: ['04-home', '02-diagnosis-restore', '07-results-choice'], links: [['40~50대를 고려한 UI/UX와 확인 과제', '/developers/ko/guide/ui-ux/']], note: note('설계 대상과 검증', '연령만으로 디지털 숙련도를 단정하지 않습니다. 현재 설명은 설계 의도와 구현 근거이며, 해당 연령대의 수요·사용성 효과를 검증했다는 뜻은 아닙니다.') }),
  section('focus', '우리가 강조하는 연결', '리본의 핵심은 정보를 많이 보여주는 데서 끝나지 않고, 내 가게의 확인된 사실 → 지금 할 일 하나 → 현실에서 실행한 결과 → 검수와 다음 안내를 연결하는 것입니다. 준비를 확인한 것과 실제 철거를 끝낸 것은 나눠 기록하며, 등록된 절차 안내가 끝나면 새로운 할 일을 억지로 만들지 않습니다. 종료 뒤에도 서류함과 기록에서 남은 자료를 확인합니다.', { links: [['기술 구성과 데이터 흐름', '/developers/ko/guide/tech-spec/'], ['절차 안내 종료의 의미', '/developers/ko/roadmap/common/#completion']] }),
  section('principles', '운영철학과 안심 이용', '사장님의 선택을 존중하고 확인한 정보로 안내하며, 서류 보호·AI 검수·정정과 복구 방법을 이용자 눈높이로 설명합니다.', { links: [['리본 안심가이드', '/safety/'], ['운영철학', '/safety/philosophy/']] }),
  section('flow', '서비스 흐름', '정해진 체크리스트를 한 번 보여주는 대신, 현실에서 알아본 내용을 받아 상태와 다음 행동을 갱신합니다.', { steps: ['로그인하고 가게 상황을 진단합니다.', '홈에서 지금 할 일과 실제로 물어볼 말을 확인합니다.', '현실에서 실행한 결과를 보기 또는 글로 알려줍니다.', '새 사실·추가 질문·충돌을 검수하고 저장합니다.', '로드맵, 서류와 기록을 보며 다음 행동을 이어갑니다.'], images: ['04-home', '07-results-choice'] }),
  section('demo', '대표 시연', '임대인에게 원상복구 범위를 확인한 뒤, 카운터·싱크대·간판만 철거하면 된다는 답을 입력합니다. 리본이 이해한 범위와 철거 필요 여부를 확인하고, 정보가 부족하면 더 답하거나 다르게 이해했으면 바로잡습니다.', { links: [['결과 알려주기', '/developers/ko/results/common/'], ['서류 점검', '/developers/ko/documents/common/']] }),
], ['docs/hero-scenario.md', 'frontend/docs/ui-guidelines.md', 'frontend/src/components/ui/TaskCard.tsx', 'frontend/src/components/ui/Button.tsx', 'backend/app/agent/roadmap.py', 'backend/app/agent/graph.py']);

doc('guide/quickstart', '개발 환경', 'FE, Backend와 Agent를 로컬에서 실행하기 전에 확인합니다.', [
  section('requirements', '요구 사항', 'FE는 Node 20.19 이상 또는 22.12 이상, BE는 Python 3.12와 MySQL 8.0.46을 사용합니다. 정확한 패키지 버전은 lockfile과 requirements가 기준입니다.', { table: [['구분', '실행 위치', '역할'], ['Frontend', 'frontend/', 'React·Vite 화면과 /api 프록시'], ['Backend와 Agent', 'backend/', 'FastAPI·LangGraph, 같은 Python 프로세스'], ['MySQL', '루트 Compose', 'Case·이력·근거·회원 상태'], ['문서', 'frontend/public/developers/', '빌드 때 생성되는 공개 정적 문서']] }),
  section('frontend', 'Frontend 실행', '처음 설치하거나 CI에서는 lockfile 그대로 설치합니다. FE 기본 API 주소는 /api이며, 로컬 BE에 직접 붙일 때만 frontend/.env.local에 공개 API 주소를 설정합니다.', { code: { language: 'Shell', text: 'cd frontend\nnpm ci\nnpm run dev' } }),
  section('backend', 'Backend 실행', 'AI 연결은 루트 .env.example, 서버 인증·DB는 backend/.env.example을 보고 각각 .env와 backend/.env를 준비합니다. 서류 기능은 OCR 준비 명령을 한 번 실행합니다. 데이터베이스와 문서 볼륨의 대상부터 확인합니다.', { code: { language: 'Shell', text: '# 저장소 루트에서 DB 실행\ndocker compose up -d db\n\n# Python 3.12 환경에서\ncd backend\npython -m pip install -r requirements.txt\npython scripts/setup_agent_ocr.py\npython -m uvicorn app.main:app --reload' }, note: note('주의', 'ENVIRONMENT=dev의 앱 시작에는 테이블 초기화가 있습니다. 운영 데이터베이스에 연결한 상태로 개발 서버를 시작하면 안 됩니다.', 'warning') }),
  section('oauth', '카카오 로그인과 로컬 미리보기', '실제 로그인은 카카오 앱의 Redirect URI, KAKAO_REDIRECT_URI와 브라우저 콜백 주소가 일치해야 합니다. 가짜 로그인은 개발·허용된 Preview에서 화면을 보는 기능이며 실제 인증 성공의 증거가 아닙니다.', { links: [['카카오 로그인 설정하기', '/developers/ko/auth/settings/']] }),
], ['frontend/README.md', 'frontend/package.json', 'backend/.python-version', 'backend/app/main.py', 'docker-compose.yml']);

doc('guide/ui-ux', '화면과 UX', '40~50대 개인 카페 사장님을 고려한 글자·버튼·정보 배치와 설계 이유를 설명합니다.', [
  section('principles', '40~50대 핵심 사용자를 위한 화면 원칙', '폐업 절차를 직접 챙기는 40~50대 사장님의 읽기·선택·입력 부담을 줄이는 것을 목표로 합니다. 홈에서는 지금 먼저 확인할 행동 하나를 강조하고, 전체 진행은 로드맵으로 분리합니다. 질문은 한 장씩 보여주며 모름·해당 없음·확인 필요를 구분합니다.', { list: ['질문은 사용자가 답할 수 있는 내용만 받습니다.', '서버가 확정한 값만 표시하고 저장 응답 전에 체크를 바꾸지 않습니다.', '중요한 선택은 미리 고르지 않습니다.', '실패하면 입력을 보존하고 가능한 복구 행동을 안내합니다.'] }),
  section('readability', '글자·버튼·배치의 구현 근거', '큰 핵심 글자와 버튼, 일관된 글꼴, 단계별 질문으로 지금 읽고 실행할 내용을 구분합니다. 아래 값은 현재 서비스 컴포넌트 기준입니다.', { table: [['설계', '현재 구현', '목적'], ['글꼴', 'Pretendard · 한국어 단어 중간 줄바꿈 방지', '한글 안내를 일관되게 읽기'], ['홈 할 일 제목', '26px · 줄높이 36px', '핵심 행동을 먼저 찾기'], ['주요 버튼', '기본 높이 56px·글자 18px / 큰 버튼 60px·19px', '주요 행동을 찾고 누르기'], ['질문과 입력', '질문을 나눠 표시 · 선택형 · 모름 · 직접 입력', '기억·타이핑·불확실한 응답 부담 줄이기'], ['정보 배치', '현재 행동 카드 · 별도 로드맵 · 홈/서류함/기록 하단 탭', '지금 할 일과 전체 진행 구분하기']], images: ['04-home', '02-diagnosis-restore', '07-results-choice'] }),
  section('screens', '화면과 이동', '홈·서류함·기록은 하단 탭입니다. 머리말의 사람 버튼은 /mypage의 내 정보로 연결됩니다. 로드맵과 개별 작업은 탭 밖에서 열며, 충돌 확인은 정상 순서의 중간 단계가 아니라 예외 분기입니다.', { images: ['04-home', '11-roadmap'], table: [['경로', '화면'], ['/login · /login/callback', '소개와 로그인 처리'], ['/cases/new', '조건별 상황 진단'], ['/case · /task', '현재 Case와 할 일 상세'], ['/results · /replan', '실행 결과와 반영 내용'], ['/confirm', '기존값과 새값 충돌 확인'], ['/roadmap · /roadmap/:taskId', '전체 순서와 작업별 입력'], ['/docs · /docs/check · /docs/done', '서류함·점검·제출 파일'], ['/log · /mypage', '작업 기록·내 정보와 로그아웃']] }),
  section('safety-motion', '공개 안심가이드의 소개 영상과 안내', '안심가이드 홈은 사용자가 제공한 12초·1920×1080 타이포그래피 MP4와 준비·완료 구분, 절차 안내 종료, 내 정보 확인의 세 가지 안내로 구성합니다. 각 안내는 설명과 미리보기 화면을 나란히 보여주고 상세 안내로 연결합니다. 영상은 무음 반복 재생과 멈춤·재생을 지원하며, 동작 줄이기 설정에서는 자동 재생하지 않습니다. 배경 탭이나 화면 밖에서는 재생을 멈춥니다. 영상은 브랜드 소개이며 실제 상담 화면이나 처리 상태가 아닙니다.', { links: [['움직이는 안심가이드 홈', '/safety/']] }),
  section('accessibility', '읽기와 접근성', 'Pretendard와 의미 기반 색·글자 토큰을 사용합니다. 입력 글자는 16px 이상, 버튼·선택 항목에는 이름과 상태를 제공합니다. 움직임 줄이기 설정을 따르고 시트·키보드 포커스를 고려합니다.'),
  section('user-validation', '40~50대 사용자에게 확인할 과업', '모바일 사용 경험이 다른 핵심 대상에게 도움 없이 진행하도록 하고, 어려운 글자·잘못 누른 곳·도움 요청과 과업 설명 여부를 기록합니다. 아래는 수행할 확인 과제이며 통과한 테스트 결과가 아닙니다.', { tests: tests(['홈에서 다음 행동 찾기', '누구에게 무엇을 확인할지 자기 말로 설명'], ['진단 답 수정 후 계속하기', '질문과 이동 경로를 이해'], ['모름·직접 입력 사용', '모름을 불필요와 구분하고 없는 보기를 글로 설명'], ['AI 이해 내용 정정', '다른 내용을 발견하고 정정 경로 찾기'], ['서류 점검 뒤 다음 단계 설명', 'ZIP 준비와 실제 기관 제출을 구분'], ['375px·브라우저 200% 확대', '핵심 내용과 버튼의 읽기·조작·잘림 여부 확인']) }),
  section('limits', '검증할 UX 과제', '11~15px 보조 글자도 남아 있어 모든 글자가 큰 것은 아닙니다. 작은 화면과 확대에서 읽기·버튼 잘림을 확인해야 합니다. 5단계 번호가 철거와 영업 종료 순서를 오해하게 할 수 있고 정상 반영 후 [맞아요]는 저장 전 승인이 아닙니다. 이러한 안내가 실제 사장님에게 이해되는지도 확인합니다.', { note: note('설계 의도와 검증 결과', '40~50대는 핵심 설계 대상이며 연령만으로 사용 능력을 단정하지 않습니다. 현재 해당 연령대의 고객 수요나 사용성 개선 효과가 실험으로 입증됐다는 뜻은 아닙니다.') }),
], ['frontend/docs/ui-guidelines.md', 'frontend/src/routes.tsx', 'frontend/src/main.tsx', 'frontend/src/index.css', 'frontend/src/styles/tokens.css', 'frontend/src/components/ui/Button.tsx', 'frontend/src/components/ui/TaskCard.tsx', 'frontend/src/components/ui/QuestionScreen.tsx', 'frontend/src/App.tsx']);

doc('case/common', '상황 진단과 Case', '가게의 기본 조건을 받고 첫 판단을 시작합니다.', [
  section('why', '이 기능이 필요한 이유', '임차·직원·대출·보험 이력에 따라 해야 할 일이 달라집니다. 먼저 버튼과 날짜 선택으로 상황을 받고, 확인하지 못한 값은 모름으로 남깁니다.'),
  section('questions', '진단 질문', '앞 답으로 불필요해진 질문은 생략합니다. 현재 직원이 0명이어도 과거 고용 이력을 별도로 확인합니다. 최초 진단에서 과거 직원·사업장 보험 가입 이력은 예·아니요로 받습니다. API에서 생략한 null과 아니요인 false는 구분합니다.', { table: [['입력', '묻는 조건과 의미'], ['업종·가게 상황', '개인 카페·프랜차이즈·음식점, 임차·직원·대출·서비스 계약'], ['월세·복구 조항', '빌린 가게일 때만 질문, 조항과 실제 범위는 별개'], ['직원·보험', '현재 인원과 과거 고용·사업장 보험 이력 구분'], ['폐업 시기', '이번 달·다음 달·미정, 실제 폐업일과 별도']], images: ['02-diagnosis-situ', '02-diagnosis-restore'] }),
  section('create', '생성과 첫 판단', 'POST /cases가 회원당 Case 하나와 PENDING 입력 이력을 만듭니다. 첫 판단은 배경에서 진행하고, 홈은 GET /cases로 현재 상태를 조회합니다. 계획 시기와 신고할 실제 폐업일은 구분해 저장합니다.', { steps: ['진단 답을 확인합니다.', 'Case와 첫 판단 이력을 저장합니다.', '요청 커넥션을 반환하고 판단을 시작합니다.', '홈에서 처리 상태와 다음 할 일을 확인합니다.'] }),
  section('tests', '테스트 케이스', '진단 답은 화면 이동·새로고침과 실패 뒤에도 이어 쓸 수 있어야 합니다.', { tests: tests(['자가로 답 변경', '월세·임차 복구 질문을 제외하고 낡은 값을 보내지 않음'], ['직원 있음·인원 0', '진행 차단'], ['과거 직원 있음·현재 0', '과거 이력 보존'], ['생성 응답 뒤 재전송', '두 번째 Case를 만들지 않음'], ['인증 만료·생성 실패', '진단 답 보존']) }),
], ['frontend/src/pages/CaseCreatePage.tsx', 'frontend/src/lib/diagnosisSteps.ts', 'frontend/src/adapters/case.ts', 'backend/app/be/services/case.py'], { family: 'case' });

doc('results/common', '결과 알려주기', '현실에서 실행한 결과를 받아 상태와 다음 행동을 다시 검토합니다.', [
  section('why', '이 기능이 필요한 이유', '임대인에게 물어본 답이나 실제 진행 상태는 최초 진단만으로 알 수 없습니다. 이 결과를 받아 확인된 사실을 채우고 다음 계획으로 이어갑니다.'),
  section('flow', '사용 흐름', '홈의 할 일에서 실제로 물어볼 질문을 확인하고, 받은 답을 보기나 글로 전달합니다.', { images: ['07-results-choice', '38-result-filled'], steps: ['GET /cases/results로 현재 입력 종류와 판단 번호를 확인합니다.', '서버가 허용한 범위 선택·완료 버튼·진행 상태 또는 최대 2,000자의 글 중 하나를 보냅니다.', '새 접수 번호로 PENDING 이후 결과를 조회합니다.', '반영된 내용·추가 질문·충돌·실패를 각각 표시합니다.'] }),
  section('choices', '선택형과 직접 입력', '원상복구 범위와 철거 여부의 선택형은 현재 행동에서 서버가 허용할 때만 사용합니다. UNKNOWN은 기존 확정값을 지우지 않습니다. PARTIAL인데 구체적인 대상이 없으면 범위를 다시 묻습니다.'),
  section('buttons', '할 일에 맞는 버튼 답변', 'GET /cases/results의 result_input_kind는 TEXT·RESTORATION_ANSWER·ACTION_DONE·RESTORATION_STATUS입니다. ACTION_DONE은 action_done_kind에 따라 [준비했어요]·[제출했어요]·[처리 끝났어요]·[끝냈어요]로 표시합니다. [아직 …]은 서버에 완료 요청을 보내지 않고 홈으로 돌아갑니다. RESTORATION_STATUS는 NOT_STARTED·IN_PROGRESS·COMPLETED 중 하나를 받습니다. 버튼 답은 모델로 다시 해석하지 않으며 검수와 저장 검증을 거칩니다.', { images: ['2026-11-09-action-done', '2026-11-09-restoration-status'], table: [['입력 종류', '전달 필드'], ['TEXT', 'raw_input'], ['RESTORATION_ANSWER', 'restoration_answer'], ['ACTION_DONE', 'action_done: true'], ['RESTORATION_STATUS', 'restoration_status']], note: note('한 번에 하나', '네 입력 필드 중 정확히 하나와 현재 case_history_id를 보냅니다. 서버는 현재 행동·질문에 맞지 않는 버튼 답을 422로 거부합니다.') }),
  section('preparation', '철거 준비 확인', '철거 준비를 확인했다고 보고한 뒤에는 같은 준비 확인을 반복 후보로 제시하지 않습니다. 준비를 마친 뒤 진행 중으로 확인된 작업은 새 진행 보고를 기다리고, 진행 상태가 미확인이면 [아직 시작 안 했어요 / 진행 중이에요 / 다 끝냈어요]로 확인합니다. 범위를 답한 사실만으로 준비나 작업 완료를 추정하지 않습니다. 지원사업 공고만으로 실제 철거 착수를 허용하지 않으며, 다음 행동은 확인된 조건에 따라 다시 정합니다.'),
  section('confirmation', '반영 결과 확인', 'UPDATED는 이미 서버에 반영한 결과입니다. 가게 정보 필드가 같아도 준비 확인이나 절차 진행이 바뀌면 UPDATED이며, changes 배열이 비어 있다는 이유로 NO_CHANGE로 표시하지 않습니다. [맞아요]가 저장을 승인하는 것은 아닙니다. 다르게 이해했으면 직접 적어 바로잡고, 기존값과 충돌한 사실 후보는 선택을 받을 수 있습니다.', { images: ['39-understood-full'], note: note('접수와 완료', 'HTTP 성공과 새 이력 번호는 접수 성공입니다. 반영 완료는 별도 result 값으로 판단합니다.') }),
  section('finished', '마지막 절차 뒤의 응답', 'PROCEDURES_COMPLETED는 등록된 절차 안내가 종료됐다는 별도 결과입니다. 다음 행동·질문을 새로 만들지 않고 홈의 종료 안내로 이동합니다. UPDATED·NO_CHANGE·실패와 구분해 처리합니다.', { links: [['종료 상태와 Case 완료의 차이', '/developers/ko/roadmap/common/#completion']] }),
  section('tests', '테스트 케이스', '정상 경로와 추가 정보·충돌·실패를 함께 확인합니다.', { tests: tests(['선택 하나 누락', '보내기 비활성화'], ['일부 복구·상세 없음', '구체 범위 질문'], ['글과 선택형 동시 전송', '422 거부'], ['지난 판단 번호 전송', '409 후 최신 상태 확인'], ['2,000자 초과', '자르지 않고 보내기 차단'], ['판단 실패', '입력을 보존하고 복구 종류 구분']) }),
], ['frontend/src/pages/ResultInputPage.tsx', 'frontend/src/lib/resultSubmit.ts', 'backend/app/be/services/case.py', 'backend/app/agent/info_agent/agent.py'], { family: 'results' });

doc('conflicts/common', '충돌 확인', '확정된 사실과 새로운 답변이 다를 때 사용자에게 확인합니다.', [
  section('why', '자동으로 덮어쓰지 않는 이유', '새 입력이 들어왔다는 이유로 기존 사실을 바꾸면 중요한 상태가 사라집니다. 기존값과 충돌하는 후보가 나오면 멈추고 어느 값을 쓸지 사용자에게 선택받습니다.', { images: ['08-confirm'] }),
  section('flow', '처리 순서', '충돌 항목은 미리 선택하지 않습니다. 사용자의 선택 뒤에도 계획은 다시 검수해야 합니다.', { steps: ['충돌 후보와 기존값을 보관하고 Case는 유지합니다.', '항목별 STORED 또는 PROPOSED를 받습니다.', '유효한 현재 충돌인지 검증하고 PENDING을 접수합니다.', '선택한 사실로 재판단·Review를 수행합니다.', '성공하면 상태 변경과 충돌 해결을 함께 저장합니다.'] }),
  section('failure', '실패와 재접속', '결정 뒤 RETRY·CONTACT_SUPPORT로 실패하면 충돌과 기존 Case를 유지하며 가능한 복구 방법을 보여줍니다. RESUBMIT_INPUT·NONE 실패는 현재 판단과 원본 충돌 묶음이 일치하는 등 서버 조건을 만족할 때 이전 묶음을 미채택으로 정리하고 새 상황 글 입력으로 이어갑니다. NONE에서는 다른 쪽을 다시 고르도록 안내하지 않습니다. 재시도 가능한 실패만 같은 선택으로 다시 보내며, 재시도 불가로 실패한 선택 조합은 같은 묶음에서 반복 전송하지 못하게 합니다. 다른 Case 참조·낡은 선택·동시 결정은 서버에서 거부합니다. 직접 URL 진입처럼 충돌 정보가 없는 화면은 안전한 진입점으로 돌아갑니다.'),
  section('tests', '테스트 케이스', '', { tests: tests(['항목 일부만 선택', '전송 차단'], ['기존값 유지', '선택한 기존값으로 재판단'], ['새값 채택', '검수 뒤에만 변경'], ['동시에 두 결정', '한 건만 접수'], ['저장 중 실패', '충돌 해결과 값 변경이 일부만 남지 않음']) }),
], ['frontend/src/pages/ConfirmChangePage.tsx', 'backend/app/be/services/conflict_decision.py', 'backend/app/be/services/decision_record.py', 'backend/tests/test_double_submit.py'], { family: 'conflicts' });

doc('roadmap/common', '폐업 로드맵', '전체 순서와 작업별 진행을 확인합니다.', [
  section('stages', '다섯 단계', '폐업 준비, 원상복구·철거, 영업 마무리·폐업 신고, 지원금 정산·가게 반환, 세금·마무리로 묶어 보여줍니다. 현재 작업 정의는 26개이며 가게마다 해당 여부와 상태가 달라집니다.', { images: ['11-roadmap'] }),
  section('status', '진행 상태', '단계는 작업을 묶는 구조입니다. 실제 영업 종료와 철거의 순서는 현재 조건과 안내를 함께 확인해야 하며 단계 번호만으로 결정하면 안 됩니다.', { table: [['값', '의미'], ['NOT_STARTED', '아직 시작하지 않음'], ['IN_PROGRESS', '진행 중'], ['COMPLETED', '완료로 기록됨'], ['NOT_APPLICABLE', '이 가게에 해당 없음'], ['NEEDS_CONFIRMATION', '조건 또는 사실 확인 필요']] }),
  section('completion', '절차 안내 종료와 Case 완료', 'PROCEDURES_COMPLETED는 Review를 통과한 등록 절차 안내 종료입니다. 홈과 작업 기록에 종료를 표시하고, 결과·충돌 처리 뒤 홈으로 이동합니다. 기관 신고·지원금 지급·모든 폐업 업무의 완료를 보증하지 않으며 Case의 COMPLETED와도 다릅니다. Case 완료는 별도로 vat_submission 체크와 연결됩니다. 확인된 원상복구 범위·철거 여부는 범위 확인 작업에 반영하고, 준비 확인과 실제 작업 진행을 혼동하지 않습니다.', { images: ['2026-11-09-procedures-completed'] }),
  section('inputs', '작업별 입력', '체크·서류 첨부·심사 결과·폐업 정보·보증금 기록·실행 결과 보고를 작업 성격에 맞게 연결합니다.', { table: [['작업', '입력과 의미'], ['사용자 체크', '저장 성공 뒤 완료 표시, 완료 취소 가능'], ['사진·증명원', '서류함에 올리기 연결, 체크와 파일 존재는 별개'], ['1차 적격심사', '기관에서 받은 결과 true·false·null 기록'], ['통합 폐업 신고', '실제 폐업일·사유·주소 저장, 기관 접수 API 아님'], ['보증금', 'FULL·PARTIAL·NONE의 기록, AI 분쟁 판단 아님'], ['공식 절차', '결과 보고와 재판단으로 진행 확인']] }),
  section('case-completion', '서비스 완료', '현재 구현은 vat_submission 체크에 Case COMPLETED를 연결합니다. 이 체크를 풀면 다시 진행 중으로 바뀝니다. 다른 세금 확인 작업은 남아 있을 수 있으므로 모든 외부 의무가 끝났다는 보증과 구분합니다.', { note: note('확인 필요 작업', 'NEEDS_CONFIRMATION 항목은 [다 했어요]를 잠그며 서버도 완료 요청을 거부합니다. 체크했다고 공식 접수·심사 통과로 승격하지 않습니다.', 'warning') }),
  section('tasks', '전체 작업 정의', '아래 목록은 실제 roadmap.py에서 생성합니다.', { roadmap: true }),
  section('tests', '테스트 케이스', '', { tests: tests(['자가·직원 없음', '해당하지 않는 작업 제외'], ['심사 결과 미확인', '정산 조건 확인 필요 유지'], ['저장 실패', '체크를 먼저 바꾸지 않음'], ['완료 취소', '서버 값으로 복원'], ['미지원 업종', '가짜 로드맵 대신 지원 준비 중 안내']) }),
], ['backend/app/agent/roadmap.py', 'frontend/src/lib/taskFlows.ts', 'frontend/src/pages/TaskFlowPage.tsx', 'backend/app/be/services/case.py'], { family: 'roadmap' });

doc('documents/common', '서류함과 정산 점검', '사진과 PDF를 모아 종류·값을 확인하고 정산 서류를 대조합니다.', [
  section('flow', '문서 처리 흐름', '업로드와 점검은 별도 기능입니다. 올린 파일이 있다는 사실만으로 점검 통과나 기관 제출이 되지 않습니다.', { steps: ['PDF·PNG·JPG/JPEG를 한 장씩 올립니다.', '로컬 OCR과 가린 자료의 모델 판독으로 종류와 값을 읽습니다.', '불확실한 판독은 사용자가 확인합니다.', '가게 이름·신청인과 실제 폐업일을 받아 코드 규칙으로 대조합니다. 직접 입력한 가게 이름은 Case에 저장하고, 서류에서 읽은 상호로 덮어쓰지 않습니다.', '문제가 없으면 점검된 서류와 요약 ZIP을 받습니다.'], images: ['17-docs', '18-docs-issues'] }),
  section('limits', '지원 형식과 제한', '20,000,000바이트 이하, 암호 없는 30쪽 이하 문서를 받습니다. 손상·과도한 페이지 크기·지원하지 않는 형식은 거부합니다. 현재 FE 업로드 제한 시간은 110초입니다.'),
  section('checks', '점검 항목', '누락, 공사내역서·세금계산서·이체 금액, 거래처·수취인·신청인·공급받는 자, 실제 폐업일, 같은 전후 사진을 대조합니다. 통장 사본은 필수 정산 목록이 아니며 카드 결제 대체 서류 경로는 아직 없습니다.', { note: note('읽기와 대조', 'OCR·모델은 문서의 종류와 값을 읽습니다. 금액·이름·날짜의 대조는 코드로 실행합니다. 서비스 점검 통과는 기관의 적격 판단이 아닙니다.') }),
  section('safety', '안전 검사 결과와 복구', '최신 구현은 안전 검사 차단을 일반 업로드 실패와 구분합니다. 같은 파일 재업로드를 반복 권하지 않습니다.', { table: [['상황', '응답·화면 분기'], ['AGENT_SAFETY_REFUSE', '422 detail.code, 처리하지 않았음을 알리고 내용 확인·다른 파일 안내'], ['AGENT_SAFETY_CRISIS_SUPPORT', '422 detail.code, 진행·서류를 보존하고 상담 창구 안내'], ['모델·OCR 실패', '502, 잠시 뒤 재시도 안내'], ['시간 초과', '기존 서류 재조회, 같은 파일의 처리 상태 확인']], code: { language: 'JSON · 응답 형식 예시', text: '{\n  "detail": {\n    "code": "AGENT_SAFETY_REFUSE",\n    "message": "이 파일은 자동으로 읽지 않았어요. 서류 내용을 확인한 뒤 다른 파일로 올려 주세요."\n  }\n}' } }),
  section('replan', '서류 변경과 재판단', '확인된 원상복구 조항이 새로 생기거나 바뀌면 DOCUMENT_SUBMITTED 판단을 예약합니다. 동일 조항·금액 서류 추가·삭제를 이유로 같은 재판단을 반복하지 않습니다. 판단 중이면 보류했다가 이어서 처리합니다.'),
  section('storage', 'DB에 보관하는 목록과 파일 산출물', '서류 목록·추출값·점검 상태와 마지막 판단에 사용한 context는 MySQL의 case_document_context에 저장합니다. 업로드 분석 중에는 긴 DB 잠금을 잡지 않고, 저장 직전 최신 목록과 비교해 그사이 삭제하거나 확인한 값을 보존합니다. 점검 도중 서류가 바뀌면 과거 점검 통과를 적용하지 않습니다. 처리한 PDF와 분석 캐시 등 산출물은 Case별 서버 파일 저장소에 남으며, 목록 삭제가 모든 파일의 영구 삭제를 뜻하지는 않습니다.'),
  section('download', '제출 파일', '현재 문서 digest·가림 정책·파일 무결성과 COMPLETE를 확인한 뒤 ZIP을 제공합니다. 서류가 바뀌면 지난 점검은 무효가 됩니다. 파일을 받은 뒤 외부 기관에 직접 제출합니다.', { images: ['20-package'] }),
  section('tests', '테스트 케이스', '', { tests: tests(['이체확인증 누락 후 추가', '구체적 누락 표시 후 재점검'], ['금액·거래처 불일치', '문제 표시·ZIP 차단'], ['애매한 OCR', '확인 전 확정값 사용 금지'], ['다른 회원 문서', '자료 격리'], ['점검 뒤 파일 변경', '과거 통과 재사용 금지'], ['안전 검사 코드', '재업로드 반복 권유 없이 코드별 안내']) }),
], ['backend/app/be/services/document.py', 'backend/app/be/routers/document.py', 'backend/app/agent/document_tool/checks.py', 'frontend/src/hooks/useDocuments.ts', 'frontend/src/pages/DocsPage.tsx'], { family: 'documents' });

doc('logs/common', '작업 기록', '사장님과 리본이 한 일을 최근 순서로 확인합니다.', [
  section('purpose', '재방문에 필요한 맥락', '지난번 입력과 판단 결과를 한 흐름으로 보여줘 진행 상황을 복원합니다. 사용자 작업 기록과 개발용 모델 추적은 서로 다릅니다.', { images: ['21-log'] }),
  section('events', '기록되는 이벤트', '진단, 결과 전달, 충돌 선택, 체크·취소, 심사 결과, 서류 업로드·점검과 새 작업 안내, 등록된 절차 안내 종료(PROCEDURES_COMPLETED)를 저장 상태에서 조립합니다. 홈의 활동 띠는 같은 기록 중 리본이 한 일을 사용합니다.'),
  section('privacy', '표시와 예외', '필요 없는 원문을 기록 탭에 반복 노출하지 않습니다. 기록 없음과 조회 실패를 나눠 표시하고 다른 회원의 Case 기록은 읽지 않습니다. 머리말의 내 정보는 /mypage로 연결되며 기존 /notifications 화면은 제거됐습니다.'),
  section('tests', '테스트 케이스', '', { tests: tests(['빈 기록', '빈 상태 표시'], ['동일 체크 재요청', '불필요 이력 중복 방지'], ['같은 서류 재점검', '같은 통과를 중복 기록하지 않음'], ['타인 자료', '기록과 문서 소유권 격리']) }),
], ['frontend/src/pages/LogPage.tsx', 'frontend/src/hooks/useLogs.ts', 'backend/app/be/services/case.py', 'frontend/src/pages/MyInfoPage.tsx', 'frontend/src/adapters/logs.ts'], { family: 'logs' });

doc('auth/common', '카카오 로그인 이해하기', '카카오 인증과 리본의 회원·JWT를 연결합니다.', [
  section('flow', '동작 흐름', 'FE가 state를 생성하고 카카오로 이동합니다. 콜백에서 일회 검증한 뒤 code를 BE에 전달합니다. BE는 카카오 토큰 교환과 사용자 정보 조회를 수행하고 리본 회원을 확인해 자체 Access·Refresh JWT를 발급합니다.', { steps: ['GET /login/form으로 인가 화면에 이동합니다.', '카카오 인증 뒤 /login/callback에서 state를 확인합니다.', 'POST /login에 code를 보냅니다.', '응답 헤더에서 리본 토큰을 받습니다.', 'Case 유무에 따라 진단 또는 홈으로 이동합니다.'], images: ['01-login'] }),
  section('tokens', '두 종류의 토큰', '카카오 사용자 정보 조회에는 카카오 토큰을 사용하며 리본 API에는 자체 JWT를 Access-Token 헤더로 보냅니다. 토큰은 sessionStorage에 있고, 401이면 Refresh-Token으로 재발급을 시도합니다.', { note: note('현재 저장 방식', 'sessionStorage는 XSS 노출을 해결하는 장치가 아닙니다. Access를 메모리에 두는 개선은 현재 코드의 후속 과제입니다.') }),
  section('state', '콜백과 동시 재발급', 'state는 누락·불일치·재사용을 거부하며 검증 후 폐기합니다. 같은 카카오 계정의 첫 로그인이 겹쳐 회원 생성이 경합하면 롤백 뒤 먼저 생성된 회원으로 로그인을 이어갑니다. 같은 Refresh 토큰의 동시 재발급은 공유하고, 늦은 응답이 로그아웃이나 새 로그인을 덮지 않게 합니다.'),
  section('login-errors', '로그인 오류 구분', '카카오 토큰 교환의 잘못되거나 재사용된 인가 코드 등 4xx는 리본의 400으로, 카카오 401인 앱 키·시크릿 설정 문제와 통신·상위 서버 오류는 502로 나눕니다. 카카오 응답 본문이나 인증 비밀을 사용자 안내·로그에 그대로 남기지 않습니다.'),
  section('official', '공식 문서', '카카오 API 자체의 설정과 규격은 공식 원문을 참고하고, 이 문서에서는 리본에서 연결하는 방법을 설명합니다.', { links: [['카카오 로그인 이해하기', 'https://developers.kakao.com/docs/ko/kakaologin/common'], ['카카오 로그인 REST API', 'https://developers.kakao.com/docs/ko/kakaologin/rest-api'], ['카카오 로그인 설정하기', 'https://developers.kakao.com/docs/ko/kakaologin/prerequisite']] }),
], ['frontend/src/lib/auth.ts', 'frontend/src/lib/api.ts', 'frontend/src/pages/LoginCallbackPage.tsx', 'backend/app/be/services/auth.py'], { family: 'auth' });

doc('auth/settings', '카카오 로그인 설정하기', '카카오 앱 설정과 리본 서버 설정을 맞춥니다.', [
  section('app', '카카오 앱', '카카오 로그인 사용 설정, Redirect URI와 필요한 동의항목을 확인합니다. 현재 BE는 profile_nickname을 요청합니다. 변경되는 카카오 콘솔의 세부 메뉴 경로는 공식 설정 문서를 기준으로 확인합니다.', { links: [['공식 설정 문서', 'https://developers.kakao.com/docs/ko/kakaologin/prerequisite']] }),
  section('server', '리본 서버', '아래 값은 서버 설정입니다. 실제 비밀값을 문서·공개 FE 환경변수·로그에 넣지 않습니다.', { table: [['설정', '역할'], ['KAKAO_CLIENT_ID', '카카오 앱 REST API 키'], ['KAKAO_CLIENT_SECRET', '토큰 교환의 client_secret'], ['KAKAO_REDIRECT_URI', '카카오에 등록한 콜백 주소'], ['JWT_SECRET_KEY', '리본 자체 JWT 서명 키']] }),
  section('local', '로컬과 배포', '로컬 실제 로그인에서는 BE의 Redirect URI와 카카오 등록값을 http://localhost:5173/login/callback에 맞춥니다. 배포 BE가 배포 콜백 주소 하나를 쓰고 있다면 로컬로 돌아오지 않습니다. 개발 가짜 로그인은 화면 검토에만 사용합니다.'),
  section('tests', '확인할 테스트', '', { tests: tests(['state 누락·불일치·재사용', '토큰 교환 전 거부'], ['토큰 응답 헤더 누락', '성공한 로그인으로 처리하지 않음'], ['리다이렉트 주소 불일치', '실제 설정값 확인'], ['동시 401', '공유 재발급 한 번, 새 세션 보호']) }),
], ['backend/app/be/routers/auth.py', 'backend/app/be/services/auth.py', 'frontend/src/lib/auth.ts', 'frontend/README.md'], { family: 'auth' });

doc('agent/architecture', 'AI 실행 구조', 'LangGraph가 정한 실행 경로와 구성요소의 책임을 설명합니다.', [
  section('graph', 'MVP 실행 경로', 'Procedure → Info → Supervisor → Review 순서로 진행합니다. 충돌은 사용자 선택을 받은 뒤 다시 판단합니다. Support는 현재 경로에서 호출하지 않습니다.', { steps: ['Procedure: 검수된 공식 자료와 조건·절차 근거를 준비합니다.', 'Info: 사실·진행·충돌 후보를 근거와 함께 추출합니다.', 'Supervisor: 검증된 행동 후보에서 하나를 선택하거나 질문합니다.', 'Review: 코드 검사 또는 모델 검수와 코드 검사로 검수합니다.', 'BE: 검수된 변경 후보를 최신 상태와 대조하고 저장합니다.'] }),
  section('codepaths', '모델을 생략하는 경로', '선택형 답은 Info 모델로 재해석하지 않습니다. 검수 정리본이 충분한 첫 판단·충돌 확인 후 처리도 가능한 경우 코드로 채웁니다. 모델이 만든 사실·문장이 없고 첫 검수인 등 제한된 조건에서는 code-only Review를 사용합니다.', { note: note('필수 검수', '모든 정상 계획은 Review 경계를 통과합니다. 모든 계획에서 별도 Review LLM을 호출한다는 뜻은 아닙니다.') }),
  section('limits', '실행 한도', '기본 모델 호출 예산 40회와 실행 제한 420초를 한 실행의 client들이 공유합니다. Review 재작업은 최대 2회이며 코드가 고정한 blocker 목록만을 문제 삼은 모델 반려는 수정 가능한 판정에서 제외하지만, 다른 계약·안전 이슈까지 제거하지 않습니다. 적용 가능한 반려와 원인·담당 구성요소는 진단 기록에 남깁니다. 이 값은 평균 시간이나 실제 호출 수가 아닙니다.'),
  section('stack', '사용 기술', 'LangGraph는 실행 순서를, Pydantic은 계약 검증을, httpx는 OpenAI 호환 endpoint 통신을 맡습니다. LangChain·Chroma·OpenAI SDK의 설치와 현재 실행 사용을 구분합니다. 요청 중 웹 수집·벡터 검색 RAG는 현재 경로가 아닙니다.'),
], ['backend/app/agent/graph.py', 'backend/app/agent/runtime.py', 'backend/app/agent/llm.py', 'backend/app/agent/info_agent/agent.py']);

doc('agent/guardrails', '근거와 검수', '검수되지 않은 초안이 확정 상태로 저장되지 않게 합니다.', [
  section('evidence', '근거', '공식 자료는 출처·버전·검수·최신성·내용 hash를 확인합니다. 자료가 없으면 다른 자료로 채우지 않습니다. 사용자 입력에는 원문 근거를 연결하고 다른 Case 자료를 섞지 않습니다.'),
  section('proof', '검수 증명', 'ReviewProof는 같은 Case·snapshot·입력·초안을 묶습니다. 초안이나 선행 결과가 바뀌면 과거 PASS를 재사용할 수 없습니다. Agent는 변경 후보를 반환하며 저장은 BE가 맡습니다.'),
  section('store', 'DB와 이력', '현재 상태는 Case, 입력·판단 상태와 다음 행동은 CaseHistory에 둡니다. 공식 문서 본문은 문서·버전별 행을 공유하고 Case Evidence가 참조합니다. 충돌 해결과 상태 변경은 함께 저장합니다.', { note: note('재현 범위', '현재 전체 snapshot·절차 목록·모든 grounded_claims를 DB에 영구 보관하지는 않습니다. 완전한 사후 재현을 보장하지 않습니다.') }),
  section('trace', '검수 진단과 외부 추적', 'credential이 있을 때 Langfuse에 모델·토큰·지연·case_id·행동 코드와 검수 이슈의 코드·경로·심각도·담당 구성요소·재작업 대상을 보냅니다. 이슈는 앞 20개와 전체 개수를 기록하며, 입력 글·OCR·prompt·evidence·검수의 자유 이유 문장은 보내지 않습니다. 판단 기록은 실제 Langfuse trace ID와 연결합니다. 코드에서 고정한 blocker 목록 관련 제외와 다른 계약 반려는 구분해 남깁니다.'),
  section('privacy', '개인정보와 문서', 'BE가 자유글에서 식별번호·연락처·주소 등을 가리고, 이름임을 밝힌 표현의 일부를 규칙으로 가립니다. 모든 문장 속 이름을 탐지하는 것은 아닙니다. 결과 확인·충돌 확인 화면에도 [주소] 같은 가림 표시가 그대로 나오며 원래 글자로 되돌리지 않습니다. 입력 원문은 재시도와 충돌 확인을 위해 서버 DB에만 남습니다. 문서 모델용 가림과 제출용 주민번호 뒷자리 가림 정책은 서로 다릅니다. 원문과 OCR 텍스트를 추적 도구로 보내지 않습니다.'),
], ['backend/app/agent/guardrails.py', 'backend/app/agent/review_tool/tool.py', 'backend/app/be/services/decision_record.py', 'backend/app/be/models/evidence.py', 'backend/app/be/services/redaction.py', 'backend/app/agent/document_tool/documents.py']);

doc('operations/common', '실패와 복구', '접수·판단·저장 실패를 나누고 복구할 수 있는 경로를 안내합니다.', [
  section('async', '배경 판단과 폴링', 'Case와 PENDING 이력을 저장한 뒤 요청 커넥션을 반환합니다. 배경 작업은 입력을 읽을 때와 결과를 저장할 때만 세션을 열며 모델 대기 중에는 DB 커넥션을 점유하지 않습니다. FE는 3초 간격, 최대 10분까지 상태를 확인합니다.'),
  section('failure', '복구 종류', 'recovery_action_code와 retryable을 확인해 다시 판단하기·내용 보완·서비스 확인·복구 행동 없음으로 나눕니다. 서버가 NONE을 반환하면 [새 상황 알려주기]로 새 글을 입력할 수 있습니다. 다만 실패 당시 judged_version과 현재 APP_VERSION이 모두 알려져 있고 서로 다르며 허용된 입력 이력인 경우 서버가 RETRY로 안내를 바꿔 같은 저장 입력을 재판단하게 합니다. 버전 하나라도 모르면 바꾸지 않습니다. 실패 카드에는 저장된 마지막 할 일도 표시합니다. 이때 지난 질문과 선택형 답은 새 입력에 넘기지 않습니다. 같은 파일의 안전 검사 차단은 일반 업로드 재시도와 다릅니다.', { table: [['코드', '의미'], ['RETRY', '보관된 같은 입력으로 허용된 판단 재개'], ['RESUBMIT_INPUT', '요청한 내용을 보완해 다시 입력'], ['CONTACT_SUPPORT', '서비스 쪽 확인이 필요'], ['NONE', '같은 제출의 복구 행동 없음, 새 상황 글 입력 가능']] }),
  section('restart', '재시작과 경합', 'BackgroundTasks는 내구성 큐가 아닙니다. 재시작으로 남은 PENDING은 실패 상태로 풀고 복구 경로를 제공합니다. 같은 Case 접수를 잠그고 저장 직전에 최신 사실을 대조해 늦은 판단의 덮어쓰기를 막습니다.'),
  section('demo-reset', '시연 계정 초기화', '운영자용 backend/sql/reset_member_case.sql이 추가됐습니다. 선택한 회원의 Case와 종속 이력을 지우고 회원·공유 자료는 남겨 같은 카카오 계정으로 진단부터 다시 시작할 수 있게 합니다. PENDING 이력이 있거나 회원 번호가 없으면 지우지 않습니다. 끝에 member_id와 case_id를 표시하며 case_id가 null이면 삭제된 Case가 없습니다. DB 삭제는 한 트랜잭션이지만 document_data의 서류 파일은 지우지 않습니다. 실제 계정에 실행하기 전 대상과 처리 상태를 별도로 확인해야 합니다.'),
  section('deployment', '현재 배포 기준', '운영 BE 배포는 develop에서 수동 GitHub Actions 버튼으로 실행하며 정한 커밋을 빌드합니다. 배포 전 작업 디렉터리 수정·진행 중 배포를 확인하고 서버 잠금으로 중복 실행을 막습니다. Compose가 해석한 fastapi의 ENVIRONMENT가 prod인지 컨테이너 생성 없이 검사하고, 실행마다 별도 백업 폴더를 만듭니다. 이미지의 GIT_SHA가 APP_VERSION으로 전달돼 /health의 version과 대조하며 짧은 해시 글자 길이 대신 같은 커밋인지 확인합니다. FE·BE·Agent·E2E 검사는 배포와 구분하고, BE·Agent는 같은 FastAPI 컨테이너로 수동 배포하며 FE는 Vercel의 GitHub 연동을 사용합니다. 최신 절차와 DB 수동 migration·백업·복원 범위는 저장소 docs/deploy.md가 기준입니다. 이번 문서 갱신은 로컬 정적 페이지 배포이며 운영 서버 배포를 새로 실행한 기록이 아닙니다.'),
  section('health', '운영 상태와 데이터', '현재 /health는 별도 DB 연결로 SELECT 1을 확인하고, 성공 시 200 status: ok, DB 오류 시 503 status: unavailable을 반환하며, 둘 다 APP_VERSION의 version(미설정 시 unknown)을 포함합니다. 연결·읽기·쓰기 제한은 각각 2초이며 앱 커넥션 풀을 쓰지 않습니다. 운영 Compose는 MySQL·FastAPI와 DB·문서 볼륨을 구성합니다. 설정이 있다는 사실과 현재 배포가 성공했다는 증거는 구분합니다.'),
], ['backend/app/be/services/judgment.py', 'backend/app/be/db.py', 'backend/app/main.py', 'frontend/src/hooks/useCase.ts', 'docker-compose.prod.yml', 'backend/sql/reset_member_case.sql'], { family: 'operations' });

doc('reference/errors', '에러 코드', 'HTTP 요청 실패와 AI 업무 결과를 구분합니다.', [
  section('http', 'HTTP 상태', '성공한 HTTP 응답도 업무 결과가 FAILED일 수 있습니다. 반대로 409는 모델 판단 실패가 아니라 현재 요청을 접수할 수 없는 상태일 수 있습니다.', { table: [['HTTP', '대표 상황', '화면 처리'], ['400', '카카오 인가 코드 등 로그인 요청 거절', '새 로그인으로 인가 코드 재발급'], ['401', '토큰 누락·만료·잘못된 유형', '재발급 또는 로그인'], ['404', 'Case·이력·문서가 없음', '현재 Case와 번호 재확인'], ['409', '오래된 판단·진행 중 제출·미해결 충돌·완료 Case', '최신 상태 조회, 허용된 흐름으로 이동'], ['422', '형식·현재 조건·파일·점검 상태 불일치', '내용과 조건 확인'], ['502', '카카오 설정·연결 오류 또는 문서 모델·OCR 실패', '로그인 오류와 서류 읽기 실패를 구분해 안내']] }),
  section('safety', '서류 안전 검사 코드', '422의 detail이 객체일 수 있습니다. FE ApiError는 detail.code를 읽어 안내를 나눕니다.', { table: [['detail.code', '처리'], ['AGENT_SAFETY_REFUSE', '같은 파일 재시도를 권하지 않고 다른 파일·내용 확인'], ['AGENT_SAFETY_CRISIS_SUPPORT', '진행 상태를 보존하고 상담 창구 안내']] }),
  section('business', '업무 결과', '결과 조회의 result 7종과 Case 조회의 judgment_status는 서로 다른 계약입니다.', { table: [['result', '의미'], ['PENDING', '판단 처리 중'], ['UPDATED', '상태 변경 반영'], ['NO_CHANGE', '이번 입력으로 바뀐 값 없음'], ['NEEDS_MORE_INFO', '추가 확인 질문'], ['CONFLICT', '기존 사실과 다른 후보, 사용자 선택 필요'], ['FAILED', '실패 및 복구 정보 확인'], ['PROCEDURES_COMPLETED', '등록 절차 안내 종료, 홈으로 이동']] }),
], ['frontend/src/lib/api.ts', 'backend/app/be/services/case.py', 'backend/app/be/services/document.py', 'backend/app/be/schemas/case.py']);

doc('reference/tests', '테스트 케이스', '정상 흐름과 경계·예외·동시성·복구를 함께 점검합니다.', [
  section('principle', '무엇을 검증하는가', '자동 테스트는 모델 응답을 대체해 계약·저장·보호 동작을 확인합니다. 격리 MySQL 테스트도 포함됩니다. 테스트 통과가 실제 LLM 정확도나 실제 사장님의 사용성을 보장하지 않습니다.'),
  section('commands', '실행 방법', '프로젝트 테스트는 실제 모델을 호출하지 않습니다. 실제 LLM 평가 스크립트는 호출 수와 비용을 확인하는 별도 규칙을 따릅니다.', { code: { language: 'Shell', text: '# Frontend\ncd frontend\nnpm test\nnpm run lint\nnpm run build\n\n# 실제 FE·BE·MySQL 브라우저 검사(Playwright, Docker 필요)\nnpm run test:e2e\n\n# Backend: Python 3.12, 테스트 의존성과 Docker 필요\ncd ../backend\npython -m pytest tests -q\n\n# 문서 소스와 계약·링크 확인\ncd ../frontend\nnpm run docs:check' } }),
  section('scenarios', '대표 시나리오', '', { tests: tests(['최초 진단', '임차·보험·이력 조합에 맞는 첫 행동'], ['선택형 일부 복구', '없는 세부 범위 되묻기'], ['기존값과 충돌', '선택 전 미변경·선택 뒤 검수'], ['동시 제출', 'Case당 한 건만 접수'], ['서류 누락·변조', '구체 문제 안내·ZIP 제한'], ['안전 검사', '코드별 화면, 원문·식별번호 추적 누출 방지'], ['서버 재시작', 'PENDING 해제와 재시도'], ['UI 접근성', '새로고침·키보드·동작 줄이기·느린 연결']) }),
  section('evidence', '검증 기록', '실행 시점과 소스 버전을 함께 남깁니다. 이전 최종 설명서의 658개 FE·1,098개 BE 통과는 4e64e0e 시점의 기록이며 현재 코드의 새 측정으로 재사용하지 않습니다. PERF 전용 테스트는 기본 실행에서 건너뜁니다.', { validation: true }),
], ['frontend/package.json', 'backend/tests/test_double_submit.py', 'backend/tests/test_document_api.py', 'backend/tests/test_llm_limits.py', 'backend/tests/test_pool_capacity.py']);

doc('reference/glossary', '용어집', '서비스와 코드에서 사용하는 주요 용어를 설명합니다.', [
  section('words', '기본 용어', '', { table: [['용어', '뜻'], ['Case', '한 회원의 가게 상황과 폐업 진행을 모은 상태'], ['CaseHistory', '입력과 그 판단·실패·다음 행동의 이력'], ['Blocker', '현재 진행을 막는 확인 필요 조건'], ['Next Action', '지금 안내할 행동 하나'], ['Snapshot', '한 번 판단할 때 읽은 Case 상태'], ['Candidate / Overlay', '저장 전의 변경 후보·판단에 덧씌운 확인값'], ['Evidence', '입력·공식 자료·검수 등 판단의 근거'], ['ReviewProof', '특정 snapshot과 초안이 검수를 통과했다는 연결 정보'], ['Digest', '문서·입력·검수 대상이 달라졌는지 대조할 내용 요약값'], ['1차 적격심사', '사용자가 기관에서 확인해 기록한 결과, 최종 지급 아님'], ['UNKNOWN / null', '모름·미확인을 뜻할 수 있으며 false와 구분']] }),
], ['backend/app/agent/schemas.py', 'backend/app/be/models/case.py']);

doc('reference/changes', '변경 이력', '문서에 반영한 서비스 변경과 확인한 코드 버전을 기록합니다.', [
  section('latest', '최신 반영', '2026년 11월 10일 develop 6cb5284를 기존 문서 작업본에 병합해 대조했습니다. 충돌 선택의 RESUBMIT_INPUT·NONE 실패 뒤 새 상황 입력과 배포 잠금·실효 환경값·백업·커밋 대조 보완을 추가 반영했습니다. Discord 오류 알림 #331은 확인 시점 미머지로 현재 동작에 포함하지 않았습니다. 준비·완료·진행 상태 버튼, 준비와 작업 완료의 분리, 등록 절차 안내 종료, 충돌 선택 실패 보존, 내 정보와 로그아웃, DB 서류함과 동시 변경 보존, 로그인 400·502 구분, 서버 버전 기반 복구와 health version을 반영했습니다. 테크스펙과 이용자 안내를 같은 구현 근거로 연결했습니다. 과거 캡처·PDF·테스트 수를 이번 실측으로 바꾸지 않습니다.'),
  section('history', '기록', '', { table: [['기준', '반영 내용'], ['2026-11-10 / 6cb5284', '충돌 실패 RESUBMIT_INPUT·NONE의 새 상황 입력 복구(#335·#338·#339), 배포 스크립트 보호(#337)'], ['2026-11-09 / 52807ae', '버튼 답변·절차 안내 종료·충돌 실패 복구·내 정보·DB 서류함·버전 기반 재판단·테크스펙 갱신'], ['2026-11-07 / c471dca', '철거 준비 반복 방지·진행 반영 표시·실패 뒤 새 글 입력(#290), 첫 로그인 경합(#287), 상담 안내 문구와 운영 복원 확인 도구 반영'], ['2026-11-07 / 대상·문제정의', '40~50대 개인 카페 사장님 중심의 문제정의, UI/UX 구현 근거와 사용자 확인 과제 정리 · 기능 변경 없음'], ['2026-11-07 / 279dad5', '가게 이름 입력·저장(#251), 서류 표시 이름·종류 목록(#260), 시작 시 공식 자료 적재(#263), 화면 원문 복원 제거(#274), 철거 작업 이름(#248) 반영'], ['2026-11-07 / b0fa738', 'DB 점검 health 200·503, Case 회전 집계 도구와 E2E 테스트 추가 반영'], ['2026-11-07 / 366617a 작업본', '리본 운영철학·안심 이용 7개 화면과 확인·정정·서류 보호 안내 추가'], ['2026-11-07 / 366617a', '시연 계정 초기화 SQL과 실행 중 제외·대상 결과 표시 반영'], ['2026-11-07 / 764f3c2', '서류 안전 차단·위기 지원 분기와 설명을 최신화'], ['2026-11-07 / 4e64e0e', '카카오 문서 방식의 대표 4개 시안 작성'], ['2026-11-07 / 4e64e0e', '59쪽 화면 설명서와 92개 테스트 점검표 작성']] }),
  section('scope', '갱신 기준', '원격 develop의 최신 코드를 먼저 확인하고 화면·라우터·스키마·서비스·테스트를 대조합니다. 사람의 설명과 자동 생성 계약을 함께 갱신하며 확인한 날짜와 소스 해시를 보관합니다.', { links: [['문서 갱신 절차', '/developers/ko/reference/maintenance/']] }),
], ['backend/app/be/services/document.py', 'frontend/src/hooks/useDocuments.ts', 'backend/app/be/services/redaction.py']);

doc('reference/maintenance', '문서 갱신', '2026년 11월 11일까지 이어지는 서비스 변경을 문서에도 반영합니다.', [
  section('commitment', '갱신 원칙', '서비스 변경 시 이 개발 문서도 함께 확인합니다. 코드 계약은 FastAPI OpenAPI에서 내보내고, 화면·기능·UX·검수 설명은 구현을 읽고 수정합니다. API 필드가 바뀌면 표를 손으로 덮어쓰기보다 생성 계약을 갱신합니다.'),
  section('steps', '갱신 순서', '', { steps: ['git fetch 후 최신 develop과 로컬 작업을 보존해 반영합니다.', '변경된 화면·API·상태·에러·모델 경로와 관련 테스트를 확인합니다.', 'content.mjs의 해당 기능 설명과 캡처 기준을 수정합니다.', 'Backend 환경에서 계약·작업 목록·소스 해시를 내보냅니다.', 'docs:check와 docs:build, 관련 테스트·브라우저 검증을 수행합니다.', '확인한 버전과 변경 이력을 기록합니다.'] }),
  section('commands', '동기화 명령', '', { code: { language: 'Shell', text: '# Backend 의존성이 설치된 Python 3.12 환경\ncd backend\npython scripts/export_documentation.py\npython scripts/export_documentation.py --check\n\ncd ../frontend\nnpm run docs:check\nnpm run docs:build' } }),
  section('boundary', '자동 생성과 사람이 확인할 것', '명세·작업 목록·소스 불일치·내부 링크는 도구로 확인합니다. 기능이 왜 필요한지, 화면이 달라진 의도, 실제 LLM 성능과 최신 정책 적합성은 별도로 검토합니다. 이 기준을 기록한 것이며 예약된 주기 작업을 실행하는 것은 아닙니다.'),
], ['AGENTS.md', 'backend/scripts/export_documentation.py', 'docs/developers/content.mjs']);

export const apiGroups = [
  { family: 'auth', title: '카카오 로그인 REST API', description: '카카오 인증 결과를 리본 회원 세션으로 연결합니다.', operations: ['GET /login/form', 'POST /login', 'POST /logout', 'POST /reissue'] },
  { family: 'case', title: 'Case REST API', description: '가게를 생성하고 현재 상태·판단을 조회합니다.', operations: ['POST /cases', 'GET /cases'] },
  { family: 'results', title: '결과 알려주기 REST API', description: '입력 가능한 결과를 확인하고 실행 결과를 접수·조회합니다.', operations: ['GET /cases/results', 'POST /cases/results', 'GET /cases/results/status'] },
  { family: 'conflicts', title: '충돌 확인 REST API', description: '확정된 사실과 다른 후보 중 사용할 값을 선택합니다.', operations: ['POST /cases/results/decision'] },
  { family: 'roadmap', title: '로드맵 REST API', description: '전체 순서와 체크·기관 결과·신고 정보·보증금 기록을 관리합니다.', operations: ['GET /cases/roadmap', 'PUT /cases/checklists/{task_id}', 'PUT /cases/support-approval', 'PUT /cases/closure-report', 'PUT /cases/deposit-return'] },
  { family: 'documents', title: '서류 REST API', description: '서류 업로드·확인·삭제·점검·제출 파일을 연결합니다.', operations: ['GET /cases/documents', 'POST /cases/documents', 'POST /cases/documents/{document_id}/confirm', 'DELETE /cases/documents/{document_id}', 'POST /cases/documents/check', 'GET /cases/documents/settlement.zip'] },
  { family: 'logs', title: '기록 REST API', description: '사용자와 리본의 작업 이력을 조회합니다.', operations: ['GET /cases/logs'] },
  { family: 'operations', title: '복구와 운영 REST API', description: '허용된 실패 판단을 재개하고 서버와 DB 연결 상태를 확인합니다.', operations: ['POST /cases/retry', 'GET /health'] },
];

export const operationNotes = {
  'GET /login/form': { title: '카카오 로그인 시작', description: '카카오 인가 화면으로 303 redirect합니다. OpenAPI의 기본 200 표기와 실제 RedirectResponse의 303을 구분합니다.', status: '303', responseExample: null },
  'POST /login': { title: '인가 코드로 로그인', description: 'code를 카카오 토큰으로 교환하고 리본 회원을 확인합니다. Access-Token·Refresh-Token은 응답 헤더로 제공합니다.', responseExample: { nickname: '예시 사용자' } },
  'POST /logout': { title: '리본 로그아웃', description: '서버의 Refresh 토큰을 지웁니다. 카카오계정과 함께 로그아웃하는 API는 아닙니다.', responseExample: { message: 'ok' } },
  'POST /reissue': { title: '리본 토큰 재발급', description: 'Refresh-Token 헤더로 인증하고 새 토큰 두 개를 응답 헤더로 발급합니다.', responseExample: { message: 'ok' } },
  'POST /cases': { title: 'Case 생성', description: 'Case와 첫 PENDING 이력을 저장하고 배경 판단을 시작합니다. 회원당 Case는 하나입니다.' },
  'GET /cases': { title: '현재 Case 조회', description: '현재 확정 상태와 최신 판단을 조회합니다. Case가 없을 때의 case:null을 오류와 구분합니다.' },
  'GET /cases/results': { title: '결과 입력 진입 상태', description: '입력 종류·최신 판단 번호·추가 질문·충돌을 확인합니다. 이전 화면의 오래된 값을 재사용하지 않습니다.' },
  'POST /cases/results': { title: '실행 결과 접수', description: 'raw_input·restoration_answer·action_done·restoration_status 중 정확히 하나만 전달합니다. 선택형은 현재 행동과 허용된 같은 답 재시도 조건을 만족해야 합니다. HTTP 200은 접수이며 반영 완료가 아닙니다.' },
  'GET /cases/results/status': { title: '접수한 판단 결과 조회', description: '접수한 case_history_id로 조회합니다. 더 최신 판단이 생기면 409를 반환할 수 있습니다. PROCEDURES_COMPLETED를 포함한 result 7종을 모두 처리합니다.' },
  'POST /cases/results/decision': { title: '충돌 선택 접수', description: '각 conflict_reference_id에 STORED 또는 PROPOSED를 선택합니다. 모든 유효한 항목을 선택한 뒤 재판단하며 성공 전 Case를 바꾸지 않습니다.' },
  'POST /cases/retry': { title: '실패 판단 재개', description: '허용된 CASE_CREATED·USER_INPUT·DOCUMENT_SUBMITTED 실패 이력을 같은 입력으로 PENDING으로 되돌립니다. 완료 Case나 허용하지 않은 상태는 409입니다.' },
  'GET /cases/roadmap': { title: '폐업 로드맵 조회', description: '현재 상태를 5단계로 투영합니다. 조회 자체는 모델을 부르거나 상태를 저장하지 않습니다.' },
  'PUT /cases/checklists/{task_id}': { title: '체크 완료와 취소', description: '사용자 체크만 받으며 해당 없음·확인 필요 작업의 완료는 422로 거부합니다. vat_submission 체크는 서비스 완료와 연결됩니다.' },
  'PUT /cases/support-approval': { title: '1차 심사 결과 기록', description: 'approved는 필수 키이며 true·false·null을 받습니다. 기관의 1차 결과 기록이고 AI 자격 판정·지급 완료가 아닙니다.' },
  'PUT /cases/closure-report': { title: '폐업 정보 기록', description: '실제 폐업일·사유·주소를 저장합니다. 계획 날짜와 별개이며 기관 신고 접수 API가 아닙니다.' },
  'PUT /cases/deposit-return': { title: '보증금 반환 기록', description: 'FULL·PARTIAL·NONE을 기록합니다. 금액·분쟁 판단을 자동 수행하지 않습니다.' },
  'GET /cases/logs': { title: '작업 기록 조회', description: '사장님과 리본의 기록을 최신 순서로 보여줍니다. 원문을 불필요하게 반복 노출하지 않습니다.' },
  'GET /cases/documents': { title: '서류와 점검 상태 조회', description: '현재 회원의 Case 문서와 현재 점검을 조회합니다.' },
  'POST /cases/documents': { title: '서류 올리기', description: 'multipart/form-data의 file과 선택적 kind를 받습니다. 20,000,000바이트 이하 PDF·PNG·JPG/JPEG, 암호 없는 30쪽 이하 문서를 처리합니다. 안전 검사 422는 detail.code로 구분합니다.' },
  'POST /cases/documents/{document_id}/confirm': { title: '서류 종류와 값 확인', description: '종류와 확인값을 저장하고 지난 점검을 무효화합니다. 확인된 원상복구 조항이 바뀌면 별도 판단을 예약할 수 있습니다.' },
  'DELETE /cases/documents/{document_id}': { title: '서류 빼기', description: '소유 Case의 DB 서류 목록에서 제외하고 이전 점검을 무효화합니다. 저장 파일의 전체 영구 삭제는 아니며 다시 점검해야 합니다.' },
  'POST /cases/documents/check': { title: '정산 서류 점검', description: '가게 이름·신청인 이름과 확인한 실제 폐업일로 코드 규칙을 실행합니다. 가게 이름을 보내면 Case에 저장하고, 생략하면 저장된 이름을 씁니다. 예상 폐업일로 대신하지 않습니다. 모델을 새로 부르는 점검은 아닙니다.' },
  'GET /cases/documents/settlement.zip': { title: '정산 제출 ZIP 받기', description: 'COMPLETE, 현재 문서 digest·가림 정책·산출물 무결성을 확인한 뒤 ZIP을 반환합니다. 다운로드는 기관 제출과 별개입니다.', binary: true },
  'GET /health': { title: '서버·DB 상태 확인', description: '별도 DB 연결로 SELECT 1을 확인합니다. 성공하면 200 status: ok, DB 오류면 503 status: unavailable입니다. 양쪽 응답 모두 빌드 커밋 version을 포함하며 미설정 시 unknown입니다. 모델 연결까지 확인하지는 않습니다.', responseExample: { status: 'ok', version: 'unknown' } },
};


doc('account/common', '내 정보와 로그아웃', '현재 저장된 가게 정보와 세션 종료 방법을 확인합니다.', [
  section('entry', '머리말에서 내 정보 열기', '홈·서류함·기록 머리말의 사람 버튼으로 /mypage에 들어갑니다. 가게 요약 카드와 저장된 업종·임차·직원·대출·계약·폐업 시기를 읽습니다. 아직 정하지 않은 폐업 시기는 그대로 표시하며, 진단 뒤 정해지는 원상복구 범위·철거 여부는 이 목록에 섞지 않습니다.', { images: ['2026-11-09-my-info'] }),
  section('facts', '조회와 정정 경로', '내 정보는 조회 화면입니다. 여기서 가게 정보를 직접 고치지 않고 바뀐 사실은 할 일 결과 입력으로 전달합니다. 기존값과 비교·검수·필요한 충돌 확인을 거쳐 반영합니다. Case 없음과 조회 실패를 나눠 보여주며 양쪽에서도 로그아웃할 수 있습니다.'),
  section('logout', '로그아웃과 기기 정리', '실제 세션은 제한 시간 안에서 POST /logout을 시도한 뒤 브라우저 토큰과 진단 답을 지우고 /login으로 이동합니다. 서버 요청 실패 때도 기기에서는 로그아웃하며 가짜 세션은 서버 요청을 생략합니다. 리본 로그아웃은 카카오계정 로그아웃이나 회원 탈퇴·가게 자료 삭제가 아닙니다.'),
], ['frontend/src/pages/MyInfoPage.tsx', 'frontend/src/components/ui/TabLayout.tsx', 'frontend/src/adapters/case.ts', 'frontend/src/lib/api.ts', 'frontend/src/lib/auth.ts']);

doc('guide/tech-spec', '테크스펙', '화면·API·AI·저장·운영의 현재 구성을 한곳에서 읽습니다.', [
  section('stack', '현재 기술 구성', '패키지 선언과 실제 실행 경로를 나눠 설명합니다. 정확한 설치 버전은 lockfile과 requirements가 기준입니다.', { table: [['영역', '현재 구성', '역할'], ['화면', 'React 19 · TypeScript 6 · Vite 8 · React Router 7', '모바일 화면·라우팅·빌드'], ['UI와 입력', 'Tailwind CSS 4 · Pretendard · Motion · Zustand 5', '일관된 글자·상태·진단 답 보관'], ['API', 'Python 3.12 · FastAPI · SQLModel · PyMySQL', '인증·계약 검증·트랜잭션'], ['저장', 'MySQL 8.0.46 + 서버 파일 저장소', '가게·이력·서류 context와 파일 분리'], ['판단', 'LangGraph · Pydantic · httpx', '정해진 실행 흐름·검수·모델 통신'], ['문서 판독', 'PyMuPDF · 로컬 한/영 OCR · 가린 자료의 모델 판독', '종류·값 추출 후 코드 규칙 점검'], ['추적', 'Langfuse (credential 설정 시)', '모델·지연·토큰·검수 이슈 metadata']] }),
  section('flow', '요청에서 반영까지', 'FE는 Backend 계약을 화면용 값으로 변환하며 절차 순서를 스스로 결정하지 않습니다. API는 Case와 PENDING을 저장해 접수 번호를 반환하고, 배경 판단 뒤 화면이 상태를 조회합니다.', { steps: ['FE: 현재 입력 종류와 case_history_id 조회', 'BE: 소유권·최신 이력·동시 제출 검증 후 접수', 'Agent: Procedure → Info → Supervisor → Review', 'BE: 검수 대상과 최신 상태 대조, 변경·이력 저장', 'FE: 7종 result에 맞는 반영·질문·충돌·실패·종료 화면 표시'] }),
  section('data', '데이터를 두는 위치', '모델 대기 중에는 DB 커넥션을 점유하지 않습니다. 서류 분석도 최신 상태를 다시 읽고 변경분만 병합합니다.', { table: [['위치', '저장 내용'], ['MySQL', '회원·Case·CaseHistory·공식 자료·Evidence·충돌·검수·절차 상태'], ['case_document_context', '서류 목록·추출값·점검 결과·판단에 사용한 context'], ['서버 파일 저장소', '처리한 PDF·분석 캐시 등 산출물'], ['브라우저 sessionStorage', '리본 Access/Refresh 토큰·진단 중 답'], ['공개 문서 localStorage', '최근 읽은 문서 제목·주소 최대 5개']] }),
  section('contracts', 'API와 상태의 기준', 'API 표·타입·요청 예제는 FastAPI OpenAPI에서 생성합니다. 이번 계약은 24개 API와 로드맵 작업 26개이며, result의 PROCEDURES_COMPLETED와 Case 완료는 구분합니다.', { links: [['API 타입과 필드', '/developers/ko/reference/schemas/'], ['결과 입력 4종', '/developers/ko/results/common/#buttons'], ['절차 안내 종료', '/developers/ko/roadmap/common/#completion'], ['오류와 복구 코드', '/developers/ko/reference/errors/']] }),
  section('operations', '실행 한도와 배포', '한 판단의 기본 한도는 모델 호출 40회·420초·Review 재작업 2회입니다. 평균 속도나 요금 보장값이 아닙니다. BackgroundTasks는 영구 큐가 아니며 재시작 잔여 PENDING은 실패와 복구로 연결합니다. /health는 별도 DB 연결 상태와 빌드 version을 반환합니다. 운영 BE는 수동 Actions 배포와 커밋 대조를 사용합니다.', { links: [['실패·재시작·배포 설명', '/developers/ko/operations/common/'], ['검수와 추적 범위', '/developers/ko/agent/guardrails/']] }),
  section('boundaries', '현재 구현과 검증의 범위', 'Support Agent는 현재 Graph에서 호출하지 않고, 요청 중 웹 수집·벡터 검색 RAG·기관 자동 신청은 제공하지 않습니다. 모든 정상 결과는 Review 경계를 거치지만 모든 경로가 별도 검수 LLM을 호출하지는 않습니다. 실제 운영 1건 검증과 과거 평가는 저장소의 기록이며 이번 문서 검증 결과와 합산하지 않습니다.', { links: [['이번 문서 검증과 과거 기록', '/developers/ko/reference/tests/'], ['이용자에게 설명하는 범위', '/safety/standards/']] }),
], ['frontend/package.json', 'backend/requirements.txt', 'backend/app/main.py', 'backend/app/agent/graph.py', 'backend/app/be/schemas/case.py', 'backend/app/be/models/case_document_context.py', 'backend/app/be/services/document.py', 'docs/deploy.md']);
