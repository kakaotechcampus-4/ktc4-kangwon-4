import { fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { saveTokens } from '../lib/auth'
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

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/me', element: <MyInfoPage /> },
      { path: '/cases/new', element: <p>상황 진단 화면</p> },
    ],
    { initialEntries: [path] },
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
    renderAt('/me')

    expect(await screen.findByRole('heading', { level: 2, name: '내 가게' })).toBeInTheDocument()
    expect(screen.getAllByRole('term')).toHaveLength(7)
    expect(valueOf('업종')).toHaveTextContent('카페')
    expect(valueOf('직원 수')).toHaveTextContent('3명')
    expect(valueOf('철거 필요 여부')).toHaveTextContent('필요함')
  })

  /** 빈칸으로 숨기면 사장님은 답한 것이 사라진 줄 안다(FE 규칙 6) */
  it('서버가 확정하지 않은 값은 빈칸이 아니라 확인 필요로 남긴다', async () => {
    saveTokens('access-1', 'refresh-1')
    serve([ok(envelope(SERVER_CASE))])
    renderAt('/me')

    await screen.findByRole('heading', { level: 2, name: '내 가게' })
    expect(valueOf('원상복구 범위')).toHaveTextContent('확인 필요')
    expect(valueOf('폐업 예정일')).toHaveTextContent('확인 필요')
  })

  /** 로그아웃은 Case가 없어도 할 수 있어야 해서 진단으로 바로 보내지 않는다 */
  it('가게가 없으면 이 화면에서 알리고 상황 진단으로 가는 길을 둔다', async () => {
    saveTokens('access-1', 'refresh-1')
    serve([ok(envelope(null))])
    const router = renderAt('/me')

    fireEvent.click(await screen.findByRole('button', { name: '상황 진단하기' }))

    expect(router.state.location.pathname).toBe('/cases/new')
  })

  it('불러오지 못하면 다시 불러올 수 있다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = serve([failing, ok(envelope(SERVER_CASE))])
    renderAt('/me')

    fireEvent.click(await screen.findByRole('button', { name: '다시 불러오기' }))

    expect(await screen.findByRole('heading', { level: 2, name: '내 가게' })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('Mock 으로 열면 서버를 부르지 않고 Mock 가게 정보를 그린다', async () => {
    const fetchMock = serve([failing])
    renderAt('/me?mock=done')

    expect(await screen.findByRole('heading', { level: 2, name: '내 가게' })).toBeInTheDocument()
    expect(screen.getAllByRole('term')).toHaveLength(7)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
