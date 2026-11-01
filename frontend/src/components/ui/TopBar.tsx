import { IconChevronLeftLine } from '@karrotmarket/react-monochrome-icon'
import { useLocation, useNavigate } from 'react-router'

interface TopBarProps {
  title: string
}

/**
 * 탭 없는 화면의 머리말. 왼쪽에 뒤로 버튼, 가운데에 화면 이름.
 *
 * 뒤로 버튼은 48px다. 시안은 44px지만 중장년 사용자를 위해 터치 영역을 48px 이상으로 둔다(UI 가이드라인).
 *
 * 뒤로 버튼은 브라우저의 뒤로 가기와 같다. 다만 주소로 바로 들어와 앱 안에 돌아갈 곳이
 * 없으면 홈(`/`)으로 보낸다. 그대로 뒤로 가면 앱을 떠나 버린다.
 * React Router는 처음 연 화면의 `location.key`를 `'default'`로 둔다.
 */
export function TopBar({ title }: TopBarProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const hasHistory = location.key !== 'default'

  return (
    <header className="grid h-14 shrink-0 grid-cols-[48px_1fr_48px] items-center px-1">
      <button
        type="button"
        aria-label="뒤로"
        onClick={() => (hasHistory ? navigate(-1) : navigate('/', { replace: true }))}
        className="grid size-12 cursor-pointer place-items-center rounded-lg text-fg-neutral active:bg-bg-transparent-pressed"
      >
        <IconChevronLeftLine size={24} aria-hidden="true" />
      </button>
      <h1 className="text-center text-18 font-bold">{title}</h1>
    </header>
  )
}
