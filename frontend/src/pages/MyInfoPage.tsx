import { TopBar } from '../components/ui/TopBar'

/**
 * 내 정보. 탭 화면 머리말의 사람 버튼으로 들어온다.
 *
 * 전에는 이 자리가 알림이었다. 알림 API가 없어 빈 화면만 있었고, 화면 쪽 알림(#311)은
 * 써 보니 흐름에 보탬이 적어 접었다. 대신 비어 있던 두 가지 — 저장된 가게 정보를 다시 볼 곳과
 * 로그아웃 — 를 여기 둔다.
 */
export function MyInfoPage() {
  return (
    <div className="screen-frame mx-auto flex min-h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <TopBar title="내 정보" />
      <main className="flex flex-1 flex-col" />
    </div>
  )
}
