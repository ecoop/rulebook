import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import AdvancedApp from './AdvancedApp'
import App from './App'
import { PreviewBar, PreviewProvider } from './preview'
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
//
// Root also owns the "View as level" PREVIEW state (docs/rbac-capabilities.md):
// it lives here, ABOVE both views, so a superuser previewing a lower level
// reshapes the Main page and the Advanced page at once, and the exit banner
// survives whatever the previewed role renders. See preview.tsx.
interface RealMe {
  level: number
  capabilities: string[]
  demo_mode: boolean
}

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

  // Preview state. `realMe` is the REAL identity (never the previewed one) — it
  // decides whether the View-as control shows and caps the selectable levels.
  const [previewLevel, setPreviewLevel] = useState<number | null>(null)
  const [roleCaps, setRoleCaps] = useState<Record<string, string[]> | null>(null)
  const [realMe, setRealMe] = useState<RealMe | null>(null)

  useEffect(() => {
    fetch('/me')
      .then((r) => (r.ok ? r.json() : null))
      .then((m) => m && setRealMe(m))
      .catch(() => {
        /* non-fatal — no preview control, the app still works */
      })
  }, [])

  // Only a superuser (roles.manage, level 8) may preview, and only in demo_mode
  // (a public deploy has no roles to preview). Fetch the level→caps map once
  // that's known — it's what translates a previewed level into a capability set.
  const mayPreview =
    !!realMe && realMe.demo_mode && realMe.capabilities.includes('roles.manage')
  useEffect(() => {
    if (!mayPreview) return
    fetch('/advanced/role-capabilities')
      .then((r) => (r.ok ? r.json() : null))
      .then((m) => m && setRoleCaps(m))
      .catch(() => {
        /* non-fatal — launcher stays hidden until the map loads */
      })
  }, [mayPreview])

  // Offer the launcher only once the map is loaded, so entering preview always
  // has caps to gate on (never a superuser stranded seeing everything).
  const canPreview = mayPreview && !!roleCaps

  return (
    <PreviewProvider value={{ previewLevel, setPreviewLevel, roleCaps }}>
      <div style={{ display: showAdvanced ? 'none' : undefined }}>
        <App />
      </div>
      {showAdvanced && <AdvancedApp />}
      <PreviewBar
        canPreview={canPreview}
        maxLevel={realMe?.level ?? 0}
        previewLevel={previewLevel}
        setPreviewLevel={setPreviewLevel}
      />
    </PreviewProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
