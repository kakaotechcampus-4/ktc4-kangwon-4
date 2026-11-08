import { LazyMotion, MotionConfig } from 'motion/react'
import { RouterProvider } from 'react-router'

import { router } from './routes'

const loadMotionFeatures = () => import('./lib/motionFeatures').then((module) => module.default)

/**
 * 라우터를 띄우는 것 외에 하는 일이 없다.
 *
 * 화면이 필요한 데이터는 각 페이지가 직접 구한다 — 여기서 모아 나눠주면
 * 화면이 늘어날 때마다 이 파일이 커지고, 나중에 fetch를 넣을 자리도 흩어진다.
 *
 * 움직임 도구(Motion)의 설정 두 가지만 여기서 한 번 감싼다.
 *
 * - `LazyMotion`: 화면은 기능을 뺀 가벼운 부품(`m.div`)만 쓰고, 기능 묶음은 첫 화면이 뜬 뒤에 따로
 *   받는다(`lib/motionFeatures.ts`). `strict` 라서 무거운 부품(`motion.div`)을 쓰면 바로 오류가 난다
 * - `MotionConfig reducedMotion="user"`: 기기에서 "동작 줄이기"를 켠 사장님에게는 Motion 움직임도
 *   꺼진다. CSS 움직임의 `motion-safe:` 와 같은 일이다
 */
function App() {
  return (
    <LazyMotion features={loadMotionFeatures} strict>
      <MotionConfig reducedMotion="user">
        <RouterProvider router={router} />
      </MotionConfig>
    </LazyMotion>
  )
}

export default App
