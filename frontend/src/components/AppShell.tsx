import type { ReactNode } from 'react'

interface AppShellProps {
  title: string
  subtitle?: string
  children: ReactNode
}

/**
 * 모든 화면을 감싸는 껍데기.
 *
 * 모바일 UI 하나로 데스크톱까지 대응한다. `max-w-md`로 폭을 묶고 가운데 정렬하지 않으면
 * 넓은 화면에서 한 줄이 200자가 되어 읽을 수 없다.
 */
export function AppShell({ title, subtitle, children }: AppShellProps) {
  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col bg-gray-50">
      <header className="border-b border-gray-200 bg-white px-4 py-3 text-center">
        <h1 className="text-lg font-bold text-gray-900">{title}</h1>
        {subtitle && <p className="mt-0.5 text-xs text-gray-500">{subtitle}</p>}
      </header>

      <main className="flex flex-col gap-5 px-4 py-5">{children}</main>
    </div>
  )
}
