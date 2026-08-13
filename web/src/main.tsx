import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import AdvancedApp from './AdvancedApp'
import App from './App'
import './index.css'

// Hash-based routing to avoid pulling in react-router for a two-view app.
// `#/advanced` → AdvancedApp; everything else → App. Old `#/admin` bookmarks
// are redirected to `#/advanced`.
//
// App stays MOUNTED across the switch and is merely hidden when Advanced is
// open, so a question/answer you're mid-engagement with — plus any in-progress
// rating, tags, or comment — survives the round trip to Advanced and back.
// Unmounting it (the old ternary) discarded all that state. AdvancedApp mounts
// on demand, so its /me + advanced fetches only run when the tab is opened.
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
  return (
    <>
      <div style={{ display: showAdvanced ? 'none' : undefined }}>
        <App />
      </div>
      {showAdvanced && <AdvancedApp />}
    </>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
