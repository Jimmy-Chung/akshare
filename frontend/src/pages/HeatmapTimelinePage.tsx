import { useEffect, useState } from 'react'
import { EmptyState, InlineError } from '../components/StateBlocks'
import type { HeatmapTimelineFramesResponse } from '../types/market'
import { formatError, requestJson } from '../utils/api'

type TimelineMarket = 'CN' | 'HK' | 'US'

const MARKET_TABS: Array<{ key: TimelineMarket; label: string; detail: string }> = [
  { key: 'CN', label: 'A 股', detail: '09:30-11:30 / 13:00-15:00' },
  { key: 'HK', label: '港股', detail: '09:30-12:00 / 13:00-16:00' },
  { key: 'US', label: '美股', detail: '纽约 09:30-16:00' },
]

const todayKey = () => new Date().toISOString().slice(0, 10)

export default function HeatmapTimelinePage() {
  const [market, setMarket] = useState<TimelineMarket>(() => {
    const requested = new URLSearchParams(window.location.search).get('market')?.toUpperCase()
    return requested === 'HK' || requested === 'US' ? requested : 'CN'
  })
  const [date, setDate] = useState(todayKey)
  const [data, setData] = useState<HeatmapTimelineFramesResponse | null>(null)
  const [frameIndex, setFrameIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speedMs, setSpeedMs] = useState(900)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadFrames = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const params = new URLSearchParams({ market, date })
      const payload = await requestJson<HeatmapTimelineFramesResponse>(
        `/api/heatmap-timeline/frames?${params.toString()}`,
      )
      setData(payload)
      setFrameIndex((current) => Math.min(current, Math.max(0, payload.frames.length - 1)))
      setError(null)
    } catch (err) {
      setError(formatError(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setFrameIndex(0)
    setPlaying(false)
    void loadFrames()
  }, [market, date])

  useEffect(() => {
    if (!playing || !data?.frames.length) return undefined
    const timer = window.setInterval(() => {
      setFrameIndex((current) => (current + 1) % data.frames.length)
    }, speedMs)
    return () => window.clearInterval(timer)
  }, [playing, data?.frames.length, speedMs])

  useEffect(() => {
    const refreshTimer = window.setInterval(() => {
      void loadFrames(true)
    }, 60 * 1000)
    return () => window.clearInterval(refreshTimer)
  }, [market, date])

  const activeFrame = data?.frames[frameIndex]
  const activeMarket = MARKET_TABS.find((item) => item.key === market) ?? MARKET_TABS[0]

  return (
    <div className="page-layout heatmap-timeline-page">
      <section className="page-hero page-hero--heatmap">
        <div>
          <span className="page-hero__kicker">Heatmap Timeline</span>
          <h2>热点图</h2>
          <p>按市场播放从开盘到当前时间采集到的行业热力图快照。</p>
        </div>
        <div className="hero-actions">
          <div className="source-pills">
            <span className="pill">每 30 分钟采集</span>
            <span className="pill">仅交易时段</span>
            <span className="pill">PNG 原帧播放</span>
          </div>
          <div className="hero-tools">
            <input
              className="timeline-date-input"
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
            />
            <button type="button" className="ghost-button" onClick={() => loadFrames(true)}>
              刷新帧
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
              onClick={() => setMarket(tab.key)}
            >
              <strong>{tab.label}</strong>
              <span>{tab.detail}</span>
            </button>
          ))}
        </div>
      </section>

      {error ? <InlineError message={error} onRetry={() => loadFrames()} /> : null}

      <section className="surface-card timeline-player-card">
        <div className="section-heading">
          <div>
            <span className="section-kicker">Timeline Player</span>
            <h2>{activeMarket.label}热点图变化</h2>
            <p>
              {data
                ? `${data.date} · 已采集 ${data.frameCount} 帧`
                : loading
                  ? '读取热点图帧中'
                  : '暂无帧数据'}
            </p>
          </div>
          <div className="timeline-controls">
            <button
              type="button"
              className="primary-button"
              onClick={() => setPlaying((value) => !value)}
              disabled={!data?.frames.length}
            >
              {playing ? '暂停' : '播放'}
            </button>
            <select
              className="timeline-speed-select"
              value={speedMs}
              onChange={(event) => setSpeedMs(Number(event.target.value))}
            >
              <option value={1500}>慢速</option>
              <option value={900}>正常</option>
              <option value={450}>快速</option>
            </select>
          </div>
        </div>

        {!activeFrame ? (
          <EmptyState
            title={loading ? '正在读取热点图帧' : '暂无热点图帧'}
            description="开盘后应用内 watcher 会按 30 分钟保存一张热力图，之后这里会自动出现可播放序列。"
          />
        ) : (
          <div className="timeline-stage">
            <div className="timeline-frame-meta">
              <span>当前帧</span>
              <strong>{activeFrame.label}</strong>
              <small>{activeFrame.filename}</small>
            </div>
            <div className="timeline-image-shell">
              <img src={activeFrame.url} alt={`${activeMarket.label}热点图 ${activeFrame.label}`} />
            </div>
            <div className="timeline-scrubber">
              <input
                type="range"
                min={0}
                max={Math.max(0, (data?.frames.length ?? 1) - 1)}
                value={frameIndex}
                onChange={(event) => {
                  setFrameIndex(Number(event.target.value))
                  setPlaying(false)
                }}
              />
              <div className="timeline-frame-list">
                {data?.frames.map((frame, index) => (
                  <button
                    key={frame.filename}
                    type="button"
                    className={index === frameIndex ? 'is-active' : ''}
                    onClick={() => {
                      setFrameIndex(index)
                      setPlaying(false)
                    }}
                  >
                    {frame.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
