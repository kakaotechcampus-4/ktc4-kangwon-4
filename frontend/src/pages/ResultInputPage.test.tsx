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
  fireEvent.change(screen.getByLabelText('어떻게 됐나요?'), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: '보내기' }))
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
  /** 눌러도 아무 일이 없는 버튼은 고장으로 읽힌다. 적기 전에는 꺼 둔다 */
  it('아무것도 적지 않으면 보내기가 꺼져 있다', async () => {
    renderFlow('/results?mock=updated')

    expect(await screen.findByRole('button', { name: '보내기' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('어떻게 됐나요?'), { target: { value: '   ' } })
    expect(screen.getByRole('button', { name: '보내기' })).toBeDisabled()
  })

  /** 판단은 길면 2분 걸린다. 그동안 눌리는 폼이 그대로 있으면 같은 글을 또 보내게 된다 */
  it('보내는 동안은 폼 대신 처리 화면을 보여준다', async () => {
    vi.useFakeTimers()
    renderFlow('/results?mock=updated')

    submit('임대인이 철거하래요')
    await advance()

    expect(screen.getByRole('heading', { name: '답변을 정리하고 있어요' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '보내기' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '처리 중이에요' })).toBeDisabled()
  })

  /** 판단은 몇 분이 걸릴 수 있다. 떠나면 결과가 사라지는 줄 알면 그동안 화면에 묶인다 */
  it('기다리는 동안 화면을 떠나도 된다고 알린다', async () => {
    vi.useFakeTimers()
    renderFlow('/results?mock=updated')

    submit('임대인이 철거하래요')
    await advance()

    expect(screen.getByText('화면을 떠나셔도 계속 처리돼요. 끝나면 홈에서 보실 수 있어요.')).toBeInTheDocument()
  })

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
    .map(([, init]) => JSON.parse(init.body as string) as { case_history_id: number; raw_input: string })
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

    /** 홈의 "답하러 가기"로 들어온 경우다. 할 일의 결과가 아니라 질문의 답을 받는다 */
    it('리본이 되물은 상태면 질문마다 답할 칸을 연다', async () => {
      serve({
        entry: [
          json(
            entryBody({
              judgment_status: 'NEEDS_MORE_INFO',
              next_action: null,
              questions_for_user: ['직원이 몇 명인가요?', '프랜차이즈 가게인가요?'],
            }),
          ),
        ],
      })
      renderFlow()
      await advance()

      expect(screen.getByLabelText('직원이 몇 명인가요?')).toBeEnabled()
      expect(screen.getByLabelText('프랜차이즈 가게인가요?')).toBeEnabled()
    })

    /**
     * 일부만 답해도 보낼 수 있다. 막지 않는 대신, 빠뜨린 것인지 한 번 보게 한다.
     * 하나도 안 적었거나 다 적었으면 알릴 것이 없다.
     */
    it('질문 일부만 답하면 남은 질문은 다시 묻는다고 알린다', async () => {
      serve({
        entry: [
          json(
            entryBody({
              judgment_status: 'NEEDS_MORE_INFO',
              next_action: null,
              questions_for_user: ['직원이 몇 명인가요?', '프랜차이즈 가게인가요?'],
            }),
          ),
        ],
      })
      renderFlow()
      await advance()
      const hint = '답하지 않은 질문은 다음에 다시 여쭤볼게요.'

      expect(screen.queryByText(hint)).not.toBeInTheDocument()

      fireEvent.change(screen.getByLabelText('직원이 몇 명인가요?'), { target: { value: '2명이요' } })
      expect(screen.getByText(hint)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: '보내기' })).toBeEnabled()

      fireEvent.change(screen.getByLabelText('프랜차이즈 가게인가요?'), { target: { value: '아니요' } })
      expect(screen.queryByText(hint)).not.toBeInTheDocument()
    })

    /**
     * 재판단 때 AI는 직전 질문을 모른다. "2명이요"만 가면 무엇의 답인지 알 수 없다.
     * 답하지 않은 질문은 보내지 않는다 — 모르는 것까지 적게 하면 지어낸 답이 들어간다.
     */
    it('답은 질문을 붙여 보내고, 답하지 않은 질문은 뺀다', async () => {
      const fetchMock = serve({
        entry: [
          json(
            entryBody({
              judgment_status: 'NEEDS_MORE_INFO',
              next_action: null,
              questions_for_user: ['직원이 몇 명인가요?', '프랜차이즈 가게인가요?'],
            }),
          ),
        ],
        submit: [ACCEPTED],
      })
      renderFlow()
      await advance()

      fireEvent.change(screen.getByLabelText('직원이 몇 명인가요?'), { target: { value: '2명이요' } })
      fireEvent.click(screen.getByRole('button', { name: '보내기' }))
      await advance()

      expect(sentBodies(fetchMock).map((body) => body.raw_input)).toEqual([
        '[리본이 물어본 것] 직원이 몇 명인가요?\n[사장님 답] 2명이요',
      ])
    })

    /** 보내다 실패했다고 질문이 사라지면, 사장님은 무엇에 답하던 중이었는지 잃는다 */
    it('보낸 뒤 되물은 질문은 보내다 실패해도 답과 함께 남는다', async () => {
      serve({
        entry: [READY],
        submit: [ACCEPTED, status(500)],
        judged: [json(judgedBody({ result: 'NEEDS_MORE_INFO', questions_for_user: ['매장 전체인가요?'] }))],
      })
      renderFlow()
      await advance()

      submit('임대인이 철거하래요')
      await advance(INTERVAL_MS)
      fireEvent.change(screen.getByLabelText('매장 전체인가요?'), { target: { value: '네, 전체래요' } })
      fireEvent.click(screen.getByRole('button', { name: '보내기' }))
      await advance()

      expect(screen.getByLabelText('매장 전체인가요?')).toHaveValue('네, 전체래요')
      expect(screen.getByRole('button', { name: '다시 보내기' })).toBeEnabled()
    })

    it.each(['PENDING', 'FAILED'] as const)(
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

    /** 읽을 것이 없는 답에 불러오는 중으로 멈춰 있으면 사장님은 기다리기만 한다 */
    it('비어 있는 답이 오면 읽지 못했다고 알리고 현재 상황으로 가는 길을 둔다', async () => {
      serve({ entry: [json(null)] })
      renderFlow()
      await advance()

      expect(screen.queryByRole('status')).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: '지금 상황 보기' })).toBeInTheDocument()
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
      // 결과를 들고 가지 않고 접수 번호만 싣는다. `/replan` 이 그 번호로 다시 묻는다
      expect(router.state.location.search).toBe('?history=13')
      expect(router.state.location.state).toBeNull()
    })

    /**
     * 서버는 처리 단계를 알려주지 않는다. 첫 줄 "보냈어요"는 접수 번호를 받았을 때만 끝난다 —
     * 받기 전에 끝났다고 그리면, 보내다 실패했을 때 이미 보낸 것처럼 보인 셈이 된다.
     */
    it('접수 번호를 받아야 "보냈어요" 줄이 끝난다', async () => {
      let accept: (response: Response) => void = () => {}
      serve({
        entry: [READY],
        submit: [() => new Promise<Response>((resolve) => (accept = resolve)) as unknown as Response],
        judged: [json(judgedBody({ result: 'PENDING' }))],
      })
      renderFlow()
      await advance()

      submit('임대인이 철거하래요')
      await advance()
      const [sent, working] = screen.getAllByRole('listitem')
      expect(sent).toHaveTextContent('처리 중')
      expect(working).toHaveTextContent('대기')

      accept(ACCEPTED())
      await advance()
      const [sentAfter, workingAfter] = screen.getAllByRole('listitem')
      expect(sentAfter).toHaveTextContent('완료')
      expect(workingAfter).toHaveTextContent('처리 중')
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

      // 되물으면 같은 화면이 그 질문에 답하는 모양으로 바뀐다
      fireEvent.change(screen.getByLabelText('매장 전체인가요?'), { target: { value: '네, 전체래요' } })
      fireEvent.click(screen.getByRole('button', { name: '보내기' }))
      await advance()

      expect(sentBodies(fetchMock).map((body) => body.case_history_id)).toEqual([12, 13])
      expect(sentBodies(fetchMock)[1].raw_input).toBe('[리본이 물어본 것] 매장 전체인가요?\n[사장님 답] 네, 전체래요')
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

    /** "더 해 보실 수 있는 것이 없다" 고 해 놓고 보내기가 눌리면 안내와 화면이 다른 말을 한다 */
    it.each([
      ['RETRY', '열어 둔다', true],
      ['RESUBMIT_INPUT', '열어 둔다', true],
      ['CONTACT_SUPPORT', '잠근다', false],
      ['NONE', '잠근다', false],
    ] as const)('판단 실패(%s)에는 폼을 %s', async (code, _, open) => {
      serve({
        entry: [READY],
        submit: [ACCEPTED],
        judged: [json(judgedBody({ result: 'FAILED', recovery_action_code: code }))],
      })
      renderFlow()
      await advance()

      submit('임대인이 철거하래요')
      await advance(INTERVAL_MS)

      expect(screen.getByRole('textbox').hasAttribute('disabled')).toBe(!open)
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

    /**
     * 접수 답이 오기 전에 떠난 경우다. 그때는 아직 끊을 기다림이 없어서, 답이 온 뒤에 막지
     * 않으면 떠난 화면이 뒤에서 10분 동안 판단을 계속 묻는다.
     */
    it('접수 답이 오기 전에 떠나면 답이 와도 판단을 묻지 않는다', async () => {
      let accept: (response: Response) => void = () => {}
      const fetchMock = serve({
        entry: [READY],
        submit: [() => new Promise<Response>((resolve) => (accept = resolve)) as unknown as Response],
        judged: [json(judgedBody({ result: 'PENDING' }))],
      })
      const router = renderFlow()
      await advance()

      submit('임대인이 철거하래요')
      await advance()
      await act(async () => {
        await router.navigate(-1)
      })
      accept(ACCEPTED())
      await advance(INTERVAL_MS * 3)

      expect(fetchMock.mock.calls.filter(([url]) => url.includes('/status'))).toHaveLength(0)
      expect(router.state.location.pathname).toBe('/case')
    })
  })
})
