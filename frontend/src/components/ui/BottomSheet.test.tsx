import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import { BottomSheet } from './BottomSheet'

/** 쓰는 쪽처럼 `open` 을 들고 있다가, 닫기 알림을 받으면 내린다 */
function Harness() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        열기
      </button>
      <BottomSheet open={open} onClose={() => setOpen(false)} title="서류 첨부하기" description="한 장씩 올려 주세요.">
        <button type="button">파일에서 고르기</button>
      </BottomSheet>
    </>
  )
}

const sheet = () => screen.queryByRole('dialog', { name: '서류 첨부하기' })

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * 손가락으로 아래로 끌었다 놓는다. 반쯤 끈 뒤 한 프레임(16ms) 지나 끝까지 끌어서 속도가 생긴다.
 * `pause` 면 놓기 전에 멈춰서 속도를 0으로 만든다
 */
async function dragDown(target: HTMLElement, distance: number, { pause }: { pause: boolean }) {
  fireEvent.pointerDown(target, { clientY: 0 })
  fireEvent.pointerMove(target, { clientY: distance / 2 })
  await wait(16)
  fireEvent.pointerMove(target, { clientY: distance })
  if (pause) await wait(50)
  fireEvent.pointerUp(target, { clientY: distance })
}

/**
 * 시트가 닫혔는데 쓰는 쪽은 열린 줄 알면, 다음에 [열기]를 눌러도 아무 일이 없다.
 * 닫히는 길(바깥 누르기 · Esc)마다 쓰는 쪽에 알리는지 본다.
 *
 * 시트는 내려가는 움직임이 끝난 뒤에 닫힌다. 그래서 닫혔는지는 기다려서 본다(`waitFor`).
 */
describe('BottomSheet', () => {
  it('열면 제목으로 불리는 시트가 뜨고, 닫혀 있을 때는 없다', () => {
    render(<Harness />)
    expect(sheet()).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '열기' }))

    expect(sheet()).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '파일에서 고르기' })).toBeInTheDocument()
  })

  it('바깥을 누르면 닫고, 다시 열 수 있다', async () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: '열기' }))

    fireEvent.click(sheet()!)
    await waitFor(() => expect(sheet()).not.toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '열기' }))
    expect(sheet()).toBeInTheDocument()
  })

  /** 안쪽을 누를 때마다 닫히면 시트 안의 어떤 버튼도 누를 수 없다 */
  it('안쪽을 누르면 닫지 않는다', () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: '열기' }))

    fireEvent.click(screen.getByRole('button', { name: '파일에서 고르기' }))

    expect(sheet()).toBeInTheDocument()
  })

  /** Esc 는 브라우저가 먼저 `cancel` 을 알린다. 시트가 그걸 막고 쓰는 쪽에 닫기를 알려야 내려가며 닫힌다 */
  it('Esc 를 누르면 쓰는 쪽에 알리고 닫는다', async () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: '열기' }))

    const cancel = new Event('cancel', { cancelable: true })
    fireEvent(sheet()!, cancel)
    // 막지 않으면 브라우저가 움직임 없이 바로 닫아 버린다
    expect(cancel.defaultPrevented).toBe(true)
    await waitFor(() => expect(sheet()).not.toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '열기' }))
    expect(sheet()).toBeInTheDocument()
  })

  /**
   * 휴대폰에서는 시트를 아래로 쓸어내려 닫는 사람이 많다. 조금 건드린 것으로 닫히면 내용을 잃는다.
   *
   * 끈 뒤 잠깐 멈췄다 놓으면 속도가 0이라 거리만으로 정해진다. 테스트는 이벤트 사이에 시간이 흐르지
   * 않아서, 멈추지 않으면 아주 빠르게 튕긴 것으로 잡힌다.
   */
  it('끌어 내린 뒤 멈췄다 놓으면, 많이 끌었을 때만 닫는다', async () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: '열기' }))
    const handle = screen.getByRole('heading', { name: '서류 첨부하기' })

    await dragDown(handle, 60, { pause: true })
    await wait(50)
    expect(sheet()).toBeInTheDocument()

    await dragDown(handle, 150, { pause: true })
    await waitFor(() => expect(sheet()).not.toBeInTheDocument())
  })

  it('짧게 끌어도 빠르게 튕기면 닫는다', async () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: '열기' }))

    await dragDown(screen.getByRole('heading', { name: '서류 첨부하기' }), 60, { pause: false })

    await waitFor(() => expect(sheet()).not.toBeInTheDocument())
  })

  /** Esc 를 연달아 누르면 브라우저가 막지 못하게 하고 바로 닫는다(`close`). 그 알림을 놓치면 다시 열 수 없다 */
  it('브라우저가 먼저 닫아도 쓰는 쪽도 닫힌 것으로 안다', async () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: '열기' }))

    fireEvent(sheet()!, new Event('close'))
    await waitFor(() => expect(sheet()).not.toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '열기' }))
    expect(sheet()).toBeInTheDocument()
  })
})
