import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { LogPage } from './LogPage'

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <LogPage />
    </MemoryRouter>,
  )
}

/**
 * 기록 조회 API(#143)가 머지 전이라 실서버에서는 빈 상태다. 가짜 기록이 실서버에 뜨면
 * 사장님이 하지 않은 일이 기록에 남는다.
 */
describe('LogPage', () => {
  it('실서버에서는 아직 빈 상태를 보여준다', () => {
    renderAt('/log')

    expect(screen.getByText('아직 남은 기록이 없어요')).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  /** 리뷰어가 링크로 채워진 모양을 보는 길이다. 끊기면 화면을 볼 방법이 없다 */
  it('Mock 으로 열면 누가 언제 했는지와 함께 기록을 그린다', () => {
    renderAt('/log?mock=done')

    const rows = screen.getAllByRole('listitem')
    expect(rows.length).toBeGreaterThan(0)
    expect(rows[0]).toHaveTextContent(/(리본|사장님) · \d{2}\.\d{2}/)
  })
})
