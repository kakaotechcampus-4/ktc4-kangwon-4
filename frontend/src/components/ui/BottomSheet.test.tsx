import { fireEvent, render, screen } from '@testing-library/react'
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

/**
 * 시트가 닫혔는데 쓰는 쪽은 열린 줄 알면, 다음에 [열기]를 눌러도 아무 일이 없다.
 * 닫히는 길(바깥 누르기 · Esc)마다 쓰는 쪽에 알리는지 본다.
 */
describe('BottomSheet', () => {
  it('열면 제목으로 불리는 시트가 뜨고, 닫혀 있을 때는 없다', () => {
    render(<Harness />)
    expect(sheet()).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '열기' }))

    expect(sheet()).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '파일에서 고르기' })).toBeInTheDocument()
  })

  it('바깥을 누르면 닫고, 다시 열 수 있다', () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: '열기' }))

    fireEvent.click(sheet()!)
    expect(sheet()).not.toBeInTheDocument()

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

  /** Esc 는 브라우저가 `<dialog>` 를 닫고 `close` 를 알린다. 그 알림을 놓치면 다시 열 수 없다 */
  it('브라우저가 닫으면(Esc) 쓰는 쪽도 닫힌 것으로 안다', () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: '열기' }))

    fireEvent(sheet()!, new Event('close'))
    expect(sheet()).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '열기' }))
    expect(sheet()).toBeInTheDocument()
  })
})
