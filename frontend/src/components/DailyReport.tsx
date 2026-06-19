import { useEffect, useState, type FC } from 'react'
import '../styles/DailyReport.css'

interface BreadthData {
  upCount: number
  downCount: number
  winRate: number
  limitUp: number
  limitDown: number
  totalTurnover: number
}

interface IndexData {
  name: string
  price: number
  changePercent: number
}

interface BoardData {
  name: string
  code: string
  changePercent: number
  netInflow?: number | null
  topStocks?: StockData[]
}

interface StockData {
  name: string
  code: string
  price: number
  changePercent: number
}

const BASE = ''

const green = (v: number) => v > 0 ? 'var(--color-up)' : v < 0 ? 'var(--color-down)' : 'var(--color-neutral)'

const DailyReport: FC = () => {
  const [breadth, setBreadth] = useState<BreadthData | null>(null)
  const [aIndices, setAIndices] = useState<IndexData[]>([])
  const [hkIndices, setHkIndices] = useState<IndexData[]>([])
  const [boards, setBoards] = useState<BoardData[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetch(`${BASE}/api/market-breadth`).then(r => r.json()),
      fetch(`${BASE}/api/a-indices`).then(r => r.json()),
      fetch(`${BASE}/api/hk-indices`).then(r => r.json()),
      fetch(`${BASE}/api/a-boards`).then(r => r.json()),
    ]).then(([b, a, h, boardsRaw]) => {
      setBreadth(b || {})
      setAIndices(a)
      setHkIndices(h)
      const sorted = (boardsRaw as BoardData[]).sort((x, y) => (y.changePercent || 0) - (x.changePercent || 0))
      setBoards(sorted)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  if (loading) return <div className="report-loading">加载中...</div>
  if (!breadth) return <div className="report-loading">数据暂不可用</div>

  const t = (breadth.totalTurnover || 0) / 1e12
  const win = breadth.winRate || 0
  const trend = win > 65 ? '强势上攻' : win > 55 ? '温和上涨' : win < 45 ? '震荡偏弱' : '多空拉锯'
  const hkTrend = hkIndices[0]?.changePercent > 0 ? '同步走高' : '全线回调'
  const now = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })

  return (
    <div className="daily-report">
      <h1>📊 A股港股日报 | {now}</h1>

      {/* A股市场 */}
      <section>
        <h2>A股市场</h2>
        <div className="metrics-grid">
          <div className="metric"><span className="label">成交额</span><strong>{t.toFixed(2)} 万亿</strong></div>
          <div className="metric"><span className="label">涨跌比</span><strong>{breadth.upCount}↑ / {breadth.downCount}↓</strong></div>
          <div className="metric"><span className="label">赚钱效应</span><strong>{win}%</strong></div>
          <div className="metric"><span className="label">涨停/跌停</span><strong>{breadth.limitUp}只 / {breadth.limitDown}只</strong></div>
        </div>

        <h3>主要指数</h3>
        <table>
          <thead><tr><th>指数</th><th>收盘价</th><th>涨跌幅</th></tr></thead>
          <tbody>
            {aIndices.map(x => (
              <tr key={x.name}>
                <td>{x.name}</td>
                <td className="num">{x.price?.toFixed(2)}</td>
                <td className="num" style={{ color: green(x.changePercent) }}>{x.changePercent > 0 ? '+' : ''}{x.changePercent?.toFixed(2)}%</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3>板块动向</h3>
        <div className="board-tags">
          <div className="tag-group">
            <span className="tag-label">🏆 涨幅 Top5</span>
            {boards.slice(0, 5).map(b => (
              <span key={b.name} className="tag up">{b.name} <em>{(b.changePercent > 0 ? '+' : '')}{b.changePercent?.toFixed(1)}%</em></span>
            ))}
          </div>
          <div className="tag-group">
            <span className="tag-label">📉 跌幅 Top5</span>
            {boards.slice(-5).reverse().map(b => (
              <span key={b.name} className="tag down">{b.name} <em>{(b.changePercent > 0 ? '+' : '')}{b.changePercent?.toFixed(1)}%</em></span>
            ))}
          </div>
        </div>

        <h3>领涨个股</h3>
        <table>
          <thead><tr><th>板块</th><th>涨幅</th><th>领涨股</th><th>涨跌幅</th></tr></thead>
          <tbody>
            {boards.slice(0, 5).map(board => {
              const leader = board.topStocks?.[0]
              return (
                <tr key={board.name}>
                  <td>{board.name}</td>
                  <td className="num" style={{ color: green(board.changePercent) }}>{(board.changePercent > 0 ? '+' : '')}{board.changePercent?.toFixed(1)}%</td>
                  <td>{leader?.name || '—'}</td>
                  <td className="num" style={{ color: green(leader?.changePercent ?? 0) }}>{leader ? `${leader.changePercent > 0 ? '+' : ''}${leader.changePercent?.toFixed(1)}%` : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>

        <h3>领跌个股</h3>
        <table>
          <thead><tr><th>板块</th><th>跌幅</th><th>领跌股</th><th>涨跌幅</th></tr></thead>
          <tbody>
            {boards.slice(-5).reverse().map(board => {
              const leader = board.topStocks?.[0]
              return (
                <tr key={board.name}>
                  <td>{board.name}</td>
                  <td className="num" style={{ color: green(board.changePercent) }}>{(board.changePercent > 0 ? '+' : '')}{board.changePercent?.toFixed(1)}%</td>
                  <td>{leader?.name || '—'}</td>
                  <td className="num" style={{ color: green(leader?.changePercent ?? 0) }}>{leader ? `${leader.changePercent > 0 ? '+' : ''}${leader.changePercent?.toFixed(1)}%` : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>

      {/* 港股市场 */}
      <section>
        <h2>港股市场</h2>
        <table>
          <thead><tr><th>指数</th><th>收盘价</th><th>涨跌幅</th></tr></thead>
          <tbody>
            {hkIndices.map(x => (
              <tr key={x.name}>
                <td>{x.name}</td>
                <td className="num">{x.price?.toFixed(2)}</td>
                <td className="num" style={{ color: green(x.changePercent) }}>{(x.changePercent > 0 ? '+' : '')}{x.changePercent?.toFixed(2)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* 小结 */}
      <section className="summary">
        <h2>📝 小结</h2>
        <p>A股今日{trend}，{breadth.upCount}涨{breadth.downCount}跌，赚钱效应{win}%，{boards[0]?.name || '—'}{boards[0]?.changePercent > 0 ? '+' : ''}{boards[0]?.changePercent?.toFixed(1)}%领涨。港股{hkTrend}，恒指{hkIndices[0]?.changePercent > 0 ? '+' : ''}{hkIndices[0]?.changePercent?.toFixed(2)}%。</p>
      </section>

      {/* Reference */}
      <footer className="report-ref">
        <h3>🔗 数据接口</h3>
        <table>
          <thead><tr><th>#</th><th>接口</th><th>数据</th></tr></thead>
          <tbody>
            <tr><td>1</td><td><code>/api/market-breadth</code></td><td>成交额、涨跌比、赚钱效应、涨停跌停</td></tr>
            <tr><td>2</td><td><code>/api/a-indices</code></td><td>上证/深证/创业板/科创50/北证50</td></tr>
            <tr><td>3</td><td><code>/api/hk-indices</code></td><td>恒生/恒生科技/国企/红筹</td></tr>
            <tr><td>4</td><td><code>/api/a-boards</code></td><td>行业板块按涨幅排序</td></tr>
            <tr><td>5</td><td><code>/api/a-board-stocks?board=BK代码</code></td><td>指定板块 Top10 成分股</td></tr>
          </tbody>
        </table>
      </footer>
    </div>
  )
}

export default DailyReport
