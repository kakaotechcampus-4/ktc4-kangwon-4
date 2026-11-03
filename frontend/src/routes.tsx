import { createBrowserRouter, Navigate } from 'react-router'

import { RequireAuth } from './components/RequireAuth'
import { TabLayout } from './components/ui/TabLayout'
import { CaseCreatePage } from './pages/CaseCreatePage'
import { ConfirmChangePage } from './pages/ConfirmChangePage'
import { LoginCallbackPage } from './pages/LoginCallbackPage'
import { CurrentCasePage } from './pages/CurrentCasePage'
import { DocsCheckPage } from './pages/DocsCheckPage'
import { DocsDonePage } from './pages/DocsDonePage'
import { DocsPage } from './pages/DocsPage'
import { EntryPage } from './pages/EntryPage'
import { LogPage } from './pages/LogPage'
import { LoginPage } from './pages/LoginPage'
import { NotificationsPage } from './pages/NotificationsPage'
import { ReplanPage } from './pages/ReplanPage'
import { RoadmapPage } from './pages/RoadmapPage'
import { TaskFlowPage } from './pages/TaskFlowPage'
import { ResultInputPage } from './pages/ResultInputPage'
import { TaskPage } from './pages/TaskPage'

/**
 * Hero Loop의 화면 순서가 그대로 경로가 된다.
 *
 *   /login          로그인      소개 4장 + 카카오. 인증 가드 밖에 있다
 *   /login/callback 로그인 처리  카카오가 돌려보내는 자리. 역시 가드 밖이다
 *   /          진입 분기      보낼 곳만 정하고 화면은 없다
 *   /cases/new 상황 진단      Case가 없는 사용자만 본다. 질문 한 장씩(?step=), 마지막에 Case를 만든다
 *   /case      현재 Case(홈)  지금 무엇이 막혀 있고 무엇을 할 차례인가
 *   /task      할 일 상세     무엇을 어떻게 물어보면 되는가
 *   /results   결과 입력      실행한 결과를 한 줄로 말한다
 *   /confirm   충돌 확인      기존 기록과 어긋날 때만 들른다 (CONFLICT)
 *   /replan    반영 결과      무엇이 바뀌었고 다음은 무엇인가 (?history= 판단 번호로 다시 묻는다)
 *
 * 하단 탭이 있는 화면은 `TabLayout` 아래에 둔다. 홈 탭은 `/case`로 간다.
 * `/`는 로그인 뒤 보낼 곳만 정하고, 탭에서는 가리키지 않는다.
 *
 *   /docs          서류함      올린 서류 · 올리기 시트 · 확인 · 빼기 (서류 API #159)
 *   /log           작업 기록   사장님·리본이 한 일 (GET /cases/logs)
 *   /notifications 알림        탭 화면의 종 버튼으로 들어온다. 아직 빈 상태
 *
 * 탭 밖에서 밀려 들어오는 화면이다. 뒤로 버튼으로 돌아간다.
 *
 *   /roadmap          폐업 전체 순서  홈 단계 카드로 들어온다. 로드맵 조회 API 전이라 실서버에서는 준비 중
 *   /roadmap/:taskId  할 일          할 일마다 체크·첨부·고르기 등을 연다 (lib/taskFlows.ts)
 *   /docs/check       서류 점검      정산 서류를 점검한다
 *   /docs/done        정산 제출 파일  점검을 통과했을 때만
 *
 * `/confirm`은 `/results`와 `/replan` 사이의 단계가 아니라 예외 분기다.
 * 정상 경로는 `/results`에서 `/replan`으로 바로 간다.
 *
 * 로그인 화면 둘을 뺀 전부가 `RequireAuth` 아래에 있다. 화면마다 로그인을 검사하지 않고
 * 구조에 한 번 끼워 두면, 새 화면을 추가할 때 보호를 빠뜨릴 수 없다.
 *
 * 모르는 경로는 `/`로 보낸다. 거기서 지금 상태에 맞는 화면을 다시 고른다 —
 * `/case`로 바로 보내면 Case가 없는 사용자가 빈 화면을 본다.
 */
export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/login/callback', element: <LoginCallbackPage /> },
  {
    element: <RequireAuth />,
    children: [
      { path: '/', element: <EntryPage /> },
      { path: '/cases/new', element: <CaseCreatePage /> },
      { path: '/task', element: <TaskPage /> },
      { path: '/results', element: <ResultInputPage /> },
      { path: '/confirm', element: <ConfirmChangePage /> },
      { path: '/replan', element: <ReplanPage /> },
      { path: '/roadmap', element: <RoadmapPage /> },
      { path: '/roadmap/:taskId', element: <TaskFlowPage /> },
      { path: '/docs/check', element: <DocsCheckPage /> },
      { path: '/docs/done', element: <DocsDonePage /> },
      {
        element: <TabLayout />,
        children: [
          { path: '/case', element: <CurrentCasePage /> },
          { path: '/docs', element: <DocsPage /> },
          { path: '/log', element: <LogPage /> },
        ],
      },
      { path: '/notifications', element: <NotificationsPage /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
