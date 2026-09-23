import { FRANCHISE_OPTIONS, LEASE_OPTIONS } from '../lib/caseOptions'
import type { CaseDraft } from '../types/view'

interface CaseCreateFormProps {
  value: CaseDraft
  onChange: (value: CaseDraft) => void
  onSubmit: () => void
  /** 보내는 중에는 잠근다. 입력한 내용은 지우지 않고 그대로 둔다 */
  disabled: boolean
}

interface ChoiceGroupProps<T> {
  legend: string
  /** 같은 이름을 공유하는 라디오끼리 한 묶음이 된다 */
  name: string
  options: { value: T; label: string; hint?: string }[]
  selected: T | null
  onSelect: (value: T) => void
  disabled: boolean
}

/**
 * 하나만 고르는 묶음.
 *
 * `select` 대신 라디오를 쓴다. 선택지가 세 개 이하면 펼쳐 두는 쪽이 누르기 쉽고,
 * 무엇 중에 고르는 것인지 한눈에 보인다.
 *
 * `fieldset`/`legend`로 감싸는 이유는 이 묶음의 질문이 무엇인지 각 선택지에 붙기
 * 때문이다. 이게 없으면 "월세를 내고 있어요"가 무슨 질문의 답인지 알 수 없다.
 */
function ChoiceGroup<T extends string | boolean>({
  legend,
  name,
  options,
  selected,
  onSelect,
  disabled,
}: ChoiceGroupProps<T>) {
  return (
    <fieldset className="rounded-2xl border border-gray-200 bg-white p-5" disabled={disabled}>
      <legend className="px-1 text-lg font-bold text-gray-900">{legend}</legend>

      <div className="mt-2 flex flex-col gap-2">
        {options.map((option) => (
          <label
            key={String(option.value)}
            className="flex min-h-13 cursor-pointer items-center gap-3 rounded-xl border border-gray-300 px-4 py-3 has-checked:border-gray-900 has-checked:bg-gray-900 has-checked:text-white"
          >
            <input
              type="radio"
              name={name}
              checked={selected === option.value}
              onChange={() => onSelect(option.value)}
              className="size-5 shrink-0 accent-white"
            />
            <span className="text-base font-bold">
              {option.label}
              {option.hint && (
                <span className="mt-0.5 block text-sm font-normal opacity-70">{option.hint}</span>
              )}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

/**
 * Case 생성 입력.
 *
 * 묻는 것은 사장님이 이미 아는 것뿐이다. 원상복구 범위나 철거 필요 여부처럼
 * 임대인·지자체에 물어봐야 아는 항목은 여기서 묻지 않는다 — 그걸 알아내는 것이
 * 이 제품이 대신 해주려는 일이라, 시작하기 전에 물으면 앞뒤가 바뀐다.
 *
 * 필수 세 개를 먼저 두고 선택 두 개를 뒤에 둔다. 모르는 것이 앞에 나오면 거기서 멈춘다.
 */
export function CaseCreateForm({ value, onChange, onSubmit, disabled }: CaseCreateFormProps) {
  /**
   * 비워두는 것은 괜찮지만 음수나 소수는 안 된다.
   *
   * 여기서 막지 않으면 버튼이 열린 채로 브라우저가 제출을 가로챈다. 그건 React의
   * `onSubmit`보다 먼저 일어나서 화면은 아무 반응이 없고, 브라우저 기본 안내만
   * 저 위 입력칸에 잠깐 뜬다 — 이 폼이 막으려던 "눌렀는데 아무 일이 없다"가 된다.
   */
  const employeeCountFilled = value.employeeCount.trim().length > 0
  const employeeCountValid = !employeeCountFilled || /^\d+$/.test(value.employeeCount.trim())

  const canSubmit =
    !disabled &&
    value.businessType.trim().length > 0 &&
    value.franchiseStatus !== null &&
    value.leaseStatus !== null &&
    employeeCountValid

  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(event) => {
        event.preventDefault()
        if (canSubmit) onSubmit()
      }}
    >
      <fieldset className="rounded-2xl border border-gray-200 bg-white p-5" disabled={disabled}>
        <label htmlFor="business-type" className="text-lg font-bold text-gray-900">
          어떤 가게인가요?
        </label>
        <input
          id="business-type"
          type="text"
          value={value.businessType}
          onChange={(event) => onChange({ ...value, businessType: event.target.value })}
          placeholder="예: 카페"
          className="mt-3 w-full rounded-xl border border-gray-300 p-3.5 text-base text-gray-900 placeholder:text-gray-400 focus:border-gray-900 focus:outline-none disabled:bg-gray-50"
        />
      </fieldset>

      <ChoiceGroup
        legend="프랜차이즈인가요?"
        name="franchise"
        options={FRANCHISE_OPTIONS}
        selected={value.franchiseStatus}
        onSelect={(franchiseStatus) => onChange({ ...value, franchiseStatus })}
        disabled={disabled}
      />

      <ChoiceGroup
        legend="가게 자리는 어떻게 쓰고 계신가요?"
        name="lease"
        options={LEASE_OPTIONS}
        selected={value.leaseStatus}
        onSelect={(leaseStatus) => onChange({ ...value, leaseStatus })}
        disabled={disabled}
      />

      <fieldset className="rounded-2xl border border-gray-200 bg-white p-5" disabled={disabled}>
        <label htmlFor="employee-count" className="text-lg font-bold text-gray-900">
          직원이 몇 명인가요?
        </label>
        <p className="mt-2 text-base text-gray-600">모르시면 비워두셔도 됩니다.</p>
        <input
          id="employee-count"
          type="number"
          inputMode="numeric"
          min={0}
          value={value.employeeCount}
          onChange={(event) => onChange({ ...value, employeeCount: event.target.value })}
          placeholder="예: 2"
          className="mt-3 w-full rounded-xl border border-gray-300 p-3.5 text-base text-gray-900 placeholder:text-gray-400 focus:border-gray-900 focus:outline-none disabled:bg-gray-50"
        />
      </fieldset>

      <fieldset className="rounded-2xl border border-gray-200 bg-white p-5" disabled={disabled}>
        <label htmlFor="planned-closure-date" className="text-lg font-bold text-gray-900">
          언제쯤 정리하실 계획인가요?
        </label>
        <p className="mt-2 text-base text-gray-600">아직 안 정하셨으면 비워두셔도 됩니다.</p>
        <input
          id="planned-closure-date"
          type="date"
          value={value.plannedClosureDate}
          onChange={(event) => onChange({ ...value, plannedClosureDate: event.target.value })}
          className="mt-3 w-full rounded-xl border border-gray-300 p-3.5 text-base text-gray-900 focus:border-gray-900 focus:outline-none disabled:bg-gray-50"
        />
      </fieldset>

      <button
        type="submit"
        disabled={!canSubmit}
        className="min-h-13 w-full rounded-xl bg-gray-900 text-base font-bold text-white disabled:bg-gray-200 disabled:text-gray-400"
      >
        시작하기
      </button>
    </form>
  )
}
