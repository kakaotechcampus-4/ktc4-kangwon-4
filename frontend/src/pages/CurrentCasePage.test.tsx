import { fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

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
    ...judgment,
  }
}

const DONE = envelope({
  judgment_status: 'DONE',
  blocker: '원상복구 범위가 아직 확인되지 않았습니다.',
  next_action: '임대인에게 원상복구 범위를 확인하세요.',
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

const recheckButton = () => screen.findByRole('button', { name: '상태 다시 확인' })

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
    mockCase(DONE)
    renderAt('/case')

    expect(await screen.findByText('분식집')).toBeInTheDocument()
    expect(screen.getByText('3명')).toBeInTheDocument()
    expect(screen.getByText('자가')).toBeInTheDocument()
  })

  /** 사장님이 직접 적어 넣은 값인데 지금까지 어디에도 보이지 않았다 */
  it('폐업 예정일을 보여준다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase(DONE)
    renderAt('/case')

    expect(await screen.findByText('2026.11.30')).toBeInTheDocument()
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

      expect(await screen.findByText('다음 할 일을 정하고 있어요.')).toBeInTheDocument()
      expect(screen.queryByRole('heading', { name: '지금 할 일' })).not.toBeInTheDocument()
    })

    it('판단이 끝나면 할 일과 막힌 것을 보여준다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(DONE)
      renderAt('/case')

      expect(await screen.findByRole('heading', { name: '지금 할 일' })).toBeInTheDocument()
      expect(screen.getByText('임대인에게 원상복구 범위를 확인하세요.')).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: '막혀 있는 것' })).toBeInTheDocument()
    })

    it('되물을 것이 있으면 질문을 보여준다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(
        envelope({ judgment_status: 'NEEDS_MORE_INFO', questions_for_user: ['철거까지 하시나요?'] }),
      )
      renderAt('/case')

      expect(await screen.findByText('철거까지 하시나요?')).toBeInTheDocument()
    })

    it('판단에 실패하면 가게 정보는 남기고 안내만 바꾼다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(envelope({ judgment_status: 'FAILED' }))
      renderAt('/case')

      expect(await screen.findByText('다음 할 일을 정하지 못했어요.')).toBeInTheDocument()
      expect(screen.getByText('분식집')).toBeInTheDocument()
    })

    /**
     * 서버가 상태를 늘리면 바로 겪는다 — BE 가 `CONFLICT` 추가를 건의해 둔 상태다.
     * 모르는 값을 "정보 부족"으로 바꿔 보여주면, 서버가 틀린 것을 사장님 탓으로 읽는다.
     */
    it('모르는 판단 상태는 정보 부족으로 바꿔 말하지 않는다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockCase(envelope({ judgment_status: 'CONFLICT' as never }))
      renderAt('/case')

      expect(await screen.findByText('판단 내용을 불러오지 못했어요.')).toBeInTheDocument()
    })

    /** 할 일이 없다고 버튼까지 사라지면 사장님은 화면만 보다 나가게 된다 */
    it.each([
      ['PENDING', envelope({ judgment_status: 'PENDING' })],
      ['FAILED', envelope({ judgment_status: 'FAILED' })],
      ['모르는 상태', envelope({ judgment_status: 'CONFLICT' as never })],
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
      return screen.findByText('최신 상태를 확인하지 못했어요.')
    }

    it('마지막으로 받은 가게 정보를 남긴다', async () => {
      await renderStale()

      expect(screen.getByText('분식집')).toBeInTheDocument()
    })

    it('결과 알려주기를 잠근다', async () => {
      await renderStale()

      expect(screen.queryByRole('link', { name: '결과 알려주기' })).not.toBeInTheDocument()
      expect(screen.getByText('최신 상태를 확인한 뒤에 알려주실 수 있어요')).toBeInTheDocument()
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

      expect(await screen.findByText('다음 할 일을 정하고 있어요.')).toBeInTheDocument()
    })

    it('more-info 면 질문 화면을 보여준다', async () => {
      saveTokens('access-1', 'refresh-1')
      renderAt('/case?mock=more-info')

      expect(await screen.findByRole('heading', { name: '추가 확인 필요' })).toBeInTheDocument()
      expect(screen.queryByRole('heading', { name: '지금 할 일' })).not.toBeInTheDocument()
    })
  })
})
