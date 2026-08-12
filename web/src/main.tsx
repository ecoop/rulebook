import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import AdminApp from './AdminApp'
import App from './App'
import './index.css'

// Hash-based routing to avoid pulling in react-router for a two-view app.
// `#/admin` → AdminApp; everything else → App. `#/` and `#` both hit App.
//
// App stays MOUNTED across the switch and is merely hidden when Advanced is
// open, so a question/answer you're mid-engagement with — plus any in-progress
// rating, tags, or comment — survives the round trip to Advanced and back.
// Unmounting it (the old ternary) discarded all that state. AdminApp mounts on
// demand, so its /me + admin fetches only run when the tab is actually opened.
function Root() {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  const showAdmin = hash === '#/admin'
  return (
    <>
      <div style={{ display: showAdmin ? 'none' : undefined }}>
        <App />
      </div>
      {showAdmin && <AdminApp />}
    </>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
