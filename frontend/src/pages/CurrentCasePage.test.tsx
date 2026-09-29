import { render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { saveTokens } from '../lib/auth'
import type { CaseResponse } from '../types/api'
import { CurrentCasePage } from './CurrentCasePage'

const SERVER_CASE: Partial<CaseResponse> = {
  id: 1,
  business_type: '분식집',
  franchise_status: false,
  employee_count: 3,
  lease_status: 'OWNED',
  restoration_scope: 'UNKNOWN',
  demolition_required: 'UNKNOWN',
}

function mockCase(body: unknown, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(status === 200 ? JSON.stringify(body) : null, { status })),
  )
}

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/case', element: <CurrentCasePage /> },
      { path: '/start', element: <p>시작 화면</p> },
    ],
    { initialEntries: [path] },
  )

  render(<RouterProvider router={router} />)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/**
 * 사용자가 돌아올 곳이고, 이 제품에서 유일하게 "지금 상황"을 보여주는 화면이다.
 * 여기 값이 틀리면 사장님이 자기 가게 상황을 잘못 알고 다음 행동을 한다.
 */
describe('CurrentCasePage', () => {
  it('서버가 준 Case를 화면에 보여준다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase({ case: SERVER_CASE })
    renderAt('/case')

    expect(await screen.findByText('분식집')).toBeInTheDocument()
    expect(screen.getByText('3명')).toBeInTheDocument()
    expect(screen.getByText('자가')).toBeInTheDocument()
  })

  /**
   * 서버가 아직 판단을 주지 않는다(BE #39). 할 일을 지어내지 않고 정보 부족으로 둔다.
   * "막혀 있는 것 없음"은 할 일이 있을 때만 의미가 있어 같이 숨긴다.
   */
  it('판단이 없으면 정보 부족을 알린다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase({ case: SERVER_CASE })
    renderAt('/case')

    expect(await screen.findByRole('heading', { name: '아직 정할 수 없음' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '지금 할 일' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '막혀 있는 것 없음' })).not.toBeInTheDocument()
  })

  /** 주소로 직접 들어온 경우다. 빈 화면 대신 만들러 보낸다 */
  it('Case가 없으면 시작 화면으로 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase({ case: null })
    renderAt('/case')

    expect(await screen.findByText('시작 화면')).toBeInTheDocument()
  })

  /** 빈 화면을 두면 사용자는 Case가 사라진 줄 안다 */
  it('서버를 부르지 못하면 다시 시도할 길을 준다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase(null, 500)
    renderAt('/case')

    expect(await screen.findByRole('button', { name: '다시 시도' })).toBeInTheDocument()
  })

  it('?mock=no-blocker면 막고 있는 것 없음을 보여준다', async () => {
    saveTokens('access-1', 'refresh-1')
    renderAt('/case?mock=no-blocker')

    expect(await screen.findByRole('heading', { name: '지금 할 일' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '막혀 있는 것 없음' })).toBeInTheDocument()
  })

  it('?mock=insufficient면 정보 부족만 보여준다', async () => {
    saveTokens('access-1', 'refresh-1')
    renderAt('/case?mock=insufficient')

    expect(await screen.findByRole('heading', { name: '아직 정할 수 없음' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '지금 할 일' })).not.toBeInTheDocument()
  })
})
