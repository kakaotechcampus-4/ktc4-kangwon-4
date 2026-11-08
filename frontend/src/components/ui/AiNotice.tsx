import { IconSparkle2Fill } from '@karrotmarket/react-monochrome-icon'

interface AiNoticeProps {
  /** 놓이는 자리의 글 정렬에 맞춘다. 가운데 정렬 화면(소개 · 반영 결과)은 `center` */
  align?: 'start' | 'center'
  /**
   * 짧은 표시("✦ 리본(AI)"). 반복해서 보는 좁은 자리(홈 할 일 카드)에 쓴다. 긴 문장은 처음 보는 소개와
   * 자세히 읽는 할 일 상세 · 반영 결과에 둔다. 화면 읽기 프로그램에는 긴 문장을 그대로 읽어 준다
   */
  compact?: boolean
  /** 위아래 여백 등. 글자 크기·색은 바꾸지 않는다 */
  className?: string
}

const FULL_TEXT = '리본(AI)이 정리한 안내예요. 참고용이며 법률 자문이 아니에요.'

/**
 * AI 사용 고지 두 줄(#215 · #237).
 *
 * AI가 만든 안내(지금 할 일, 이유, "이렇게 이해하고 반영했어요") 아래와 소개 마지막 장에 작게 둔다.
 * 사람이 검수한 로드맵 설명에는 두지 않는다 — AI가 쓴 글이 아니다.
 *
 * **줄을 처음부터 둘로 나눈다.** 화면 폭에 맡기면 "자문이 / 아니에요"처럼 아무 데서나 꺾인다.
 * 아이콘은 첫 줄 글 안에 넣어 첫 글자에 붙인다 — 따로 칸을 두면 줄이 꺾일 때 아이콘만 떨어져 보인다.
 * 왼쪽 정렬이면 둘째 줄을 아이콘 다음 글자에 맞춘다(내어쓰기). 두 줄이 한 묶음으로 읽힌다.
 *
 * 강조하지 않는다. 한 화면에서 강하게 보이는 것은 Next Action 하나다(FE 규칙 5, ui-guidelines "재촉하지 않는다").
 * 반짝이 아이콘은 홈 "AI 처리 중" 배지와 같은 표시다. 글자로도 "AI"라고 적어 색·모양만으로 알리지 않는다.
 */
export function AiNotice({ align = 'start', compact = false, className = '' }: AiNoticeProps) {
  if (compact) {
    return (
      <p className={`flex items-center gap-1 text-14 text-fg-neutral-muted ${className}`}>
        <IconSparkle2Fill size={14} aria-hidden="true" className="shrink-0" />
        <span aria-hidden="true">리본(AI)</span>
        <span className="sr-only">{FULL_TEXT}</span>
      </p>
    )
  }

  // 아이콘 14px + 띄움 4px = 18px(4.5칸) 만큼 둘째 줄을 들인다
  const alignment = align === 'center' ? 'text-center' : 'pl-4.5 -indent-4.5'
  return (
    <p className={`text-14 text-fg-neutral-muted ${alignment} ${className}`}>
      <IconSparkle2Fill size={14} aria-hidden="true" className="mr-1 inline-block align-[-2px]" />
      리본(AI)이 정리한 안내예요.
      <br />
      참고용이며 법률 자문이 아니에요.
    </p>
  )
}
