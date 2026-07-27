import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import AdminApp from './AdminApp'
import App from './App'
import './index.css'

// Hash-based routing to avoid pulling in react-router for a two-view app.
// `#/admin` → AdminApp; everything else → App. `#/` and `#` both hit App.
function Root() {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash === '#/admin' ? <AdminApp /> : <App />
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
