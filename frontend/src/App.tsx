import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import DashboardPage from './pages/DashboardPage'
import AssistantPage from './pages/AssistantPage'
import AccessPage, { type DashboardAccessStatus } from './pages/AccessPage'
import ReportPage from './pages/ReportPage'
import ConnectPage from './pages/ConnectPage'
import { formatError, requestJson } from './utils/api'
import './styles/App.css'

const isReportExportRoute = () => (
  window.location.hash === '#report'
  && new URLSearchParams(window.location.search).has('snapshotId')
)

type AppTab = 'dashboard' | 'assistant'

const tabFromHash = (): AppTab => (
  window.location.hash === '#assistant' ? 'assistant' : 'dashboard'
)

function DashboardIcon() {
  return (
    <svg className="app-icon" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="3" y="3" width="7" height="7" rx="2" />
      <rect x="14" y="3" width="7" height="7" rx="2" />
      <rect x="3" y="14" width="7" height="7" rx="2" />
      <rect x="14" y="14" width="7" height="7" rx="2" />
    </svg>
  )
}

function AssistantIcon() {
  return (
    <svg className="app-icon" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M12 3.25c.5 3.76 2.49 5.75 6.25 6.25C14.49 10 12.5 11.99 12 15.75 11.5 11.99 9.51 10 5.75 9.5 9.51 9 11.5 7.01 12 3.25Z" />
      <path d="M18.5 15.25c.2 1.65 1.1 2.55 2.75 2.75-1.65.2-2.55 1.1-2.75 2.75-.2-1.65-1.1-2.55-2.75-2.75 1.65-.2 2.55-1.1 2.75-2.75Z" />
    </svg>
  )
}

function App() {
  const [accessStatus, setAccessStatus] = useState<DashboardAccessStatus | null>(null)
  const [accessError, setAccessError] = useState('')
  const [connected, setConnected] = useState(false)
  const [activeTab, setActiveTab] = useState<AppTab>(tabFromHash)
  const [visitedTabs, setVisitedTabs] = useState<Set<AppTab>>(
    () => new Set([tabFromHash()]),
  )
  const handleConnected = useCallback(() => setConnected(true), [])

  const loadAccessStatus = useCallback(() => {
    setAccessError('')
    requestJson<DashboardAccessStatus>('/api/access/status')
      .then(setAccessStatus)
      .catch((error) => setAccessError(formatError(error)))
  }, [])

  useEffect(() => {
    loadAccessStatus()
    const handleAccessRequired = () => {
      setConnected(false)
      setAccessStatus((current) => ({
        authenticated: false,
        configured: current?.configured ?? true,
        bypassed: false,
        sessionDays: current?.sessionDays ?? 30,
      }))
    }
    window.addEventListener('dashboard-access-required', handleAccessRequired)
    return () => window.removeEventListener('dashboard-access-required', handleAccessRequired)
  }, [loadAccessStatus])

  useEffect(() => {
    const handleHashChange = () => {
      if (isReportExportRoute()) return
      const nextTab = tabFromHash()
      setActiveTab(nextTab)
      setVisitedTabs((current) => new Set(current).add(nextTab))
    }
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  if (!accessStatus?.authenticated) {
    return (
      <AccessPage
        status={accessStatus}
        initialError={accessError}
        onAuthenticated={setAccessStatus}
        onRetry={loadAccessStatus}
      />
    )
  }

  if (!connected) {
    return <ConnectPage onConnected={handleConnected} />
  }

  const reportExportRoute = isReportExportRoute()

  return (
    <>
      <div className="app-shell">
        <header className="app-topbar">
          <div className="brand-block">
            <span className="brand-mark" aria-hidden="true">
              <svg className="app-icon" width="21" height="21" viewBox="0 0 24 24" focusable="false">
                <path d="M4 17.5 9 12l3.25 3.25L20 7.5" />
                <path d="M15.5 7.5H20V12" />
              </svg>
            </span>
            <h1>Financial dashboard</h1>
          </div>
          {!reportExportRoute ? (
            <nav className="page-tabs app-primary-nav app-primary-nav--desktop" aria-label="主导航">
              <a
                className={activeTab === 'dashboard' ? 'page-tab is-active' : 'page-tab'}
                href="#dashboard"
                aria-current={activeTab === 'dashboard' ? 'page' : undefined}
              >
                看板
              </a>
              <a
                className={activeTab === 'assistant' ? 'page-tab is-active' : 'page-tab'}
                href="#assistant"
                aria-current={activeTab === 'assistant' ? 'page' : undefined}
              >
                AI 助手
              </a>
            </nav>
          ) : null}
          {!reportExportRoute && !accessStatus.bypassed ? (
            <button
              type="button"
              className="ghost-button app-logout-button"
              onClick={async () => {
                await requestJson('/api/access/logout', { method: 'POST' })
                setConnected(false)
                setAccessStatus({ ...accessStatus, authenticated: false })
              }}
            >
              退出
            </button>
          ) : null}
        </header>

        <main className="app-content">
          {reportExportRoute ? <ReportPage /> : (
            <>
              {visitedTabs.has('dashboard') ? (
                <div className="app-view" hidden={activeTab !== 'dashboard'}>
                  <DashboardPage />
                </div>
              ) : null}
              {visitedTabs.has('assistant') ? (
                <div className="app-view" hidden={activeTab !== 'assistant'}>
                  <AssistantPage />
                </div>
              ) : null}
            </>
          )}
        </main>
      </div>

      {!reportExportRoute ? createPortal(
        <nav className="mobile-tab-bar" aria-label="底部导航">
          <a
            className={activeTab === 'dashboard' ? 'mobile-tab is-active' : 'mobile-tab'}
            href="#dashboard"
            aria-current={activeTab === 'dashboard' ? 'page' : undefined}
          >
            <DashboardIcon />
            <span>看板</span>
          </a>
          <a
            className={activeTab === 'assistant' ? 'mobile-tab is-active' : 'mobile-tab'}
            href="#assistant"
            aria-current={activeTab === 'assistant' ? 'page' : undefined}
          >
            <AssistantIcon />
            <span>AI 助手</span>
          </a>
        </nav>,
        document.body,
      ) : null}
    </>
  )
}

export default App
