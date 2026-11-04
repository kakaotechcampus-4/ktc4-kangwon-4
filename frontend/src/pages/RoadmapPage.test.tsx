import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { saveTokens } from '../lib/auth'
import { RoadmapPage } from './RoadmapPage'

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <RoadmapPage />
    </MemoryRouter>,
  )
}

const stageButton = (title: RegExp) => screen.getByRole('button', { name: title })

type Answer = () => Response | Promise<Response>
const json = (body: unknown): Answer => () => new Response(JSON.stringify(body), { status: 200 })
const status = (code: number): Answer => () => new Response(null, { status: code })

function serve(...answers: Answer[]) {
  let call = 0
  const fetchMock = vi.fn(async () => answers[Math.min(call++, answers.length - 1)]())
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** 실서버 경로. 진단으로 보내는지 보려고 라우터에 진단 자리를 둔다 */
function renderServer() {
  saveTokens('access-1', 'refresh-1')
  const router = createMemoryRouter(
    [
      { path: '/roadmap', element: <RoadmapPage /> },
      { path: '/cases/new', element: <p>상황 진단</p> },
    ],
    { initialEntries: ['/roadmap'] },
  )
  render(<RouterProvider router={router} />)
  return router
}

const SERVER_ROADMAP = {
  supported: true,
  unsupported_reason: null,
  current_stage: 3,
  stages: [
    {
      stage: 1,
      title: '폐업 준비',
      tasks: [{ task_id: 'closure_date', title: '폐업 날짜 정하기', kind: 'CASE_FACT', status: 'COMPLETED', guidance: null }],
    },
    {
      stage: 3,
      title: '영업 마무리·폐업 신고',
      tasks: [{ task_id: 'dispose_stock', title: '재고·장비 처분', kind: 'CHECKLIST', status: 'NOT_STARTED', guidance: null }],
    },
  ],
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/** 로드맵 조회(`GET /cases/roadmap`, #178). 지금 단계는 서버(`current_stage`, #179)가 정한다 */
describe('RoadmapPage — 서버', () => {
  it('받은 로드맵을 그리고, 서버가 정한 지금 단계만 펼친다', async () => {
    const fetchMock = serve(json(SERVER_ROADMAP))
    renderServer()

    expect(await screen.findByText('재고·장비 처분')).toBeInTheDocument()
    expect(stageButton(/영업 마무리·폐업 신고/)).toHaveAttribute('aria-expanded', 'true')
    expect(stageButton(/폐업 준비/)).toHaveAttribute('aria-expanded', 'false')
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/cases/roadmap'), expect.anything())
  })

  /** Case 가 없는 사용자는 볼 로드맵이 없다. 빈 화면 대신 상황 진단으로 */
  it('Case 가 없으면(404) 상황 진단으로 보낸다', async () => {
    serve(status(404))
    renderServer()

    expect(await screen.findByText('상황 진단')).toBeInTheDocument()
  })

  it('불러오지 못하면 알리고, 다시 불러오면 그린다', async () => {
    serve(status(500), json(SERVER_ROADMAP))
    renderServer()

    fireEvent.click(await screen.findByRole('button', { name: '다시 불러오기' }))

    expect(await screen.findByText('재고·장비 처분')).toBeInTheDocument()
  })
})

/**
 * 아래 테스트가 쓰는 로드맵. Mock(`mocks/roadmap.ts`)은 시연용이라 바뀌므로 테스트가 따로 들고 있는다.
 * 1단계는 5개 중 하나가 해당 없음이고 남은 4개 중 3개를 마쳤다. 지금 단계는 2단계다
 */
const task = (task_id: string, title: string, kind: string, status: string, guidance: string | null = null) => ({
  task_id,
  title,
  kind,
  status,
  guidance,
})

const ROADMAP = {
  supported: true,
  unsupported_reason: null,
  current_stage: 2,
  stages: [
    {
      stage: 1,
      title: '폐업 준비',
      tasks: [
        task('intake', '상황 진단', 'CASE_FACT', 'COMPLETED'),
        task('closure_date', '폐업 날짜 정하기', 'CASE_FACT', 'IN_PROGRESS'),
        task('notify_landlord', '임대인에게 폐업 알리고 계약 종료일 맞추기', 'CHECKLIST', 'COMPLETED'),
        task('notify_employees', '직원에게 폐업 알리기', 'CHECKLIST', 'COMPLETED', '폐업으로 해고하면 적어도 30일 전에 알려야 하고, 못 알렸다면 30일분 통상임금을 줘야 해요.'),
        task('check_loan', '은행에 폐업 후 상환 조건 확인', 'CHECKLIST', 'NOT_APPLICABLE'),
      ],
    },
    {
      stage: 2,
      title: '원상복구·철거',
      tasks: [
        task('restoration', '원상복구 범위 확인', 'PROCEDURE', 'IN_PROGRESS'),
        task('support_approval', '1차 적격심사 결과 확인', 'CASE_FACT', 'NEEDS_CONFIRMATION'),
        task('choose_contractor', '철거 업체 정하기', 'CHECKLIST', 'NOT_STARTED'),
      ],
    },
    {
      stage: 3,
      title: '영업 마무리·폐업 신고',
      tasks: [task('dispose_stock', '재고·장비 처분', 'CHECKLIST', 'NOT_STARTED')],
    },
  ],
}

/** 서버가 위 로드맵을 주는 화면을 띄우고 그려질 때까지 기다린다 */
async function renderRoadmap(body: unknown = ROADMAP) {
  serve(json(body))
  renderServer()
  await screen.findByRole('button', { name: /폐업 준비/ })
}

describe('RoadmapPage — 단계와 할 일', () => {
  /** 지금 단계는 서버가 정한다. 그 단계만 펼쳐 지금 할 일이 먼저 보이게 한다 */
  it('지금 단계만 펼치고, 다른 단계는 눌러야 펼친다', async () => {
    await renderRoadmap()

    expect(stageButton(/원상복구·철거/)).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('원상복구 범위 확인')).toBeInTheDocument()
    expect(stageButton(/영업 마무리·폐업 신고/)).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('재고·장비 처분')).not.toBeInTheDocument()

    fireEvent.click(stageButton(/영업 마무리·폐업 신고/))

    expect(screen.getByText('재고·장비 처분')).toBeInTheDocument()
  })

  /**
   * 접힌 단계의 할 일은 화면에서 빠져야 한다. 보이지만 않고 남아 있으면 키보드로 넘기다 숨은 할 일에
   * 닿는다. 접는 움직임이 끝난 뒤에 빠지므로 기다려서 본다
   */
  it('펼친 단계를 다시 누르면 접고, 그 단계의 할 일을 빼낸다', async () => {
    await renderRoadmap()

    fireEvent.click(stageButton(/원상복구·철거/))

    expect(stageButton(/원상복구·철거/)).toHaveAttribute('aria-expanded', 'false')
    await waitFor(() => expect(screen.queryByText('원상복구 범위 확인')).not.toBeInTheDocument())
  })

  it('할 일마다 서버가 준 상태를 글자 배지로 단다', async () => {
    await renderRoadmap()

    expect(screen.getByRole('link', { name: /1차 적격심사 결과 확인\s*확인 필요/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /원상복구 범위 확인\s*진행 중/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /철거 업체 정하기\s*예정/ })).toBeInTheDocument()
  })

  /** 이 가게가 할 필요 없는 일까지 세면 끝까지 해도 다 채워지지 않는다 */
  it('단계의 완료 수는 해당 없는 할 일을 빼고 센다', async () => {
    await renderRoadmap()

    expect(stageButton(/폐업 준비/)).toHaveTextContent('3/4')
    fireEvent.click(stageButton(/폐업 준비/))
    expect(screen.getByText('은행에 폐업 후 상환 조건 확인').closest('li')).toHaveTextContent('해당 없음')
  })

  it('검수한 설명이 있는 할 일은 설명을 함께 보여준다', async () => {
    await renderRoadmap()
    fireEvent.click(stageButton(/폐업 준비/))

    expect(screen.getByText(/30일 전에 알려야 하고/)).toBeInTheDocument()
  })

  /** 미지원 업종은 단계가 비어 온다. 빈 화면 대신 서버 안내를 보여준다 */
  it('미지원 업종이면 서버 안내 문구를 보여준다', async () => {
    serve(
      json({ supported: false, unsupported_reason: '지금은 개인 카페만 폐업 순서를 안내해요.', current_stage: null, stages: [] }),
    )
    renderServer()

    expect(await screen.findByText('지금은 개인 카페만 폐업 순서를 안내해요.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /폐업 준비/ })).not.toBeInTheDocument()
  })

  /** 해당 없는 할 일이 눌리면 아무것도 없는 화면이 열린다. 눌릴 것만 링크로 둔다 */
  it('할 일은 그 할 일 화면으로 가는 링크이고, 해당 없는 할 일은 링크가 아니다', async () => {
    await renderRoadmap()

    expect(screen.getByRole('link', { name: /원상복구 범위 확인/ })).toHaveAttribute('href', '/roadmap/restoration')

    fireEvent.click(stageButton(/폐업 준비/))
    expect(screen.queryByRole('link', { name: /은행에 폐업 후 상환 조건 확인/ })).not.toBeInTheDocument()
  })
})

/** Mock 은 Preview 에서 화면을 보려고 둔다. 서버를 부르지 않고 그려지는지만 본다(화면당 하나) */
describe('RoadmapPage — Mock', () => {
  it('?mock= 이면 서버를 부르지 않고 예시 로드맵을 그리며, 할 일 주소에 Mock 표시를 잇는다', () => {
    const fetchMock = serve(json(ROADMAP))
    renderAt('/roadmap?mock=roadmap')

    expect(screen.getByRole('link', { name: /원상복구 범위 확인/ })).toHaveAttribute('href', '/roadmap/restoration?mock=roadmap')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
