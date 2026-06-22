import { useEffect, useState } from 'react'
import GlobalOverviewBar from '../components/GlobalOverviewBar'
import IndicesSection from '../components/IndicesSection'
import SessionSwitcher from '../components/SessionSwitcher'
import { EmptyState, InlineError, SkeletonBlocks } from '../components/StateBlocks'
import type {
  MarketIndexGroup,
  SectorRankingItem,
  SectorRankingPair,
  SessionKey,
  SessionReport,
} from '../types/market'
import { formatError, requestJson } from '../utils/api'
import {
  formatChineseAmount,
  formatPercent,
  formatPrice,
  formatReportDate,
  getTrendClass,
  sessionLabel,
} from '../utils/market'

const SCHEDULE = [
  { session: 'morning' as const, time: '09:30', markets: '美股 · A 股 · 港股' },
  { session: 'midday' as const, time: '12:30', markets: 'A 股 · 港股' },
  { session: 'close' as const, time: '16:30', markets: 'A 股 · 港股' },
  { session: 'us-night' as const, time: '22:30', markets: '美股' },
]

function RankingList({
  title,
  items,
  showIndustryRelationship = false,
}: {
  title: string
  items: SectorRankingItem[]
  showIndustryRelationship?: boolean
}) {
  return (
    <div className="report-ranking-list">
      <h4>{title}</h4>
      {items.map((item, index) => (
        <div
          className={showIndustryRelationship ? 'report-ranking-row report-ranking-row--linked' : 'report-ranking-row'}
          key={item.code || `${item.name}-${index}`}
        >
          <div className="report-ranking-main">
            <span className="report-ranking-index">{index + 1}</span>
            <span className="report-ranking-name">
              {showIndustryRelationship && item.parentName ? (
                <small className="report-ranking-parent">
                  <span>一级分类</span>
                  <strong>{item.parentName}</strong>
                </small>
              ) : null}
              <strong>{item.name}</strong>
              {!showIndustryRelationship ? <small>{item.parentName || item.code}</small> : null}
            </span>
            <span className="report-ranking-value">
              <strong className={getTrendClass(item.changePercent)}>
                {formatPercent(item.changePercent)}
              </strong>
              <small>{item.marketValue ? formatChineseAmount(item.marketValue) : '--'}</small>
            </span>
          </div>
          {showIndustryRelationship ? (
            <div className="report-ranking-leader">
              <span className="report-ranking-link-mark" aria-hidden="true">↳</span>
              <span>
                <small>行业领涨股</small>
                <strong>{item.dayLeader?.name || '暂无数据'}</strong>
              </span>
              <span className="report-ranking-leader-code">
                <small>{item.dayLeader?.code || '--'}</small>
                <strong>
                  {item.dayLeader?.price == null ? '--' : formatPrice(item.dayLeader.price)}
                </strong>
              </span>
              <strong className={getTrendClass(item.dayLeader?.changePercent ?? 0)}>
                {item.dayLeader?.name ? formatPercent(item.dayLeader.changePercent) : '--'}
              </strong>
            </div>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function RankingLevel({
  title,
  ranking,
  showIndustryRelationship = false,
}: {
  title: string
  ranking: SectorRankingPair
  showIndustryRelationship?: boolean
}) {
  return (
    <section className="report-ranking-level">
      <h3>{title}</h3>
      <div className="report-ranking-columns">
        <RankingList
          title="领涨前三"
          items={ranking.leaders}
          showIndustryRelationship={showIndustryRelationship}
        />
        <RankingList
          title="领跌前三"
          items={ranking.laggards}
          showIndustryRelationship={showIndustryRelationship}
        />
      </div>
    </section>
  )
}

export default function ReportPage() {
  const [session, setSession] = useState<SessionKey>('morning')
  const [report, setReport] = useState<SessionReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [regenerating, setRegenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadReport = async (targetSession?: SessionKey, regenerate = false) => {
    const params = targetSession ? `?session=${encodeURIComponent(targetSession)}` : ''
    const url = regenerate ? `/api/reports/generate${params}` : `/api/reports/latest${params}`
    regenerate ? setRegenerating(true) : setLoading(true)
    try {
      const payload = await requestJson<SessionReport>(url, {
        method: regenerate ? 'POST' : 'GET',
      })
      setReport(payload)
      setSession(payload.session)
      setError(null)
    } catch (err) {
      setError(formatError(err))
    } finally {
      setLoading(false)
      setRegenerating(false)
    }
  }

  useEffect(() => {
    loadReport()
  }, [])

  const groups: MarketIndexGroup[] = (report?.majorMarkets ?? []).map((group) => ({
    key: group.market,
    title: group.title,
    subtitle: group.subtitle,
    indices: group.indices,
  }))

  return (
    <div className="page-layout">
      <section className="page-hero page-hero--report">
        <div>
          <span className="page-hero__kicker">Reports</span>
          <h2>四时段市场日报</h2>
          <p>每天于 09:30、12:30、16:30、22:30 生成结构化市场快照。</p>
        </div>
        <div className="report-hero__actions">
          <SessionSwitcher
            value={session}
            onChange={(next) => {
              setSession(next)
              void loadReport(next)
            }}
            disabled={loading}
          />
          <div className="hero-tools">
            <button
              type="button"
              className="ghost-button"
              onClick={() => loadReport(session, true)}
              disabled={regenerating}
            >
              {regenerating ? '生成中' : '重新生成'}
            </button>
            <span className="meta-text">
              {report ? `${report.label} · ${formatReportDate(report.generatedAt)}` : '读取中'}
            </span>
          </div>
        </div>
      </section>

      <section className="surface-card surface-card--compact">
        <div className="report-schedule-grid">
          {SCHEDULE.map((item) => (
            <button
              type="button"
              key={item.session}
              className={item.session === session ? 'report-schedule-card is-active' : 'report-schedule-card'}
              onClick={() => {
                setSession(item.session)
                void loadReport(item.session)
              }}
            >
              <span>{item.time}</span>
              <strong>{sessionLabel(item.session)}</strong>
              <small>{item.markets}</small>
            </button>
          ))}
        </div>
      </section>

      {error && !report ? <InlineError message={error} onRetry={() => loadReport(session)} /> : null}

      {loading && !report ? (
        <SkeletonBlocks blocks={4} height={180} />
      ) : !report ? (
        <EmptyState title="暂无日报" description="当前时段的日报尚未生成。" />
      ) : (
        <>
          <section className="surface-card surface-card--compact">
            <div className="report-meta-strip">
              <div>
                <span>当前报告</span>
                <strong>{report.label}</strong>
              </div>
              <div>
                <span>主要市场</span>
                <strong>{report.marketLabels.join(' · ')}</strong>
              </div>
              <div>
                <span>计划时间</span>
                <strong>{report.scheduledAt}</strong>
              </div>
              <div>
                <span>数据时间</span>
                <strong>{formatReportDate(report.generatedAt)}</strong>
              </div>
            </div>
          </section>

          <GlobalOverviewBar
            groups={report.globalOverview}
            updatedAt={report.generatedAt}
          />

          <IndicesSection
            groups={groups}
            title="主要市场主要指数"
            kicker="Major Market Indices"
          />

          <section className="surface-card">
            <div className="section-heading">
              <div>
                <span className="section-kicker">Sector Rankings</span>
                <h2>主要市场板块涨跌幅前三</h2>
                <p>分别展示一级分类与二级行业的领涨、领跌前三。</p>
              </div>
            </div>
            <div className="report-sector-markets">
              {report.sectorRankings.map((market) => (
                <section className="report-sector-market" key={market.market}>
                  <div className="panel-header">
                    <div>
                      <h3>{market.title}</h3>
                      <p>数据源：{market.source}</p>
                    </div>
                  </div>
                  <RankingLevel title="一级分类" ranking={market.primary} />
                  <RankingLevel
                    title="二级行业 · 分类与领涨股关联"
                    ranking={market.secondary}
                    showIndustryRelationship
                  />
                </section>
              ))}
            </div>
          </section>

          <section className="surface-card surface-card--compact">
            <div className="report-source-note">
              <strong>数据来源</strong>
              <span>全球指数：{report.sources.globalIndices}</span>
              <span>主要指数：{report.sources.majorIndices}</span>
              <span>板块排行：{report.sources.sectorRankings}</span>
            </div>
          </section>
        </>
      )}

      {error && report ? <InlineError message={`刷新失败：${error}`} onRetry={() => loadReport(session)} /> : null}
    </div>
  )
}
