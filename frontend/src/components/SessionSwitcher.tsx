import type { SessionKey } from '../types/market'
import { sessionLabel } from '../utils/market'

interface SessionSwitcherProps {
  value: SessionKey
  onChange: (session: SessionKey) => void
  disabled?: boolean
}

const SESSIONS: SessionKey[] = ['morning', 'midday', 'close', 'us-night']

export default function SessionSwitcher({ value, onChange, disabled }: SessionSwitcherProps) {
  return (
    <div className="session-switcher">
      {SESSIONS.map((session) => (
        <button
          key={session}
          type="button"
          className={value === session ? 'session-tab is-active' : 'session-tab'}
          onClick={() => onChange(session)}
          disabled={disabled}
        >
          {sessionLabel(session)}
        </button>
      ))}
    </div>
  )
}
