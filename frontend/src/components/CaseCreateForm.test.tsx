import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { CaseDraft } from '../types/view'
import { CaseCreateForm } from './CaseCreateForm'

const EMPTY: CaseDraft = {
  businessType: '',
  franchiseStatus: null,
  leaseStatus: null,
  employeeCount: '',
  plannedClosureDate: '',
}

/** 필수 세 가지를 모두 채운 상태. 선택 두 가지는 비워 둔다 */
const FILLED: CaseDraft = {
  ...EMPTY,
  businessType: '카페',
  franchiseStatus: false,
  leaseStatus: 'LEASED_PAID',
}

function renderForm(value: CaseDraft, disabled = false, onChange = () => {}) {
  render(
    <CaseCreateForm value={value} onChange={onChange} onSubmit={() => {}} disabled={disabled} />,
  )

  return screen.getByRole('button', { name: '시작하기' })
}

/**
 * 필수 항목이 빈 채로 나가면 서버가 422로 막는다. 사용자에게는 "눌렀는데 아무 일이
 * 없다"로 보이고, 어느 칸이 문제인지는 알려주지 못한다.
 *
 * 반대로 선택 항목까지 막으면 모르는 것을 지어내 적게 된다. 직원 수와 폐업 예정일은
 * 사장님도 아직 모를 수 있는 값이라 비운 채로 통과해야 한다.
 */
describe('CaseCreateForm', () => {
  it('아무것도 채우지 않으면 시작할 수 없다', () => {
    expect(renderForm(EMPTY)).toBeDisabled()
  })

  it('업종만 채우면 아직 시작할 수 없다', () => {
    expect(renderForm({ ...EMPTY, businessType: '카페' })).toBeDisabled()
  })

  it('점포 형태를 고르지 않으면 시작할 수 없다', () => {
    expect(renderForm({ ...FILLED, leaseStatus: null })).toBeDisabled()
  })

  it('업종에 공백만 넣으면 시작할 수 없다', () => {
    expect(renderForm({ ...FILLED, businessType: '   ' })).toBeDisabled()
  })

  it('필수 세 가지를 채우면 직원 수와 예정일이 비어 있어도 시작할 수 있다', () => {
    expect(renderForm(FILLED)).toBeEnabled()
  })

  /**
   * `franchiseStatus`가 `false`인 상태는 "아니오를 골랐다"지 "안 골랐다"가 아니다.
   * 값을 truthy로 판단하면 프랜차이즈가 아닌 사장님은 영원히 시작하지 못한다.
   */
  it('프랜차이즈가 아니라고 골라도 시작할 수 있다', () => {
    expect(renderForm({ ...FILLED, franchiseStatus: false })).toBeEnabled()
  })

  it('보내는 중에는 다 채웠어도 잠긴다', () => {
    expect(renderForm(FILLED, true)).toBeDisabled()
  })

  /** 고른 값이 그대로 올라오지 않으면 화면만 멀쩡하고 서버에는 엉뚱한 값이 간다 */
  it('선택지를 고르면 그 값을 그대로 올려보낸다', () => {
    const onChange = vi.fn()
    renderForm(EMPTY, false, onChange)

    fireEvent.click(screen.getByRole('radio', { name: /아니에요/ }))

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ franchiseStatus: false }))
  })
})
