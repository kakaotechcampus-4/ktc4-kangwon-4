import type { ReactNode } from 'react'

/**
 * 화면이 쓰는 폭.
 *
 * 기본은 모바일 폭 하나다. `wide` 는 넓은 화면에서 2단으로 나눌 내용이 있는 화면만
 * 쓴다 — 지금은 `/case` 뿐이다. 폼처럼 한 줄로 읽는 화면은 넓혀도 읽기 어려워지기만 한다.
 */
type ShellWidth = 'narrow' | 'wide'

interface AppShellProps {
  title: string
  subtitle?: string
  width?: ShellWidth
  children: ReactNode
}

const WIDTH_STYLE: Record<ShellWidth, { frame: string; main: string }> = {
  narrow: { frame: 'max-w-md border-x border-gray-200', main: 'gap-5 px-4 py-5' },
  // 좁은 화면에서는 720px 까지만 넓힌다. 그 이상은 한 줄이 길어져 읽기 어렵다
  wide: { frame: 'max-w-[720px] lg:max-w-[1120px]', main: 'gap-6 px-4 py-5 lg:px-8 lg:py-8' },
}

/**
 * 모든 화면을 감싸는 껍데기.
 *
 * 모바일 UI 하나로 데스크톱까지 대응한다. 폭을 묶고 가운데 정렬하지 않으면 넓은 화면에서
 * 한 줄이 200자가 되어 읽을 수 없다.
 */
export function AppShell({ title, subtitle, width = 'narrow', children }: AppShellProps) {
  const style = WIDTH_STYLE[width]

  return (
    <div className={`mx-auto flex min-h-dvh flex-col bg-gray-50 ${style.frame}`}>
      <header className="border-b border-gray-200 bg-white px-4 py-3 text-center">
        <h1 className="text-lg font-bold text-gray-900">{title}</h1>
        {subtitle && <p className="mt-0.5 text-xs text-gray-500">{subtitle}</p>}
      </header>

      <main className={`flex flex-col ${style.main}`}>{children}</main>
    </div>
  )
}
