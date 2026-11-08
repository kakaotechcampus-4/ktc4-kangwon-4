import { act, fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { saveTokens } from '../lib/auth'
import { JudgmentWatcher } from './JudgmentWatcher'
import { TOAST_DURATION_MS } from './ui/Toast'

/** `RequireAuth` 처럼 화면 옆에 감시를 둔다 */
function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      {
        element: (
          <>
            <Outlet />
            <JudgmentWatcher />
          </>
        ),
        children: [
          { path: '/roadmap', element: <p>로드맵</p> },
          { path: '/docs', element: <p>서류함</p> },
          { path: '/case', element: <p>홈</p> },
          { path: '/replan', element: <p>반영 결과</p> },
        ],
      },
    ],
    { initialEntries: [path] },
  )
  render(<RouterProvider router={router} />)
  return router
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

const entry = (judgment_status: string) => ({
  judgment_status,
  result_input_kind: 'FREE_TEXT',
  action_done_kind: null,
  case_history_id: 7,
  raw_input: null,
  conflicts: null,
  next_action: null,
  questions_for_user: null,
  recovery_action_code: null,
  requested_field_paths: null,
})

const status = (result: string) => ({
  result,
  changes: [],
  blocker: null,
  next_action: null,
  questions_for_user: null,
  raw_input: null,
  conflicts: null,
  recovery_action_code: null,
  requested_field_paths: null,
  new_tasks: null,
})

/** 판단 상태 조회는 `entry` 로, 판단 번호 조회는 `results` 를 차례로 답한다(마지막 답을 계속 준다) */
function serve(first: unknown, ...results: unknown[]) {
  let calls = 0
  const fetchMock = vi.fn(async (url: string) => {
    if (url.includes('/cases/results/status')) {
      return new Response(JSON.stringify(results[Math.min(calls++, results.length - 1)]), { status: 200 })
    }
    if (url.includes('/cases/results')) return new Response(JSON.stringify(first), { status: 200 })
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

beforeEach(() => {
  vi.useFakeTimers()
  saveTokens('access-1', 'refresh-1')
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

/** 결과를 보내고 다른 화면으로 가도, 판단이 끝나면 알 수 있어야 한다 */
describe('JudgmentWatcher', () => {
  it('판단 중이던 것이 끝나면 띠를 띄우고, 보기를 누르면 그 판단의 결과로 간다', async () => {
    serve(entry('PENDING'), status('PENDING'), status('UPDATED'))
    const router = renderAt('/roadmap')

    await advance(3_000)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    await advance(3_000)
    expect(screen.getByRole('status')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('link', { name: '보기' }))
    expect(router.state.location.pathname).toBe('/replan')
    expect(router.state.location.search).toBe('?history=7')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('더 여쭤볼 게 생기면 홈으로 보낸다', async () => {
    serve(entry('PENDING'), status('NEEDS_MORE_INFO'))
    const router = renderAt('/roadmap')

    await advance(3_000)
    fireEvent.click(screen.getByRole('link', { name: '답하러 가기' }))

    expect(router.state.location.pathname).toBe('/case')
  })

  /** 언제 끝났는지 모르는 판단을 방금 끝난 것처럼 알리지 않는다. 그건 종 버튼의 점이 알린다 */
  it('들어왔을 때 이미 끝나 있던 판단은 알리지 않는다', async () => {
    const fetchMock = serve(entry('DONE'))
    renderAt('/roadmap')

    await advance(10_000)

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  /** 홈·결과 화면은 스스로 판단을 기다린다. 같은 판단을 두 번 묻지 않는다 */
  it('판단을 스스로 기다리는 화면에서는 묻지 않는다', async () => {
    const fetchMock = serve(entry('PENDING'), status('UPDATED'))
    renderAt('/case')

    await advance(10_000)

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('판단을 기다리는 화면으로 옮기면 기다리기를 멈춘다', async () => {
    const fetchMock = serve(entry('PENDING'), status('PENDING'))
    const router = renderAt('/roadmap')
    await advance(3_000)
    const calls = fetchMock.mock.calls.length

    await act(() => router.navigate('/case'))
    await advance(30_000)

    expect(fetchMock).toHaveBeenCalledTimes(calls)
  })

  /** 띠는 덧붙인 도움이다. 묻다 실패했다고 아무 말이나 띄우지 않는다 */
  it('판단 상태를 묻지 못하면 아무것도 띄우지 않는다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 500 })))
    renderAt('/roadmap')

    await advance(10_000)

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('그사이 더 새로운 판단이 생기면 알리지 않는다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        url.includes('/status')
          ? new Response(null, { status: 409 })
          : new Response(JSON.stringify(entry('PENDING')), { status: 200 }),
      ),
    )
    renderAt('/roadmap')

    await advance(10_000)

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('띠는 잠시 뒤 저절로 닫힌다', async () => {
    serve(entry('PENDING'), status('FAILED'))
    renderAt('/docs')

    await advance(3_000)
    expect(screen.getByRole('status')).toBeInTheDocument()
    await advance(TOAST_DURATION_MS)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('닫기를 누르면 띠가 닫힌다', async () => {
    serve(entry('PENDING'), status('CONFLICT'))
    renderAt('/docs')

    await advance(3_000)
    fireEvent.click(screen.getByRole('button', { name: '알림 닫기' }))

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  /** 읽는 도중에 사라지면 안 된다. 홈 띠와 같은 원칙이다 */
  it('동작 줄이기를 켰으면 저절로 닫지 않는다', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })))
    serve(entry('PENDING'), status('UPDATED'))
    renderAt('/docs')

    await advance(3_000 + TOAST_DURATION_MS)

    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  /** 판단이 끝나면 기록도 늘었다. 종 버튼의 점이 화면을 옮기지 않아도 켜지게 기록을 다시 묻게 한다 */
  it('판단이 끝난 것을 보면 기록이 늘었다고 알린다', async () => {
    const heard = vi.fn()
    window.addEventListener('reborn:logs-changed', heard)
    serve(entry('PENDING'), status('UPDATED'))
    renderAt('/docs')

    await advance(3_000)
    window.removeEventListener('reborn:logs-changed', heard)

    expect(heard).toHaveBeenCalledTimes(1)
  })
})
