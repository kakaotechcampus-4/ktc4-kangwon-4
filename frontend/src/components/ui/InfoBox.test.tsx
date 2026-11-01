import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { InfoBox } from './InfoBox'

describe('InfoBox', () => {
  it('행동 버튼을 누르면 넘겨받은 일을 한다', async () => {
    const onClick = vi.fn()
    render(<InfoBox title="결과를 보내지 못했어요." action={{ label: '다시 보내기', onClick }} />)

    await userEvent.click(screen.getByRole('button', { name: '다시 보내기' }))

    expect(onClick).toHaveBeenCalledOnce()
  })

  it('행동을 막아 두면 버튼이 꺼진다', () => {
    render(<InfoBox title="안내" action={{ label: '다시 보내기', onClick: () => {}, disabled: true }} />)

    expect(screen.getByRole('button', { name: '다시 보내기' })).toBeDisabled()
  })
})
