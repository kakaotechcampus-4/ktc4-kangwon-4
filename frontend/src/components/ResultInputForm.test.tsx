import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ResultInputForm } from './ResultInputForm'

function renderForm(value: string, disabled = false) {
  render(
    <ResultInputForm value={value} onChange={() => {}} onSubmit={() => {}} disabled={disabled} />,
  )

  return screen.getByRole('button', { name: '알려주기' })
}

/**
 * 빈 내용이 서버로 나가면 Agent가 판단할 근거 없이 한 턴을 소모한다.
 * 화면에는 제출 경로가 버튼·Ctrl+Enter·"다시 시도" 셋이라 잠금은 값으로 판단해야 한다.
 */
describe('ResultInputForm', () => {
  it('아무것도 입력하지 않으면 보낼 수 없다', () => {
    expect(renderForm('')).toBeDisabled()
  })

  it('공백만 입력하면 보낼 수 없다', () => {
    expect(renderForm('   ')).toBeDisabled()
  })

  it('내용을 입력하면 보낼 수 있다', () => {
    expect(renderForm('임대인이 철거하래요')).toBeEnabled()
  })

  it('보내는 중에는 내용이 있어도 잠긴다', () => {
    expect(renderForm('임대인이 철거하래요', true)).toBeDisabled()
  })
})
