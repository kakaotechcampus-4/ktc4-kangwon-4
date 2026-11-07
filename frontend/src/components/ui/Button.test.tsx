import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Button } from './Button'

describe('Button', () => {
  it('누르면 동작한다', async () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>다음</Button>)

    await userEvent.click(screen.getByRole('button', { name: '다음' }))

    expect(onClick).toHaveBeenCalledOnce()
  })

  it('꺼져 있으면 눌러도 동작하지 않는다', async () => {
    const onClick = vi.fn()
    render(
      <Button onClick={onClick} disabled>
        다음
      </Button>,
    )

    await userEvent.click(screen.getByRole('button', { name: '다음' }))

    expect(onClick).not.toHaveBeenCalled()
  })

  /** HTML 기본값(submit)이면 폼 안의 보조 버튼이 폼을 제출해 버린다 */
  it('폼 안에 있어도 따로 정하지 않으면 제출하지 않는다', async () => {
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault())
    render(
      <form onSubmit={onSubmit}>
        <Button variant="neutral">취소</Button>
        <Button type="submit">보내기</Button>
      </form>,
    )

    await userEvent.click(screen.getByRole('button', { name: '취소' }))
    expect(onSubmit).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: '보내기' }))
    expect(onSubmit).toHaveBeenCalledOnce()
  })
})
