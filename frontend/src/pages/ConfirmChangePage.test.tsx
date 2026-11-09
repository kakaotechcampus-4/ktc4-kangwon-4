import { act, fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { CaseResultsSubmitResponse } from '../types/api'
import type { ConfirmView } from '../types/view'
import { ConfirmChangePage } from './ConfirmChangePage'

/**
 * 이 화면의 규칙을 확인하는 데 필요한 최소한의 데이터.
 *
 * Mock에 기대지 않고 여기 두는 이유는, `mocks/resultFlow.ts`가 화면을 눈으로 보려고
 * 만든 데이터라 언제든 바뀌기 때문이다. 충돌 항목을 하나로 줄이는 순간
 * "다 고르기 전에는 진행할 수 없다"를 검증할 수 없게 된다.
 *
 * 일부러 두 건을 둔다. 한 건짜리로는 "하나라도 안 골랐으면 막는다"와
 * "아무것도 안 골랐으면 막는다"가 같은 상황이 되어 구분되지 않는다.
 */
const TWO_CONFLICTS: ConfirmView = {
  rawInput: '다시 확인했는데 철거까지 해야 한대요.',
  conflicts: [
    {
      key: 'demolition_required',
      referenceId: 1,
      label: '철거 필요 여부',
      storedValue: '필요 없음',
      incomingValue: '필요함',
    },
    {
      key: 'restoration_scope',
      referenceId: 2,
      label: '원상복구 범위',
      storedValue: '일부만',
      incomingValue: '전체',
    },
  ],
}

/**
 * 앞뒤 화면을 실제 경로로 함께 등록한다. 히스토리가 어떻게 쌓이는지를 보는 테스트가
 * 있어서 이 화면만 띄워서는 확인할 수 없다. `/results`에서 넘어온 상황을 흉내 낸다.
 *
 * 기본은 Mock 으로 연다. 서버로 보내는 테스트는 `search` 를 비워 연다(아래 "서버").
 */
function renderWith(view: ConfirmView | null, search = '?mock=conflict') {
  const router = createMemoryRouter(
    [
      { path: '/', element: <p>진입 분기</p> },
      { path: '/login', element: <p>로그인</p> },
      { path: '/case', element: <p>현재 Case</p> },
      { path: '/results', element: <p>결과 입력</p> },
      { path: '/confirm', element: <ConfirmChangePage /> },
      { path: '/replan', element: <p>재계획 결과</p> },
    ],
    {
      initialEntries: ['/results', { pathname: '/confirm', search, state: view }],
      initialIndex: 1,
    },
  )

  render(<RouterProvider router={router} />)
  return router
}

const proceedButton = () => screen.getByRole('button', { name: /이대로 진행하기/ })

/**
 * 새 값 쪽을 고른다.
 *
 * 설명("이번에 말씀하신 내용")과 값이 붙은 `span` 두 개라 접근 이름이 띄어쓰기 없이
 * 이어진다. 그 모양에 기대면 마크업을 손볼 때마다 깨지므로 값으로만 찾는다.
 */
function chooseIncoming(value: string) {
  fireEvent.click(screen.getByRole('button', { name: new RegExp(value) }))
}

afterEach(() => {
  vi.useRealTimers()
})

/**
 * 되돌리기 API가 계약에서 빠져, 잘못 반영된 값을 되돌릴 수 있는 지점은 이 화면뿐이다.
 * 그래서 고르지 않은 항목이 하나라도 있으면 진행할 수 없어야 한다 —
 * 기본 선택을 두지 않는 것과 같은 이유다.
 */
describe('ConfirmChangePage', () => {
  it('서류에서 온 충돌 인용에는 중립적인 제목을 쓴다', () => {
    const rawInput = '확인한 임대차계약서: 원상복구는 일부만 필요합니다.'
    renderWith({ ...TWO_CONFLICTS, rawInput })

    expect(screen.getByRole('figure')).toHaveTextContent(/^새로 확인한 내용/)
    expect(screen.getByRole('figure')).toHaveTextContent(rawInput)
  })

  it('고르기 전에는 진행할 수 없다', () => {
    renderWith(TWO_CONFLICTS)

    expect(proceedButton()).toBeDisabled()
  })

  /** 여러 건이 한 화면에 오면 앞의 것만 고르고 넘어가려 한다 */
  it('일부만 고르면 아직 진행할 수 없다', () => {
    renderWith(TWO_CONFLICTS)

    chooseIncoming('필요함')

    expect(proceedButton()).toBeDisabled()
  })

  it('모든 항목을 고르면 진행할 수 있다', () => {
    renderWith(TWO_CONFLICTS)

    chooseIncoming('필요함')
    chooseIncoming('전체')

    expect(proceedButton()).toBeEnabled()
  })

  /** 고를 것이 없으면 이 화면의 존재 이유가 없다. 막다른 골목이 되지 않게 돌려보낸다 */
  it('충돌 항목이 비어 있으면 진입 분기로 돌려보낸다', async () => {
    renderWith({ rawInput: '철거해야 한대요.', conflicts: [] })

    expect(await screen.findByText('진입 분기')).toBeInTheDocument()
  })

  /** 고른 것을 보내는 동안 다시 누르면 같은 결정이 두 번 간다. 고르는 칸과 버튼을 함께 걷는다 */
  it('보내는 동안은 고르기 대신 처리 화면을 보여준다', () => {
    vi.useFakeTimers()
    renderWith(TWO_CONFLICTS)

    chooseIncoming('필요함')
    chooseIncoming('전체')
    fireEvent.click(proceedButton())

    expect(screen.getByRole('heading', { name: '고르신 내용을 반영하고 있어요' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /이대로 진행하기/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /필요함/ })).not.toBeInTheDocument()
  })

  /**
   * 확인을 마친 화면이 히스토리에 남아 있으면, 뒤로 가서 같은 결정을 다시 제출할 수 있다.
   * 표시만 어긋나는 다른 화면과 달리 이쪽은 서버 상태를 바꾸는 요청이라 피해가 다르다.
   *
   * `navigate`의 `replace` 옵션 하나로 막고 있어서, 파일을 옮기거나 고치는 과정에서
   * 조용히 사라지기 쉽다. 사라져도 화면은 그대로여서 뒤로가기를 해보지 않으면 모른다.
   */
  it('확인을 마치면 그 화면으로 뒤로 돌아갈 수 없다', async () => {
    // 클릭은 fireEvent로 한다. userEvent는 내부 지연이 있어 가짜 타이머와 맞물리면 멈춘다
    vi.useFakeTimers()
    const router = renderWith(TWO_CONFLICTS)

    chooseIncoming('필요함')
    chooseIncoming('전체')
    fireEvent.click(proceedButton())

    // 처리 중 지연을 흘려보낸다. act 안에서는 동기 타이머 함수를 쓴다
    await act(async () => {
      vi.runAllTimers()
    })
    expect(router.state.location.pathname).toBe('/replan')
    // 반영 결과가 고른 것을 반영했다고 말하게 하는 표시를 붙이고, Mock 표시는 그대로 이어간다
    const params = new URLSearchParams(router.state.location.search)
    expect(params.get('from')).toBe('confirm')
    expect(params.get('mock')).toBe('conflict')

    await act(async () => {
      await router.navigate(-1)
    })

    expect(router.state.location.pathname).toBe('/results')
  })

  /**
   * 라우터 state 없이 주소만으로 열었을 때 Mock으로 그려지는지 하나만 확인한다.
   * 리뷰어가 링크로 이 화면을 보는 경로라, 끊기면 화면을 볼 방법이 없다.
   *
   * 나머지 테스트는 state를 직접 태운다. 여기에 전부 기대면 Mock 데이터를 손볼 때마다
   * 관계없는 테스트가 함께 깨진다.
   */
  it('state 없이 열면 Mock으로 그린다', () => {
    renderWith(null)

    expect(proceedButton()).toBeInTheDocument()
  })
})


type Answer = () => Response

const json =
  (body: unknown, code = 200): Answer =>
  () =>
    new Response(JSON.stringify(body), { status: code })

const status =
  (code: number): Answer =>
  () =>
    new Response(null, { status: code })

const offline: Answer = () => {
  throw new TypeError('Failed to fetch')
}

/**
 * 결정 보내기와 결과 묻기에 각각 순서대로 답한다. 목록이 끝나면 마지막 답을 계속 준다.
 * 부른 순서가 아니라 주소로 답을 고른다(결과 입력 테스트와 같은 이유).
 */
function serve({ decide = [], judged = [] }: Partial<Record<'decide' | 'judged', Answer[]>>) {
  const calls = { decide: 0, judged: 0 }
  const pick = (kind: keyof typeof calls, answers: Answer[]) => {
    const answer = answers[Math.min(calls[kind], answers.length - 1)]
    calls[kind] += 1
    return answer()
  }

  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    void init
    return url.includes('/cases/results/decision') ? pick('decide', decide) : pick('judged', judged)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** 결정으로 보낸 본문들 */
function decisions(fetchMock: ReturnType<typeof serve>) {
  return fetchMock.mock.calls
    .filter(([url]) => url.includes('/cases/results/decision'))
    .map(([, init]) => JSON.parse(init?.body as string))
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
    new_tasks: null,
    ...overrides,
  }
}

const ACCEPTED = json({ case_history_id: 21 })
const UPDATED = json(
  judgedBody({
    result: 'UPDATED',
    changes: [],
    blocker: '철거 범위 미확인',
    next_action: { title: '철거 업체 견적 받기', reason: '', questions_to_ask: [] },
  }),
)
const failed = (code: CaseResultsSubmitResponse['recovery_action_code']) =>
  json(judgedBody({ result: 'FAILED', recovery_action_code: code }))
const INTERVAL_MS = 3_000

/** 가짜 시계를 돌리고, 그 사이 끝난 요청과 그에 따른 렌더까지 반영한다 */
async function advance(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

/** 첫 충돌은 새 값, 둘째는 지금 기록을 고르고 보낸다 */
function decide() {
  chooseIncoming('필요함')
  fireEvent.click(screen.getByRole('button', { name: /일부만/ }))
  fireEvent.click(proceedButton())
}

/** 보내고, 판단 결과를 한 번 받을 때까지 기다린다 */
async function decideAndWait() {
  decide()
  await advance(INTERVAL_MS)
}

/**
 * 고른 것이 실제로 서버에 가는 경로. 여기서 틀리면 사장님은 반영된 줄 아는데 기록은 그대로이거나,
 * 버린 값이 저장된다.
 */
describe('ConfirmChangePage — 서버', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('넘겨받은 충돌을 그리고 고를 수 있게 한다', () => {
    renderWith(TWO_CONFLICTS, '')

    chooseIncoming('필요함')

    expect(screen.getByRole('button', { name: /필요함/ })).toHaveAttribute('aria-pressed', 'true')
  })

  /** 없는 충돌을 지어내 보여주면 사장님이 기록에 없는 것을 고르게 된다 */
  it('넘겨받은 충돌 없이 열면 Mock 으로 채우지 않고 진입 분기로 돌려보낸다', async () => {
    renderWith(null, '')
    await advance()

    expect(screen.getByText('진입 분기')).toBeInTheDocument()
  })

  it('고른 쪽을 충돌마다 서버 번호로 보낸다', async () => {
    const fetchMock = serve({ decide: [ACCEPTED], judged: [UPDATED] })
    renderWith(TWO_CONFLICTS, '')

    await decideAndWait()

    expect(decisions(fetchMock)).toEqual([
      {
        decisions: [
          { conflict_reference_id: 1, side: 'PROPOSED' },
          { conflict_reference_id: 2, side: 'STORED' },
        ],
      },
    ])
  })

  /** 결과를 들고 가지 않고 번호로 다시 묻는다. 뒤로 가서 같은 결정을 또 보낼 수도 없다 */
  it('반영되면 판단 번호로 반영 결과에 가고, 확인 화면으로 돌아올 수 없다', async () => {
    serve({ decide: [ACCEPTED], judged: [UPDATED] })
    const router = renderWith(TWO_CONFLICTS, '')

    await decideAndWait()

    expect(router.state.location.pathname).toBe('/replan')
    expect(router.state.location.search).toBe('?history=21&from=confirm')
    await act(async () => {
      await router.navigate(-1)
    })
    expect(router.state.location.pathname).toBe('/results')
  })

  /** 고른 값은 저장됐고 물을 것이 남았다. 결과 입력이 그 질문을 받는다 */
  it('되물으면 결과 입력으로 간다', async () => {
    serve({
      decide: [ACCEPTED],
      judged: [json(judgedBody({ result: 'NEEDS_MORE_INFO', questions_for_user: ['철거는 전체인가요?'] }))],
    })
    const router = renderWith(TWO_CONFLICTS, '')

    await decideAndWait()

    expect(router.state.location.pathname).toBe('/results')
  })

  /** 실패하면 충돌이 그대로 남는다. 다시 해볼 수 있으면 고른 것을 지우지 않고 다시 보내게 한다 */
  it('다시 해볼 수 있는 실패면 고른 채로 머물고, 다시 보낼 수 있다', async () => {
    const fetchMock = serve({ decide: [ACCEPTED], judged: [failed('RETRY'), UPDATED] })
    const router = renderWith(TWO_CONFLICTS, '')

    await decideAndWait()

    expect(router.state.location.pathname).toBe('/confirm')
    expect(screen.getByRole('button', { name: /필요함/ })).toHaveAttribute('aria-pressed', 'true')
    expect(proceedButton()).toBeEnabled()

    fireEvent.click(proceedButton())
    await advance(INTERVAL_MS)
    expect(decisions(fetchMock)).toHaveLength(2)
    expect(router.state.location.pathname).toBe('/replan')
  })

  /** 고른 것으로 마지막 절차까지 마쳤다(#315). 마쳤다는 안내는 홈이 하고, 같은 선택을 다시 보내지 않는다 */
  it('등록된 절차를 다 마쳤으면 홈으로 가고 다시 보내지 않는다', async () => {
    const fetchMock = serve({ decide: [ACCEPTED], judged: [json(judgedBody({ result: 'PROCEDURES_COMPLETED', changes: [] }))] })
    const router = renderWith(TWO_CONFLICTS, '')

    await decideAndWait()

    expect(router.state.location.pathname).toBe('/case')
    await advance(INTERVAL_MS * 3)
    expect(decisions(fetchMock)).toHaveLength(1)
  })

  /** 같은 선택으로 다시 보내도 풀리지 않는 실패다. 홈 실패 카드가 이유를 안내한다 */
  it('그 밖의 실패면 홈으로 간다', async () => {
    serve({ decide: [ACCEPTED], judged: [failed('CONTACT_SUPPORT')] })
    const router = renderWith(TWO_CONFLICTS, '')

    await decideAndWait()

    expect(router.state.location.pathname).toBe('/case')
  })

  /** 이미 해결됐거나 직전 결정이 판단 중이다. 결과 입력이 지금 상태를 다시 물어 맞는 화면으로 보낸다 */
  it('결정을 받을 수 없다는 답이면 결과 입력으로 다시 들어간다', async () => {
    serve({ decide: [status(409)] })
    const router = renderWith(TWO_CONFLICTS, '')

    decide()
    await advance()

    expect(router.state.location.pathname).toBe('/results')
  })

  /** 서버가 받았는지 모른다. 이미 받았다면 다시 보낸 것은 409로 막혀 결과 입력이 정리한다 */
  it('보내다 끊기면 고른 채로 머물고, 다시 보낼 수 있다', async () => {
    serve({ decide: [offline] })
    const router = renderWith(TWO_CONFLICTS, '')

    decide()
    await advance()

    expect(router.state.location.pathname).toBe('/confirm')
    expect(proceedButton()).toBeEnabled()
  })

  /** 요청을 잘못 만든 것이라 다시 보내도 같다. 누를 수 있게 두면 같은 실패를 되풀이한다 */
  it('서버가 받지 않는 요청이면 다시 보낼 수 없고, 현재 상황으로 가는 길을 남긴다', async () => {
    serve({ decide: [status(422)] })
    const router = renderWith(TWO_CONFLICTS, '')

    decide()
    await advance()

    expect(proceedButton()).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '지금 상황 보기' }))
    expect(router.state.location.pathname).toBe('/case')
  })

  /** 접수는 됐고 판단이 아직이다. 다시 보내면 409라 버튼을 잠그고 홈에서 기다리게 한다 */
  it('끝내 결과를 못 받으면 다시 보낼 수 없고, 현재 상황으로 가는 길을 남긴다', async () => {
    serve({ decide: [ACCEPTED], judged: [json(judgedBody({ result: 'PENDING' }))] })
    renderWith(TWO_CONFLICTS, '')

    decide()
    await advance(10 * 60 * 1000 + INTERVAL_MS)

    expect(proceedButton()).toBeDisabled()
    expect(screen.getByRole('button', { name: '지금 상황 보기' })).toBeInTheDocument()
  })

  /** AI에는 없는 경로지만 오면, 앞에서 고른 것이 새 충돌에 섞이지 않게 처음부터 고른다 */
  it('또 충돌이 나면 새 충돌을 처음부터 고른다', async () => {
    serve({
      decide: [ACCEPTED],
      judged: [
        json(
          judgedBody({
            result: 'CONFLICT',
            raw_input: '다시 확인했는데 철거까지 해야 한대요.',
            conflicts: [{ id: 9, field: 'lease_status', stored_value: 'OWNED', proposed_value: 'LEASED_PAID' }],
          }),
        ),
      ],
    })
    const router = renderWith(TWO_CONFLICTS, '')

    await decideAndWait()

    expect(router.state.location.pathname).toBe('/confirm')
    expect(screen.queryByRole('button', { name: /필요함/ })).not.toBeInTheDocument()
    expect(proceedButton()).toBeDisabled()
  })

  it('로그인이 풀렸으면 로그인으로 간다', async () => {
    serve({ decide: [status(401)] })
    const router = renderWith(TWO_CONFLICTS, '')

    decide()
    await advance()

    expect(router.state.location.pathname).toBe('/login')
  })

  /** 떠난 화면이 몇 초 뒤 결과를 받아 사장님을 다른 곳으로 끌고 가면 안 된다 */
  it('기다리는 중에 화면을 떠나면 이동하지 않는다', async () => {
    serve({ decide: [ACCEPTED], judged: [UPDATED] })
    const router = renderWith(TWO_CONFLICTS, '')

    decide()
    await advance()
    await act(async () => {
      await router.navigate(-1)
    })
    await advance(INTERVAL_MS)

    expect(router.state.location.pathname).toBe('/results')
  })
})
