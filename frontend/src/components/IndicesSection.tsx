import { useEffect, useState } from 'react'
import type { MarketIndexGroup } from '../types/market'
import { exportChartElement, normalizeChartId } from '../utils/chartExport'
import {
  buildChartPoints,
  formatDashboardTime,
  formatPercent,
  formatPrice,
  formatSignedNumber,
  getTrendClass,
} from '../utils/market'
import LineChart from './LineChart'
import SourceBadge from './SourceBadge'
import { EmptyState, SkeletonBlocks } from './StateBlocks'

interface IndicesSectionProps {
  groups: MarketIndexGroup[]
  loading?: boolean
  title?: string
  kicker?: string
  preferredCodes?: Record<string, string>
  exportFilenamePrefix?: string
}

export default function IndicesSection({
  groups,
  loading,
  title = '三市场主要指数',
  kicker = 'Cross Market Indices',
  preferredCodes = {},
  exportFilenamePrefix = '',
}: IndicesSectionProps) {
  const [selectedCodes, setSelectedCodes] = useState<Record<string, string>>({})

  useEffect(() => {
    setSelectedCodes((current) => {
      const next = { ...current }
      let changed = false
      for (const group of groups) {
        const preferred = preferredCodes[group.key]
        if (
          preferred
          && current[group.key] !== preferred
          && group.indices.some((item) => item.code === preferred)
        ) {
          next[group.key] = preferred
          changed = true
        } else if (!next[group.key] && group.indices[0]) {
          next[group.key] = group.indices[0].code
          changed = true
        }
      }
      return changed ? next : current
    })
  }, [groups, preferredCodes])

  return (
    <section className="surface-card">
      <div className="section-heading">
        <div>
          <span className="section-kicker">{kicker}</span>
          <h2>{title}</h2>
        </div>
      </div>

      {loading ? (
        <SkeletonBlocks blocks={3} height={260} />
      ) : (
        <div className={groups.length === 1 ? 'market-grid market-grid--single' : 'market-grid'}>
          {groups.map((group) => {
            const selected =
              group.indices.find((item) => item.code === selectedCodes[group.key]) ?? group.indices[0]
            const chartId = selected ? `trend-${normalizeChartId(selected.code)}` : ''
            const exportFilename = `${exportFilenamePrefix ? `${exportFilenamePrefix}-` : ''}${chartId}.png`

            return (
              <section key={group.key} className="market-panel">
                <div className="panel-header">
                  <div>
                    <h3>{group.title}</h3>
                    <p>{group.subtitle}</p>
                  </div>
                </div>

                {group.indices.length === 0 ? (
                  <EmptyState title="暂无指数数据" description="当前分组未返回可展示行情。" />
                ) : (
                  <>
                    <div className="index-grid">
                      {group.indices.map((item) => (
                        <button
                          key={item.code}
                          type="button"
                          className={selected?.code === item.code ? 'index-card is-selected' : 'index-card'}
                          onClick={() =>
                            setSelectedCodes((current) => ({
                              ...current,
                              [group.key]: item.code,
                            }))
                          }
                        >
                          <div>
                            <strong>{item.name}</strong>
                            <span>{item.code}</span>
                            <SourceBadge source={item.source} isFallback={item.isFallback} />
                          </div>
                          <div className="index-card__value">
                            <strong>{formatPrice(item.price)}</strong>
                            <span className={getTrendClass(item.changePercent)}>{formatPercent(item.changePercent)}</span>
                          </div>
                        </button>
                      ))}
                    </div>

                    {selected ? (
                      <div className="focus-panel">
                        <div className="chart-export-toolbar">
                          <span>附件 ID：{chartId}</span>
                          <button
                            type="button"
                            className="chart-export-button chart-export-button--inline"
                            data-export-chart-id={chartId}
                            data-export-filename={exportFilename}
                            aria-label={`导出图表 ${chartId}`}
                            onClick={() => void exportChartElement(chartId, exportFilename)}
                          >
                            导出 PNG
                          </button>
                        </div>
                        <div
                          className="report-chart-card report-index-chart-card"
                          data-chart-id={chartId}
                        >
                          <div className="report-chart-card__header">
                            <div>
                              <span>{group.title}</span>
                              <h3>{selected.name}</h3>
                              <small>{selected.code} · {formatDashboardTime(selected.tradeDate)}</small>
                            </div>
                            <SourceBadge source={selected.source} isFallback={selected.isFallback} />
                          </div>
                          <div className="report-index-chart-card__metrics">
                            <strong>{formatPrice(selected.price)}</strong>
                            <span className={getTrendClass(selected.changePercent)}>
                              {formatPercent(selected.changePercent)}
                            </span>
                            <span className={getTrendClass(selected.changePercent)}>
                              {formatSignedNumber(selected.changeAmount)}
                            </span>
                          </div>
                          {buildChartPoints(selected).length >= 2 ? (
                            <LineChart
                              data={buildChartPoints(selected)}
                              changePercent={selected.changePercent}
                              height={220}
                              showTimeScale
                            />
                          ) : (
                            <div className="chart-empty-state">暂无真实分时走势</div>
                          )}
                          <div className="report-chart-card__footer">
                            <span>分时走势</span>
                            <span>时间均为北京时间</span>
                          </div>
                        </div>
                      </div>
                    ) : null}
                  </>
                )}
              </section>
            )
          })}
        </div>
      )}
    </section>
  )
}
