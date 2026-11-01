import { fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { saveTokens } from '../lib/auth'
import type { CasesEnvelope, CaseResponse } from '../types/api'
import { TaskPage } from './TaskPage'

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

function done(questions: string[]) {
  return envelope({
    judgment_status: 'DONE',
    blocker: '원상복구 범위가 아직 확인되지 않았습니다.',
    next_action: {
      title: '임대인에게 원상복구 범위를 확인하세요.',
      reason: '철거가 필요한지 판단하려면 원상복구 범위를 먼저 알아야 합니다.',
      questions_to_ask: questions,
    },
  })
}

function mockCase(body: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body))))
}

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/task', element: <TaskPage /> },
      { path: '/case', element: <p>홈 화면</p> },
      { path: '/results', element: <p>결과 입력 화면</p> },
    ],
    { initialEntries: [path] },
  )

  render(<RouterProvider router={router} />)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('TaskPage', () => {
  it('할 일과 물어볼 말을 순서대로 보여준다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase(done(['어디까지 원래대로 돌려놔야 하나요?', '철거까지 해야 하나요?']))
    renderAt('/task')

    expect(
      await screen.findByRole('heading', { level: 1, name: '임대인에게 원상복구 범위를 확인하세요.' }),
    ).toBeInTheDocument()
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('어디까지 원래대로 돌려놔야 하나요?')
  })

  it('답을 들었어요를 누르면 결과 입력으로 간다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase(done(['철거까지 해야 하나요?']))
    renderAt('/task')

    fireEvent.click(await screen.findByRole('button', { name: '답을 들었어요' }))

    expect(await screen.findByText('결과 입력 화면')).toBeInTheDocument()
  })

  it('아직 못 물어봤으면 홈으로 돌아간다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase(done(['철거까지 해야 하나요?']))
    renderAt('/task')

    fireEvent.click(await screen.findByRole('button', { name: '아직 못 물어봤어요' }))

    expect(await screen.findByText('홈 화면')).toBeInTheDocument()
  })

  /** 물어볼 게 없는데 "답을 들었어요"라고 하면 사장님이 무엇의 답인지 헤맨다 */
  it('물어볼 말이 없으면 결과 알려주기만 둔다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase(done([]))
    renderAt('/task')

    expect(await screen.findByRole('button', { name: '결과 알려주기' })).toBeEnabled()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '아직 못 물어봤어요' })).not.toBeInTheDocument()
  })

  /** 할 일이 없는 상태는 홈이 안내한다. 여기서 빈 화면을 보여주지 않는다 */
  it('판단이 끝나지 않았으면 홈으로 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase(envelope({ judgment_status: 'PENDING' }))
    renderAt('/task')

    expect(await screen.findByText('홈 화면')).toBeInTheDocument()
  })
})
