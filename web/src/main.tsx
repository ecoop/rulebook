import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import AdvancedApp from './AdvancedApp'
import App from './App'
import './index.css'

// Hash-based routing to avoid pulling in react-router for a two-view app.
// `#/advanced` → AdvancedApp; everything else → App. `#/` and `#` both hit App.
// Old `#/admin` bookmarks still land on Advanced (rewritten to `#/advanced`).
function Root() {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  useEffect(() => {
    if (hash === '#/admin') window.location.hash = '#/advanced' // legacy redirect
  }, [hash])
  const showAdvanced = hash === '#/advanced' || hash === '#/admin'
  return showAdvanced ? <AdvancedApp /> : <App />
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
