import { FormEvent, useState } from 'react'
import { formatError, requestJson } from '../utils/api'

export type DashboardAccessStatus = {
  authenticated: boolean
  configured: boolean
  bypassed: boolean
  sessionDays: number
}

type AccessPageProps = {
  status: DashboardAccessStatus | null
  initialError?: string
  onAuthenticated: (status: DashboardAccessStatus) => void
  onRetry: () => void
}

export default function AccessPage({
  status,
  initialError = '',
  onAuthenticated,
  onRetry,
}: AccessPageProps) {
  const [password, setPassword] = useState('')
  const [passwordVisible, setPasswordVisible] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!password || submitting) return
    setSubmitting(true)
    setError('')
    try {
      const result = await requestJson<{ authenticated: boolean; sessionDays: number }>(
        '/api/access/login',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password }),
        },
      )
      onAuthenticated({
        authenticated: result.authenticated,
        configured: true,
        bypassed: false,
        sessionDays: result.sessionDays,
      })
      setPassword('')
    } catch (nextError) {
      setError(formatError(nextError))
    } finally {
      setSubmitting(false)
    }
  }

  const configurationMissing = status && !status.configured

  return (
    <main className="connect-page access-page">
      <div className="access-page__glow access-page__glow--top" aria-hidden="true" />
      <div className="access-page__glow access-page__glow--bottom" aria-hidden="true" />
      <section className="connect-card access-card">
        <header className="access-card__header">
          <div className="access-card__mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" focusable="false">
              <path d="M12 3.25 19 6v5.4c0 4.45-2.82 7.62-7 9.35-4.18-1.73-7-4.9-7-9.35V6l7-2.75Z" />
              <path d="m9.1 12.1 1.85 1.85 3.95-4.1" />
            </svg>
          </div>
          <span className="access-status-pill">
            <span aria-hidden="true" />
            安全访问
          </span>
        </header>

        <div className="access-card__copy">
          <span className="brand-kicker">Financial dashboard</span>
          <h1>欢迎回来</h1>
          <p>输入访问凭证以继续查看你的金融看板。</p>
        </div>

        {initialError || error ? (
          <div className="connect-error" role="alert">{error || initialError}</div>
        ) : null}

        {configurationMissing ? (
          <div className="access-configuration">
            <div className="connect-error" role="alert">
              服务器尚未配置访问凭证，请在服务器运行 ./start.sh configure-access。
            </div>
            <button type="button" className="connect-button" onClick={onRetry}>重新检查</button>
          </div>
        ) : (
          <form className="access-form" onSubmit={submit}>
            <label htmlFor="dashboard-access-password">访问凭证</label>
            <div className="access-input-shell" data-testid="access-password-field">
              <span className="access-input-shell__icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" focusable="false">
                  <rect x="5" y="10" width="14" height="10" rx="3" />
                  <path d="M8.5 10V7.5a3.5 3.5 0 0 1 7 0V10" />
                </svg>
              </span>
              <input
                id="dashboard-access-password"
                data-testid="access-password-input"
                type={passwordVisible ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value)
                  if (error) setError('')
                }}
                placeholder="输入访问凭证"
                autoFocus
              />
              <button
                type="button"
                className="access-password-toggle"
                data-testid="access-password-toggle"
                aria-label={passwordVisible ? '隐藏访问凭证' : '显示访问凭证'}
                aria-pressed={passwordVisible}
                onClick={() => setPasswordVisible((current) => !current)}
              >
                <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
                  <path d="M2.75 12s3.25-5 9.25-5 9.25 5 9.25 5-3.25 5-9.25 5-9.25-5-9.25-5Z" />
                  <circle cx="12" cy="12" r="2.5" />
                  {!passwordVisible ? <path d="m4 4 16 16" /> : null}
                </svg>
              </button>
            </div>
            <div className="access-form__helper">
              <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
                <path d="M12 3.75a8.25 8.25 0 1 0 0 16.5 8.25 8.25 0 0 0 0-16.5Z" />
                <path d="m8.75 12 2.1 2.1 4.4-4.45" />
              </svg>
              此设备将保持登录 {status?.sessionDays || 30} 天
            </div>
            <button type="submit" className="connect-button access-submit-button" disabled={!password || submitting}>
              <span>{submitting ? '正在验证…' : '进入看板'}</span>
              {!submitting ? (
                <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
                  <path d="m9 5 7 7-7 7" />
                </svg>
              ) : <span className="access-submit-button__spinner" aria-hidden="true" />}
            </button>
          </form>
        )}

        <footer className="access-card__footer">
          <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
            <path d="M12 3.5 19 6v5.25c0 4.4-2.8 7.55-7 9.25-4.2-1.7-7-4.85-7-9.25V6l7-2.5Z" />
          </svg>
          <span>凭证仅在本机安全验证，不会保存明文</span>
        </footer>
      </section>
    </main>
  )
}
