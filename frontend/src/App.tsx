import { RouterProvider } from 'react-router'

import { router } from './routes'

/**
 * 라우터를 띄우는 것 외에 하는 일이 없다.
 *
 * 화면이 필요한 데이터는 각 페이지가 직접 구한다 — 여기서 모아 나눠주면
 * 화면이 늘어날 때마다 이 파일이 커지고, 나중에 fetch를 넣을 자리도 흩어진다.
 */
function App() {
  return <RouterProvider router={router} />
}

export default App
