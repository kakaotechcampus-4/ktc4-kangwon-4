/**
 * 테스트 전역 설정.
 *
 * `toBeDisabled`, `toBeInTheDocument` 같은 DOM 단언을 쓰려면 matcher를 등록해야 한다.
 * `/vitest` 진입점은 등록과 타입 확장을 함께 해준다 — 이것 없이는 타입 검사에서 막힌다.
 */
import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { MotionGlobalConfig } from 'motion/react'
import { afterEach } from 'vitest'

import { useDiagnosisStore } from './stores/useDiagnosisStore'

/**
 * jsdom 에는 `<dialog>` 의 `showModal()`·`close()` 가 없다(시트 `BottomSheet` 가 쓴다).
 *
 * 브라우저가 하는 것 중 화면이 기대는 두 가지만 흉내 낸다 — 열면 `open` 이 서고, 닫으면
 * `open` 이 내려가며 `close` 를 알린다. 포커스 가두기·뒤 화면 막기는 흉내 내지 않아서,
 * 그 동작은 브라우저에서 눈으로 확인한다.
 */
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true
  }
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    if (!this.open) return
    this.open = false
    this.dispatchEvent(new Event('close'))
  }
}

/**
 * 테스트는 움직임을 보지 않는다. Motion 움직임은 기다리지 않고 바로 끝낸다.
 *
 * 움직임이 끝난 뒤에 일어나는 일(시트가 내려간 뒤 닫히기)은 그래도 한 박자 뒤에 일어나서,
 * 테스트는 `waitFor` 로 기다린다. 움직임 자체는 브라우저에서 눈으로 확인한다.
 */
MotionGlobalConfig.skipAnimations = true

/**
 * 렌더한 화면을 테스트마다 걷어낸다.
 *
 * Testing Library는 `afterEach`가 전역에 있을 때만 이 정리를 스스로 건다.
 * 이 프로젝트는 `describe`·`it`을 명시적으로 import하는 쪽이라 전역이 없어서 직접 건다.
 * 없으면 앞 테스트의 화면이 남아 같은 역할이 여러 개로 잡힌다.
 */
afterEach(cleanup)

/**
 * 로그인 여부와 Case 유무를 `sessionStorage`에 두고 있어서, 지우지 않으면 앞 테스트의
 * 상태가 다음 테스트로 샌다. 화면이 실제로 어떤 판단을 하는지가 실행 순서에 따라
 * 달라지므로, 통과하던 테스트가 파일 하나 추가했다고 깨진다.
 */
afterEach(() => {
  window.sessionStorage.clear()
})

/**
 * 진단 답은 저장소만이 아니라 메모리(Zustand)에도 들고 있다. 저장소를 지워도 메모리에
 * 남은 답이 다음 테스트의 첫 화면에 그대로 나온다.
 *
 * 저장소를 지우는 위 정리보다 뒤에 둔다. 비우는 순간 저장소에 빈 답을 한 번 쓰는데,
 * 그것까지 남기지 않으려면 지우기가 마지막이어야 한다 — `afterEach`는 나중에 건 것이
 * 먼저 돈다.
 */
afterEach(() => {
  useDiagnosisStore.getState().reset()
})
