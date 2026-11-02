import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { IntroCarousel } from './IntroCarousel'

const heading = () => screen.getByRole('heading', { level: 1 })
const prev = () => screen.getByRole('button', { name: '이전 소개' })
const next = () => screen.getByRole('button', { name: '다음 소개' })

/**
 * 막대 움직임이 끝났다는 신호를 보낸다.
 *
 * jsdom은 CSS 움직임을 돌리지 않으니 신호를 직접 보내야 한다. 그런데 `fireEvent.animationEnd`는
 * 닿지 않는다 — jsdom에 `AnimationEvent`가 없어서 React가 표준 이름 대신 옛 브라우저용
 * 이름(`webkitAnimationEnd`)을 듣기 때문이다. 실제 브라우저에서는 표준 이름을 듣는다.
 */
function finishProgress() {
  fireEvent(screen.getByTestId('intro-progress'), new Event('webkitAnimationEnd', { bubbles: true }))
}

/**
 * 소개는 로그인 버튼 위에 놓인다. 넘김이 고장 나면 사장님은 첫 장만 보고 시작하거나,
 * 저절로 넘어가다 마지막 장을 지나쳐 빈 화면을 본다.
 */
describe('IntroCarousel', () => {
  it('첫 장에서 시작하고, 앞 장으로는 갈 수 없다', () => {
    render(<IntroCarousel />)

    expect(heading()).toHaveTextContent(/순서대로/)
    expect(prev()).toBeDisabled()
  })

  it('누르면 다음 장, 다시 앞으로 누르면 앞 장으로 간다', () => {
    render(<IntroCarousel />)

    fireEvent.click(next())
    expect(heading()).toHaveTextContent(/리본이 먼저/)

    fireEvent.click(prev())
    expect(heading()).toHaveTextContent(/순서대로/)
  })

  it('막대가 다 차면 다음 장으로 넘어간다', () => {
    render(<IntroCarousel />)

    finishProgress()

    expect(heading()).toHaveTextContent(/리본이 먼저/)
  })

  /** 넘어갈 곳이 없는데 넘기면 장 번호가 목록 밖으로 나가 아무것도 그리지 못한다 */
  it('마지막 장에서는 막대가 다 차도 그대로 있다', () => {
    render(<IntroCarousel />)
    for (let k = 0; k < 3; k += 1) fireEvent.click(next())

    finishProgress()

    expect(heading()).toHaveTextContent(/사장님이 직접/)
    expect(next()).toBeDisabled()
  })
})
