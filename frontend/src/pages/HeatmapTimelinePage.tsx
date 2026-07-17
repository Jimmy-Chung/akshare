import { useState } from 'react'
import SectorStateTrajectory from '../components/SectorStateTrajectory'
import { EmptyState } from '../components/StateBlocks'

type TimelineMarket = 'CN' | 'HK' | 'US'

const MARKET_TABS: Array<{ key: TimelineMarket; label: string; detail: string }> = [
  { key: 'CN', label: 'A 股', detail: '09:30-11:30 / 13:00-15:00' },
  { key: 'HK', label: '港股', detail: '09:30-12:00 / 13:00-16:00' },
  { key: 'US', label: '美股', detail: '纽约 09:30-16:00' },
]

const heatmapParams = () => {
  const hashQuery = window.location.hash.split('?')[1] ?? ''
  return new URLSearchParams(hashQuery || window.location.search)
}

export default function HeatmapTimelinePage() {
  const [market, setMarket] = useState<TimelineMarket>(() => {
    const requested = heatmapParams().get('market')?.toUpperCase()
    return requested === 'HK' || requested === 'US' ? requested : 'CN'
  })
  const [date, setDate] = useState(() => heatmapParams().get('date') ?? '')
  const [refreshVersion, setRefreshVersion] = useState(0)

  return (
    <div className="page-layout heatmap-timeline-page">
      <section className="page-hero page-hero--heatmap">
        <div>
          <span className="page-hero__kicker">Sector State Timeline</span>
          <h2>热点图</h2>
          <p>按市场播放开盘后的板块涨跌、交易活跃度与市值结构变化。</p>
        </div>
        <div className="hero-actions">
          <div className="source-pills">
            <span className="pill">每 30 分钟采集</span>
            <span className="pill">仅交易时段</span>
            <span className="pill">实时轨迹播放</span>
          </div>
          <div className="hero-tools">
            <input
              className="timeline-date-input"
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
              aria-label="选择热点图交易日期"
              title="选择需要查看的交易日期"
            />
            <button
              type="button"
              className="ghost-button"
              disabled={!date}
              onClick={() => setRefreshVersion((current) => current + 1)}
            >
              刷新快照
            </button>
          </div>
        </div>
      </section>

      <section className="surface-card surface-card--compact">
        <div className="timeline-market-switcher" aria-label="热点图市场切换">
          {MARKET_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              className={market === tab.key ? 'timeline-market-card is-active' : 'timeline-market-card'}
              onClick={() => {
                setDate('')
                setMarket(tab.key)
              }}
            >
              <strong>{tab.label}</strong>
              <span>{tab.detail}</span>
            </button>
          ))}
        </div>
      </section>

      {date ? (
        <SectorStateTrajectory
          key={`${market}:${date}:${refreshVersion}`}
          market={market}
          date={date}
          refreshVersion={refreshVersion}
        />
      ) : (
        <EmptyState title="请选择交易日期" description="选择日期后再加载并显示该市场的板块状态轨迹。" />
      )}
    </div>
  )
}
