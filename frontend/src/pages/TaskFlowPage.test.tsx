import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactElement } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { saveTokens } from '../lib/auth'
import type { RoadmapTaskView } from '../types/view'
import { CheckFlow, ClosureReportFlow, DepositFlow, InfoFlow, SupportResultFlow, TaskFlowPage } from './TaskFlowPage'

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

/** 장면 하나만 띄운다. 장면이 보내는 저장 요청만 보려고 로드맵 조회를 건너뛴다 */
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

/** 부를 때마다 차례로 답한다. 목록이 끝나면 마지막 답을 계속 준다 */
function serve(...answers: Answer[]) {
  let call = 0
  const fetchMock = vi.fn(async () => answers[Math.min(call++, answers.length - 1)]())
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/**
 * 장면 고르기에 쓰는 로드맵. Mock(`mocks/roadmap.ts`)은 시연용이라 바뀌므로 테스트가 따로 들고 있는다.
 * 할 일 종류(체크 · 첨부 · 공식 절차 · 서류 점검)와 해당 없음을 하나씩 둔다
 */
const SCENE_ROADMAP = {
  supported: true,
  unsupported_reason: null,
  current_stage: 2,
  stages: [
    {
      stage: 2,
      title: '원상복구·철거',
      tasks: [
        { task_id: 'restoration', title: '원상복구 범위 확인', kind: 'PROCEDURE', status: 'IN_PROGRESS', guidance: null },
        { task_id: 'before_photo', title: '철거 전 사진', kind: 'CHECKLIST', status: 'NOT_STARTED', guidance: null },
      ],
    },
    {
      stage: 3,
      title: '영업 마무리·폐업 신고',
      tasks: [
        { task_id: 'dispose_stock', title: '재고·장비 처분', kind: 'CHECKLIST', status: 'NOT_STARTED', guidance: null },
        { task_id: 'check_loan', title: '은행에 폐업 후 상환 조건 확인', kind: 'CHECKLIST', status: 'NOT_APPLICABLE', guidance: null },
      ],
    },
    {
      stage: 4,
      title: '지원금 정산·가게 반환',
      tasks: [{ task_id: 'document_check', title: 'AI 서류 점검', kind: 'DOCUMENT_CHECK', status: 'NOT_STARTED', guidance: null }],
    },
  ],
}

/** 서버가 위 로드맵(과 뒤이은 저장 응답들)을 주는 할 일 화면을 띄운다 */
function renderTask(taskId: string, ...after: Answer[]) {
  saveTokens('access-1', 'refresh-1')
  serve(json(SCENE_ROADMAP), ...after)
  return renderAt(`/roadmap/${taskId}`)
}

/** 할 일 화면은 로드맵(`GET /cases/roadmap`)에서 그 할 일을 찾아 어떤 장면을 열지 정한다 */
describe('TaskFlowPage — 장면 고르기', () => {
  it('체크 항목은 다 했어요로 기록하고 완료 취소로 되돌릴 수 있다', async () => {
    renderTask('dispose_stock', json({ task_id: 'dispose_stock', completed: true }), json({ task_id: 'dispose_stock', completed: false }))

    fireEvent.click(await screen.findByRole('button', { name: '다 했어요' }))

    expect(await screen.findByText('마치셨다고 기록했어요')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '완료 취소하기' }))
    await waitFor(() => expect(screen.queryByText('마치셨다고 기록했어요')).not.toBeInTheDocument())
  })

  /** 사진은 서류함에 있어야 정산 점검에 쓰인다. 체크만 하고 끝나면 점검에서 빠진 서류가 된다 */
  it('서류가 필요한 할 일은 서류함에 올리는 길을 먼저 둔다', async () => {
    const router = renderTask('before_photo')

    fireEvent.click(await screen.findByRole('button', { name: '서류함에 올리기' }))

    expect(router.state.location.pathname).toBe('/docs')
  })

  /** 공식 절차는 끝났는지를 판단이 정한다. 체크 버튼을 두면 사장님이 대신 완료한다 */
  it('공식 절차는 체크 없이 결과 알려주기로 보낸다', async () => {
    const router = renderTask('restoration')

    fireEvent.click(await screen.findByRole('button', { name: '결과 알려주기' }))
    expect(screen.queryByRole('button', { name: '다 했어요' })).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/results')
  })

  it('서류 점검 할 일은 점검 화면으로 보낸다', async () => {
    const router = renderTask('document_check')

    await waitFor(() => expect(router.state.location.pathname).toBe('/docs/check'))
  })

  /** 해당 없는 할 일과 없는 할 일은 열 것이 없다. 빈 화면 대신 순서로 돌려보낸다 */
  it.each(['check_loan', 'no_such_task'])('해당 없거나 없는 할 일(%s)이면 로드맵으로 돌려보낸다', async (taskId) => {
    const router = renderTask(taskId)

    await waitFor(() => expect(router.state.location.pathname).toBe('/roadmap'))
  })

  it('로드맵을 불러오지 못하면 알린다', async () => {
    saveTokens('access-1', 'refresh-1')
    serve(status(500))
    renderAt('/roadmap/dispose_stock')

    expect(await screen.findByText('할 일을 불러오지 못했어요.')).toBeInTheDocument()
  })
})

