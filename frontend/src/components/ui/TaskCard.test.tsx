import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Button } from './Button'
import { TaskCard } from './TaskCard'

describe('TaskCard', () => {
  it('할 일은 화면 제목 아래의 소제목으로 읽힌다', () => {
    render(
      <TaskCard
        tone="brand"
        icon={<span />}
        badge="사장님 할 일"
        title="임대인에게 원상복구 범위를 물어보세요"
        actions={<Button size="lg">결과 알려주기</Button>}
      />,
    )

    expect(
      screen.getByRole('heading', { level: 2, name: '임대인에게 원상복구 범위를 물어보세요' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '결과 알려주기' })).toBeEnabled()
  })
})
