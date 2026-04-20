import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Mount the React app once at the Vite root element.
createRoot(document.getElementById('root')!).render(
  // StrictMode helps surface accidental side effects during development.
  <StrictMode>
    <App />
  </StrictMode>,
)
