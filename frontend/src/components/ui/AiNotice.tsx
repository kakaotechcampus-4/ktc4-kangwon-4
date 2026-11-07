import { IconSparkle2Fill } from '@karrotmarket/react-monochrome-icon'

interface AiNoticeProps {
  /** 놓이는 자리에 맞춘 줄 맞춤 등. 글자 크기·색은 바꾸지 않는다 */
  className?: string
}

/**
 * AI 사용 고지 한 줄(#215 · #237).
 *
 * AI가 만든 안내(지금 할 일, 이유, "이렇게 이해하고 반영했어요") 아래와 소개 마지막 장에 작게 둔다.
 * 사람이 검수한 로드맵 설명에는 두지 않는다 — AI가 쓴 글이 아니다.
 *
 * 강조하지 않는다. 한 화면에서 강하게 보이는 것은 Next Action 하나다(FE 규칙 5, ui-guidelines "재촉하지 않는다").
 * 반짝이 아이콘은 홈 "AI 처리 중" 배지와 같은 표시다. 글자로도 "AI"라고 적어 색·모양만으로 알리지 않는다.
 */
export function AiNotice({ className = '' }: AiNoticeProps) {
  return (
    <p className={`flex items-center gap-1 text-14 text-fg-neutral-muted ${className}`}>
      <IconSparkle2Fill size={14} aria-hidden="true" className="shrink-0" />
      리본(AI)이 정리한 안내예요. 참고용이며 법률 자문이 아니에요.
    </p>
  )
}
