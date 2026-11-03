import { fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { logInWithMock, saveTokens } from '../lib/auth'
import { EMPTY_DIAGNOSIS, useDiagnosisStore } from '../stores/useDiagnosisStore'
import { CaseCreatePage } from './CaseCreatePage'

/**
 * 서버 두 곳을 흉내 낸다. `GET /cases`는 Case가 없다고 답하고, `POST /cases`는 받은 상태로 답한다.
 * `pending`이면 가입 요청의 답을 끝까지 주지 않는다 — 저장하는 동안의 화면을 보려는 것이다.
 */
function mockServer(post: number | 'pending') {
  const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
    if (init?.method !== 'POST') return Promise.resolve(new Response(JSON.stringify({ case: null })))
    if (post === 'pending') return new Promise<Response>(() => {})
    return Promise.resolve(new Response(post === 200 ? JSON.stringify({ id: 1 }) : null, { status: post }))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const postBody = (fetchMock: ReturnType<typeof mockServer>) => {
  const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
  return call && JSON.parse(String(call[1]?.body))
}

function renderPage(path = '/cases/new') {
  const router = createMemoryRouter(
    [
      { path: '/cases/new', element: <CaseCreatePage /> },
      { path: '/case', element: <p>현재 Case</p> },
      { path: '/login', element: <p>로그인 화면</p> },
    ],
    { initialEntries: [path] },
  )

  render(<RouterProvider router={router} />)
  return router
}

/** 질문이 바뀌면 화면을 다시 그리므로, 누를 것을 매번 기다렸다가 누른다 */
async function press(role: 'radio' | 'button', name: string | RegExp) {
  fireEvent.click(await screen.findByRole(role, { name }))
}

/** 해당하는 게 없는 개인 카페로 마지막 질문까지 답한다. 보내기 직전에 멈춘다 */
async function answerUntilLast() {
  await press('radio', /개인 카페/)
  await press('button', '다음')
  await press('button', '해당하는 게 없어요')
  await press('radio', '아니요, 없어요')
  await press('button', '다음')
  await press('button', '가입한 적 없어요')
  await press('radio', '아직 안 정했어요')
}

const sendButton = () => screen.getByRole('button', { name: '폐업 순서 만들기' })

afterEach(() => {
  vi.unstubAllGlobals()
})

/**
 * 이 화면이 사장님이 처음으로 무언가를 서버에 남기는 자리다. 여기서 값이 잘못 나가면
 * Case 하나가 틀린 채로 만들어지고, 회원당 하나라 다시 만들 수도 없다.
 */
describe('CaseCreatePage', () => {
  it('질문을 차례로 답하면 답을 서버 모양으로 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockServer(200)
    renderPage()

    await answerUntilLast()
    fireEvent.click(sendButton())

    expect(postBody(fetchMock)).toEqual({
      store_name: null,
      business_type: 'CAFE',
      franchise_status: false,
      employee_count: 0,
      has_business_loan: false,
      has_service_contracts: false,
      lease_status: 'OWNED',
      restoration_clause: 'UNKNOWN',
      planned_closure_date: null,
      had_employees: false,
      pension_enrolled: false,
      health_insurance_enrolled: false,
      employment_insurance_enrolled: false,
      industrial_accident_insurance_enrolled: false,
    })
  })

  /** 서버가 월세 여부를 꼭 받아야 한다. 건너뛰면 점포 형태를 정할 수 없어 보내지 못한다 */
  it('빌린 가게를 고르면 다음은 월세 질문이다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockServer(200)
    renderPage()

    await press('radio', /개인 카페/)
    await press('button', '다음')
    fireEvent.click(await screen.findByRole('button', { name: /빌려서 써요/ }))
    await press('button', '1개 선택 완료')

    expect(await screen.findByRole('radio', { name: '네, 내고 있어요' })).toBeInTheDocument()
  })

  /** 남아 있으면 다음에 진단에 들어온 사람이 지난 답으로 시작한다 */
  it('저장되면 현재 Case로 보내고 진단 답을 비운다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockServer(200)
    renderPage()

    await answerUntilLast()
    fireEvent.click(sendButton())

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
    expect(useDiagnosisStore.getState().answers).toEqual(EMPTY_DIAGNOSIS)
  })

  /**
   * 회원당 Case는 하나다. 두 탭에서 동시에 만들거나, 요청이 오래 걸리다 끊겨 다시 눌렀을 때
   * 온다. 이미 만들어졌다는 뜻이라 실패 화면을 보여주면 사장님이 다시 만들려 든다.
   */
  it('이미 Case가 있으면 실패가 아니라 현재 Case로 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockServer(409)
    renderPage()

    await answerUntilLast()
    fireEvent.click(sendButton())

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
  })

  /** 다시 로그인한 뒤 처음부터 답하지 않게, 답은 남긴다 */
  it('인증이 통하지 않으면 로그인 화면으로 보내고 답은 남긴다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockServer(401)
    renderPage()

    await answerUntilLast()
    fireEvent.click(sendButton())

    expect(await screen.findByText('로그인 화면')).toBeInTheDocument()
    expect(useDiagnosisStore.getState().answers.business).toBe('PERSONAL_CAFE')
  })

  it('저장하는 동안 폐업 순서를 만드는 중이라고 보여준다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockServer('pending')
    renderPage()

    await answerUntilLast()
    fireEvent.click(sendButton())

    expect(await screen.findByRole('status')).toHaveTextContent('폐업 순서를 만들고 있어요')
  })

  /** 고른 답이 남아 있어야 다시 누르기만 하면 된다 */
  it('실패하면 안내를 띄우고 고른 답을 남긴다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockServer(500)
    renderPage()

    await answerUntilLast()
    fireEvent.click(sendButton())

    expect(await screen.findByText('저장하지 못했어요')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '아직 안 정했어요' })).toBeChecked()
  })

  /**
   * 다른 화면이 전부 Mock인데 여기서만 진짜 Case를 만들면, 회원당 하나라 지울 수도 없는
   * Case가 서버에 남는다. Preview의 가짜 로그인도 같은 길이다.
   */
  it('?mock=을 따라왔으면 서버에 가입 요청을 보내지 않는다', async () => {
    logInWithMock()
    const fetchMock = mockServer(200)
    renderPage('/cases/new?mock=no-case')

    await answerUntilLast()
    fireEvent.click(sendButton())

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
    expect(postBody(fetchMock)).toBeUndefined()
  })

  /** Mock 에서는 서버를 부르지 않아 저장 중 화면이 스치지도 않는다. 눈으로 볼 길이 이것뿐이다 */
  it('?mock=creating이면 저장하는 동안의 화면을 바로 보여준다', async () => {
    logInWithMock()
    renderPage('/cases/new?mock=creating')

    expect(await screen.findByRole('status')).toHaveTextContent('폐업 순서를 만들고 있어요')
  })

  /** 가입한 뒤 뒤로가기로 닿으면 두 번째 Case를 만들려 든다 */
  it('Case가 이미 있으면 진단 대신 현재 Case로 보낸다', async () => {
    logInWithMock()
    renderPage('/cases/new?mock=done')

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
  })

  /** 앞 답 없이 뒤 질문이 열리면 빈 답을 보내게 된다 */
  it('주소로 뒤 질문을 열면 답하지 않은 첫 질문을 보여준다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockServer(200)
    const router = renderPage('/cases/new?step=date')

    expect(await screen.findByRole('radio', { name: /개인 카페/ })).toBeInTheDocument()
    expect(router.state.location.search).toBe('?step=biz')
  })

  /**
   * 주소로 바로 들어와 앞 기록이 없을 때 그대로 뒤로 가면 앱을 떠난다. 진입 분기를 거쳐
   * 들어온 경우도 같다 — 그 앞은 카카오나 로그인 화면이다.
   */
  it('앞 질문에서 넘어온 기록이 없으면 뒤로를 눌러도 앞 질문으로 간다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockServer(200)
    useDiagnosisStore.getState().setAnswers({ business: 'PERSONAL_CAFE' })
    const router = renderPage('/cases/new?step=situ')

    fireEvent.click(await screen.findByRole('button', { name: '뒤로' }))

    expect(await screen.findByRole('radio', { name: /개인 카페/ })).toBeChecked()
    expect(router.state.location.pathname).toBe('/cases/new')
  })
})
