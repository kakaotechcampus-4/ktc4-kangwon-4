import { Navigate, useLocation, useNavigate } from 'react-router'

import { AppShell } from '../components/AppShell'
import { loginFormUrl } from '../lib/api'
import { createOAuthState, isLoggedIn, logInWithMock } from '../lib/auth'
import { MOCK_SWITCH_ENABLED } from '../lib/mockSwitch'

/**
 * 로그인. 인증 가드 밖에 있는 유일한 화면이다.
 *
 * 카카오 하나만 둔다. 고를 것이 없으면 잘못 고를 일도 없다.
 *
 * 로그아웃한 사용자가 여기로 오는 길은 따로 만들지 않는다. `RequireAuth`가 보호된
 * 경로를 전부 막고 있어서, 로그인 상태가 풀리면 다음 이동에서 저절로 이 화면에 닿는다.
 *
 * 카카오로 넘어갔다가 `/login/callback`으로 돌아온다.
 */
export function LoginPage() {
  const navigate = useNavigate()
  const { search } = useLocation()

  // 이미 로그인한 사용자에게 로그인 버튼을 다시 보여줄 이유가 없다.
  // 뒤로가기로는 닿을 수 없고 주소를 직접 열었을 때만 생기는 경로다
  if (isLoggedIn(search)) return <Navigate to={{ pathname: '/', search }} replace />

  /**
   * 라우터가 아니라 브라우저를 움직인다. 우리 화면 안에서 이동하는 것이 아니라
   * 카카오라는 다른 사이트로 나가는 것이라, 서버가 주는 303을 브라우저가 따라가야 한다.
   *
   * 나가기 직전에 state 를 만든다. 화면을 열 때 만들면, 열어두고 한참 뒤에 누른 탭이나
   * 두 탭을 번갈아 쓴 경우에 먼저 만든 값이 덮여 로그인이 막힌다.
   */
  function handleKakaoLogin() {
    window.location.assign(loginFormUrl(createOAuthState()))
  }

  function handleMockLogin() {
    logInWithMock()
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
        onClick={handleKakaoLogin}
        className="flex min-h-13 w-full items-center justify-center rounded-xl bg-[#FEE500] text-base font-bold text-black/85"
      >
        카카오로 시작하기
      </button>

      {/*
        카카오는 돌아올 주소를 정확히 일치하는 것만 허용해서, 주소가 매번 다른 feature 브랜치
        Preview 에서는 진짜 로그인을 할 수 없다. 리뷰어가 화면을 보려면 우회로가 필요하다.
        Production 빌드에서는 이 블록 자체가 사라진다.
      */}
      {MOCK_SWITCH_ENABLED && (
        <button
          type="button"
          onClick={handleMockLogin}
          className="flex min-h-13 w-full items-center justify-center rounded-xl border border-gray-300 bg-white text-base font-bold text-gray-600"
        >
          가짜로 로그인 (미리보기용)
        </button>
      )}
    </AppShell>
  )
}
