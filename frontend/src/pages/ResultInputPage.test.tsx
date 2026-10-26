import { act, fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { CaseResultsEntryResponse, CaseResultsSubmitResponse } from '../types/api'
import { ResultInputPage } from './ResultInputPage'

/**
 * 앞뒤 화면을 실제 경로로 함께 등록한다. 대기 중에 화면을 떠나는 상황을 만들어야 해서
 * 이 화면만 띄워서는 확인할 수 없다.
 */
function renderFlow(results = '/results') {
  const router = createMemoryRouter(
    [
      { path: '/', element: <p>진입 분기</p> },
      { path: '/login', element: <p>로그인</p> },
      { path: '/case', element: <p>현재 Case</p> },
      { path: '/results', element: <ResultInputPage /> },
      { path: '/confirm', element: <p>충돌 확인</p> },
      { path: '/replan', element: <p>재계획 결과</p> },
    ],
    { initialEntries: ['/case', results], initialIndex: 1 },
  )

  render(<RouterProvider router={router} />)
  return router
}

/** 입력하고 제출한다. 클릭은 fireEvent로 — userEvent는 가짜 타이머와 맞물리면 멈춘다 */
function submit(text: string) {
  fireEvent.change(screen.getByLabelText(/어떻게 되었나요/), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: /알려주기/ }))
}

