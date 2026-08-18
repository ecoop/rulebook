// Copyright (c) 2026 Eric Cooper.
//
// The floating-widgets header control, shared by the main page and the "Your
// activity" page. The EYE is always present and toggles the whole HUD's
// visibility (app-level, via useWidgetVisibility) — hidden means no floating
// widgets on desktop and no dock on mobile. When hidden it tints green if new
// info arrived behind it. Snap-to-corner is a small secondary shown only when
// the widgets are visible AND floating (desktop), for re-cornering a dragged
// widget.

import { type RefObject } from 'react'
import { Eye, EyeOff, PanelRightOpen } from 'lucide-react'
import { useDock, type FloatingWidgetStackHandle } from '@nobadeer/floating-widgets'
import { useWidgetVisibility } from './widgetVisibility'

const BTN =
  'shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground'

export function WidgetControls({
  stackRef,
}: {
  stackRef?: RefObject<FloatingWidgetStackHandle | null>
}) {
  const { hidden, hasNew, toggle } = useWidgetVisibility()
  const { isDock } = useDock()
  return (
    <div className="-mr-1.5 flex shrink-0 items-center">
      {!hidden && !isDock && stackRef && (
        <button
          type="button"
          onClick={() => stackRef.current?.snapAll()}
          title="Snap widgets back to the corner"
          aria-label="Snap widgets back to the corner"
          className={BTN}
        >
          <PanelRightOpen className="h-4 w-4" />
        </button>
      )}
      <button
        type="button"
        onClick={toggle}
        aria-pressed={!hidden}
        title={hidden ? (hasNew ? 'Show widgets — new info' : 'Show widgets') : 'Hide widgets'}
        aria-label={hidden ? 'Show widgets' : 'Hide widgets'}
        className={BTN}
      >
        {hidden ? (
          <Eye className={'h-4 w-4' + (hasNew ? ' text-emerald-600 dark:text-emerald-500' : '')} />
        ) : (
          <EyeOff className="h-4 w-4" />
        )}
      </button>
    </div>
  )
}
