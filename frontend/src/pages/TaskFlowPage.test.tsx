import { act, fireEvent, render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { RoadmapTaskView } from '../types/view'
import { CheckFlow, ClosureReportFlow, SupportResultFlow, TaskFlowPage } from './TaskFlowPage'

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/roadmap', element: <p>로드맵</p> },
      { path: '/roadmap/:taskId', element: <TaskFlowPage /> },
      { path: '/docs', element: <p>서류함</p> },
      { path: '/docs/check', element: <p>서류 점검</p> },
      { path: '/results', element: <p>결과 입력</p> },
      { path: '/login', element: <p>로그인</p> },
    ],
    { initialEntries: [path] },
  )
  render(<RouterProvider router={router} />)
  return router
}

/** 실서버 경로의 장면 하나만 띄운다. 로드맵 조회 API 전이라 할 일 화면으로는 실서버에 닿을 수 없다 */
function renderFlow(element: ReactElement) {
  const router = createMemoryRouter(
    [
      { path: '/flow', element },
      { path: '/login', element: <p>로그인</p> },
    ],
    { initialEntries: ['/flow'] },
  )
  render(<RouterProvider router={router} />)
  return router
}

const checklistTask: RoadmapTaskView = { id: 'dispose_stock', title: '재고·장비 처분', kind: 'CHECKLIST', status: 'NOT_STARTED' }
const supportTask: RoadmapTaskView = {
  id: 'support_approval',
  title: '1차 적격심사 결과 확인',
  kind: 'CASE_FACT',
  status: 'NEEDS_CONFIRMATION',
}

type Answer = () => Response | Promise<Response>
const json = (body: unknown): Answer => () => new Response(JSON.stringify(body), { status: 200 })
const status = (code: number): Answer => () => new Response(null, { status: code })
const hanging: Answer = () => new Promise(() => {})

function serve(answer: Answer) {
  const fetchMock = vi.fn(async () => answer())
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('TaskFlowPage — 장면 고르기 (Mock)', () => {
  it('체크 항목은 다 했어요로 기록하고 완료 취소로 되돌릴 수 있다', () => {
    renderAt('/roadmap/dispose_stock?mock=roadmap')

    fireEvent.click(screen.getByRole('button', { name: '다 했어요' }))

    expect(screen.getByText('마치셨다고 기록했어요')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '완료 취소하기' }))
    expect(screen.queryByText('마치셨다고 기록했어요')).not.toBeInTheDocument()
  })

  /** 사진은 서류함에 있어야 정산 점검에 쓰인다. 체크만 하고 끝나면 점검에서 빠진 서류가 된다 */
  it('서류가 필요한 할 일은 서류함에 올리는 길을 먼저 둔다', () => {
    const router = renderAt('/roadmap/before_photo?mock=roadmap')

    fireEvent.click(screen.getByRole('button', { name: '서류함에 올리기' }))

    expect(router.state.location.pathname).toBe('/docs')
    expect(router.state.location.search).toBe('?mock=roadmap')
  })

  /** 공식 절차는 끝났는지를 판단이 정한다. 체크 버튼을 두면 사장님이 대신 완료한다 */
  it('공식 절차는 체크 없이 결과 알려주기로 보낸다', () => {
    const router = renderAt('/roadmap/restoration?mock=roadmap')

    expect(screen.queryByRole('button', { name: '다 했어요' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '결과 알려주기' }))
    expect(router.state.location.pathname).toBe('/results')
  })

  it('서류 점검 할 일은 점검 화면으로 보낸다', () => {
    const router = renderAt('/roadmap/document_check?mock=roadmap')

    expect(router.state.location.pathname).toBe('/docs/check')
  })

  /** 해당 없는 할 일과 없는 할 일은 열 것이 없다. 빈 화면 대신 순서로 돌려보낸다 */
  it('해당 없거나 없는 할 일이면 로드맵으로 돌려보낸다', () => {
    expect(renderAt('/roadmap/check_loan?mock=roadmap').state.location.pathname).toBe('/roadmap')
  })

  it('없는 할 일 번호도 로드맵으로 돌려보낸다', () => {
    expect(renderAt('/roadmap/no_such_task?mock=roadmap').state.location.pathname).toBe('/roadmap')
  })

  it('로드맵 조회 API 전에는 준비 중이라고 알린다', () => {
    renderAt('/roadmap/dispose_stock')

    expect(screen.getByText('할 일 화면은 준비 중이에요.')).toBeInTheDocument()
  })
})

