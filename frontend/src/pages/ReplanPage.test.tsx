import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { CaseResultsSubmitResponse } from '../types/api'
import type { ReplanView } from '../types/view'
import { ReplanPage } from './ReplanPage'

function renderAt(entry: string | { pathname: string; search: string; state: unknown }) {
  const router = createMemoryRouter(
    [
      { path: '/', element: <p>진입 분기</p> },
      { path: '/login', element: <p>로그인</p> },
      { path: '/case', element: <p>현재 Case</p> },
      { path: '/results', element: <p>결과 입력</p> },
      { path: '/replan', element: <ReplanPage /> },
    ],
    { initialEntries: ['/case', entry], initialIndex: 1 },
  )

  render(<RouterProvider router={router} />)
  return router
}

type Answer = () => Response | Promise<Response>

const json =
  (body: unknown, status = 200): Answer =>
  () =>
    new Response(JSON.stringify(body), { status })

const status =
  (code: number): Answer =>
  () =>
    new Response(null, { status: code })

/** 부를 때마다 차례로 답한다. 목록이 끝나면 마지막 답을 계속 준다 */
function serve(...answers: Answer[]) {
  let calls = 0
  const fetchMock = vi.fn(async () => answers[Math.min(calls++, answers.length - 1)]())
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function judged(overrides: Partial<CaseResultsSubmitResponse>): CaseResultsSubmitResponse {
  return {
    result: 'UPDATED',
    changes: [{ field: 'employee_count', stored_value: '3', new_value: '2' }],
    blocker: '철거 전에 지원 조건을 확인해야 합니다.',
    next_action: { title: '지원 조건 확인하기', reason: '철거 비용 지원은 신청이 먼저예요.', questions_to_ask: [] },
    questions_for_user: null,
    raw_input: null,
    conflicts: null,
    recovery_action_code: null,
    requested_field_paths: null,
    new_tasks: null,
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ReplanPage — 서버', () => {
  it('주소의 판단 번호로 결과를 다시 물어 그린다', async () => {
    const fetchMock = serve(json(judged({})))
    renderAt('/replan?history=13')

    expect(await screen.findByText('지원 조건 확인하기')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('case_history_id=13'), expect.anything())
  })

  it('바뀐 내용과 다음 할 일을 보여주고, 막힌 것은 그리지 않는다', async () => {
    serve(json(judged({})))
    renderAt('/replan?history=13')

    expect(await screen.findByRole('heading', { name: '이렇게 이해하고 반영했어요' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '이해한 내용' })).toBeInTheDocument()
    expect(screen.getByText('철거 비용 지원은 신청이 먼저예요.')).toBeInTheDocument()
    // 홈에서 뺀 것과 같은 기준이다
    expect(screen.queryByText('철거 전에 지원 조건을 확인해야 합니다.')).not.toBeInTheDocument()
    // 처리 중 화면에서 이어지게, 같은 단계 줄을 모두 끝난 모양으로 보여준다
    for (const step of screen.getAllByRole('listitem').slice(0, 3)) expect(step).toHaveTextContent('완료')
  })

  /** 시안 "할 일 3개가 새로 생겼어요"(#182). 서버가 준 순서 그대로, 누르는 줄이 아니라 목록이다 */
  it('새로 생긴 할 일을 순서대로 보여준다', async () => {
    serve(
      json(
        judged({
          new_tasks: [
            { task_id: 'support_application', title: '소상공인24 사전 신청' },
            { task_id: 'before_photo', title: '철거 전 사진' },
          ],
        }),
      ),
    )
    renderAt('/replan?history=13')

    const box = await screen.findByRole('region', { name: '새로 생긴 할 일' })
    const items = within(box).getAllByRole('listitem')
    expect(items.map((item) => item.textContent)).toEqual(['소상공인24 사전 신청', '철거 전 사진'])
    expect(within(box).queryByRole('link')).not.toBeInTheDocument()
  })

  it('새로 생긴 할 일이 없거나 비교할 수 없으면 그 상자를 그리지 않는다', async () => {
    serve(json(judged({ new_tasks: null })))
    renderAt('/replan?history=13')

    expect(await screen.findByText('지원 조건 확인하기')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '새로 생긴 할 일' })).not.toBeInTheDocument()
  })

  /** "반영했어요"라고 하고 바뀐 것이 없으면 사장님은 무엇이 반영됐는지 찾게 된다 */
  it('바뀐 칸이 없으면 그렇다고 말하고 바뀐 내용 상자를 그리지 않는다', async () => {
    serve(json(judged({ result: 'NO_CHANGE', changes: [] })))
    renderAt('/replan?history=13')

    expect(await screen.findByRole('heading', { name: '가게 정보에 바뀐 내용은 없어요' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '이해한 내용' })).not.toBeInTheDocument()
    expect(screen.getByText('지원 조건 확인하기')).toBeInTheDocument()
  })

  /** 바뀐 것이 없는데 "반영했어요"라고 하면 제목과 엇갈린다 */
  it.each([
    ['바뀐 것이 있으면 다시 정했다고 한다', {}, '다음 할 일을 다시 정했어요.', '다음 할 일을 다시 확인했어요.'],
    [
      '바뀐 것이 없으면 다시 확인했다고 한다',
      { result: 'NO_CHANGE', changes: [] },
      '다음 할 일을 다시 확인했어요.',
      '다음 할 일을 다시 정했어요.',
    ],
  ] as const)('%s', async (_, overrides, shown, hidden) => {
    serve(json(judged(overrides as Partial<CaseResultsSubmitResponse>)))
    renderAt('/replan?history=13')

    expect(await screen.findByText(shown)).toBeInTheDocument()
    expect(screen.queryByText(hidden)).not.toBeInTheDocument()
  })

  it('맞아요를 누르면 지금 상황으로 간다', async () => {
    serve(json(judged({})))
    renderAt('/replan?history=13')

    await userEvent.click(await screen.findByRole('button', { name: '맞아요' }))

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
  })

  /** 이미 반영된 결과라 되돌리지 않는다. 바로잡아 다시 적게 하고, 다르면 서버가 충돌로 묻는다 */
  it('다르게 이해했어요를 누르면 바로잡는 결과 입력으로 간다', async () => {
    serve(json(judged({})))
    const router = renderAt('/replan?history=13')

    await userEvent.click(await screen.findByRole('button', { name: '다르게 이해했어요' }))

    expect(await screen.findByText('결과 입력')).toBeInTheDocument()
    expect(new URLSearchParams(router.state.location.search).get('fix')).toBe('1')
  })

  /**
   * 충돌 확인에서 사장님이 직접 고른 것을 반영했다. AI가 "이해한" 것이 아니라 바로잡을 것도 없다 —
   * [다르게 이해했어요]를 두면 방금 고른 것을 글로 다시 적게 된다
   */
  it('충돌 확인에서 왔으면 고른 것을 반영했다고 하고, 맞는지 묻지 않는다', async () => {
    serve(json(judged({})))
    renderAt('/replan?history=13&from=confirm')

    expect(await screen.findByRole('heading', { name: '고르신 내용을 반영했어요' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '바뀐 내용' })).toBeInTheDocument()
    expect(screen.getByText('고르신 내용을 반영하고 있어요')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '홈으로' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '다르게 이해했어요' })).not.toBeInTheDocument()
  })

  it('바뀐 것이 없으면 맞는지 묻지 않고 홈으로만 보낸다', async () => {
    serve(json(judged({ result: 'NO_CHANGE', changes: [] })))
    renderAt('/replan?history=13')

    await userEvent.click(await screen.findByRole('button', { name: '홈으로' }))

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '다르게 이해했어요' })).not.toBeInTheDocument()
  })

  /**
   * 번호를 숫자 글자로만 받는다. `Number()` 에 맡기면 빈 값은 0, `1e3` 은 1000, `12.0` 은 12 가
   * 되어 엉뚱한 판단을 묻는다.
   */
  it.each(['', '?history=', '?history=0', '?history=-3', '?history=1.5', '?history=1e3', '?history=abc'])(
    '판단 번호가 %j 이면 묻지 않고 지금 상황으로 보낸다',
    async (search) => {
      const fetchMock = serve(json(judged({})))
      const router = renderAt(`/replan${search}`)

      expect(await screen.findByText('현재 Case')).toBeInTheDocument()
      expect(router.state.historyAction).toBe('REPLACE')
      expect(fetchMock).not.toHaveBeenCalled()
    },
  )

  /** 루프를 더 돈 뒤 뒤로 가기·새로고침으로 돌아온 경우다. 지난 결과를 지금 것처럼 그리지 않는다 */
  it('이 결과 뒤로 새 판단이 생겼으면 지난 결과 대신 그 사실을 알린다', async () => {
    serve(status(409))
    renderAt('/replan?history=13')

    expect(await screen.findByText('이 결과 뒤로 새 판단이 나왔어요.')).toBeInTheDocument()
    expect(screen.queryByText('지원 조건 확인하기')).not.toBeInTheDocument()
  })

  it('그 번호의 기록이 없으면 지금 상황으로 보낸다', async () => {
    serve(status(404))
    renderAt('/replan?history=13')

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
  })

  /** 반영된 결과만 이 화면의 것이다. 판단 중을 반영 결과처럼 그리면 빈 칸이 뜬다 */
  it.each(['PENDING', 'NEEDS_MORE_INFO', 'FAILED'] as const)(
    '반영된 결과가 아니면(%s) 지금 상황으로 보낸다',
    async (result) => {
      serve(json(judged({ result, questions_for_user: ['직원이 몇 명인가요?'] })))
      renderAt('/replan?history=13')

      expect(await screen.findByText('현재 Case')).toBeInTheDocument()
    },
  )

  it('로그인이 풀렸으면 로그인으로 보낸다', async () => {
    serve(status(401))
    renderAt('/replan?history=13')

    expect(await screen.findByText('로그인')).toBeInTheDocument()
  })

  it('불러오지 못하면 다시 불러올 수 있다', async () => {
    serve(status(500), json(judged({})))
    renderAt('/replan?history=13')

    await userEvent.click(await screen.findByRole('button', { name: '다시 불러오기' }))

    expect(await screen.findByText('지원 조건 확인하기')).toBeInTheDocument()
  })

  /** 기다리는 사이 떠났다. 늦게 온 결과가 떠난 사장님을 다시 끌고 가면 안 된다 */
  it('떠난 뒤에 온 응답은 무시한다', async () => {
    let answer: (response: Response) => void = () => {}
    serve(() => new Promise<Response>((resolve) => (answer = resolve)))
    const router = renderAt('/replan?history=13')

    await act(async () => {
      await router.navigate('/case')
    })
    await act(async () => {
      answer(json(judged({ result: 'PENDING' }))() as Response)
    })

    expect(router.state.location.pathname).toBe('/case')
    expect(router.state.historyAction).toBe('PUSH')
  })
})

describe('ReplanPage — Mock', () => {
  /** Mock 은 물을 서버가 없다. 앞 화면이 넘겨준 결과를 그대로 그린다 */
  it('앞 화면이 넘겨준 결과를 그린다', async () => {
    const fetchMock = serve(json(judged({})))
    const view: ReplanView = {
      changes: [],
      blocker: null,
      nextAction: { title: '넘겨받은 할 일', reason: '' },
      newTasks: [],
    }
    renderAt({ pathname: '/replan', search: '?mock=updated', state: view })

    expect(await screen.findByText('넘겨받은 할 일')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
