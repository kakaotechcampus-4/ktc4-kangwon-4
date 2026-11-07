import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { AiNotice } from './AiNotice'

/** 사장님이 리본의 안내를 확정된 법률 판단으로 읽지 않게 하는 한 줄이다. 아이콘만 남고 글이 빠지면 뜻이 전해지지 않는다 */
describe('AiNotice', () => {
  it('AI가 정리한 참고용 안내라고 글로 알린다', () => {
    render(<AiNotice />)

    expect(screen.getByText(/리본\(AI\)이 정리한 안내예요/)).toHaveTextContent('법률 자문이 아니에요')
  })

  /** 홈 카드는 좁아 "✦ 리본(AI)"만 보인다. 눈으로 못 보는 사장님도 같은 고지를 들어야 한다 */
  it('짧은 표시도 화면 읽기에는 고지 문장 전체를 준다', () => {
    render(<AiNotice compact />)

    expect(screen.getByText('리본(AI)이 정리한 안내예요. 참고용이며 법률 자문이 아니에요.')).toBeInTheDocument()
    expect(screen.queryByText(/참고용이며/, { selector: ':not(.sr-only)' })).toBeNull()
  })

  /** 화면 폭에 맡기면 "자문이 / 아니에요"처럼 아무 데서나 꺾인다. 문장 사이에서 나눈다 */
  it('두 문장을 줄을 나눠 보여준다', () => {
    render(<AiNotice />)

    expect(screen.getByText(/리본\(AI\)이 정리한 안내예요/).querySelector('br')).not.toBeNull()
  })
})