/**
 * 실서버 저장(#149, 머지됨). 저장이 끝나기 전에 체크를 바꿔 보여주면, 저장이 실패해도 사장님은
 * 한 줄 알고 넘어간다(FE 규칙 2).
 */
describe('CheckFlow — 서버', () => {
  it('저장이 끝나기 전에는 기록했다고 하지 않는다', () => {
    serve(hanging)
    renderFlow(<CheckFlow task={checklistTask} />)

    fireEvent.click(screen.getByRole('button', { name: '다 했어요' }))

    expect(screen.queryByText('마치셨다고 기록했어요')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '다 했어요' })).toBeDisabled()
  })

  it('저장되면 서버가 돌려준 상태로 바꾼다', async () => {
    const fetchMock = serve(json({ task_id: 'dispose_stock', completed: true }))
    renderFlow(<CheckFlow task={checklistTask} />)

    fireEvent.click(screen.getByRole('button', { name: '다 했어요' }))

    expect(await screen.findByText('마치셨다고 기록했어요')).toBeInTheDocument()
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toMatch(/\/cases\/checklists\/dispose_stock$/)
    expect(JSON.parse(init.body as string)).toEqual({ completed: true })
  })

  it('연결이 끊기면 다시 누를 수 있게 둔다', async () => {
    serve(status(500))
    renderFlow(<CheckFlow task={checklistTask} />)

    fireEvent.click(screen.getByRole('button', { name: '다 했어요' }))

    expect(await screen.findByText('저장하지 못했어요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '다 했어요' })).toBeEnabled()
  })

  /** 이 가게에서 받지 않는 항목이다. 다시 눌러도 같은 답이라 버튼을 잠근다 */
  it('서버가 받지 않는 항목이면 다시 누를 수 없게 한다', async () => {
    serve(status(422))
    renderFlow(<CheckFlow task={checklistTask} />)

    fireEvent.click(screen.getByRole('button', { name: '다 했어요' }))

    expect(await screen.findByText('이 할 일은 지금 기록할 수 없어요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '다 했어요' })).toBeDisabled()
  })

  it('로그인이 풀렸으면 로그인으로 간다', async () => {
    serve(status(401))
    const router = renderFlow(<CheckFlow task={checklistTask} />)

    fireEvent.click(screen.getByRole('button', { name: '다 했어요' }))

    expect(await screen.findByText('로그인')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
  })
})

describe('SupportResultFlow — 서버', () => {
  /** 서버가 지금 값을 돌려주지 않는다. 미리 골라 두면 사장님이 확인하지 않고 넘긴다 */
  it('아무것도 골라 두지 않고, 골라야 기록할 수 있다', () => {
    renderFlow(<SupportResultFlow task={supportTask} />)

    for (const option of screen.getAllByRole('radio')) expect(option).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByRole('button', { name: '기록하기' })).toBeDisabled()
  })

  /** "아직 몰라요"는 키를 빼지 않고 null 로 보낸다. 빠지면 서버가 422 로 막는다 */
  it('아직 몰라요를 null 로 보내고 저장된 결과를 알린다', async () => {
    const fetchMock = serve(json({ approved: null }))
    renderFlow(<SupportResultFlow task={supportTask} />)

    fireEvent.click(screen.getByRole('radio', { name: '아직 몰라요' }))
    fireEvent.click(screen.getByRole('button', { name: '기록하기' }))

    expect(await screen.findByText(/아직 몰라요.*로 기록했어요/)).toBeInTheDocument()
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toMatch(/\/cases\/support-approval$/)
    expect(JSON.parse(init.body as string)).toEqual({ approved: null })
  })
})

/** 주소 찾기 창 대신 고른 주소를 바로 돌려준다. 실제 창은 외부 서비스라 브라우저에서 확인한다 */
function stubPostcode(picked = { roadAddress: '서울 마포구 망원로 52', bname: '망원동', buildingName: '', apartment: 'N' as const }) {
  const embed = vi.fn()
  window.daum = {
    Postcode: vi.fn(function Postcode(this: unknown, options: { oncomplete: (data: typeof picked) => void }) {
      return { embed: () => embed(options.oncomplete) }
    }) as never,
  }
  return () => embed.mock.calls[0][0](picked)
}

const closureTask: RoadmapTaskView = { id: 'closure_submission', title: '통합 폐업 신고', kind: 'PROCEDURE', status: 'NOT_STARTED' }

/**
 * 통합 폐업 신고(#168). 폐업일·사유·도로명 주소가 다 있어야 서버가 받는다. 하나라도 빈 채로
 * 보내면 422 라, 다 채우기 전에는 저장을 잠근다.
 */
describe('ClosureReportFlow', () => {
  afterEach(() => {
    delete window.daum
  })

  it('폐업일·사유·주소를 다 채워야 저장할 수 있고, 주소는 찾기에서 고른다', async () => {
    const pick = stubPostcode()
    renderFlow(<ClosureReportFlow task={closureTask} />)
    const save = screen.getByRole('button', { name: '저장하기' })

    fireEvent.change(screen.getByLabelText('폐업일'), { target: { value: '2026-10-31' } })
    fireEvent.click(screen.getByRole('radio', { name: '사업 부진' }))
    expect(save).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '주소 찾기' }))
    await vi.waitFor(() => expect(window.daum?.Postcode).toHaveBeenCalled())
    act(() => pick())

    expect(screen.getByText('서울 마포구 망원로 52 (망원동)')).toBeInTheDocument()
    expect(save).toBeEnabled()
  })

  /** 상세 주소는 비워도 된다(단독 건물 등). 빈 글자를 보내면 빈 주소가 저장된다 */
  it('네 값을 한 번에 보내고, 상세 주소를 비우면 없는 것으로 보낸다', async () => {
    const pick = stubPostcode()
    const fetchMock = serve(
      json({ closure_date: '2026-10-31', closure_reason: 'PERSONAL', road_address: '서울 마포구 망원로 52 (망원동)', address_detail: null }),
    )
    renderFlow(<ClosureReportFlow task={closureTask} />)

    fireEvent.change(screen.getByLabelText('폐업일'), { target: { value: '2026-10-31' } })
    fireEvent.click(screen.getByRole('radio', { name: '개인 사정' }))
    fireEvent.click(screen.getByRole('button', { name: '주소 찾기' }))
    await vi.waitFor(() => expect(window.daum?.Postcode).toHaveBeenCalled())
    act(() => pick())
    fireEvent.change(screen.getByLabelText('상세 주소 (선택)'), { target: { value: '   ' } })
    fireEvent.click(screen.getByRole('button', { name: '저장하기' }))

    expect(await screen.findByText('신고 정보를 저장했어요')).toBeInTheDocument()
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toMatch(/\/cases\/closure-report$/)
    expect(init.method).toBe('PUT')
    expect(JSON.parse(init.body as string)).toEqual({
      closure_date: '2026-10-31',
      closure_reason: 'PERSONAL',
      road_address: '서울 마포구 망원로 52 (망원동)',
      address_detail: null,
    })
    // 신고는 공식 절차라 끝났는지는 판단이 정한다. 결과를 알려 달라고 이어 준다
    expect(screen.getByRole('button', { name: '결과 알려주기' })).toBeInTheDocument()
  })

  it('저장이 끝나기 전에는 저장했다고 하지 않는다', async () => {
    const pick = stubPostcode()
    serve(hanging)
    renderFlow(<ClosureReportFlow task={closureTask} />)

    fireEvent.change(screen.getByLabelText('폐업일'), { target: { value: '2026-10-31' } })
    fireEvent.click(screen.getByRole('radio', { name: '기타' }))
    fireEvent.click(screen.getByRole('button', { name: '주소 찾기' }))
    await vi.waitFor(() => expect(window.daum?.Postcode).toHaveBeenCalled())
    act(() => pick())
    fireEvent.click(screen.getByRole('button', { name: '저장하기' }))

    expect(screen.queryByText('신고 정보를 저장했어요')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '저장하기' })).toBeDisabled()
  })
})
