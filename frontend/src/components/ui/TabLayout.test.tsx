import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { DocsPage } from '../../pages/DocsPage'
import { LogPage } from '../../pages/LogPage'
import { MyInfoPage } from '../../pages/MyInfoPage'
import { TabLayout } from './TabLayout'

/**
 * `routes.tsx`와 같은 구조.
 * 홈(`/case`)은 서버를 불러오는 화면이라 여기서는 빈 자리로 둔다. 이 파일은 틀만 본다.
 */
function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      {
        element: <TabLayout />,
        children: [
          { path: '/case', element: <div /> },
          { path: '/docs', element: <DocsPage /> },
          { path: '/log', element: <LogPage /> },
        ],
      },
      { path: '/me', element: <MyInfoPage /> },
    ],
    { initialEntries: [path] },
  )

  render(<RouterProvider router={router} />)
}

describe('TabLayout', () => {
  /** 서류함은 서버(#159)에서 목록을 불러온다. 비어 있다고 답하면 빈 서류함을 그린다 */
  it('서류함은 머리말에 이름을 두고, 서류가 없으면 없다는 화면을 보여준다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ documents: [], check: null }), { status: 200 })))
    renderAt('/docs')

    expect(screen.getByRole('heading', { level: 1, name: '서류함' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 2 })).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('홈 머리말은 이름 대신 워드마크를 두고, 제목은 화면에 맡긴다', () => {
    renderAt('/case')

    expect(screen.getByRole('img', { name: '리본' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 1 })).not.toBeInTheDocument()
  })

  it('탭을 누르면 머리말 이름도 그 화면으로 바뀐다', async () => {
    renderAt('/docs')

    await userEvent.click(screen.getByRole('link', { name: '기록' }))

    expect(await screen.findByRole('heading', { level: 1, name: '작업 기록' })).toBeInTheDocument()
  })

  it('사람 버튼을 누르면 내 정보로 가고, 뒤로 누르면 돌아온다', async () => {
    renderAt('/docs')

    await userEvent.click(screen.getByRole('link', { name: '내 정보' }))
    expect(await screen.findByRole('heading', { level: 1, name: '내 정보' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '주요 화면' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '뒤로' }))
    expect(await screen.findByRole('heading', { level: 1, name: '서류함' })).toBeInTheDocument()
  })
})
