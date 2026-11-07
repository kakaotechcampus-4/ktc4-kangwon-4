import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PillChoices, QuestionScreen } from './QuestionScreen'

const TITLE = { pre: '', highlight: '어떤 가게', post: '를\n정리하시나요?' }
const OPTIONS = [
  { value: 'A', label: '개인 카페' },
  { value: 'B', label: '다른 음식점' },
]
const ACTION = { label: '다음', onClick: () => {} }

/**
 * 질문 부품은 받은 것을 그리기만 한다. 여기서 고른 표시가 틀리면 사장님은 무엇을
 * 골랐는지 모른 채 넘어가고, 누른 보기가 위로 전해지지 않으면 답이 저장되지 않는다.
 */
describe('QuestionScreen', () => {
  it('하나만 고르는 보기는 고른 것만 선택됨으로 표시하고, 누른 보기를 알린다', () => {
    const onSelect = vi.fn()
    render(
      <QuestionScreen
        position={{ current: 1, total: 5 }}
        title={TITLE}
        sub=""
        input={{ type: 'list', options: OPTIONS, selected: 'A', onSelect }}
        action={ACTION}
      />,
    )

    expect(screen.getByRole('radio', { name: /개인 카페/ })).toBeChecked()
    expect(screen.getByRole('radio', { name: /다른 음식점/ })).not.toBeChecked()

    fireEvent.click(screen.getByRole('radio', { name: /다른 음식점/ }))
    expect(onSelect).toHaveBeenCalledWith('B')
  })

  it('여럿 고르는 보기는 고른 것마다 눌림으로 표시하고, 누른 보기를 알린다', () => {
    const onToggle = vi.fn()
    render(
      <QuestionScreen
        position={{ current: 2, total: 5 }}
        title={TITLE}
        sub=""
        input={{ type: 'grid', options: OPTIONS, selected: ['B'], onToggle }}
        action={ACTION}
      />,
    )

    expect(screen.getByRole('button', { name: /다른 음식점/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /개인 카페/ })).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(screen.getByRole('button', { name: /개인 카페/ }))
    expect(onToggle).toHaveBeenCalledWith('A')
  })

  /** 0명에서 빼기가 열려 있으면 -1명이 되고, 상한에서 더하기가 열려 있으면 서버가 거절한다 */
  it('스테퍼는 0명이면 빼기를, 상한이면 더하기를 잠근다', () => {
    const onIncrease = vi.fn()
    render(
      <QuestionScreen
        position={{ current: 3, total: 5 }}
        title={TITLE}
        sub=""
        input={{
          type: 'stepper',
          rows: [
            { label: '정직원', sub: '', value: 0, onDecrease: () => {}, onIncrease },
            { label: '아르바이트', sub: '', value: 3, onDecrease: () => {}, onIncrease: () => {}, increaseDisabled: true },
          ],
        }}
        action={ACTION}
      />,
    )

    expect(screen.getByRole('button', { name: '정직원 빼기' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '아르바이트 더하기' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '정직원 더하기' }))
    expect(onIncrease).toHaveBeenCalled()
  })

  it('아래 버튼을 잠그라고 하면 누를 수 없다', () => {
    render(
      <QuestionScreen
        position={{ current: 1, total: 5 }}
        title={TITLE}
        sub=""
        input={{ type: 'pills', options: OPTIONS, selected: null, onSelect: () => {} }}
        action={{ ...ACTION, disabled: true }}
      />,
    )

    expect(screen.getByRole('button', { name: '다음' })).toBeDisabled()
  })

  /** 첫 질문에서 뒤로를 누르면 돌아갈 화면이 없다 */
  it('돌아갈 곳을 주지 않으면 뒤로 버튼을 두지 않는다', () => {
    render(
      <QuestionScreen
        position={{ current: 1, total: 5 }}
        title={TITLE}
        sub=""
        input={{ type: 'pills', options: OPTIONS, selected: null, onSelect: () => {} }}
        action={ACTION}
      />,
    )

    expect(screen.queryByRole('button', { name: '뒤로' })).not.toBeInTheDocument()
  })
})

/**
 * 진단 질문 밖(결과 입력의 원상복구 답, #197)에서도 쓰는 글자 보기. 묶음 제목으로 무엇을 고르는지
 * 읽혀야 하고, 보내는 중에는 고른 것을 바꿀 수 없어야 한다 — 바뀌면 보낸 것과 화면이 어긋난다.
 */
describe('PillChoices', () => {
  function renderPills({ selected = null, disabled }: { selected?: 'A' | 'B' | null; disabled?: boolean } = {}) {
    const onSelect = vi.fn()
    render(
      <>
        <p id="pill-title">원상복구 범위</p>
        <PillChoices
          options={OPTIONS as { value: 'A' | 'B'; label: string }[]}
          selected={selected}
          onSelect={onSelect}
          labelledBy="pill-title"
          disabled={disabled}
        />
      </>,
    )
    return onSelect
  }

  it('묶음 제목으로 읽히고, 고른 것만 선택됨으로 표시하고, 누른 보기를 알린다', () => {
    const onSelect = renderPills({ selected: 'A' })

    expect(screen.getByRole('radiogroup', { name: '원상복구 범위' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '개인 카페' })).toBeChecked()
    expect(screen.getByRole('radio', { name: '다른 음식점' })).not.toBeChecked()

    fireEvent.click(screen.getByRole('radio', { name: '다른 음식점' }))
    expect(onSelect).toHaveBeenCalledWith('B')
  })

  it('잠그면 고를 수 없다', () => {
    const onSelect = renderPills({ disabled: true })

    fireEvent.click(screen.getByRole('radio', { name: '다른 음식점' }))
    expect(screen.getByRole('radio', { name: '다른 음식점' })).toBeDisabled()
    expect(onSelect).not.toHaveBeenCalled()
  })
})
