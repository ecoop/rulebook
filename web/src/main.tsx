import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import ActivityApp from './ActivityApp'
import App from './App'
import './index.css'

// Hash-based routing to avoid pulling in react-router for a two-view app.
// `#/activity` → ActivityApp; everything else → App. Old `#/advanced` and
// `#/admin` bookmarks are redirected to `#/activity`.
//
// App stays MOUNTED across the switch and is merely hidden when the activity
// view is open, so a question/answer you're mid-engagement with — plus any
// in-progress rating, tags, or comment — survives the round trip and back.
// Unmounting it (the old ternary) discarded all that state. ActivityApp mounts
// on demand, so its /me + advanced fetches only run when the view is opened.
const LEGACY_HASHES = new Set(['#/advanced', '#/admin'])

function Root() {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  useEffect(() => {
    if (LEGACY_HASHES.has(hash)) window.location.hash = '#/activity' // legacy redirect
  }, [hash])
  const showActivity = hash === '#/activity' || LEGACY_HASHES.has(hash)
  return (
    <>
      <div style={{ display: showActivity ? 'none' : undefined }}>
        <App />
      </div>
      {showActivity && <ActivityApp />}
    </>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
