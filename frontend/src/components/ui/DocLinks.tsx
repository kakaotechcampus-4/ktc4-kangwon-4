/**
 * 앱 밖 정적 문서(`public/`)로 가는 작은 링크 줄. 로그인 화면과 내 정보 화면 아래에 둔다.
 *
 * 라우터 `Link`로 옮기면 앱 안에서 그 주소를 찾다가 모르는 경로라 홈으로 가 버려서, 브라우저가
 * 문서를 받아 오게 `<a>`를 쓴다. 글자는 작게 두고 누르는 영역만 높이 44px(`min-h-11`)로 둔다.
 * 375px 폭에서 세 링크가 한 줄에 들어가게 옆 여백을 줄였다. 더 좁으면 다음 줄로 넘긴다.
 */
const DOC_LINKS = [
  { href: '/safety/policy/', label: '개인정보처리방침' },
  { href: '/safety/', label: '운영철학과 안심 이용' },
  { href: '/developers/ko/home/', label: '서비스 안내와 개발 문서' },
]

export function DocLinks() {
  return (
    <nav aria-label="안내 문서" className="flex flex-wrap items-center justify-center gap-x-1 text-12 text-fg-neutral-muted">
      {DOC_LINKS.map(({ href, label }) => (
        <a key={href} href={href} className="inline-flex min-h-11 items-center px-1.5 underline underline-offset-4">
          {label}
        </a>
      ))}
    </nav>
  )
}
