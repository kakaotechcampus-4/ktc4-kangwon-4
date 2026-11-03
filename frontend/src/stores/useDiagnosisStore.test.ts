import { describe, expect, it } from 'vitest'

import { EMPTY_DIAGNOSIS, useDiagnosisStore } from './useDiagnosisStore'

/**
 * 진단은 질문 한 장마다 주소가 바뀐다. 답이 저장소에 남지 않으면 새로고침 한 번에
 * 앞에서 고른 것이 전부 사라지고, 사장님은 처음부터 다시 답해야 한다.
 */
describe('useDiagnosisStore', () => {
  it('고친 답만 바꾸고 나머지 답은 그대로 둔다', () => {
    useDiagnosisStore.getState().setAnswers({ business: 'PERSONAL_CAFE' })
    useDiagnosisStore.getState().setAnswers({ situations: ['LEASE'] })

    expect(useDiagnosisStore.getState().answers).toMatchObject({
      business: 'PERSONAL_CAFE',
      situations: ['LEASE'],
    })
  })

  /**
   * 새로고침은 "저장소에 남은 것을 다시 읽는 것"이다. 고른 답이 저장소에 써지는지와,
   * 저장소에 있는 답을 다시 읽어 오는지를 나눠서 본다.
   */
  it('고른 답을 저장소에 쓴다', () => {
    useDiagnosisStore.getState().setAnswers({ business: 'RESTAURANT' })

    const saved = JSON.parse(window.sessionStorage.getItem('reborn:diagnosis') ?? '{}')
    expect(saved.state.answers.business).toBe('RESTAURANT')
  })

  it('새로고침하면 저장소에 남은 답을 다시 읽는다', async () => {
    window.sessionStorage.setItem(
      'reborn:diagnosis',
      JSON.stringify({
        state: { answers: { ...EMPTY_DIAGNOSIS, business: 'RESTAURANT', franchise: false } },
        version: 0,
      }),
    )

    await useDiagnosisStore.persist.rehydrate()

    expect(useDiagnosisStore.getState().answers).toMatchObject({
      business: 'RESTAURANT',
      franchise: false,
    })
  })

  /** 남아 있으면 가입한 뒤 다시 진단에 들어왔을 때 지난 답으로 시작한다 */
  it('비우면 처음 상태로 돌아가고 저장소에도 남지 않는다', async () => {
    useDiagnosisStore.getState().setAnswers({ business: 'PERSONAL_CAFE', fullTimeCount: 2 })

    useDiagnosisStore.getState().reset()
    await useDiagnosisStore.persist.rehydrate()

    expect(useDiagnosisStore.getState().answers).toEqual(EMPTY_DIAGNOSIS)
  })
})
