import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ChangeList } from './ChangeList'

/**
 * `UNKNOWN`은 "없음"이 아니라 "아직 확인되지 않음"이다(`/CLAUDE.md` 용어).
 * 이전 값이 비어 있다고 빈 칸으로 두면 확인된 적 없는 항목이 확인된 것처럼 읽힌다.
 */
describe('ChangeList', () => {
  it('이전 값이 없으면 미확인으로 보여준다', () => {
    render(
      <ChangeList
        changes={[
          { key: 'demolition_required', label: '철거 필요 여부', previousValue: null, newValue: '필요함' },
        ]}
      />,
    )

    expect(screen.getByText('미확인')).toBeInTheDocument()
    expect(screen.getByText('필요함')).toBeInTheDocument()
  })

  it('이전 값이 있으면 그 값을 그대로 보여준다', () => {
    render(
      <ChangeList
        changes={[
          {
            key: 'demolition_required',
            label: '철거 필요 여부',
            previousValue: '필요 없음',
            newValue: '필요함',
          },
        ]}
      />,
    )

    expect(screen.getByText('필요 없음')).toBeInTheDocument()
    expect(screen.queryByText('미확인')).not.toBeInTheDocument()
  })
})
