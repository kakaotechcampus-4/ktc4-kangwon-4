import { fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { saveTokens } from '../lib/auth'
import type { CaseLogItem } from '../types/api'
import { LogPage } from './LogPage'

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/log', element: <LogPage /> },
      { path: '/login', element: <p>로그인</p> },
    ],
    { initialEntries: [path] },
  )
  render(<RouterProvider router={router} />)
  return router
}

type Answer = () => Response

const json = (body: unknown): Answer => () => new Response(JSON.stringify(body), { status: 200 })
const status = (code: number): Answer => () => new Response(null, { status: code })

/** 부를 때마다 차례로 답한다. 목록이 끝나면 마지막 답을 계속 준다 */
function serve(...answers: Answer[]) {
  let calls = 0
  const fetchMock = vi.fn(async () => answers[Math.min(calls++, answers.length - 1)]())
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const item = (overrides: Partial<CaseLogItem>): CaseLogItem => ({
  actor: 'RIBBON',
  event: 'NEXT_ACTION_DECIDED',
  occurred_at: '2026-10-18T09:00:00+09:00',
  task_id: null,
  detail: '철거 업체 견적 받기',
  ...overrides,
})

afterEach(() => {
  vi.unstubAllGlobals()
})

/** 체크 기록은 서버가 번호만 준다. 기록 탭이 로드맵을 따로 물어 그 이름을 붙인다 */
describe('LogPage — 할 일 이름', () => {
  it('마친 할 일 아래에 로드맵의 할 일 이름을 붙인다', async () => {
    saveTokens('access-1', 'refresh-1')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        url.includes('/cases/roadmap')
          ? json({
              supported: true,
              unsupported_reason: null,
              current_stage: 3,
              stages: [
                {
                  stage: 3,
                  title: '영업 마무리·폐업 신고',
                  tasks: [{ task_id: 'dispose_stock', title: '재고·장비 처분', kind: 'CHECKLIST', status: 'COMPLETED', guidance: null }],
                },
              ],
            })()
          : json({ logs: [item({ actor: 'OWNER', event: 'CHECKLIST_COMPLETED', task_id: 'dispose_stock', detail: null })] })(),
      ),
    )
    renderAt('/log')

    expect(await screen.findByText('재고·장비 처분')).toBeInTheDocument()
    expect(screen.getByText('할 일 하나를 마치셨어요')).toBeInTheDocument()
  })
})

/**
 * 기록은 사장님이 무엇을 했는지 돌아보는 자리다. 불러오지 못한 것을 "기록 없음"으로 그리면
 * 한 일이 사라진 것처럼 읽힌다.
 */
describe('LogPage — 서버', () => {
  it('기록을 불러와 누가 언제 했는지와 함께 최근 것부터 그린다', async () => {
    const fetchMock = serve(
      json({ logs: [item({}), item({ actor: 'OWNER', event: 'RESULT_SUBMITTED', occurred_at: '2026-10-17T14:00:00+09:00', detail: null })] }),
    )
    renderAt('/log')

    const rows = await screen.findAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('다음 할 일을 정했어요')
    expect(rows[0]).toHaveTextContent('철거 업체 견적 받기')
    expect(rows[0]).toHaveTextContent('리본 · 10.18')
    expect(rows[1]).toHaveTextContent('사장님 · 10.17')
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/cases\/logs$/), expect.anything())
  })

  /** Case 가 없으면 서버가 404 를 준다. 기록이 없는 것과 같다 */
  it('Case 가 없으면 빈 상태로 둔다', async () => {
    serve(status(404))
    renderAt('/log')

    expect(await screen.findByText('아직 남은 기록이 없어요')).toBeInTheDocument()
  })

  it('불러오지 못하면 그렇다고 말하고 다시 불러올 수 있다', async () => {
    serve(status(500), json({ logs: [item({})] }))
    renderAt('/log')

    expect(await screen.findByText('기록을 불러오지 못했어요')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '다시 불러오기' }))

    expect(await screen.findByText('다음 할 일을 정했어요')).toBeInTheDocument()
  })

  /** 모양이 깨진 응답을 빈 목록으로 읽으면 기록이 사라진 것처럼 보인다 */
  it('받은 모양을 읽지 못하면 불러오지 못한 것으로 둔다', async () => {
    serve(json({ items: [] }))
    renderAt('/log')

    expect(await screen.findByText('기록을 불러오지 못했어요')).toBeInTheDocument()
  })

  it('로그인이 풀렸으면 로그인으로 간다', async () => {
    serve(status(401))
    const router = renderAt('/log')

    expect(await screen.findByText('로그인')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
  })
})

/** 리뷰어가 링크로 채워진 모양을 보는 길이다. 끊기면 화면을 볼 방법이 없다 */
describe('LogPage — Mock', () => {
  it('Mock 으로 열면 서버를 부르지 않고 예시 기록을 그린다', () => {
    const fetchMock = serve(status(500))
    renderAt('/log?mock=done')

    expect(screen.getAllByRole('listitem').length).toBeGreaterThan(0)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('logs-empty 로 열면 빈 상태를 그린다', () => {
    renderAt('/log?mock=logs-empty')

    expect(screen.getByText('아직 남은 기록이 없어요')).toBeInTheDocument()
  })
})
