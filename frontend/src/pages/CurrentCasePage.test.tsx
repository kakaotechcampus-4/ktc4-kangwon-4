import { act, fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TabLayout } from '../components/ui/TabLayout'
import { saveTokens } from '../lib/auth'
import type { CasesEnvelope, CaseResponse } from '../types/api'
import { CurrentCasePage } from './CurrentCasePage'

const SERVER_CASE: Partial<CaseResponse> = {
  id: 1,
  business_type: '분식집',
  franchise_status: false,
  employee_count: 3,
  lease_status: 'OWNED',
  planned_closure_date: '2026-11-30',
  restoration_scope: 'UNKNOWN',
  demolition_required: 'UNKNOWN',
}

/** 판단 칸만 바꿔 끼운다. 가게 칸은 어느 상태에서나 같아야 한다 */
function envelope(judgment: Partial<CasesEnvelope>) {
  return {
    case: SERVER_CASE,
    blocker: null,
    next_action: null,
    judgment_status: null,
    questions_for_user: null,
    recovery_action_code: null,
    requested_field_paths: null,
    ...judgment,
  }
}

const DONE = envelope({
  judgment_status: 'DONE',
  blocker: '원상복구 범위가 아직 확인되지 않았습니다.',
  next_action: {
    title: '임대인에게 원상복구 범위를 확인하세요.',
    reason: '철거가 필요한지 판단하려면 원상복구 범위를 먼저 알아야 합니다.',
    questions_to_ask: ['어디까지 원래대로 돌려놔야 하나요?', '철거까지 해야 하나요?'],
  },
})

function response(body: unknown, status = 200) {
  return new Response(status === 200 ? JSON.stringify(body) : null, { status })
}

/**
 * 홈은 Case 와 기록(띠)·로드맵(단계 카드)을 함께 부른다. 기록은 이 파일이 보는 것이 아니라 늘 빈 목록으로,
 * 로드맵은 늘 실패로 답한다(단계 카드는 조용히 "곧 보여드릴게요"). 띠가 채워지는 것은 `HomeBanner`·`LogPage`,
 * 단계 카드가 채워지는 것은 아래 "단계 카드" 테스트가 따로 본다
 */
const isLogs = (url: string) => url.includes('/cases/logs')
const isRoadmap = (url: string) => url.includes('/cases/roadmap')

function mockCase(body: unknown, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      isLogs(url) ? response({ logs: [] }) : isRoadmap(url) ? response(null, 500) : response(body, status),
    ),
  )
}

/** 처음엔 받아오고 그 뒤로는 실패한다. 갱신만 실패한 상태를 만들 때 쓴다 */
function mockThenFail(body: unknown) {
  let called = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (isLogs(url)) return response({ logs: [] })
      if (isRoadmap(url)) return response(null, 500)
      const first = !called
      called = true
      return first ? response(body) : response(null, 500)
    }),
  )
}

/** `routes.tsx`처럼 탭 틀 안에 둔다 */
function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      {
        element: <TabLayout />,
        children: [
          { path: '/case', element: <CurrentCasePage /> },
          { path: '/log', element: <p>기록 화면</p> },
        ],
      },
      { path: '/cases/new', element: <p>상황 진단</p> },
      { path: '/task', element: <p>할 일 상세 화면</p> },
      { path: '/results', element: <p>결과 입력 화면</p> },
      { path: '/login', element: <p>로그인 화면</p> },
      { path: '/confirm', element: <p>충돌 확인 화면</p> },
    ],
    { initialEntries: [path] },
  )

  render(<RouterProvider router={router} />)
}

const recheckButton = () => screen.findByRole('button', { name: '상태 다시 확인' })

afterEach(() => {
  vi.unstubAllGlobals()
})

/**
 * 사용자가 돌아올 곳이고, 이 제품에서 유일하게 "지금 상황"을 보여주는 화면이다.
 * 여기 값이 틀리면 사장님이 자기 가게 상황을 잘못 알고 다음 행동을 한다.
 */
