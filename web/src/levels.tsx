// Level presentation — colors (a judo-belt palette) + one-line descriptions for
// the level badge. Mirrors ROLE_LEVELS in src/rulebook/roles.py; the backend is
// the source of truth for policy, this is pure presentation. /me returns the
// numeric `level`; role ids are "level0" … "level8".

export interface LevelInfo {
  color: string
  description: string
}

// Indexed by level number 0–8.
export const LEVELS: readonly LevelInfo[] = [
  { color: '#9AA0A6', description: 'Suspended — no access' },
  { color: '#E8E8E8', description: 'Beginner — ask and rate' },
  { color: '#E5B80B', description: 'Can comment on answers' },
  { color: '#E07A20', description: 'Can suggest gold answers' },
  { color: '#3A8C3A', description: 'Sees the workings (own items)' },
  { color: '#2C64B4', description: "Reviews everyone's items" },
  { color: '#7A4A2B', description: 'Operator — curates and rebuilds' },
  { color: '#1A1A1A', description: 'Admin — manages users' },
  { color: '#C4272E', description: 'Superuser — full control' },
]

// Level number from a role id ("level5" → 5); 0 for anything unrecognized.
export function levelNumber(role: string | null | undefined): number {
  const m = /^level([0-8])$/.exec(role ?? '')
  return m ? Number(m[1]) : 0
}

export function levelInfo(level: number): LevelInfo {
  return LEVELS[level] ?? LEVELS[0]
}

// A short human label for a level, for select options / help text.
export function levelLabel(level: number): string {
  return `Level ${level} — ${levelInfo(level).description}`
}

// Readable text color for a filled chip of the given hex (luminance threshold).
function textOn(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? '#1a1a1a' : '#ffffff'
}

// A small colored chip: the level number, the belt color, description on hover.
export function LevelBadge({ level, className }: { level: number; className?: string }) {
  const info = levelInfo(level)
  return (
    <span
      title={info.description}
      className={className}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        background: info.color,
        color: textOn(info.color),
        border: '1px solid rgba(0,0,0,0.12)',
        borderRadius: 9999,
        padding: '0 7px',
        height: 18,
        fontSize: 11,
        fontWeight: 500,
        lineHeight: '18px',
        whiteSpace: 'nowrap',
      }}
    >
      L{level}
    </span>
  )
}
