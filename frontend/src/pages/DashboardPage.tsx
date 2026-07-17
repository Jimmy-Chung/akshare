import { useEffect, useState } from 'react'
import GlobalOverviewBar from '../components/GlobalOverviewBar'
import IndicesSection from '../components/IndicesSection'
import SectorStateTrajectory from '../components/SectorStateTrajectory'
import { InlineError } from '../components/StateBlocks'
import type {
  DashboardOverview,
  HeatmapSnapshotDatesResponse,
  MarketIndexGroup,
} from '../types/market'
import { formatError, requestJson } from '../utils/api'
import { formatDashboardTime } from '../utils/market'

type DashboardMarket = 'CN' | 'HK' | 'US'

const MARKET_TABS: Array<{ key: DashboardMarket; label: string }> = [
  { key: 'CN', label: 'A 股' },
  { key: 'HK', label: '港股' },
  { key: 'US', label: '美股' },
]

export default function DashboardPage() {
  const exportSession = new URLSearchParams(window.location.search).get('session') || ''
  const heatmapSnapshotId = new URLSearchParams(window.location.search).get('heatmapSnapshotId') || ''
  const heatmapExportMode = new URLSearchParams(window.location.search).get('heatmapExport') === '1'
  const [data, setData] = useState<DashboardOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [heatmapDates, setHeatmapDates] = useState<HeatmapSnapshotDatesResponse | null>(null)
  const [heatmapDate, setHeatmapDate] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [market, setMarket] = useState<DashboardMarket>(() => {
    const requested = new URLSearchParams(window.location.search).get('market')?.toUpperCase()
    return requested === 'HK' || requested === 'US' ? requested : 'CN'
  })

  useEffect(() => {
    if (heatmapExportMode) return undefined
    let cancelled = false
    requestJson<HeatmapSnapshotDatesResponse>(`/api/heatmap-snapshots/dates?market=${market}`)
      .then((payload) => {
        if (cancelled) return
        setHeatmapDates(payload)
        setHeatmapDate(payload.latestDate)
      })
      .catch(() => {
        if (cancelled) return
        setHeatmapDates(null)
        setHeatmapDate('')
      })
    return () => {
      cancelled = true
    }
  }, [heatmapExportMode, market])

  const loadOverview = async (silent = false) => {
    if (silent) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }

    try {
      const payload = await requestJson<DashboardOverview>('/api/dashboard/overview')
      setData(payload)
      setError(null)
    } catch (err) {
      setError(formatError(err))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    loadOverview()
    const timer = window.setInterval(() => {
      loadOverview(true)
    }, 5 * 60 * 1000)

    return () => window.clearInterval(timer)
  }, [])

  const groups: MarketIndexGroup[] = [
    {
      key: 'aShares',
      title: 'A 股主要指数',
      subtitle: '上证、深成指、创业板与宽基风格同步观察',
      indices: data?.majorIndices.aShares ?? [],
    },
    {
      key: 'hk',
      title: '港股主要指数',
      subtitle: '恒指、恒生科技与国企指数并列展示',
      indices: data?.majorIndices.hk ?? [],
    },
    {
      key: 'us',
      title: '美股主要指数',
      subtitle: '标普、纳指与道指作为夜盘锚点',
      indices: data?.majorIndices.us ?? [],
    },
  ]
  const marketConfig = {
    CN: {
      group: groups[0],
      title: 'A 股市场',
      description: '集中查看 A 股主要指数与板块状态轨迹。',
    },
    HK: {
      group: groups[1],
      title: '港股市场',
      description: '集中查看港股主要指数与板块状态轨迹。',
    },
    US: {
      group: groups[2],
      title: '美股市场',
      description: '集中查看美股主要指数与板块状态轨迹。',
    },
  } satisfies Record<DashboardMarket, {
    group: MarketIndexGroup
    title: string
    description: string
  }>
  const activeMarket = marketConfig[market]

  const longbridgeStatus = data?.sourceStatus?.longbridge
  const longbridgeLabel = longbridgeStatus?.usingLiveSource
    ? '长桥已接通'
    : longbridgeStatus?.configured
      ? '长桥未连通'
      : '长桥未配置'
  const fallbackCount =
    (data?.sourceSummary?.global.fallback ?? 0)
    + (data?.sourceSummary?.majorIndices.fallback ?? 0)
  const indexRows = [
    ...(data?.globalIndices ?? []),
    ...(data?.majorIndices.aShares ?? []),
    ...(data?.majorIndices.hk ?? []),
    ...(data?.majorIndices.us ?? []),
  ]
  const indexSources = Array.from(new Set(indexRows.map((item) => item.source).filter(Boolean)))
  const fallbackSources = Array.from(new Set(
    indexRows
      .filter((item) => item.isFallback)
      .map((item) => item.source)
      .filter(Boolean),
  ))

  return (
    <div className="page-layout">
      <section className="page-hero">
        <div>
          <span className="page-hero__kicker">Dashboard</span>
          <h2>看板</h2>
          <p>统一展示全球指数、三地核心指数、板块状态轨迹与自动点评。</p>
        </div>
        <div className="hero-actions">
          <div className="hero-tools">
            <span className="meta-text">最近更新 {formatDashboardTime(data?.updatedAt)}</span>
            <button type="button" className="ghost-button" onClick={() => loadOverview(true)} disabled={refreshing}>
              {refreshing ? '刷新中' : '刷新指数'}
            </button>
          </div>
        </div>
      </section>

      {error && !data ? <InlineError message={error} onRetry={() => loadOverview()} /> : null}

      <GlobalOverviewBar
        groups={data?.globalMarketGroups ?? []}
        updatedAt={data?.updatedAt}
        loading={loading && !data}
      />
      <section className="market-workspace">
        <div className="market-workspace__header">
          <div>
            <span className="section-kicker">Three Market Workspace</span>
            <h2>{activeMarket.title}</h2>
            <p>{activeMarket.description}</p>
          </div>
          <div className="session-switcher" aria-label="市场切换">
            {MARKET_TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                className={market === tab.key ? 'session-tab is-active' : 'session-tab'}
                onClick={() => setMarket(tab.key)}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <IndicesSection
          groups={[activeMarket.group]}
          title={`${activeMarket.title}主要指数`}
          kicker="Market Indices"
          loading={loading && !data}
        />
        {!heatmapExportMode ? (
          <div className="heatmap-review-bar">
            <div>
              <strong>热点回顾</strong>
              <span>
                {heatmapDates?.timezoneLabel || (market === 'US' ? '纽约时间' : '北京时间')}
                交易日归档
              </span>
            </div>
            <label>
              <span>选择日期</span>
              <select
                value={heatmapDate}
                onChange={(event) => setHeatmapDate(event.target.value)}
                disabled={!heatmapDates?.dates.length}
              >
                {!heatmapDates?.dates.length ? <option value="">暂无历史数据</option> : null}
                {heatmapDates?.dates.map((item) => (
                  <option key={item.date} value={item.date}>
                    {item.date}（{item.snapshotCount} 个快照）
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : null}
        <SectorStateTrajectory
          key={`${market}:${heatmapDate}:${heatmapSnapshotId}`}
          market={market}
          date={heatmapDate}
          snapshotId={heatmapSnapshotId}
          reportMode={heatmapExportMode}
          exportFilenamePrefix={exportSession}
        />
      </section>
      {error && data ? <InlineError message={`局部刷新失败：${error}`} onRetry={() => loadOverview(true)} /> : null}
      {!heatmapExportMode ? (
        <div className="dashboard-source-tip-wrap">
          <details className="dashboard-source-tip">
            <summary aria-label="查看当前接口与数据源">
              <span className="dashboard-source-tip__chevron" aria-hidden="true" />
              数据来源
            </summary>
            <div className="dashboard-source-tip__popover">
              <strong>当前接口与数据源</strong>
              <dl>
                <div>
                  <dt>指数行情</dt>
                  <dd>{indexSources.length ? indexSources.join('、') : '等待数据'}</dd>
                </div>
                <div>
                  <dt>取数策略</dt>
                  <dd>
                    Longbridge 优先
                    {fallbackCount > 0
                      ? `，${fallbackCount} 项由 ${fallbackSources.join('、') || '备用接口'} 补齐`
                      : '，当前没有使用备用接口'}
                  </dd>
                </div>
                <div>
                  <dt>板块状态</dt>
                  <dd>Longbridge 统一快照</dd>
                </div>
                <div>
                  <dt>连接状态</dt>
                  <dd>{longbridgeLabel}</dd>
                </div>
              </dl>
              <span>更新时间 {formatDashboardTime(data?.updatedAt)}</span>
            </div>
          </details>
        </div>
      ) : null}
    </div>
  )
}
