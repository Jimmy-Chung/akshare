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
    <main className="connect-page">
      <section className="connect-card access-card">
        <div className="connect-card__mark" aria-hidden="true">FD</div>
        <span className="brand-kicker">Financial dashboard</span>
        <h1>访问看板</h1>
        <p>
          输入网页访问凭证。验证成功后，这台设备会保持登录
          {status?.sessionDays ? ` ${status.sessionDays} 天` : '一段时间'}。
        </p>

        {initialError || error ? (
          <div className="connect-error" role="alert">{error || initialError}</div>
        ) : null}

        {configurationMissing ? (
          <>
            <div className="connect-error" role="alert">
              服务器尚未配置访问凭证，请在服务器运行 ./start.sh configure-access。
            </div>
            <button type="button" className="connect-button" onClick={onRetry}>重新检查</button>
          </>
        ) : (
          <form className="access-form" onSubmit={submit}>
            <label htmlFor="dashboard-access-password">访问凭证</label>
            <input
              id="dashboard-access-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="输入访问凭证"
              autoFocus
            />
            <button type="submit" className="connect-button" disabled={!password || submitting}>
              {submitting ? '正在验证…' : '进入看板'}
            </button>
          </form>
        )}

        <div className="connect-notes">
          <span>凭证明文不会保存在服务器或浏览器。</span>
          <span>修改服务器访问凭证后，已有登录会自动失效。</span>
        </div>
      </section>
    </main>
  )
}
