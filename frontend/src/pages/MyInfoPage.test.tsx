import { act, fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { getAccessToken, getRefreshToken, logInWithMock, saveTokens } from '../lib/auth'
import { EMPTY_DIAGNOSIS, useDiagnosisStore } from '../stores/useDiagnosisStore'
import type { CaseResponse } from '../types/api'
import { MyInfoPage } from './MyInfoPage'

const SERVER_CASE: Partial<CaseResponse> = {
  id: 1,
  business_type: 'CAFE',
  franchise_status: false,
  employee_count: 3,
  lease_status: 'LEASED_PAID',
  planned_closure_date: null,
  planned_closure_month: null,
  restoration_scope: 'UNKNOWN',
  demolition_required: 'REQUIRED',
}

function envelope(serverCase: Partial<CaseResponse> | null) {
  return {
    case: serverCase,
    blocker: null,
    next_action: null,
    judgment_status: null,
    questions_for_user: null,
    recovery_action_code: null,
    requested_field_paths: null,
  }
}

const ok = (body: unknown) => () => new Response(JSON.stringify(body))
const failing = () => new Response(null, { status: 500 })

/** `GET /cases` 에 순서대로 답한다. 목록이 끝나면 마지막 답을 계속 준다 */
function serve(answers: Array<() => Response>) {
  let calls = 0
  const fetchMock = vi.fn(async () => answers[Math.min(calls++, answers.length - 1)]())
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderAt(path: string, before: string[] = []) {
  const router = createMemoryRouter(
    [
      { path: '/mypage', element: <MyInfoPage /> },
      { path: '/cases/new', element: <p>상황 진단 화면</p> },
      { path: '/case', element: <p>홈 화면</p> },
      { path: '/login', element: <p>로그인 화면</p> },
    ],
    { initialEntries: [...before, path], initialIndex: before.length },
  )

  render(<RouterProvider router={router} />)
  return router
}

/** 항목 이름으로 그 줄의 값을 찾는다 */
function valueOf(label: string) {
  const term = screen.getAllByRole('term').find((element) => element.textContent === label)
  if (term === undefined) throw new Error(`${label} 항목이 없습니다`)
  return term.nextElementSibling
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('MyInfoPage', () => {
  it('저장된 가게 정보를 항목마다 보여준다', async () => {
    saveTokens('access-1', 'refresh-1')
    serve([ok(envelope(SERVER_CASE))])
    renderAt('/mypage')

    expect(await screen.findByRole('heading', { level: 2, name: '내 가게' })).toBeInTheDocument()
    expect(screen.getAllByRole('term')).toHaveLength(5)
    expect(valueOf('업종')).toHaveTextContent('카페')
    expect(valueOf('직원 수')).toHaveTextContent('3명')
    expect(valueOf('점포 형태')).toHaveTextContent('임차 (월세)')
  })

  /** 빈칸으로 숨기면 사장님은 답한 것이 사라진 줄 안다(FE 규칙 6) */
  it('서버가 확정하지 않은 값은 빈칸이 아니라 확인 필요로 남긴다', async () => {
    saveTokens('access-1', 'refresh-1')
    serve([ok(envelope(SERVER_CASE))])
    renderAt('/mypage')

    await screen.findByRole('heading', { level: 2, name: '내 가게' })
    expect(valueOf('폐업 예정일')).toHaveTextContent('확인 필요')
  })

  /** 로그아웃은 Case가 없어도 할 수 있어야 해서 진단으로 바로 보내지 않는다 */
  it('가게가 없으면 이 화면에서 알리고 상황 진단으로 가는 길을 둔다', async () => {
    saveTokens('access-1', 'refresh-1')
    serve([ok(envelope(null))])
    const router = renderAt('/mypage')

    fireEvent.click(await screen.findByRole('button', { name: '상황 진단하기' }))

    expect(router.state.location.pathname).toBe('/cases/new')
  })

  it('불러오지 못하면 다시 불러올 수 있다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = serve([failing, ok(envelope(SERVER_CASE))])
    renderAt('/mypage')

    fireEvent.click(await screen.findByRole('button', { name: '다시 불러오기' }))

    expect(await screen.findByRole('heading', { level: 2, name: '내 가게' })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('Mock 으로 열면 서버를 부르지 않고 Mock 가게 정보를 그린다', async () => {
    const fetchMock = serve([failing])
    renderAt('/mypage?mock=done')

    expect(await screen.findByRole('heading', { level: 2, name: '내 가게' })).toBeInTheDocument()
    expect(screen.getAllByRole('term')).toHaveLength(5)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

/** `GET /cases` 와 `POST /logout` 을 주소로 나눠 답한다 */
function serveWithLogout(logout: () => Response | Promise<Response>, cases: unknown = envelope(SERVER_CASE)) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    void init
    return url.endsWith('/logout') ? logout() : new Response(JSON.stringify(cases))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const logoutCalls = (fetchMock: ReturnType<typeof serveWithLogout>) =>
  fetchMock.mock.calls.filter(([url]) => url.endsWith('/logout'))

const offline = () => {
  throw new TypeError('Failed to fetch')
}

describe('MyInfoPage — 로그아웃', () => {
  it('서버에 알리고 브라우저 토큰을 지운 뒤 로그인으로 간다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = serveWithLogout(() => new Response(JSON.stringify({ message: 'ok' })))
    const router = renderAt('/mypage')

    fireEvent.click(await screen.findByRole('button', { name: '로그아웃' }))

    expect(await screen.findByText('로그인 화면')).toBeInTheDocument()
    expect(logoutCalls(fetchMock)).toHaveLength(1)
    expect(logoutCalls(fetchMock)[0][1]).toMatchObject({ method: 'POST' })
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
    expect(router.state.location.pathname).toBe('/login')
  })

  /** 누른 사장님이 그대로 남아 있으면 안 된다. 서버가 못 받아도 화면에서는 로그아웃시킨다 */
  it.each([
    ['서버 오류', () => new Response(null, { status: 500 })],
    ['연결 끊김', offline],
  ])('%s 여도 브라우저 토큰을 지우고 로그인으로 간다', async (_, logout) => {
    saveTokens('access-1', 'refresh-1')
    serveWithLogout(logout)
    renderAt('/mypage')

    fireEvent.click(await screen.findByRole('button', { name: '로그아웃' }))

    expect(await screen.findByText('로그인 화면')).toBeInTheDocument()
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
  })

  /** 가짜 세션의 토큰은 서버가 모른다 */
  it('가짜 세션이면 서버를 부르지 않고 로그아웃한다', async () => {
    logInWithMock()
    const fetchMock = serveWithLogout(() => new Response(null))
    renderAt('/mypage')

    fireEvent.click(await screen.findByRole('button', { name: '로그아웃' }))

    expect(await screen.findByText('로그인 화면')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(getAccessToken()).toBeNull()
  })

  /** 화면만 Mock 을 보고 있어도 로그인은 진짜다. 서버의 Refresh 토큰도 지워야 한다 */
  it('진짜 로그인으로 Mock 화면을 보고 있으면 서버에도 알린다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = serveWithLogout(() => new Response(JSON.stringify({ message: 'ok' })))
    renderAt('/mypage?mock=done')

    fireEvent.click(await screen.findByRole('button', { name: '로그아웃' }))

    expect(await screen.findByText('로그인 화면')).toBeInTheDocument()
    expect(logoutCalls(fetchMock)).toHaveLength(1)
  })

  /** 같은 탭에 남아 있으면 다음에 로그인한 계정이 앞 사람의 진단 답을 이어받는다 */
  it('진단 중이던 답도 지운다', async () => {
    saveTokens('access-1', 'refresh-1')
    useDiagnosisStore.getState().setAnswers({ business: 'PERSONAL_CAFE', fullTimeCount: 2 })
    serveWithLogout(() => new Response(JSON.stringify({ message: 'ok' })))
    renderAt('/mypage')

    fireEvent.click(await screen.findByRole('button', { name: '로그아웃' }))

    await screen.findByText('로그인 화면')
    expect(useDiagnosisStore.getState().answers).toEqual(EMPTY_DIAGNOSIS)
  })

  it('로그아웃한 뒤 뒤로 가도 내 정보로 돌아오지 않는다', async () => {
    saveTokens('access-1', 'refresh-1')
    serveWithLogout(() => new Response(JSON.stringify({ message: 'ok' })))
    const router = renderAt('/mypage', ['/case'])

    fireEvent.click(await screen.findByRole('button', { name: '로그아웃' }))
    await screen.findByText('로그인 화면')
    await act(() => router.navigate(-1))

    expect(router.state.location.pathname).not.toBe('/mypage')
  })

  it('서버 답을 기다리는 동안 버튼을 잠가 두 번 보내지 않는다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = serveWithLogout(() => new Promise<Response>(() => {}))
    renderAt('/mypage')

    const button = await screen.findByRole('button', { name: '로그아웃' })
    fireEvent.click(button)
    fireEvent.click(button)

    expect(button).toBeDisabled()
    expect(logoutCalls(fetchMock)).toHaveLength(1)
  })

  /** Case가 없어도 로그아웃은 할 수 있어야 한다 */
  it('가게가 없어도 로그아웃할 수 있다', async () => {
    saveTokens('access-1', 'refresh-1')
    serveWithLogout(() => new Response(JSON.stringify({ message: 'ok' })), envelope(null))
    renderAt('/mypage')

    await screen.findByRole('button', { name: '상황 진단하기' })
    expect(screen.getByRole('button', { name: '로그아웃' })).toBeEnabled()
  })
})