/** 가짜 시계를 돌리고, 그 사이 끝난 요청과 그에 따른 렌더까지 반영한다 */
async function advance(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('ResultInputPage — Mock', () => {
  /** 기다린 사람은 결과 화면으로 간다 — 아래 테스트가 이동 자체를 막아버리지 않았는지 함께 본다 */
  it('응답이 오면 재계획 화면으로 이동한다', async () => {
    vi.useFakeTimers()
    const router = renderFlow('/results?mock=updated')

    submit('임대인이 철거하래요')
    await act(async () => {
      vi.runAllTimers()
    })

    expect(router.state.location.pathname).toBe('/replan')
  })

  /**
   * 응답을 기다리는 동안 사용자가 뒤로 갈 수 있다. 그때 이동을 그대로 실행하면
   * 일부러 빠져나온 화면으로 몇 초 뒤에 끌려간다 — 사용자에게는 고장으로 읽힌다.
   *
   * 화면이 아직 붙어 있는지 확인하는 한 줄로 막고 있어서, 파일을 옮기거나 고치는
   * 과정에서 조용히 사라지기 쉽다. 사라져도 기다리다 뒤로 가보지 않으면 모른다.
   */
  it('대기 중에 화면을 떠나면 이동하지 않는다', async () => {
    vi.useFakeTimers()
    const router = renderFlow('/results?mock=updated')

    submit('임대인이 철거하래요')

    await act(async () => {
      await router.navigate(-1)
    })
    expect(router.state.location.pathname).toBe('/case')

    await act(async () => {
      vi.runAllTimers()
    })

    expect(router.state.location.pathname).toBe('/case')
  })
})

type Answer = () => Response

const json =
  (body: unknown, status = 200): Answer =>
  () =>
    new Response(JSON.stringify(body), { status })

const status =
  (code: number): Answer =>
  () =>
    new Response(null, { status: code })

/**
 * 세 군데 주소에 각각 순서대로 답한다. 목록이 끝나면 마지막 답을 계속 준다.
 *
 * 부른 순서가 아니라 주소로 답을 고른다. 화면이 어떤 순서로 부르는지까지 테스트가
 * 정해 두면, 순서를 바꾸는 정당한 수정에도 관계없는 테스트가 깨진다.
 */
function serve({ entry = [], submit = [], judged = [] }: Partial<Record<'entry' | 'submit' | 'judged', Answer[]>>) {
  const calls = { entry: 0, submit: 0, judged: 0 }
  const pick = (kind: keyof typeof calls, answers: Answer[]) => {
    const answer = answers[Math.min(calls[kind], answers.length - 1)]
    calls[kind] += 1
    return answer()
  }

  const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
    if (url.includes('/cases/results/status')) return pick('judged', judged)
    if (init.method === 'POST') return pick('submit', submit)
    return pick('entry', entry)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** `POST` 로 보낸 본문들 */
function sentBodies(fetchMock: ReturnType<typeof serve>) {
  return fetchMock.mock.calls
    .filter(([, init]) => init.method === 'POST')
    .map(([, init]) => JSON.parse(init.body as string) as { case_history_id: number })
}

function entryBody(overrides: Partial<CaseResultsEntryResponse>): CaseResultsEntryResponse {
  return {
    judgment_status: 'DONE',
    case_history_id: 12,
    raw_input: null,
    conflicts: null,
    next_action: { title: '임대인에게 원상복구 범위 묻기', reason: '', questions_to_ask: [] },
    questions_for_user: null,
    recovery_action_code: null,
    requested_field_paths: null,
    ...overrides,
  }
}

function judgedBody(overrides: Partial<CaseResultsSubmitResponse>): CaseResultsSubmitResponse {
  return {
    result: 'PENDING',
    changes: null,
    blocker: null,
    next_action: null,
    questions_for_user: null,
    raw_input: null,
    conflicts: null,
    recovery_action_code: null,
    requested_field_paths: null,
    ...overrides,
  }
}

const READY = json(entryBody({}))
const ACCEPTED = json({ case_history_id: 13 })
const INTERVAL_MS = 10_000

/**
 * 서버를 부르는 경로. 들어올 때 지금 판단을 묻고, 보낸 뒤 판단이 끝날 때까지 기다린다.
 *
 * 앞의 Mock 테스트로는 이 경로가 하나도 지나가지 않는다 — Mock 은 서버를 아예 부르지 않는다.
 */
describe('ResultInputPage — 서버', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  describe('들어올 때', () => {
    it('결과를 받을 수 있으면 할 일과 폼을 연다', async () => {
      serve({ entry: [READY] })
      renderFlow()
      await advance()

      expect(screen.getByText('임대인에게 원상복구 범위 묻기')).toBeInTheDocument()
      expect(screen.getByRole('textbox')).toBeEnabled()
    })

    /** 충돌부터 풀어야 한다. 뒤로 가기로 이 화면에 돌아오면 같은 곳으로 또 튕긴다 */
    it('확인을 기다리는 충돌이 있으면 충돌 확인으로 바꿔 낀다', async () => {
      serve({
        entry: [
          json(
            entryBody({
              judgment_status: 'CONFLICT',
              case_history_id: null,
              next_action: null,
              raw_input: '철거해야 한대요',
              conflicts: [{ id: 3, field: 'demolition_required', stored_value: 'NOT_REQUIRED', proposed_value: 'REQUIRED' }],
            }),
          ),
        ],
      })
      const router = renderFlow()
      await advance()

      expect(router.state.location.pathname).toBe('/confirm')
      await act(async () => {
        await router.navigate(-1)
      })
      expect(router.state.location.pathname).toBe('/case')
    })

    it.each(['PENDING', 'NEEDS_MORE_INFO', 'FAILED'] as const)(
      '판단이 %s 면 현재 Case 로 돌려보낸다',
      async (judgment) => {
        serve({ entry: [json(entryBody({ judgment_status: judgment, next_action: null }))] })
        const router = renderFlow()
        await advance()

        expect(router.state.location.pathname).toBe('/case')
      },
    )

    it.each([
      [404, '/'],
      [401, '/login'],
    ])('%i 이면 %s 로 보낸다', async (code, path) => {
      serve({ entry: [status(code)] })
      const router = renderFlow()
      await advance()

      expect(router.state.location.pathname).toBe(path)
    })

    it('불러오지 못하면 다시 불러올 수 있다', async () => {
      serve({ entry: [status(500), READY] })
      renderFlow()
      await advance()

      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: '다시 불러오기' }))
      await advance()

      expect(screen.getByRole('textbox')).toBeEnabled()
    })
  })

  describe('보낸 뒤', () => {
    it('판단이 끝날 때까지 기다렸다가 재계획 화면으로 간다', async () => {
      serve({
        entry: [READY],
        submit: [ACCEPTED],
        judged: [
          json(judgedBody({ result: 'PENDING' })),
          json(
            judgedBody({
              result: 'UPDATED',
              changes: [],
              blocker: '철거 전에 지원 조건을 확인해야 합니다.',
              next_action: { title: '지원 조건 확인하기', reason: '', questions_to_ask: [] },
            }),
          ),
        ],
      })
      const router = renderFlow()
      await advance()

      submit('임대인이 철거하래요')
      await advance(INTERVAL_MS)
      expect(router.state.location.pathname).toBe('/results')

      await advance(INTERVAL_MS)
      expect(router.state.location.pathname).toBe('/replan')
    })

    /**
     * 되물은 뒤 다시 보낼 때는 방금 접수된 것이 가장 최근 판단이다.
     * 들어올 때 받은 번호로 또 보내면 서버가 409 로 막고, 사장님은 답하고도 못 보낸다.
     */
    it('되물은 뒤 다시 보내면 방금 받은 접수 번호로 보낸다', async () => {
      const fetchMock = serve({
        entry: [READY],
        submit: [ACCEPTED, json({ case_history_id: 14 })],
        judged: [json(judgedBody({ result: 'NEEDS_MORE_INFO', questions_for_user: ['매장 전체인가요?'] }))],
      })
      renderFlow()
      await advance()

      submit('임대인이 철거하래요')
      await advance(INTERVAL_MS)
      expect(screen.getByText('매장 전체인가요?')).toBeInTheDocument()

      submit('매장 전체래요')
      await advance()

      expect(sentBodies(fetchMock).map((body) => body.case_history_id)).toEqual([12, 13])
    })

    /** 무엇이 실패했든 적은 글을 다시 쓰게 하지 않는다 */
    it('보내지 못하면 적은 글을 그대로 두고 다시 보낼 수 있게 한다', async () => {
      serve({ entry: [READY], submit: [status(500)] })
      renderFlow()
      await advance()

      submit('임대인이 철거하래요')
      await advance()

      expect(screen.getByRole('textbox')).toHaveValue('임대인이 철거하래요')
      expect(screen.getByRole('button', { name: '다시 보내기' })).toBeEnabled()
    })

    /** 이 화면이 아는 판단이 낡았다. 같은 글을 또 보내도 같은 답이 온다 */
    it('지금 받을 수 없다는 답이면 다시 보내기 대신 현재 상황으로 안내한다', async () => {
      serve({ entry: [READY], submit: [status(409)] })
      const router = renderFlow()
      await advance()

      submit('임대인이 철거하래요')
      await advance()

      expect(screen.getByRole('textbox')).toHaveValue('임대인이 철거하래요')
      expect(screen.getByRole('textbox')).toBeDisabled()
      expect(screen.queryByRole('button', { name: '다시 보내기' })).not.toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: '지금 상황 보기' }))
      expect(router.state.location.pathname).toBe('/case')
    })

    /**
     * 판단은 끝났는데 읽지 못했다. 이미 반영됐을 수 있어 같은 글을 또 보내면 두 번 들어간다.
     * 안내가 `/case` 로 보내는 상태에서는 폼도 닫아 둔다
     */
    it('판단 결과를 읽지 못하면 폼을 잠근다', async () => {
      serve({ entry: [READY], submit: [ACCEPTED], judged: [json(null)] })
      renderFlow()
      await advance()

      submit('임대인이 철거하래요')
      await advance(INTERVAL_MS)

      expect(screen.getByRole('textbox')).toBeDisabled()
      expect(screen.getByRole('button', { name: '지금 상황 보기' })).toBeInTheDocument()
    })

    /**
     * 뒤로 가면 이 화면이 다시 물어 충돌 화면으로 되돌려 보낸다. 결과 입력을 거쳐 가지 않아야
     * 뒤로 가기 한 번에 빠져나온다
     */
    it('판단이 충돌이면 결과 입력을 거치지 않고 충돌 확인으로 간다', async () => {
      serve({
        entry: [READY],
        submit: [ACCEPTED],
        judged: [
          json(
            judgedBody({
              result: 'CONFLICT',
              raw_input: '임대인이 철거하래요',
              conflicts: [{ id: 3, field: 'demolition_required', stored_value: 'NOT_REQUIRED', proposed_value: 'REQUIRED' }],
            }),
          ),
        ],
      })
      const router = renderFlow()
      await advance()

      submit('임대인이 철거하래요')
      await advance(INTERVAL_MS)
      expect(router.state.location.pathname).toBe('/confirm')

      await act(async () => {
        await router.navigate(-1)
      })
      expect(router.state.location.pathname).toBe('/case')
    })

    /** 더 적어야 하는 실패에 다시 보내기를 달면 고치지 않은 글로 같은 실패를 되풀이한다 */
    it.each([
      ['RETRY', '단다', true],
      ['RESUBMIT_INPUT', '달지 않는다', false],
      ['CONTACT_SUPPORT', '달지 않는다', false],
    ] as const)('판단 실패(%s)에는 다시 보내기를 %s', async (code, _, retryable) => {
      serve({
        entry: [READY],
        submit: [ACCEPTED],
        judged: [json(judgedBody({ result: 'FAILED', recovery_action_code: code }))],
      })
      renderFlow()
      await advance()

      submit('임대인이 철거하래요')
      await advance(INTERVAL_MS)

      expect(screen.queryByRole('button', { name: '다시 보내기' }) !== null).toBe(retryable)
    })

    /** 떠난 화면이 결과를 받아 사장님을 다른 화면으로 끌고 가면 안 된다 */
    it('기다리는 중에 화면을 떠나면 더 묻지 않는다', async () => {
      const fetchMock = serve({
        entry: [READY],
        submit: [ACCEPTED],
        judged: [json(judgedBody({ result: 'PENDING' }))],
      })
      const router = renderFlow()
      await advance()

      submit('임대인이 철거하래요')
      await advance()
      await act(async () => {
        await router.navigate(-1)
      })
      await advance(INTERVAL_MS * 3)

      expect(fetchMock.mock.calls.filter(([url]) => url.includes('/status'))).toHaveLength(0)
      expect(router.state.location.pathname).toBe('/case')
    })
  })
})
