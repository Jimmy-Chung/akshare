import { useEffect, useState } from 'react'
import GlobalOverviewBar from '../components/GlobalOverviewBar'
import IndicesSection from '../components/IndicesSection'
import SessionSwitcher from '../components/SessionSwitcher'
import { EmptyState, InlineError, SkeletonBlocks } from '../components/StateBlocks'
import type {
  MarketIndexGroup,
  SessionKey,
  SessionReport,
} from '../types/market'
import { formatError, requestJson } from '../utils/api'
import {
  formatReportDate,
  sessionLabel,
} from '../utils/market'

const SCHEDULE = [
  { session: 'morning' as const, time: '09:30', markets: '美股 · A 股 · 港股' },
  { session: 'midday' as const, time: '12:30', markets: 'A 股 · 港股' },
  { session: 'close' as const, time: '16:30', markets: 'A 股 · 港股' },
  { session: 'us-night' as const, time: '22:30', markets: '美股' },
]

export default function ReportPage() {
  const searchParams = new URLSearchParams(window.location.search)
  const requestedSession = searchParams.get('session')
  const requestedSnapshotId = searchParams.get('snapshotId') || ''
  const initialSession: SessionKey = (
    requestedSession === 'midday'
    || requestedSession === 'close'
    || requestedSession === 'us-night'
  ) ? requestedSession : 'morning'
  const [session, setSession] = useState<SessionKey>(initialSession)
  const [snapshotId, setSnapshotId] = useState(requestedSnapshotId)
  const [report, setReport] = useState<SessionReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [regenerating, setRegenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadReport = async ({
    targetSession,
    regenerate = false,
    targetSnapshotId = snapshotId,
  }: {
    targetSession?: SessionKey
    regenerate?: boolean
    targetSnapshotId?: string
  } = {}) => {
    const params = new URLSearchParams()
    if (targetSession) params.set('session', targetSession)
    if (!regenerate && targetSnapshotId) params.set('snapshotId', targetSnapshotId)
    const query = params.toString()
    const url = regenerate
      ? `/api/reports/generate${query ? `?${query}` : ''}`
      : targetSnapshotId
        ? `/api/reports/snapshot?snapshotId=${encodeURIComponent(targetSnapshotId)}`
        : `/api/reports/latest${query ? `?${query}` : ''}`
    regenerate ? setRegenerating(true) : setLoading(true)
    try {
      const payload = await requestJson<SessionReport>(url, {
        method: regenerate ? 'POST' : 'GET',
      })
      setReport(payload)
      setSession(payload.session)
      setSnapshotId(payload.snapshotId)
      setError(null)
    } catch (err) {
      setError(formatError(err))
    } finally {
      setLoading(false)
      setRegenerating(false)
    }
  }

  useEffect(() => {
    void loadReport({
      targetSession: initialSession,
      targetSnapshotId: requestedSnapshotId,
    })
  }, [])

  const groups: MarketIndexGroup[] = (report?.majorMarkets ?? []).map((group) => ({
    key: group.market,
    title: group.title,
    subtitle: group.subtitle,
    indices: group.indices,
  }))
  const preferredCodes = Object.fromEntries(
    (report?.chartExports ?? [])
      .filter((item) => item.kind === 'trend' && item.groupKey && item.indexCode)
      .map((item) => [item.groupKey as string, item.indexCode as string]),
  )

  return (
    <div className="page-layout">
      <section className="page-hero page-hero--report">
        <div>
          <span className="page-hero__kicker">Reports</span>
          <h2>四时段市场日报</h2>
          <p>每天于 09:30、12:30、16:30、22:30 固化指数数据包，不包含热点图。</p>
        </div>
        <div className="report-hero__actions">
          <SessionSwitcher
            value={session}
            onChange={(next) => {
              setSession(next)
              setSnapshotId('')
              void loadReport({ targetSession: next, targetSnapshotId: '' })
            }}
            disabled={loading}
          />
          <div className="hero-tools">
            <button
              type="button"
              className="ghost-button"
              onClick={() => {
                setSnapshotId('')
                void loadReport({ targetSession: session, regenerate: true, targetSnapshotId: '' })
              }}
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
                setSnapshotId('')
                void loadReport({ targetSession: item.session, targetSnapshotId: '' })
              }}
            >
              <span>{item.time}</span>
              <strong>{sessionLabel(item.session)}</strong>
              <small>{item.markets}</small>
            </button>
          ))}
        </div>
      </section>

      {error && !report ? (
        <InlineError
          message={error}
          onRetry={() => loadReport({ targetSession: session, targetSnapshotId: snapshotId })}
        />
      ) : null}

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
            preferredCodes={preferredCodes}
            exportFilenamePrefix={session}
            reportMode
          />

          <section className="surface-card surface-card--compact">
            <div className="report-source-note">
              <strong>数据来源</strong>
              <span>全球指数：{report.sources.globalIndices}</span>
              <span>主要指数：{report.sources.majorIndices}</span>
              <span>热点图：不属于报告数据包</span>
            </div>
          </section>
        </>
      )}

      {error && report ? (
        <InlineError
          message={`刷新失败：${error}`}
          onRetry={() => loadReport({ targetSession: session, targetSnapshotId: snapshotId })}
        />
      ) : null}
    </div>
  )
}