describe('CurrentCasePage', () => {
  it('불러오는 동안 기다리라고 알린다', () => {
    saveTokens('access-1', 'refresh-1')
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))
    renderAt('/case')

    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  /** 시안처럼 리본이 해둔 일 띠를 누르면 작업 기록으로 간다 */
  it('리본이 해둔 일 띠를 누르면 기록으로 간다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase(DONE)
    renderAt('/case')

    fireEvent.click(await screen.findByRole('link', { name: /리본이 해둔 일/ }))

    expect(await screen.findByText('기록 화면')).toBeInTheDocument()
  })

  /** 주소로 직접 들어온 경우다. 빈 화면 대신 만들러 보낸다 */
  it('Case가 없으면 상황 진단으로 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase(envelope({ case: null }))
    renderAt('/case')

    expect(await screen.findByText('상황 진단')).toBeInTheDocument()
  })

  /** 빈 화면을 두면 사용자는 Case가 사라진 줄 안다 */
  it('한 번도 못 불러오면 다시 시도할 길을 준다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase(null, 500)
    renderAt('/case')

    expect(await screen.findByRole('button', { name: '다시 불러오기' })).toBeInTheDocument()
  })

  /**
   * 판단 상태마다 사장님이 할 수 있는 일이 다르다. 전에는 "다음 할 일이 없다" 하나로
   * 셋을 다 덮어서, 기다려야 하는 사람과 답해야 하는 사람이 같은 화면을 봤다.
   */
  describe('판단 상태', () => {
    it('판단 중이면 기다리는 안내를 보여준다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(envelope({ judgment_status: 'PENDING' }))
      renderAt('/case')

      expect(
        await screen.findByRole('heading', { level: 2, name: '다음 할 일을 정하고 있어요' }),
      ).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: '물어볼 내용 보기' })).not.toBeInTheDocument()
    })

    it('판단이 끝나면 할 일과 이유를 보여준다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(DONE)
      renderAt('/case')

      expect(
        await screen.findByRole('heading', { level: 2, name: '임대인에게 원상복구 범위를 확인하세요.' }),
      ).toBeInTheDocument()
      expect(
        screen.getByText('철거가 필요한지 판단하려면 원상복구 범위를 먼저 알아야 합니다.'),
      ).toBeInTheDocument()
      // 할 일과 이유는 AI가 정한 것이라 알린다. 카드가 좁아 짧은 표시만 보이고, 화면 읽기에는 문장 전체를 준다
      expect(screen.getByText('리본(AI)')).toBeInTheDocument()
      expect(screen.getByText(/리본\(AI\)이 정리한 안내예요/)).toHaveClass('sr-only')
    })

    it('물어볼 내용 보기를 누르면 할 일 상세로 간다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(DONE)
      renderAt('/case')

      fireEvent.click(await screen.findByRole('button', { name: '물어볼 내용 보기' }))

      expect(await screen.findByText('할 일 상세 화면')).toBeInTheDocument()
    })

    /** 물어볼 말이 없는 할 일에 "물어볼 내용 보기"라고 하면 거짓말이 된다 */
    it('물어볼 말이 없으면 자세히 보기로 부른다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase({ ...DONE, next_action: { ...DONE.next_action, questions_to_ask: [] } })
      renderAt('/case')

      expect(await screen.findByRole('button', { name: '자세히 보기' })).toBeEnabled()
    })

    it('되물을 것이 있으면 질문을 보여준다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(
        envelope({ judgment_status: 'NEEDS_MORE_INFO', questions_for_user: ['철거까지 하시나요?'] }),
      )
      renderAt('/case')

      expect(await screen.findByText('철거까지 하시나요?')).toBeInTheDocument()
    })

    it('되물을 것이 있으면 답하러 가기를 눌러 답 입력으로 간다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(
        envelope({ judgment_status: 'NEEDS_MORE_INFO', questions_for_user: ['철거까지 하시나요?'] }),
      )
      renderAt('/case')

      fireEvent.click(await screen.findByRole('button', { name: '답하러 가기' }))

      expect(await screen.findByText('결과 입력 화면')).toBeInTheDocument()
    })

    it('판단에 실패하면 무엇을 못 했는지 알린다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(envelope({ judgment_status: 'FAILED', recovery_action_code: 'RETRY' }))
      renderAt('/case')

      expect(
        await screen.findByRole('heading', { level: 2, name: '다음 할 일을 정하지 못했어요' }),
      ).toBeInTheDocument()
      // AI가 정한 안내가 없는 카드에는 고지를 붙이지 않는다
      expect(screen.queryByText(/리본\(AI\)이 정리한 안내예요/)).not.toBeInTheDocument()
    })

    /**
     * 사장님이 알려줘야 끝나는 실패다. 이유를 안 밝히면 "저희가 다시 해보겠습니다" 로 읽혀
     * 기다리면 되는 줄 알고 가만히 있게 된다. 어느 칸인지까지 말해야 움직일 수 있다.
     *
     * 다섯 갈래 중 여기만 사장님이 알려줘야 풀리는 실패라 머리 문구가 다르다.
     * 이 줄이 그것을 고정한다.
     */
    it('다시 알아야 할 것이 있으면 어느 칸인지까지 알린다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(
        envelope({
          judgment_status: 'FAILED',
          recovery_action_code: 'RESUBMIT_INPUT',
          requested_field_paths: ['restoration_scope', 'demolition_required'],
        }),
      )
      renderAt('/case')

      expect(
        await screen.findByRole('heading', { level: 1, name: '확인하실 일이 있어요' }),
      ).toBeInTheDocument()
      expect(screen.getByText(/원상복구 범위, 철거 필요 여부/)).toBeInTheDocument()
    })

    /** 아는 것만 적고 그것이 전부인 척하면 사장님이 나머지를 영영 모른 채로 남는다 */
    it('일부만 알아봤으면 그것이 전부인 것처럼 말하지 않는다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(
        envelope({
          judgment_status: 'FAILED',
          recovery_action_code: 'RESUBMIT_INPUT',
          requested_field_paths: ['restoration_scope', 'closure_subsidy'],
        }),
      )
      renderAt('/case')

      expect(await screen.findByText(/원상복구 범위 등/)).toBeInTheDocument()
    })

    /** 더 알려주시면 풀리는 실패다. 같은 길로 다시 보내면 서버가 다시 판단한다 */
    it('다시 알아야 할 것이 있으면 다시 알려주기를 눌러 결과 입력으로 간다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(
        envelope({
          judgment_status: 'FAILED',
          recovery_action_code: 'RESUBMIT_INPUT',
          requested_field_paths: ['restoration_scope'],
        }),
      )
      renderAt('/case')

      fireEvent.click(await screen.findByRole('button', { name: '다시 알려주기' }))

      expect(await screen.findByText('결과 입력 화면')).toBeInTheDocument()
    })

    /** 더 적어도 같은 실패가 돌아온다(#57). 누르면 되는 것처럼 보이는 버튼을 달지 않는다 */
    it('사장님이 알려줘서 풀리는 실패가 아니면 다시 알려주기를 달지 않는다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(envelope({ judgment_status: 'FAILED', recovery_action_code: 'CONTACT_SUPPORT' }))
      renderAt('/case')

      await screen.findByRole('heading', { level: 1 })
      expect(screen.queryByRole('button', { name: '다시 알려주기' })).not.toBeInTheDocument()
    })

    /**
     * 서버가 "할 수 있는 것이 없다" 고 **말한** 경우와 우리가 그 말을 **못 알아들은** 경우는
     * 다르다. 같은 문구로 덮으면 계약이 어긋난 사실이 화면 뒤로 숨는다.
     */
    it('이유를 모를 때 할 수 있는 것이 없다고 단정하지 않는다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(envelope({ judgment_status: 'FAILED' }))
      renderAt('/case')

      await screen.findByRole('heading', { level: 2, name: '다음 할 일을 정하지 못했어요' })
      expect(screen.queryByText(/더 해 보실 수 있는 것이 없어요/)).not.toBeInTheDocument()
    })

    /**
     * 사장님이 답해야 끝나는 상태다. 전에는 모르는 값이라 "불러오지 못했어요" 가 떠서,
     * 할 일이 있는 사람이 기다리라는 말을 듣고 있었다(#66).
     */
    it('확인이 필요하면 무엇을 해야 하는지 알린다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(envelope({ judgment_status: 'CONFLICT' }))
      renderAt('/case')

      expect(
        await screen.findByRole('heading', { level: 2, name: '확인이 필요한 내용이 있어요' }),
      ).toBeInTheDocument()
    })

    /**
     * 확인 화면은 어긋난 목록을 넘겨받아야 열린다. 목록은 결과 입력이 `GET /cases/results` 로 받아 넘긴다.
     * 충돌 선택이 실패한 뒤에도 서버는 `CONFLICT` 를 줘서, 이 길이 없으면 홈에서 풀 수 없다(#196)
     */
    it('확인이 필요하면 확인하러 가기로 결과 입력에 보낸다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(envelope({ judgment_status: 'CONFLICT' }))
      renderAt('/case')

      fireEvent.click(await screen.findByRole('button', { name: '확인하러 가기' }))

      expect(await screen.findByText('결과 입력 화면')).toBeInTheDocument()
    })

    /** Mock 은 서버가 없어 결과 입력이 확인 화면으로 넘겨 주지 못한다. 확인 화면은 Mock 이면 예시 충돌로 열린다 */
    it('Mock 에서는 확인하러 가기가 확인 화면으로 바로 간다', async () => {
      saveTokens('access-1', 'refresh-1')
      vi.stubGlobal('fetch', vi.fn())
      renderAt('/case?mock=judgment-conflict')

      fireEvent.click(await screen.findByRole('button', { name: '확인하러 가기' }))

      expect(await screen.findByText('충돌 확인 화면')).toBeInTheDocument()
    })

    /**
     * 서버가 상태를 늘리면 바로 겪는다 — `CONFLICT` 가 그렇게 늘었고, AI 가 따로 내는
     * `SAFE_FAILURE` 도 BE 가 접기를 그만두면 그대로 온다.
     * 모르는 값을 "정보 부족"으로 바꿔 보여주면, 서버가 틀린 것을 사장님 탓으로 읽는다.
     */
    it('모르는 판단 상태는 정보 부족으로 바꿔 말하지 않는다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(envelope({ judgment_status: 'SAFE_FAILURE' as never }))
      renderAt('/case')

      expect(
        await screen.findByRole('heading', { level: 2, name: '판단 내용을 불러오지 못했어요' }),
      ).toBeInTheDocument()
    })

    /**
     * 할 일이 없다고 버튼까지 사라지면 사장님은 화면만 보다 나가게 된다.
     *
     * 실패 갈래를 전부 적는다. 주 버튼(다시 알려주기 · 다시 판단하기)이 있든 없든
     * "저장된 상태를 다시 읽기"는 늘 남는다는 것이 여기서 고정된다.
     */
    it.each([
      ['PENDING', envelope({ judgment_status: 'PENDING' })],
      ['실패 · 다시 해볼 수 있음', envelope({ judgment_status: 'FAILED', recovery_action_code: 'RETRY' })],
      [
        '실패 · 더 알아야 함',
        envelope({
          judgment_status: 'FAILED',
          recovery_action_code: 'RESUBMIT_INPUT',
          requested_field_paths: ['restoration_scope'],
        }),
      ],
      [
        '실패 · 서비스가 볼 것',
        envelope({ judgment_status: 'FAILED', recovery_action_code: 'CONTACT_SUPPORT' }),
      ],
      ['실패 · 할 수 있는 것 없음', envelope({ judgment_status: 'FAILED', recovery_action_code: 'NONE' })],
      ['실패 · 이유를 모름', envelope({ judgment_status: 'FAILED' })],
      ['CONFLICT', envelope({ judgment_status: 'CONFLICT' })],
      ['모르는 상태', envelope({ judgment_status: 'SAFE_FAILURE' as never })],
      [
        'NEEDS_MORE_INFO',
        envelope({ judgment_status: 'NEEDS_MORE_INFO', questions_for_user: ['철거까지 하시나요?'] }),
      ],
    ])('%s 에서도 누를 것이 남는다', async (_name, body) => {
      saveTokens('access-1', 'refresh-1')
      mockCase(body)
      renderAt('/case')

      expect(await recheckButton()).toBeEnabled()
    })
  })

  /**
   * 서버가 "다시 해볼 수 있다"고 한 실패를 다시 판단해 달라고 맡긴다(#196, `POST /cases/retry`).
   * 맡긴 뒤에는 지금 상황을 다시 물어 그대로 그린다 — 기다리는 자리를 따로 만들지 않는다.
   */
  describe('다시 판단하기', () => {
    const RETRYABLE = envelope({ judgment_status: 'FAILED', recovery_action_code: 'RETRY' })
    const PENDING = envelope({ judgment_status: 'PENDING' })
    const retryButton = () => screen.findByRole('button', { name: '다시 판단하기' })
    const HANG = Symbol('답하지 않음')

    /**
     * `GET /cases` 는 차례대로 `cases` 를 돌려주고(마지막 것을 계속), `POST /cases/retry` 는 `retry` 로 답한다.
     * 기록·로드맵은 위 `mockCase` 와 같다
     */
    function serve({ cases, retry }: { cases: unknown[]; retry: Response | Promise<Response> }) {
      let index = 0
      const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
        if (isLogs(url)) return response({ logs: [] })
        if (isRoadmap(url)) return response(null, 500)
        if (url.includes('/cases/retry') && init?.method === 'POST') return retry
        const body = cases[Math.min(index, cases.length - 1)]
        index += 1
        // `HANG` 이면 답하지 않는다. 묻는 중인 상태를 만들 때 쓴다
        return body === HANG ? new Promise<Response>(() => {}) : response(body)
      })
      vi.stubGlobal('fetch', fetchMock)
      return fetchMock
    }

    const retryCalls = (fetchMock: ReturnType<typeof serve>) =>
      fetchMock.mock.calls.filter(([url]) => url.includes('/cases/retry'))

    it('다시 해볼 수 있는 실패에만 버튼을 단다', async () => {
      saveTokens('access-1', 'refresh-1')
      serve({ cases: [RETRYABLE], retry: response({ case_history_id: 3 }) })
      renderAt('/case')

      expect(await retryButton()).toBeEnabled()
    })

    it.each([
      ['더 알아야 함', envelope({ judgment_status: 'FAILED', recovery_action_code: 'RESUBMIT_INPUT', requested_field_paths: [] })],
      ['서비스가 볼 것', envelope({ judgment_status: 'FAILED', recovery_action_code: 'CONTACT_SUPPORT' })],
      ['할 수 있는 것 없음', envelope({ judgment_status: 'FAILED', recovery_action_code: 'NONE' })],
      ['이유를 모름', envelope({ judgment_status: 'FAILED' })],
    ])('실패 · %s 에는 달지 않는다', async (_name, body) => {
      saveTokens('access-1', 'refresh-1')
      mockCase(body)
      renderAt('/case')

      await recheckButton()
      expect(screen.queryByRole('button', { name: '다시 판단하기' })).not.toBeInTheDocument()
    })

    it('맡기면 다시 물어 판단 중 화면으로 바뀐다', async () => {
      saveTokens('access-1', 'refresh-1')
      const fetchMock = serve({ cases: [RETRYABLE, PENDING], retry: response({ case_history_id: 3 }) })
      renderAt('/case')

      fireEvent.click(await retryButton())

      expect(await screen.findByRole('heading', { level: 1, name: '지금은 리본이 일하고 있어요' })).toBeInTheDocument()
      expect(retryCalls(fetchMock)).toHaveLength(1)
    })

    /** 두 번 맡기면 서버가 하나만 받고 나머지를 409 로 돌려준다. 화면이 먼저 막는다 */
    it('맡기는 동안 버튼을 잠근다', async () => {
      saveTokens('access-1', 'refresh-1')
      const fetchMock = serve({ cases: [RETRYABLE], retry: new Promise<Response>(() => {}) })
      renderAt('/case')

      const button = await retryButton()
      fireEvent.click(button)
      fireEvent.click(button)

      expect(button).toBeDisabled()
      expect(retryCalls(fetchMock)).toHaveLength(1)
    })

    /** 결과 알려주기의 실패는 서버가 다시 돌리지 않는다. 눌러도 아무 일 없는 버튼으로 두지 않는다 */
    it('거절됐는데 다시 물어도 같은 실패면 그렇다고 알리고 버튼을 잠근다', async () => {
      saveTokens('access-1', 'refresh-1')
      serve({ cases: [RETRYABLE], retry: response(null, 409) })
      renderAt('/case')

      fireEvent.click(await retryButton())

      expect(await screen.findByText('이 실패는 여기서 다시 판단할 수 없어요.')).toBeInTheDocument()
      expect(await retryButton()).toBeDisabled()
    })

    /** 두 번 눌렀거나 그사이 다른 곳에서 맡겼다. 지금 상황을 그리면 된다 */
    it('거절됐어도 다시 물어 상황이 바뀌었으면 그 화면을 그린다', async () => {
      saveTokens('access-1', 'refresh-1')
      serve({ cases: [RETRYABLE, PENDING], retry: response(null, 409) })
      renderAt('/case')

      fireEvent.click(await retryButton())

      expect(await screen.findByRole('heading', { level: 1, name: '지금은 리본이 일하고 있어요' })).toBeInTheDocument()
    })

    /** 응답만 끊겼을 수 있다. 실패 카드는 저절로 다시 묻지 않아서, 묻지 않으면 판단 중에도 실패 카드가 남는다 */
    it.each([
      ['응답이 끊김', response(null, 500)],
      ['받았다는데 번호를 못 읽음', response({})],
    ])('%s 이어도 다시 물어, 서버가 받았으면 판단 중 화면을 그린다', async (_name, retry) => {
      saveTokens('access-1', 'refresh-1')
      serve({ cases: [RETRYABLE, PENDING], retry })
      renderAt('/case')

      fireEvent.click(await retryButton())

      expect(await screen.findByRole('heading', { level: 1, name: '지금은 리본이 일하고 있어요' })).toBeInTheDocument()
    })

    /** 묻는 중에 맡기면 뒤따르는 다시 묻기가 무시되고, 맡긴 직후 또 누르면 409 다 */
    it('지금 상황을 묻는 중에는 누를 수 없다', async () => {
      saveTokens('access-1', 'refresh-1')
      const fetchMock = serve({ cases: [RETRYABLE, HANG], retry: response({ case_history_id: 3 }) })
      renderAt('/case')

      fireEvent.click(await recheckButton())

      expect(await retryButton()).toBeDisabled()
      fireEvent.click(await retryButton())
      expect(retryCalls(fetchMock)).toHaveLength(0)
    })

    it('맡긴 뒤 다시 묻는 동안 또 누를 수 없다', async () => {
      saveTokens('access-1', 'refresh-1')
      const fetchMock = serve({ cases: [RETRYABLE, HANG], retry: response({ case_history_id: 3 }) })
      renderAt('/case')

      fireEvent.click(await retryButton())
      await vi.waitFor(() => expect(retryCalls(fetchMock)).toHaveLength(1))

      fireEvent.click(await retryButton())
      expect(await retryButton()).toBeDisabled()
      expect(retryCalls(fetchMock)).toHaveLength(1)
    })

    it('맡기는 동안 수동 조회를 잠그고 접수 뒤 새 상태를 보여준다', async () => {
      saveTokens('access-1', 'refresh-1')
      let resolveRetry!: (response: Response) => void
      let resolveRefresh!: (response: Response) => void
      const retryResponse = new Promise<Response>((resolve) => { resolveRetry = resolve })
      const refreshResponse = new Promise<Response>((resolve) => { resolveRefresh = resolve })
      let reads = 0
      let accepted = false
      vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
        if (isLogs(url)) return response({ logs: [] })
        if (isRoadmap(url)) return response(null, 500)
        if (url.includes('/cases/retry') && init?.method === 'POST') return retryResponse
        reads += 1
        if (reads === 1) return response(RETRYABLE)
        if (!accepted) return refreshResponse
        return response(PENDING)
      }))
      renderAt('/case')
      fireEvent.click(await retryButton())
      const recheck = await recheckButton()
      expect(recheck).toBeDisabled()
      fireEvent.click(recheck)
      expect(reads).toBe(1)
      await act(async () => {
        accepted = true
        resolveRetry(response({ case_history_id: 3 }))
      })
      await act(async () => { resolveRefresh(response(RETRYABLE)) })
      expect(await screen.findByRole('heading', { level: 1, name: '지금은 리본이 일하고 있어요' })).toBeInTheDocument()
    })

    it.each([200, 401, 409, 500])('떠난 홈의 늦은 재판단 응답(%i)은 재조회·이동을 만들지 않는다', async (status) => {
      saveTokens('access-1', 'refresh-1')
      let resolveRetry!: (response: Response) => void
      const retry = new Promise<Response>((resolve) => { resolveRetry = resolve })
      const fetchMock = serve({ cases: [RETRYABLE], retry })
      renderAt('/case')
      fireEvent.click(await retryButton())
      fireEvent.click(screen.getByRole('link', { name: /리본이 해둔 일/ }))
      expect(await screen.findByText('기록 화면')).toBeInTheDocument()
      await act(async () => { resolveRetry(response({ case_history_id: 3 }, status)) })
      expect(screen.queryByText('로그인 화면')).not.toBeInTheDocument()
      expect(screen.getByText('기록 화면')).toBeInTheDocument()
      expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/cases'))).toHaveLength(1)
    })

    it('맡기지 못하면 알리고 다시 누를 수 있게 둔다', async () => {
      saveTokens('access-1', 'refresh-1')
      serve({ cases: [RETRYABLE], retry: response(null, 500) })
      renderAt('/case')

      fireEvent.click(await retryButton())

      expect(await screen.findByText(/다시 판단을 요청하지 못했어요/)).toBeInTheDocument()
      expect(await retryButton()).toBeEnabled()
    })

    it('로그인이 풀렸으면 로그인으로 보낸다', async () => {
      saveTokens('access-1', 'refresh-1')
      serve({ cases: [RETRYABLE], retry: response(null, 401) })
      renderAt('/case')

      fireEvent.click(await retryButton())

      expect(await screen.findByText('로그인 화면')).toBeInTheDocument()
    })

    it('Mock 에서는 서버를 부르지 않고 판단 중 화면으로 넘어간다', async () => {
      saveTokens('access-1', 'refresh-1')
      const fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)
      renderAt('/case?mock=judgment-failed')

      fireEvent.click(await retryButton())

      expect(await screen.findByRole('heading', { level: 1, name: '지금은 리본이 일하고 있어요' })).toBeInTheDocument()
      expect(fetchMock).not.toHaveBeenCalled()
    })
  })

  /**
   * 갱신에 실패하면 지금 들고 있는 판단이 최신인지 알 수 없다. 그 상태로 결과를 보내면
   * 사장님은 이미 지난 할 일에 대해 답하게 된다. 그렇다고 지우면 적어낸 내용이 날아간
   * 줄 알기 때문에, 남겨두고 제출만 막는다.
   */
  describe('갱신에 실패했을 때', () => {
    async function renderStale() {
      saveTokens('access-1', 'refresh-1')
      mockThenFail(DONE)
      renderAt('/case')

      fireEvent.click(await recheckButton())
      return screen.findByText(/최신 상태를 확인하지 못했어요/)
    }

    it('마지막으로 받은 할 일을 남긴다', async () => {
      await renderStale()

      expect(
        screen.getByRole('heading', { level: 2, name: '임대인에게 원상복구 범위를 확인하세요.' }),
      ).toBeInTheDocument()
    })

    it('할 일 상세로 가는 길을 잠근다', async () => {
      await renderStale()

      expect(screen.getByRole('button', { name: '물어볼 내용 보기' })).toBeDisabled()
      expect(screen.getByText('최신 상태를 확인한 뒤에 볼 수 있어요')).toBeInTheDocument()
    })

    /** 조회까지 막으면 회복할 길이 없어진다 */
    it('다시 확인은 계속 누를 수 있다', async () => {
      await renderStale()

      expect(await recheckButton()).toBeEnabled()
    })
  })

  /**
   * 폐업 정리를 마친 가게(#167). 완료돼도 마지막 판단 기록이 남아 있어서, 판단부터 보면 이미 마친
   * 가게에 할 일과 [결과 알려주기]가 다시 뜨고 누르면 409 다.
   */
  describe('폐업을 마쳤을 때', () => {
    const COMPLETED_CASE = { ...SERVER_CASE, case_status: 'COMPLETED', completed_at: '2026-11-04T10:00:00' } as CaseResponse

    it('할 일 대신 마쳤다고 알린다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase({ ...DONE, case: COMPLETED_CASE })
      renderAt('/case')

      expect(await screen.findByRole('heading', { level: 1, name: '폐업 정리를 모두 마쳤어요' })).toBeInTheDocument()
      expect(screen.getByRole('heading', { level: 2, name: '수고 많으셨어요, 사장님' })).toBeInTheDocument()
      expect(screen.queryByRole('heading', { level: 2, name: '임대인에게 원상복구 범위를 확인하세요.' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: '물어볼 내용 보기' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: '상태 다시 확인' })).not.toBeInTheDocument()
    })

    /** 되물을 것이 남은 판단이어도, 완료된 가게는 답을 받지 않는다(409) */
    it('남은 판단이 질문이어도 답하러 가기를 달지 않는다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(envelope({ case: COMPLETED_CASE, judgment_status: 'NEEDS_MORE_INFO', questions_for_user: ['철거까지 해야 하나요?'] }))
      renderAt('/case')

      expect(await screen.findByRole('heading', { level: 1, name: '폐업 정리를 모두 마쳤어요' })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: '답하러 가기' })).not.toBeInTheDocument()
    })

    it('전체 기록 보기를 누르면 기록으로 간다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase({ ...DONE, case: COMPLETED_CASE })
      renderAt('/case')

      fireEvent.click(await screen.findByRole('button', { name: '전체 기록 보기' }))

      expect(await screen.findByText('기록 화면')).toBeInTheDocument()
    })
  })

  /** 단계는 서버(`GET /cases/roadmap` `current_stage`, #179)가 정한다. 홈이 할 일 상태로 짐작하지 않는다 */
  describe('단계 카드', () => {
    const roadmapWithStage = {
      supported: true,
      unsupported_reason: null,
      current_stage: 2,
      stages: [{ stage: 2, title: '원상복구·철거', tasks: [] }],
    }

    it('로드맵이 준 지금 단계를 카드 제목에 쓴다', async () => {
      saveTokens('access-1', 'refresh-1')
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) =>
          isLogs(url) ? response({ logs: [] }) : isRoadmap(url) ? response(roadmapWithStage) : response(DONE),
        ),
      )
      renderAt('/case')

      expect(await screen.findByRole('link', { name: /챙길 일이 남은 단계: 원상복구·철거/ })).toBeInTheDocument()
    })

    /** 단계 카드는 덤이다. 로드맵 하나 못 받았다고 홈에 오류를 띄우면 할 일 카드가 가려진다 */
    it('로드맵을 불러오지 못해도 알리지 않고 할 일 카드를 그대로 보여준다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(DONE)
      renderAt('/case')

      expect(
        await screen.findByRole('heading', { level: 2, name: '임대인에게 원상복구 범위를 확인하세요.' }),
      ).toBeInTheDocument()
      expect(await screen.findByText('단계 정보는 곧 보여드릴게요')).toBeInTheDocument()
      expect(screen.queryByText(/불러오지 못했어요/)).not.toBeInTheDocument()
    })
  })

  /** Mock 은 Preview 에서 화면을 보려고 둔다. 서버를 부르지 않고 그 키의 화면이 그려지는지만 본다(화면당 하나) */
  describe('?mock=', () => {
    it('?mock= 이면 서버를 부르지 않고 그 키의 화면을 그린다', async () => {
      saveTokens('access-1', 'refresh-1')
      const fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)
      renderAt('/case?mock=completed')

      expect(await screen.findByRole('heading', { level: 1, name: '폐업 정리를 모두 마쳤어요' })).toBeInTheDocument()
      expect(fetchMock).not.toHaveBeenCalled()
    })
  })
})
