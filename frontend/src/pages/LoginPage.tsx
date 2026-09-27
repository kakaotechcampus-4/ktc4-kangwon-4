import { Navigate, useLocation, useNavigate } from 'react-router'

import { AppShell } from '../components/AppShell'
import { isLoggedIn, logIn } from '../lib/auth'

/**
 * 로그인. 인증 가드 밖에 있는 유일한 화면이다.
 *
 * 카카오 하나만 둔다. 고를 것이 없으면 잘못 고를 일도 없다.
 *
 * 로그아웃한 사용자가 여기로 오는 길은 따로 만들지 않는다. `RequireAuth`가 보호된
 * 경로를 전부 막고 있어서, 로그인 상태가 풀리면 다음 이동에서 저절로 이 화면에 닿는다.
 *
 * TODO(API): 실제 흐름은 `GET /login/form`이 카카오로 303 리다이렉트하는 구조라
 * `fetch`로 부를 수 없다 — 리다이렉트가 CORS에 막힌다. `window.location`으로 이동해야 한다.
 * 카카오가 돌려주는 `code`를 FE와 BE 중 누가 받는지(`redirect_uri`)는 아직 확인 중이다.
 */
export function LoginPage() {
  const navigate = useNavigate()
  const { search } = useLocation()

  // 이미 로그인한 사용자에게 로그인 버튼을 다시 보여줄 이유가 없다.
  // 뒤로가기로는 닿을 수 없고 주소를 직접 열었을 때만 생기는 경로다
  if (isLoggedIn(search)) return <Navigate to={{ pathname: '/', search }} replace />

  function handleLogin() {
    logIn()
    // 로그인한 화면이 뒤로가기에 남으면 다시 돌아와 로그인 버튼을 마주한다
    navigate('/', { replace: true })
  }

  return (
    <AppShell title="RE:BORN" subtitle="폐업 준비, 다음 할 일 하나씩">
      <section className="rounded-2xl bg-white p-5">
        <p className="text-base leading-relaxed text-gray-700">
          정리해야 할 일이 많지만, 한 번에 하나씩만 알려드립니다.
        </p>
        <p className="mt-2 text-base leading-relaxed text-gray-700">
          카카오 계정으로 시작하면 진행 상황이 저장됩니다.
        </p>
      </section>

      {/*
        카카오 로그인 버튼은 색·문구·비율에 공식 가이드라인이 있다.
        배경 #FEE500, 글자 검정 85%는 그 규정을 따른 값이라 임의로 바꾸지 않는다.
        TODO: 공식 심볼 이미지를 받아 글자 왼쪽에 넣는다.
      */}
      <button
        type="button"
        onClick={handleLogin}
        className="flex min-h-13 w-full items-center justify-center rounded-xl bg-[#FEE500] text-base font-bold text-black/85"
      >
        카카오로 시작하기
      </button>
    </AppShell>
  )
}
