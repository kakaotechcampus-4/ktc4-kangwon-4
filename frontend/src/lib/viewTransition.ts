import { useLayoutEffect } from 'react'
import { useNavigationType } from 'react-router'

/**
 * 화면 이동이 앞으로 가는지 뒤로 가는지를 `<html data-nav>` 에 적는다.
 *
 * 화면 이동 움직임은 브라우저의 화면 전환 기능(View Transitions)이 그린다. 라우터는 이동에
 * `viewTransition` 을 켜면 그 기능을 부르고, 그 화면에서 뒤로 돌아올 때도 같은 전환을 다시 켠다.
 * 앱의 [뒤로]든 브라우저 뒤로 가기든 같다.
 * 그런데 방향은 알려주지 않는다. 그래서 여기서 방향을 적고, `index.css` 가 그 값을 보고
 * 새 화면을 오른쪽에서 밀어 넣을지(앞으로), 지금 화면을 오른쪽으로 밀어낼지(뒤로) 고른다.
 *
 * 그리기 직후(`useLayoutEffect`)에 적는다. 브라우저는 새 화면이 그려진 뒤에 움직임을 시작하므로,
 * 그 전에 값이 바뀌어 있다.
 */
export function useNavigationDirection() {
  const type = useNavigationType()

  useLayoutEffect(() => {
    document.documentElement.dataset.nav = type === 'POP' ? 'back' : 'forward'
  }, [type])
}
