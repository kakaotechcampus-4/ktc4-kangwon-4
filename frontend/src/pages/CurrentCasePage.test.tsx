import { fireEvent, render, screen } from '@testing-library/react'
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

function mockCase(body: unknown, status = 200) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body, status)))
}

/** 처음엔 받아오고 그 뒤로는 실패한다. 갱신만 실패한 상태를 만들 때 쓴다 */
function mockThenFail(body: unknown) {
  let called = false
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() => {
      const first = !called
      called = true
      return Promise.resolve(first ? response(body) : response(null, 500))
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
      { path: '/start', element: <p>시작 화면</p> },
      { path: '/task', element: <p>할 일 상세 화면</p> },
      { path: '/results', element: <p>결과 입력 화면</p> },
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
  /** 홈은 하단 탭이 있는 화면이고, 지금 있는 곳이 홈이라는 것을 탭이 알려야 한다 */
  it('홈 탭이 고른 상태로 보인다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase(DONE)
    renderAt('/case')

    expect(await screen.findByRole('link', { name: '홈' })).toHaveAttribute('aria-current', 'page')
  })

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
  it('Case가 없으면 시작 화면으로 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase(envelope({ case: null }))
    renderAt('/case')

    expect(await screen.findByText('시작 화면')).toBeInTheDocument()
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
     * 어긋난 목록을 받아올 API 가 아직 없다. 보내봐야 `/confirm` 이 빈손으로 열려
     * `/` 로 튕긴다 — 눌리는데 아무 데도 못 가는 버튼이 없는 버튼보다 나쁘다.
     */
    it('확인하러 가는 길은 아직 내보내지 않는다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(envelope({ judgment_status: 'CONFLICT' }))
      renderAt('/case')

      await screen.findByRole('heading', { level: 2, name: '확인이 필요한 내용이 있어요' })
      expect(screen.queryByRole('link', { name: /확인/ })).not.toBeInTheDocument()
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
     * 실패 네 갈래를 전부 적는다. **이유마다 다른 버튼을 만들지 않는다는 것**이 여기서
     * 고정된다 — 지금은 재판단도 재입력도 보낼 곳이 없어서, 늘릴 수 있는 것은 "저장된
     * 상태를 다시 읽기" 하나뿐이다.
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

  describe('?mock=', () => {
    it('pending 이면 기다리는 화면을 보여준다', async () => {
      saveTokens('access-1', 'refresh-1')
      renderAt('/case?mock=pending')

      expect(
        await screen.findByRole('heading', { level: 2, name: '다음 할 일을 정하고 있어요' }),
      ).toBeInTheDocument()
    })

    it('judgment-conflict 면 확인이 필요한 화면을 보여준다', async () => {
      saveTokens('access-1', 'refresh-1')
      renderAt('/case?mock=judgment-conflict')

      expect(
        await screen.findByRole('heading', { level: 2, name: '확인이 필요한 내용이 있어요' }),
      ).toBeInTheDocument()
    })

    it('more-info 면 질문 화면을 보여준다', async () => {
      saveTokens('access-1', 'refresh-1')
      renderAt('/case?mock=more-info')

      expect(
        await screen.findByRole('heading', { level: 2, name: '이 내용을 알려주세요' }),
      ).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: '물어볼 내용 보기' })).not.toBeInTheDocument()
    })
  })
})