/** Mock 은 Preview 에서 화면을 보려고 둔다. 서버를 부르지 않고 열리는지, 다음 화면에 Mock 표시를 잇는지만 본다 */
/**
 * 폐업 날짜를 "아직 안 정했어요"로 고른 가게는 이 할 일이 확인 필요다.
 * 그때 "따로 하실 것이 없어요"라고 하면 사장님은 정할 필요가 없는 줄 안다
 */
describe('InfoFlow', () => {
  const closureDateTask: RoadmapTaskView = { id: 'closure_date', title: '폐업 날짜 정하기', kind: 'CASE_FACT', status: 'NEEDS_CONFIRMATION' }

  function renderInfo(task: RoadmapTaskView) {
    const router = createMemoryRouter(
      [
        { path: '/flow', element: <InfoFlow task={task} /> },
        { path: '/results', element: <p>결과 입력</p> },
      ],
      { initialEntries: ['/flow'] },
    )
    render(<RouterProvider router={router} />)
  }

  it('확인이 필요하면 결과 알려주기로 보낸다', async () => {
    renderInfo(closureDateTask)
    fireEvent.click(screen.getByRole('button', { name: '결과 알려주기' }))
    expect(await screen.findByText('결과 입력')).toBeInTheDocument()
  })

  it('정해져 있으면 할 일을 내밀지 않는다', () => {
    renderInfo({ ...closureDateTask, status: 'COMPLETED' })
    expect(screen.queryByRole('button', { name: '결과 알려주기' })).not.toBeInTheDocument()
  })
})

