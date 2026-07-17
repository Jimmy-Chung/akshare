import { useCallback, useEffect, useState } from 'react'
import DashboardPage from './pages/DashboardPage'
import AssistantPage from './pages/AssistantPage'
import ReportPage from './pages/ReportPage'
import ConnectPage from './pages/ConnectPage'
import './styles/App.css'

const isReportExportRoute = () => (
  window.location.hash === '#report'
  && new URLSearchParams(window.location.search).has('snapshotId')
)

type AppTab = 'dashboard' | 'assistant'

const tabFromHash = (): AppTab => (
  window.location.hash === '#assistant' ? 'assistant' : 'dashboard'
)

function App() {
  const [connected, setConnected] = useState(false)
  const [activeTab, setActiveTab] = useState<AppTab>(tabFromHash)
  const [visitedTabs, setVisitedTabs] = useState<Set<AppTab>>(
    () => new Set([tabFromHash()]),
  )
  const handleConnected = useCallback(() => setConnected(true), [])

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

  if (!connected) {
    return <ConnectPage onConnected={handleConnected} />
  }

  const reportExportRoute = isReportExportRoute()

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand-block">
          <span className="brand-kicker">Finogeeks Market Terminal</span>
          <h1>长桥主源行情看板</h1>
          <p>全球指数、三地主要市场、板块状态轨迹与 AI 市场报告</p>
        </div>
        {!reportExportRoute ? (
          <nav className="page-tabs app-primary-nav" aria-label="主导航">
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
  )
}

export default App
