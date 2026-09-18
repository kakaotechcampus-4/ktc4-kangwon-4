import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { ConfirmChangePage } from './ConfirmChangePage'

function renderPage() {
  const router = createMemoryRouter([{ path: '/confirm', element: <ConfirmChangePage /> }], {
    initialEntries: ['/confirm'],
  })

  render(<RouterProvider router={router} />)
}

/**
 * 되돌리기 API가 계약에서 빠져, 잘못 반영된 값을 되돌릴 수 있는 지점은 이 화면뿐이다.
 * 그래서 고르지 않은 항목이 하나라도 있으면 진행할 수 없어야 한다 —
 * 기본 선택을 두지 않는 것과 같은 이유다.
 */
describe('ConfirmChangePage', () => {
  it('고르기 전에는 진행할 수 없다', () => {
    renderPage()

    expect(screen.getByRole('button', { name: /이대로 진행하기/ })).toBeDisabled()
  })

  it('충돌 항목을 고르면 진행할 수 있다', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('button', { name: /이번에 말씀하신 내용/ }))

    expect(screen.getByRole('button', { name: /이대로 진행하기/ })).toBeEnabled()
  })
})
