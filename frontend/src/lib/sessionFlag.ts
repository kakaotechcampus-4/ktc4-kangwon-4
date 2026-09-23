/**
 * 탭 하나 동안만 사는 참/거짓 값.
 *
 * `sessionStorage`를 쓰는 이유는 탭을 닫으면 같이 끝나기 때문이다. 공용 PC나 가게
 * 컴퓨터에서 쓰는 사용자가 있을 수 있어 브라우저를 껐다 켜도 남아 있게 두지 않는다.
 *
 * 저장소는 생각보다 자주 못 쓴다 — 사생활 보호 모드, 저장소 차단 확장, 용량 초과.
 * 특히 **읽기는 되는데 쓰기만 실패하는** 브라우저가 있다. 그 경우 저장한 값이
 * 조용히 사라지므로, 한 번이라도 실패하면 그 뒤로는 메모리에 든 값만 믿는다.
 * 새로고침하면 풀리지만, 눌러도 아무 일이 없는 화면보다는 낫다.
 */
export interface SessionFlag {
  read: () => boolean
  write: (value: boolean) => void
}

export function createSessionFlag(key: string): SessionFlag {
  let fallback = false
  let storageUsable = true

  return {
    read() {
      if (!storageUsable) return fallback

      try {
        return window.sessionStorage.getItem(key) === 'true'
      } catch {
        storageUsable = false
        return fallback
      }
    },

    write(value) {
      fallback = value
      if (!storageUsable) return

      try {
        window.sessionStorage.setItem(key, String(value))
      } catch {
        storageUsable = false
      }
    },
  }
}
