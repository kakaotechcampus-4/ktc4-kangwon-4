type NoticeTone = 'WARNING' | 'NEUTRAL'

interface NoticeCardProps {
  /** `WARNING`은 사용자가 고쳐야 하는 것, `NEUTRAL`은 서버 쪽 문제 */
  tone: NoticeTone
  title: string
  description: string
  /** 사용자가 할 수 있는 일이 있을 때만 준다 */
  action?: { label: string; onClick: () => void }
}

/**
 * 진행을 멈추고 알려야 하는 상태.
 *
 * 어두운 배경을 쓰지 않는다. 강하게 강조하는 것은 Next Action 하나다.
 *
 * 새 tone이 늘면 컴파일이 막히도록 `Record`로 둔다.
 */
const TONE_STYLE: Record<NoticeTone, { card: string; label: string; text: string }> = {
  WARNING: {
    card: 'border-amber-200 bg-amber-50',
    label: 'text-amber-700',
    text: 'text-amber-900',
  },
  NEUTRAL: {
    card: 'border-gray-200 bg-white',
    label: 'text-gray-500',
    text: 'text-gray-900',
  },
}

const TONE_LABEL: Record<NoticeTone, string> = {
  WARNING: '확인이 필요해요',
  NEUTRAL: '알려드립니다',
}

export function NoticeCard({ tone, title, description, action }: NoticeCardProps) {
  const style = TONE_STYLE[tone]

  return (
    <section className={`rounded-2xl border p-5 ${style.card}`}>
      <h2 className={`text-sm font-bold tracking-wide ${style.label}`}>{TONE_LABEL[tone]}</h2>

      <p className={`mt-3 text-lg font-bold ${style.text}`}>{title}</p>
      <p className="mt-2 text-base leading-relaxed text-gray-600">{description}</p>

      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="mt-4 min-h-13 w-full rounded-xl border border-gray-300 bg-white text-base font-bold text-gray-900"
        >
          {action.label}
        </button>
      )}
    </section>
  )
}
