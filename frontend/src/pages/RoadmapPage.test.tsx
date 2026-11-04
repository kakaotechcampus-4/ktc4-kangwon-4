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

describe('RoadmapPage — Mock', () => {
  /** 지금 단계는 서버가 정한다. 그 단계만 펼쳐 지금 할 일이 먼저 보이게 한다 */
  it('지금 단계만 펼치고, 다른 단계는 눌러야 펼친다', () => {
    renderAt('/roadmap?mock=roadmap')

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
    renderAt('/roadmap?mock=roadmap')

    fireEvent.click(stageButton(/원상복구·철거/))

    expect(stageButton(/원상복구·철거/)).toHaveAttribute('aria-expanded', 'false')
    await waitFor(() => expect(screen.queryByText('원상복구 범위 확인')).not.toBeInTheDocument())
  })

  it('할 일마다 서버가 준 상태를 글자 배지로 단다', () => {
    renderAt('/roadmap?mock=roadmap')

    expect(screen.getByText('1차 적격심사 결과 확인').closest('li')).toHaveTextContent('확인 필요')
    expect(screen.getByText('원상복구 범위 확인').closest('li')).toHaveTextContent('진행 중')
    expect(screen.getByText('철거 업체 정하기').closest('li')).toHaveTextContent('예정')
  })

  /** 이 가게가 할 필요 없는 일까지 세면 끝까지 해도 다 채워지지 않는다 */
  it('단계의 완료 수는 해당 없는 할 일을 빼고 센다', () => {
    renderAt('/roadmap?mock=roadmap')

    // 1단계는 5개 중 하나가 해당 없음이고, 남은 4개 중 3개를 마쳤다
    expect(stageButton(/폐업 준비/)).toHaveTextContent('3/4')
    fireEvent.click(stageButton(/폐업 준비/))
    expect(screen.getByText('은행에 폐업 후 상환 조건 확인').closest('li')).toHaveTextContent('해당 없음')
  })

  it('검수한 설명이 있는 할 일은 설명을 함께 보여준다', () => {
    renderAt('/roadmap?mock=roadmap')
    fireEvent.click(stageButton(/폐업 준비/))

    expect(screen.getByText(/30일 전에 알려야 하고/)).toBeInTheDocument()
  })

  /** 미지원 업종은 단계가 비어 온다. 빈 화면 대신 서버 안내를 보여준다 */
  it('미지원 업종이면 서버 안내 문구를 보여준다', () => {
    renderAt('/roadmap?mock=roadmap-unsupported')

    expect(screen.getByText(/개인 카페만 폐업 순서를 안내해요/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /폐업 준비/ })).not.toBeInTheDocument()
  })
})

/** 해당 없는 할 일이 눌리면 아무것도 없는 화면이 열린다. 눌릴 것만 링크로 둔다 */
describe('RoadmapPage — 할 일 열기', () => {
  it('할 일은 그 할 일 화면으로 가는 링크이고, 해당 없는 할 일은 링크가 아니다', () => {
    renderAt('/roadmap?mock=roadmap')

    expect(screen.getByRole('link', { name: /원상복구 범위 확인/ })).toHaveAttribute(
      'href',
      '/roadmap/restoration?mock=roadmap',
    )

    fireEvent.click(stageButton(/폐업 준비/))
    expect(screen.queryByRole('link', { name: /은행에 폐업 후 상환 조건 확인/ })).not.toBeInTheDocument()
  })
})
