import type { ButtonHTMLAttributes } from 'react'

/**
 * 버튼 종류.
 *
 * - `brand`   화면에서 가장 중요한 행동. 화면당 하나
 * - `neutral` 나란히 놓인 보조 행동
 * - `outline` 흰 바탕 위에서 고르는 행동
 */
type ButtonVariant = 'brand' | 'neutral' | 'outline'

/**
 * 버튼 크기.
 *
 * - `md` 기본. 높이 56px, 18px
 * - `lg` 홈 할 일 카드처럼 화면의 단 하나뿐인 큰 행동. 높이 60px, 19px
 */
type ButtonSize = 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
}

const VARIANT_STYLE: Record<ButtonVariant, string> = {
  brand:
    'bg-bg-brand-solid text-fg-on-brand-solid hover:bg-bg-brand-solid-pressed active:bg-bg-brand-solid-pressed',
  neutral:
    'bg-bg-neutral-weak text-fg-neutral hover:bg-bg-neutral-weak-pressed active:bg-bg-neutral-weak-pressed',
  outline:
    'bg-bg-layer-default text-fg-neutral ring-1 ring-stroke-neutral-weak ring-inset active:bg-bg-layer-default-pressed',
}

const SIZE_STYLE: Record<ButtonSize, string> = {
  md: 'h-14 text-18',
  lg: 'h-15 text-19',
}

/**
 * 시안의 기본 버튼. 높이 56px로 가로를 꽉 채운다.
 *
 * `type`의 기본값을 `button`으로 둔다. HTML 기본값은 `submit`이라, 폼 안에 놓인 보조 버튼을
 * 누르면 폼이 제출된다. 제출 버튼만 `type="submit"`을 적는다.
 *
 * 꺼진 버튼은 종류와 상관없이 회색 바탕에 연한 글자다. 누를 수 없다는 것만 보이면 된다.
 */
export function Button({
  variant = 'brand',
  size = 'md',
  type = 'button',
  className = '',
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={`w-full shrink-0 cursor-pointer rounded-14 px-5 font-bold whitespace-nowrap focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stroke-brand-solid disabled:cursor-not-allowed disabled:bg-bg-neutral-weak disabled:text-fg-disabled disabled:ring-0 ${SIZE_STYLE[size]} ${VARIANT_STYLE[variant]} ${className}`}
      {...props}
    />
  )
}