describe('TaskFlowPage — Mock', () => {
  it('?mock= 이면 서버를 부르지 않고 할 일을 열고, 다음 화면에 Mock 표시를 잇는다', () => {
    const fetchMock = serve(json(SCENE_ROADMAP))
    const router = renderAt('/roadmap/before_photo?mock=roadmap')

    fireEvent.click(screen.getByRole('button', { name: '서류함에 올리기' }))

    expect(router.state.location.search).toBe('?mock=roadmap')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('CheckFlow — 서버', () => {
  /** 서버가 "확인 필요"로 준 할 일은 체크를 받지 않는다(422, #181). 눌러 보고 거절당하게 두지 않는다 */
  it('확인이 필요한 할 일은 다 했어요를 꺼 두고, 보내지 않는다', () => {
    const fetchMock = serve(json({}))
    renderFlow(<CheckFlow task={{ ...checklistTask, status: 'NEEDS_CONFIRMATION' }} />)

    expect(screen.getByText('아직 기록할 수 없는 할 일이에요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '다 했어요' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '다 했어요' }))
    expect(fetchMock).not.toHaveBeenCalled()
  })

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

  /** 거절은 "이 값은 받지 않는다"는 뜻이다. 다른 답을 골라도 버튼이 꺼져 있으면 화면을 나갔다 와야 한다 */
  it('거절된 뒤 다른 답을 고르면 다시 기록할 수 있다', async () => {
    serve(status(422))
    renderFlow(<SupportResultFlow task={supportTask} />)
    fireEvent.click(screen.getByRole('radio', { name: '승인됐어요' }))
    fireEvent.click(screen.getByRole('button', { name: '기록하기' }))
    expect(await screen.findByText('이 할 일은 지금 기록할 수 없어요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '기록하기' })).toBeDisabled()

    fireEvent.click(screen.getByRole('radio', { name: '아직 몰라요' }))

    expect(screen.getByRole('button', { name: '기록하기' })).toBeEnabled()
    expect(screen.queryByText('이 할 일은 지금 기록할 수 없어요.')).not.toBeInTheDocument()
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

  /** 다시 열 때 빈 칸이면 사장님은 저장이 안 된 줄 알고 처음부터 다시 적는다(#170 현석님) */
  it('저장해 둔 값이 있으면 칸을 채우고 저장한 뒤 모양으로 연다', () => {
    renderFlow(
      <ClosureReportFlow
        task={closureTask}
        initial={{ closureDate: '2026-10-31', closureReason: 'PERSONAL', roadAddress: '서울 마포구 망원로 52 (망원동)', addressDetail: '1층' }}
      />,
    )

    expect(screen.getByLabelText('폐업일')).toHaveValue('2026-10-31')
    expect(screen.getByRole('radio', { name: '개인 사정' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText('서울 마포구 망원로 52 (망원동)')).toBeInTheDocument()
    expect(screen.getByLabelText('상세 주소 (선택)')).toHaveValue('1층')
    expect(screen.getByRole('button', { name: '다시 저장하기' })).toBeEnabled()
  })

  /** 폐업일을 받지 않으면(422) 고친 날짜로 다시 저장할 수 있어야 한다 */
  it('거절된 뒤 칸을 고치면 다시 저장할 수 있다', async () => {
    serve(status(422))
    renderFlow(
      <ClosureReportFlow
        task={closureTask}
        initial={{ closureDate: '2026-10-31', closureReason: 'PERSONAL', roadAddress: '서울 마포구 망원로 52 (망원동)', addressDetail: null }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '다시 저장하기' }))
    expect(await screen.findByText('이 할 일은 지금 기록할 수 없어요.')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('폐업일'), { target: { value: '2026-11-30' } })

    expect(screen.getByRole('button', { name: '저장하기' })).toBeEnabled()
  })

  /** 저장한 뒤 고친 칸은 아직 서버에 없다. "저장했어요"가 남으면 고친 내용까지 저장된 줄 알고 떠난다 */
  it('저장한 뒤 칸을 고치면 저장했다는 안내와 결과 알려주기를 내린다', () => {
    renderFlow(
      <ClosureReportFlow
        task={closureTask}
        initial={{ closureDate: '2026-10-31', closureReason: 'PERSONAL', roadAddress: '서울 마포구 망원로 52 (망원동)', addressDetail: null }}
      />,
    )
    expect(screen.getByText('신고 정보를 저장했어요')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('폐업일'), { target: { value: '2026-11-30' } })

    expect(screen.queryByText('신고 정보를 저장했어요')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '결과 알려주기' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '저장하기' })).toBeEnabled()
  })
})

const depositTask: RoadmapTaskView = { id: 'deposit_settlement', title: '보증금 정산 기록', kind: 'CHECKLIST', status: 'NOT_STARTED' }

/** 주소로 답을 고른다. 부른 순서가 아니라 주소로 골라야 순서를 바꾸는 정당한 수정에 테스트가 깨지지 않는다 */
function serveByUrl(answers: Record<'deposit' | 'checklist', Answer[]>) {
  const calls = { deposit: 0, checklist: 0 }
  const fetchMock = vi.fn(async (url: string) => {
    const kind = url.includes('/cases/deposit-return') ? 'deposit' : 'checklist'
    const list = answers[kind]
    return list[Math.min(calls[kind]++, list.length - 1)]()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const urlsOf = (fetchMock: ReturnType<typeof serveByUrl>) => fetchMock.mock.calls.map(([url]) => url as string)

/**
 * 보증금 정산 기록. [기록하기] 한 번으로 결과(#168)와 로드맵 체크(#149)를 함께 남긴다.
 * 결과가 저장되지 않았는데 체크만 켜지면, 로드맵은 끝났다고 하는데 기록은 비어 있다.
 */
describe('DepositFlow', () => {
  it('결과를 먼저 저장하고, 그다음 체크를 켠다', async () => {
    const fetchMock = serveByUrl({
      deposit: [json({ result: 'PARTIAL' })],
      checklist: [json({ task_id: 'deposit_settlement', completed: true })],
    })
    renderFlow(<DepositFlow task={depositTask} />)

    expect(screen.getByRole('button', { name: '기록하기' })).toBeDisabled()
    fireEvent.click(screen.getByRole('radio', { name: '일부 빼고 받았어요' }))
    fireEvent.click(screen.getByRole('button', { name: '기록하기' }))

    expect(await screen.findByText(/일부 빼고 받았어요.*로 기록했어요/)).toBeInTheDocument()
    const urls = urlsOf(fetchMock)
    expect(urls[0]).toMatch(/\/cases\/deposit-return$/)
    expect(urls[1]).toMatch(/\/cases\/checklists\/deposit_settlement$/)
    expect(JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)).toEqual({
      result: 'PARTIAL',
    })
  })

  /** 결과를 못 남겼으면 체크도 보내지 않는다. 체크만 켜지면 기록이 빈 채로 끝난 것이 된다 */
  it('결과 저장이 실패하면 체크를 보내지 않는다', async () => {
    const fetchMock = serveByUrl({ deposit: [status(500)], checklist: [json({ task_id: 'deposit_settlement', completed: true })] })
    renderFlow(<DepositFlow task={depositTask} />)

    fireEvent.click(screen.getByRole('radio', { name: '다 받았어요' }))
    fireEvent.click(screen.getByRole('button', { name: '기록하기' }))

    expect(await screen.findByText('저장하지 못했어요.')).toBeInTheDocument()
    expect(urlsOf(fetchMock).some((url) => url.includes('/cases/checklists/'))).toBe(false)
  })

  /** 결과는 서버에 남았다. 같은 결과를 다시 보내지 않고 체크만 다시 보낸다 */
  it('체크만 실패하면 결과는 저장됐다고 알리고 체크만 다시 보낸다', async () => {
    const fetchMock = serveByUrl({
      deposit: [json({ result: 'NONE' })],
      checklist: [status(500), json({ task_id: 'deposit_settlement', completed: true })],
    })
    renderFlow(<DepositFlow task={depositTask} />)

    fireEvent.click(screen.getByRole('radio', { name: '아직 못 받았어요' }))
    fireEvent.click(screen.getByRole('button', { name: '기록하기' }))

    expect(await screen.findByText('보증금 결과는 저장했는데 할 일 체크는 못 했어요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '기록하기' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '체크만 다시 보내기' }))

    expect(await screen.findByText(/아직 못 받았어요.*로 기록했어요/)).toBeInTheDocument()
    const urls = urlsOf(fetchMock)
    expect(urls.filter((url) => url.includes('/cases/deposit-return'))).toHaveLength(1)
    expect(urls.filter((url) => url.includes('/cases/checklists/'))).toHaveLength(2)
  })

  it('기록해 둔 결과가 있으면 골라 둔 채 기록했다고 연다', () => {
    const fetchMock = serveByUrl({ deposit: [], checklist: [] })
    renderFlow(<DepositFlow task={depositTask} initial="FULL" />)

    expect(screen.getByRole('radio', { name: '다 받았어요' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText(/다 받았어요.*로 기록했어요/)).toBeInTheDocument()
    // 여는 것만으로는 아무것도 보내지 않는다
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
