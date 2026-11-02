import { Navigate, useLocation, useNavigate } from 'react-router'

import kakaoSymbolUrl from '../assets/brand/kakao-symbol.svg'
import { IntroCarousel } from '../components/IntroCarousel'
import { Button } from '../components/ui/Button'
import { loginFormUrl } from '../lib/api'
import { createOAuthState, isLoggedIn, logInWithMock } from '../lib/auth'
import { MOCK_SWITCH_ENABLED } from '../lib/mockSwitch'

/**
 * 로그인. 인증 가드 밖에 있는 유일한 화면이다.
 *
 * 소개 네 장 아래에 카카오 버튼을 둔다. 시안은 소개 뒤 [시작하기]로 바로 상황 진단에
 * 들어가는데, 진단 답을 저장하려면 로그인이 먼저라 시작 버튼 자리를 로그인으로 바꿨다.
 * 진단을 먼저 하고 마지막에 로그인하면, 카카오로 나갔다 돌아오는 사이에 답을 들고 있어야 한다.
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
    <div className="mx-auto flex h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <IntroCarousel />

      <div className="flex shrink-0 flex-col gap-2 px-4 pt-3 pb-8.5">
        {/*
          카카오 로그인 버튼은 카카오 디자인 가이드를 따른다. 바탕 #FEE500, 심볼 #000000,
          글자 검정 85%, 모서리 12px(`rounded-xl`)이라 공통 버튼(`Button`)을 쓰지 않는다.
          폭을 넓힐 때는 심볼과 글자 크기는 두고 좌우 여백만 늘린다 — 심볼은 공식 버튼
          (46px 높이에 13px)의 비율대로 56px 높이에 16px로 둔다.

          문구 "카카오로 시작하기"는 가이드의 기본 문구("카카오 로그인")가 아니다. 소개를 보고
          누르는 시작 버튼이라 이 문구로 두기로 했다(11/03). 가이드가 금지하는 문구는 아니다.
        */}
        <button
          type="button"
          onClick={handleKakaoLogin}
          className="flex h-14 w-full cursor-pointer items-center justify-center gap-2 rounded-xl bg-[#FEE500] text-18 font-bold text-black/85"
        >
          <img src={kakaoSymbolUrl} alt="" className="size-4" />
          카카오로 시작하기
        </button>

        {/*
          카카오는 돌아올 주소를 정확히 일치하는 것만 허용해서, 주소가 매번 다른 feature 브랜치
          Preview 에서는 진짜 로그인을 할 수 없다. 리뷰어가 화면을 보려면 우회로가 필요하다.
          Production 빌드에서는 이 블록 자체가 사라진다.
        */}
        {MOCK_SWITCH_ENABLED && (
          <Button variant="outline" onClick={handleMockLogin}>
            가짜로 로그인 (미리보기용)
          </Button>
        )}
      </div>
    </div>
  )
}
