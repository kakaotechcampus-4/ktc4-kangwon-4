import hammerUrl from '../../assets/brand/reborn-hammer.svg'

interface HammerLoaderProps {
  /** 망치 크기(px). 시안은 자리마다 20·24·40·56·64·72를 쓴다 */
  size: number
  /** 화면 읽기 프로그램이 읽는 말. 화면에는 보이지 않는다 */
  label?: string
}

/**
 * 리본이 일하는 중임을 보여주는 망치.
 *
 * 망치 그림은 꾸밈이라 `alt`를 비우고, 무엇을 기다리는지는 숨긴 글자로 알린다.
 * `role="status"`는 화면 읽기 프로그램이 이 글자를 사용자의 흐름을 끊지 않고 읽게 한다.
 *
 * 기기에서 "움직임 줄이기"를 켠 사용자에게는 돌지 않는다. 계속 도는 화면이 어지러울 수 있다.
 */
export function HammerLoader({ size, label = '불러오는 중' }: HammerLoaderProps) {
  return (
    <span role="status" className="inline-block shrink-0">
      <img
        src={hammerUrl}
        alt=""
        width={size}
        height={size}
        className="block animate-hammer-spin motion-reduce:animate-none"
      />
      <span className="sr-only">{label}</span>
    </span>
  )
}
