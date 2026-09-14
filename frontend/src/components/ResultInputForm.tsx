interface ResultInputFormProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  /** 보내는 중에는 잠근다. 입력한 내용은 지우지 않고 그대로 둔다 */
  disabled: boolean
}

/**
 * 실행 결과를 한 줄로 말하는 입력.
 *
 * 자유 서술로 받는다. 항목별 선택지를 두면 사용자가 "어느 칸에 적어야 하나"를
 * 먼저 판단해야 하는데, 그 판단이 이 제품이 대신 해주려는 일이다.
 */
export function ResultInputForm({ value, onChange, onSubmit, disabled }: ResultInputFormProps) {
  const canSubmit = !disabled && value.trim().length > 0

  return (
    <form
      className="rounded-2xl border border-gray-200 bg-white p-5"
      onSubmit={(event) => {
        event.preventDefault()
        if (canSubmit) onSubmit()
      }}
    >
      <label htmlFor="result-input" className="text-lg font-bold text-gray-900">
        어떻게 되었나요?
      </label>
      <p className="mt-2 text-base leading-relaxed text-gray-600">
        들으신 내용을 그대로 말씀해 주세요. 정리하지 않으셔도 됩니다.
      </p>

      <textarea
        id="result-input"
        rows={4}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        placeholder="예: 임대인이 철거해야 한다고 했어요."
        className="mt-4 w-full resize-none rounded-xl border border-gray-300 p-3.5 text-base leading-relaxed text-gray-900 placeholder:text-gray-400 focus:border-gray-900 focus:outline-none disabled:bg-gray-50 disabled:text-gray-500"
      />

      <button
        type="submit"
        disabled={!canSubmit}
        className="mt-3 min-h-13 w-full rounded-xl bg-gray-900 text-base font-bold text-white disabled:bg-gray-200 disabled:text-gray-400"
      >
        알려주기
      </button>
    </form>
  )
}
