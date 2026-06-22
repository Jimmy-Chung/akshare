import { useEffect, useState } from 'react'
import GlobalOverviewBar from '../components/GlobalOverviewBar'
import IndicesSection from '../components/IndicesSection'
import LongbridgeSectorHeatmap from '../components/LongbridgeSectorHeatmap'
import NewsDigestPanel from '../components/NewsDigestPanel'
import { InlineError } from '../components/StateBlocks'
import WeightStocksSection from '../components/WeightStocksSection'
import type { DashboardOverview, MarketIndexGroup } from '../types/market'
import { formatError, requestJson } from '../utils/api'
import { formatDashboardTime } from '../utils/market'

type DashboardMarket = 'CN' | 'HK' | 'US'

const MARKET_TABS: Array<{ key: DashboardMarket; label: string }> = [
  { key: 'CN', label: 'A 股' },
  { key: 'HK', label: '港股' },
  { key: 'US', label: '美股' },
]

export default function DashboardPage() {
  const [data, setData] = useState<DashboardOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [market, setMarket] = useState<DashboardMarket>('CN')

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
      description: '集中查看 A 股主要指数、行业热力图与核心权重股。',
      weightTitle: 'A 股核心权重股',
      weightSubtitle: '观察消费、金融、制造与新能源龙头的市场影响力',
      weights: data?.aWeights ?? [],
    },
    HK: {
      group: groups[1],
      title: '港股市场',
      description: '集中查看港股主要指数、行业热力图与核心权重股。',
      weightTitle: '港股权重股',
      weightSubtitle: '按市场影响力观察腾讯、阿里、美团与金融权重',
      weights: data?.hkWeights ?? [],
    },
    US: {
      group: groups[2],
      title: '美股市场',
      description: '集中查看美股主要指数、行业热力图与核心权重股。',
      weightTitle: '美股权重股',
      weightSubtitle: '按市值与波动观察科技巨头与指数权重',
      weights: data?.usWeights ?? [],
    },
  } satisfies Record<DashboardMarket, {
    group: MarketIndexGroup
    title: string
    description: string
    weightTitle: string
    weightSubtitle: string
    weights: DashboardOverview['hkWeights']
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
    + (data?.sourceSummary?.weights.fallback ?? 0)

  return (
    <div className="page-layout">
      <section className="page-hero">
        <div>
          <span className="page-hero__kicker">Dashboard</span>
          <h2>看板</h2>
          <p>统一展示全球指数、三地核心指数、A 股板块强弱、权重股与自动点评。</p>
        </div>
        <div className="hero-actions">
          <div className="source-pills">
            <span className="pill">
              行情 长桥优先{fallbackCount > 0 ? ` · ${fallbackCount} 项备用` : ''}
            </span>
            <span className="pill">{longbridgeLabel}</span>
            <span className="pill">板块 Longbridge</span>
            <span className="pill">新闻 {data?.sources?.news ?? 'rss'}</span>
          </div>
          <div className="hero-tools">
            <span className="meta-text">最近更新 {formatDashboardTime(data?.updatedAt)}</span>
            <button type="button" className="ghost-button" onClick={() => loadOverview(true)} disabled={refreshing}>
              {refreshing ? '刷新中' : '刷新数据'}
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
        <LongbridgeSectorHeatmap market={market} showMarketTabs={false} />
        <WeightStocksSection
          title={activeMarket.weightTitle}
          subtitle={activeMarket.weightSubtitle}
          stocks={activeMarket.weights}
          loading={loading && !data}
        />
      </section>
      <NewsDigestPanel articles={data?.newsDigest ?? []} loading={loading && !data} />

      {error && data ? <InlineError message={`局部刷新失败：${error}`} onRetry={() => loadOverview(true)} /> : null}
    </div>
  )
}
