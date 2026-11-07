import { afterEach, describe, expect, it, vi } from 'vitest'

import { POSTCODE_SCRIPT_URL, toRoadAddress } from './postcode'

const result = (overrides: Partial<Parameters<typeof toRoadAddress>[0]> = {}) => ({
  roadAddress: '서울 마포구 망원로 52',
  bname: '망원동',
  buildingName: '',
  apartment: 'N' as const,
  ...overrides,
})

/** 서류에 적힌 주소와 맞춰 보기 쉽게 다음 우편번호 안내서의 "참고 항목" 규칙대로 붙인다 */
describe('toRoadAddress', () => {
  it('동·로·가로 끝나는 법정동 이름을 괄호로 붙인다', () => {
    expect(toRoadAddress(result())).toBe('서울 마포구 망원로 52 (망원동)')
  })

  it('공동주택이면 건물 이름도 붙이고, 아니면 붙이지 않는다', () => {
    expect(toRoadAddress(result({ buildingName: '망원아파트', apartment: 'Y' }))).toBe(
      '서울 마포구 망원로 52 (망원동, 망원아파트)',
    )
    expect(toRoadAddress(result({ buildingName: '망원상가', apartment: 'N' }))).toBe('서울 마포구 망원로 52 (망원동)')
  })

  /** 리(里)는 안내서도 붙이지 않는다. 붙일 것이 없으면 괄호를 남기지 않는다 */
  it('붙일 것이 없으면 도로명 주소만 둔다', () => {
    expect(toRoadAddress(result({ bname: '청평리' }))).toBe('서울 마포구 망원로 52')
  })
})

/** 쓰지 않는 사장님은 받지 않고, 쓸 때는 한 번만 받는다. 받다 실패하면 다시 받을 수 있어야 한다 */
describe('loadPostcode', () => {
  afterEach(() => {
    document.head.querySelectorAll(`script[src="${POSTCODE_SCRIPT_URL}"]`).forEach((script) => script.remove())
    vi.resetModules()
    delete window.daum
  })

  it('스크립트를 한 번만 넣고, 받으면 끝난다', async () => {
    const { loadPostcode } = await import('./postcode')
    const first = loadPostcode()
    const second = loadPostcode()
    const scripts = document.head.querySelectorAll(`script[src="${POSTCODE_SCRIPT_URL}"]`)
    expect(scripts).toHaveLength(1)

    window.daum = { Postcode: vi.fn() as never }
    scripts[0].dispatchEvent(new Event('load'))

    await expect(first).resolves.toBeUndefined()
    await expect(second).resolves.toBeUndefined()
  })

  it('받다 실패하면 다음에 다시 받는다', async () => {
    const { loadPostcode } = await import('./postcode')
    const first = loadPostcode()
    document.head.querySelector(`script[src="${POSTCODE_SCRIPT_URL}"]`)!.dispatchEvent(new Event('error'))
    await expect(first).rejects.toThrow()

    void loadPostcode().catch(() => {})
    expect(document.head.querySelectorAll(`script[src="${POSTCODE_SCRIPT_URL}"]`)).toHaveLength(2)
  })
})
