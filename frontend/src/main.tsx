import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// 한글 글자를 쓰는 만큼만 나눠 받는 판. 전체 판은 한 번에 수 MB를 받는다
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
