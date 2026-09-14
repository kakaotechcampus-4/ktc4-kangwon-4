import type { ConflictItem } from '../types/view'

export type ConflictSide = 'STORED' | 'INCOMING'

interface ConflictChoiceProps {
  item: ConflictItem
  /** 아직 고르지 않았으면 null. 기본 선택을 두지 않는다 */
  selected: ConflictSide | null
  onSelect: (side: ConflictSide) => void
}

/**
 * 기존 기록과 새 입력이 어긋난 항목 하나를 나란히 놓고 고르게 한다.
 *
 * 어느 쪽도 미리 선택해두지 않는다. 기본값이 있으면 사용자가 읽지 않고 넘길 수 있고,
 * 그러면 서버가 자동으로 고른 것과 다를 바가 없다. 충돌은 항상 사용자 확인을
 * 거친다는 것이 이 제품의 약속이다.
 *
 * 어두운 배경을 쓰지 않는다. 강하게 강조하는 것은 Next Action 하나다.
 */
export function ConflictChoice({ item, selected, onSelect }: ConflictChoiceProps) {
  return (
    <section className="rounded-2xl border border-gray-300 bg-white p-5">
      <h2 className="text-base font-bold text-gray-900">{item.label}</h2>

      <div className="mt-3 flex flex-col gap-2.5">
        <ChoiceButton
          caption="지금 기록된 내용"
          value={item.storedValue}
          pressed={selected === 'STORED'}
          onClick={() => onSelect('STORED')}
        />
        <ChoiceButton
          caption="이번에 말씀하신 내용"
          value={item.incomingValue}
          pressed={selected === 'INCOMING'}
          onClick={() => onSelect('INCOMING')}
        />
      </div>
    </section>
  )
}

interface ChoiceButtonProps {
  caption: string
  value: string
  pressed: boolean
  onClick: () => void
}

function ChoiceButton({ caption, value, pressed, onClick }: ChoiceButtonProps) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={`min-h-13 rounded-xl border p-3.5 text-left ${
        pressed ? 'border-gray-900 bg-gray-50' : 'border-gray-200 bg-white'
      }`}
    >
      <span className="block text-sm text-gray-500">{caption}</span>
      <span className="mt-0.5 flex items-center gap-2">
        <span className="text-base font-bold text-gray-900">{value}</span>
        {pressed && <span className="text-sm font-bold text-gray-900">선택함</span>}
      </span>
    </button>
  )
}
