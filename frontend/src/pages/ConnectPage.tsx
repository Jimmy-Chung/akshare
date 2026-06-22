import { useEffect, useState } from 'react'
import { formatError, requestJson } from '../utils/api'

type AuthStatus = {
  authenticated: boolean
  authMode: 'api_key' | 'oauth' | 'none'
  sdkAvailable: boolean
  loginUrl: string
  oauth: {
    clientConfigured: boolean
    authenticated: boolean
    canRefresh: boolean
    expiresAt?: number
  }
}

type ConnectPageProps = {
  onConnected: () => void
}

function ConnectPage({ onConnected }: ConnectPageProps) {
  const [status, setStatus] = useState<AuthStatus | null>(null)
  const [error, setError] = useState(() => {
    const message = new URLSearchParams(window.location.search).get('oauth_error')
    return message ? `授权未完成：${message}` : ''
  })

  useEffect(() => {
    let active = true

    requestJson<AuthStatus>('/api/auth/longbridge/status')
      .then((nextStatus) => {
        if (!active) return
        setStatus(nextStatus)
        if (nextStatus.authenticated) {
          onConnected()
        }
      })
      .catch((nextError) => {
        if (active) setError(formatError(nextError))
      })

    return () => {
      active = false
    }
  }, [onConnected])

  const startLogin = () => {
    setError('')
    const next = `${window.location.pathname}#dashboard`
    window.location.assign(
      `${status?.loginUrl || '/api/auth/longbridge/login'}?next=${encodeURIComponent(next)}`,
    )
  }

  return (
    <main className="connect-page">
      <section className="connect-card">
        <div className="connect-card__mark" aria-hidden="true">LB</div>
        <span className="brand-kicker">Longbridge OpenAPI</span>
        <h1>连接长桥账户</h1>
        <p>
          当前服务还没有可用凭证。完成一次 OAuth 授权后，访问令牌会由后端安全保存并自动续期。
        </p>

        {error ? <div className="connect-error">{error}</div> : null}

        <button
          className="connect-button"
          disabled={!status || !status.sdkAvailable}
          onClick={startLogin}
          type="button"
        >
          {!status ? '正在检查连接…' : '使用 Longbridge 授权'}
        </button>

        <div className="connect-notes">
          <span>凭证只保存在服务器，不会写入浏览器。</span>
          <span>如果已配置固定 API 凭证，这个页面会自动跳过。</span>
        </div>
      </section>
    </main>
  )
}

export default ConnectPage
