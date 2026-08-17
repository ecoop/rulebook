// Copyright (c) 2026 Eric Cooper.
//
// The floating-widgets header control, shared by the main page and the "Your
// activity" page. Rendered inside <LayoutProvider> (lifted to main.tsx so both
// pages share it), so it can read the dock state via useDock() — holding NO
// state of its own (two owners of "is the HUD open" is how they drift).
//
//   - phone (dock presentation): toggles the docked bottom sheet.
//   - desktop (floating), with a stackRef: snaps the widgets to the corner.
//   - desktop without a stackRef (the activity page): nothing to show.

import { type RefObject } from 'react'
import { Eye, EyeOff, PanelRightOpen } from 'lucide-react'
import { useDock, type FloatingWidgetStackHandle } from '@nobadeer/floating-widgets'

const BTN =
  '-mr-1.5 shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground'

export function WidgetControls({
  stackRef,
}: {
  stackRef?: RefObject<FloatingWidgetStackHandle | null>
}) {
  const { isDock, open, toggle } = useDock()
  if (isDock) {
    return (
      <button
        type="button"
        onClick={toggle}
        aria-pressed={open}
        title={open ? 'Hide widgets' : 'Show widgets'}
        aria-label={open ? 'Hide widgets' : 'Show widgets'}
        className={BTN}
      >
        {open ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    )
  }
  if (stackRef) {
    return (
      <button
        type="button"
        onClick={() => stackRef.current?.snapAll()}
        title="Snap widgets back to the corner"
        aria-label="Snap widgets back to the corner"
        className={BTN}
      >
        <PanelRightOpen className="h-4 w-4" />
      </button>
    )
  }
  return null
}
