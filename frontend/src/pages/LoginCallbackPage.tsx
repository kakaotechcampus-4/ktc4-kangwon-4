import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { AppShell } from '../components/AppShell'
import { postLogin } from '../lib/api'
import { saveTokens } from '../lib/auth'

/**
 * 카카오가 사용자를 돌려보내는 자리. 인증 가드 밖에 둔다 — 아직 로그인 전이다.
 *
 * 사용자가 볼 일이 거의 없는 화면이다. 성공하면 곧바로 진입 분기로 넘어가고,
 * 남아 있는 것은 실패했을 때뿐이다.
 *
 * 카카오는 실패해도 이 주소로 돌려보낸다 — 로그인 창에서 "취소"를 누른 경우가 그렇다.
 * 그때는 `code` 대신 `error`가 붙어 오므로, `code`가 없다는 것만 보면 둘 다 걸러진다.
 * 사용자에게는 어느 쪽이든 "로그인이 안 됐다" 하나이고 할 수 있는 일도 다시 시도뿐이다.
 *
 * `state`가 어긋난 경우도 같은 실패로 묶는다. 우리가 시작하지 않은 로그인이라는 뜻인데,
 * 그걸 설명해도 사용자가 할 수 있는 일은 역시 다시 로그인뿐이다.
 */
export function LoginCallbackPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [failed, setFailed] = useState(false)

  const code = params.get('code')

  // 우리가 보낸 값이 그대로 실려 돌아온다. 맞춰보는 것은 `postLogin` 이 한다
  const state = params.get('state')

  /**
   * `code`는 한 번만 쓸 수 있다.
   *
   * React는 개발 중 effect를 일부러 두 번 실행해 정리 누락을 드러낸다. 그대로 두면
   * 두 번째 호출이 이미 쓴 `code`로 들어가 실패하고, 화면에는 실패만 남는다.
   * 그래서 한 번 보냈으면 다시 보내지 않는다.
   */
  const sent = useRef(false)

  useEffect(() => {
    // 주소에 code 가 없으면 보낼 것이 없다. 그건 렌더 중에 알 수 있어 상태로 두지 않는다
    if (sent.current || code === null) return

    sent.current = true

    postLogin(code, state)
      .then(({ accessToken, refreshToken }) => {
        saveTokens(accessToken, refreshToken)
        // 다 쓴 code 가 주소에 남아 있어, 뒤로 가면 실패한 로그인을 다시 시도하게 된다
        navigate('/', { replace: true })
      })
      .catch(() => {
        setFailed(true)
      })
  }, [code, state, navigate])

  if (failed || code === null) {
    return (
      <AppShell title="로그인하지 못했습니다">
        <section className="rounded-2xl bg-white p-5">
          <p className="text-base leading-relaxed text-gray-600">
            로그인이 완료되지 않았습니다. 잠시 후 다시 시도해 주세요.
          </p>
        </section>

        <Link
          to="/login"
          replace
          className="flex min-h-13 w-full items-center justify-center rounded-xl bg-gray-900 text-base font-bold text-white"
        >
          다시 로그인하기
        </Link>
      </AppShell>
    )
  }

  return (
    <AppShell title="로그인 중입니다">
      <section className="rounded-2xl bg-white p-5" role="status" aria-live="polite">
        <p className="text-base leading-relaxed text-gray-600">잠시만 기다려 주세요.</p>
      </section>
    </AppShell>
  )
}
