import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ProcessSteps } from './ProcessSteps'

describe('ProcessSteps', () => {
  it('단계마다 상태를 글자로 함께 보여준다', () => {
    render(
      <ProcessSteps
        steps={[
          { label: '보냈어요', status: 'done' },
          { label: '정리하고 있어요', status: 'run' },
          { label: '다음 할 일 다시 정하기', status: 'wait' },
        ]}
      />,
    )

    const [sent, working, next] = screen.getAllByRole('listitem')
    expect(within(sent).getByText('완료')).toBeInTheDocument()
    expect(within(working).getByText('처리 중')).toBeInTheDocument()
    expect(within(next).getByText('대기')).toBeInTheDocument()
  })

  /** 위쪽 큰 망치가 이미 알린다. 같은 말을 두 번 읽지 않게 한다 */
  it('하는 중인 줄의 망치는 화면 읽기 프로그램에 알리지 않는다', () => {
    render(<ProcessSteps steps={[{ label: '정리하고 있어요', status: 'run' }]} />)

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
