import { useCallback, useEffect, useState } from 'react'
import DashboardPage from './pages/DashboardPage'
import ReportPage from './pages/ReportPage'
import ConnectPage from './pages/ConnectPage'
import './styles/App.css'

type PageTab = 'dashboard' | 'report'

const getInitialTab = (): PageTab => {
  return window.location.hash === '#report' ? 'report' : 'dashboard'
}

function App() {
  const [activeTab, setActiveTab] = useState<PageTab>(getInitialTab)
  const [connected, setConnected] = useState(false)
  const handleConnected = useCallback(() => setConnected(true), [])

  useEffect(() => {
    const handleHashChange = () => {
      setActiveTab(getInitialTab())
    }

    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  useEffect(() => {
    const nextHash = activeTab === 'report' ? '#report' : '#dashboard'
    if (window.location.hash !== nextHash) {
      window.history.replaceState(null, '', nextHash)
    }
  }, [activeTab])

  if (!connected) {
    return <ConnectPage onConnected={handleConnected} />
  }

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand-block">
          <span className="brand-kicker">Finogeeks Market Terminal</span>
          <h1>长桥主源行情看板</h1>
          <p>全球指数、三地主要市场、A 股板块强弱、权重股异动与分时点评</p>
        </div>
        <div className="topbar-actions">
          <nav className="page-tabs" aria-label="主页面签">
            <button
              className={activeTab === 'dashboard' ? 'page-tab is-active' : 'page-tab'}
              onClick={() => setActiveTab('dashboard')}
              type="button"
            >
              看板
            </button>
            <button
              className={activeTab === 'report' ? 'page-tab is-active' : 'page-tab'}
              onClick={() => setActiveTab('report')}
              type="button"
            >
              日报
            </button>
          </nav>
        </div>
      </header>

      <main className="app-content">
        {activeTab === 'dashboard' ? <DashboardPage /> : <ReportPage />}
      </main>
    </div>
  )
}

export default App
