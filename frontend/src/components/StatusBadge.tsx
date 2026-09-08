import type { FactStatus } from '../types/view'

/**
 * 색만으로 상태를 전달하지 않는다. 배지에 항상 텍스트 라벨이 함께 들어간다.
 */
const STATUS_STYLE: Record<FactStatus, { label: string; className: string }> = {
  CONFIRMED: {
    label: '확인',
    className: 'text-emerald-800 bg-emerald-50 border-emerald-200',
  },
  IN_PROGRESS: {
    label: '지금 확인 중',
    className: 'text-amber-800 bg-amber-50 border-amber-200',
  },
  UNKNOWN: {
    label: '아직 확인 안 됨',
    className: 'text-gray-600 bg-gray-100 border-gray-200',
  },
}

interface StatusBadgeProps {
  status: FactStatus
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const { label, className } = STATUS_STYLE[status]

  return (
    <span
      className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-bold whitespace-nowrap ${className}`}
    >
      {label}
    </span>
  )
}
