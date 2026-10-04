import { render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { logInWithMock, saveTokens } from '../lib/auth'
import type { CaseResponse } from '../types/api'
import { useCase } from './useCase'

const SERVER_CASE: Partial<CaseResponse> = {
  id: 1,
  business_type: '카페',
  franchise_status: false,
  employee_count: 2,
  lease_status: 'LEASED_PAID',
  restoration_scope: 'UNKNOWN',
  demolition_required: 'UNKNOWN',
}

/** 판단 칸이 전부 비어 있는 봉투. 테스트마다 필요한 칸만 덮어쓴다 */
const EMPTY_JUDGMENT = {
  blocker: null,
  next_action: null,
  judgment_status: null,
  questions_for_user: null,
}

function mockFetch(body: unknown, status = 200) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(status === 200 ? JSON.stringify(body) : null, { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** 훅이 돌려준 상태를 글자로 드러내는 최소한의 화면 */
function Probe() {
  const { query } = useCase()

  if (query.status === 'READY') {
    const businessType = query.view.facts.find((fact) => fact.key === 'business_type')?.value
    return <p>{`READY ${query.view.judgment.status} ${businessType}`}</p>
  }
  return <p>{query.status}</p>
}

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/case', element: <Probe /> },
      { path: '/login', element: <p>로그인 화면</p> },
    ],
    { initialEntries: [path] },
  )

  render(<RouterProvider router={router} />)
  return router
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/**
 * 세 화면이 이 훅 하나로 Case 를 묻는다. 여기가 틀리면 처음 온 사장님이 빈 현재 Case 를
 * 보거나, 이미 Case 가 있는 사장님이 다시 "시작하기"를 마주한다.
 */
describe('useCase', () => {
  it('서버가 준 Case 를 화면 모양으로 돌려준다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockFetch({ ...EMPTY_JUDGMENT, case: SERVER_CASE, judgment_status: 'PENDING' })
    renderAt('/case')

    expect(await screen.findByText('READY PENDING 카페')).toBeInTheDocument()
  })

  it('Case 가 없으면 EMPTY 다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockFetch({ ...EMPTY_JUDGMENT, case: null })
    renderAt('/case')

    expect(await screen.findByText('EMPTY')).toBeInTheDocument()
  })

  /**
   * 못 쓰는 토큰을 들고 화면에 머물면 아무것도 되지 않는다. 화면은 멀쩡한데
   * 누르는 것마다 실패해서, 사용자는 무엇이 잘못됐는지 알 수 없다.
   */
  it('인증이 통하지 않으면 로그인 화면으로 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockFetch(null, 401)
    renderAt('/case')

    expect(await screen.findByText('로그인 화면')).toBeInTheDocument()
  })

  it('서버를 부르지 못하면 실패로 둔다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockFetch(null, 500)
    renderAt('/case')

    expect(await screen.findByText('LOAD_FAILED')).toBeInTheDocument()
  })

  /**
   * Preview 에서는 진짜 카카오 로그인을 할 수 없어 가짜 로그인을 쓴다. 그 토큰으로 서버를
   * 부르면 곧바로 401 이라, 화면을 보러 온 리뷰어가 화면을 못 본다.
   */
  it('가짜 세션이면 서버를 부르지 않는다', async () => {
    logInWithMock()
    const fetchMock = mockFetch({ ...EMPTY_JUDGMENT, case: SERVER_CASE })
    renderAt('/case')

    expect(await screen.findByText(/^READY/)).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  /** 리뷰어가 링크 하나로 예외 화면을 보는 길이다. 진짜 세션에서도 살아 있어야 한다 */
  it('?mock= 이 있으면 서버 대신 그 화면을 쓴다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockFetch({ ...EMPTY_JUDGMENT, case: SERVER_CASE })
    renderAt('/case?mock=no-case')

    expect(await screen.findByText('EMPTY')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
