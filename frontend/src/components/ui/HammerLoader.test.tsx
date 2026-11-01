import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { HammerLoader } from './HammerLoader'

/**
 * 망치는 그림이라 화면 읽기 프로그램 사용자에게는 아무것도 전달하지 않는다.
 * 기다리는 중이라는 사실은 상태 알림으로 따로 전해야 한다.
 */
describe('HammerLoader', () => {
  it('기다리는 중임을 상태 알림으로 전한다', () => {
    render(<HammerLoader size={40} label="폐업 순서를 정리하는 중" />)

    expect(screen.getByRole('status')).toHaveTextContent('폐업 순서를 정리하는 중')
  })

  it('망치 그림은 꾸밈이라 따로 읽지 않는다', () => {
    render(<HammerLoader size={40} />)

    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })
})
