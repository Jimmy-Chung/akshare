import { useCallback, useState } from 'react'
import DashboardPage from './pages/DashboardPage'
import ReportPage from './pages/ReportPage'
import ConnectPage from './pages/ConnectPage'
import './styles/App.css'

const isReportExportRoute = () => (
  window.location.hash === '#report'
  && new URLSearchParams(window.location.search).has('snapshotId')
)

function App() {
  const [connected, setConnected] = useState(false)
  const handleConnected = useCallback(() => setConnected(true), [])

  if (!connected) {
    return <ConnectPage onConnected={handleConnected} />
  }

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand-block">
          <span className="brand-kicker">Finogeeks Market Terminal</span>
          <h1>长桥主源行情看板</h1>
          <p>全球指数、三地主要市场、板块状态轨迹与 AI 市场报告</p>
        </div>
      </header>

      <main className="app-content">
        {isReportExportRoute() ? <ReportPage /> : <DashboardPage />}
      </main>
    </div>
  )
}

export default App
