/**
 * 다음(카카오) 우편번호 서비스. 가게 주소를 찾을 때만 스크립트를 불러온다.
 *
 * 무료 외부 서비스라 키가 없다. 패키지로 넣지 않고 공식
 * 스크립트를 쓴다 — 주소 데이터가 그 스크립트 안에서 갱신되어, 묶어 두면 주소가 낡는다.
 *
 * 주소 찾기 화면을 열 때 한 번만 받는다. 첫 화면에서 받으면 쓰지 않는 사장님도 기다리게 된다.
 */

export const POSTCODE_SCRIPT_URL = 'https://t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js'

/** 고른 주소. 우리가 쓰는 칸만 적었다 */
export interface PostcodeResult {
  /** 도로명 주소(예: "서울 마포구 망원로 52") */
  roadAddress: string
  /** 법정동·법정리 이름(예: "망원동") */
  bname: string
  buildingName: string
  /** 공동주택이면 `Y` */
  apartment: 'Y' | 'N'
}

interface PostcodeWidget {
  embed: (element: HTMLElement) => void
}

declare global {
  interface Window {
    daum?: {
      Postcode: new (options: {
        oncomplete: (data: PostcodeResult) => void
        width?: string
        height?: string
      }) => PostcodeWidget
    }
  }
}

let loading: Promise<void> | null = null

/** 스크립트를 한 번만 받는다. 받다 실패하면 다음에 다시 받을 수 있게 비운다 */
export function loadPostcode(): Promise<void> {
  if (window.daum?.Postcode) return Promise.resolve()
  if (loading) return loading

  loading = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = POSTCODE_SCRIPT_URL
    script.async = true
    script.onload = () => (window.daum?.Postcode ? resolve() : reject(new Error('우편번호 서비스를 읽지 못했습니다.')))
    script.onerror = () => reject(new Error('우편번호 서비스를 불러오지 못했습니다.'))
    document.head.appendChild(script)
  }).catch((error: unknown) => {
    loading = null
    throw error
  })
  return loading
}

/** 찾기 창을 `element` 안에 띄운다. 주소를 고르면 `onSelect` 로 알린다 */
export function embedPostcode(element: HTMLElement, onSelect: (data: PostcodeResult) => void) {
  const Postcode = window.daum?.Postcode
  if (!Postcode) throw new Error('우편번호 서비스를 아직 불러오지 않았습니다.')
  new Postcode({ oncomplete: onSelect, width: '100%', height: '100%' }).embed(element)
}

/**
 * 고른 주소 → 서버에 보낼 도로명 주소 한 줄.
 *
 * 다음 우편번호 안내서의 "참고 항목" 규칙을 따른다 — 동·로·가로 끝나는 법정동 이름과 공동주택 이름을
 * 괄호로 붙인다(예: "서울 마포구 망원로 52 (망원동)"). 서류에 적힌 주소와 맞춰 보기 쉬워진다.
 */
export function toRoadAddress(data: PostcodeResult): string {
  const extra = [
    data.bname !== '' && /[동로가]$/.test(data.bname) ? data.bname : '',
    data.buildingName !== '' && data.apartment === 'Y' ? data.buildingName : '',
  ].filter(Boolean)

  return extra.length > 0 ? `${data.roadAddress} (${extra.join(', ')})` : data.roadAddress
}
