import { useEffect, useState } from 'react'
import type { DashboardOverview, WeightStockEntry } from '../types/market'
import { requestJson } from '../utils/api'
import { formatChineseAmount, formatPercent, formatPrice, getTrendClass } from '../utils/market'
import { EmptyState, SkeletonBlocks } from './StateBlocks'

interface SectorHeatmapProps {
  data?: DashboardOverview['aShareSectors']
  loading?: boolean
}

function cellOpacity(changePercent: number) {
  const intensity = Math.min(Math.abs(changePercent) / 6, 1)
  return 0.12 + intensity * 0.28
}

function highlightStyle(changePercent: number) {
  if (changePercent > 0) {
    return {
      backgroundColor: `rgba(229, 72, 77, ${cellOpacity(changePercent)})`,
      borderColor: 'rgba(229, 72, 77, 0.18)',
    }
  }
  if (changePercent < 0) {
    return {
      backgroundColor: `rgba(22, 163, 74, ${cellOpacity(changePercent)})`,
      borderColor: 'rgba(22, 163, 74, 0.18)',
    }
  }
  return {
    backgroundColor: '#f8fafc',
    borderColor: '#e5e7eb',
  }
}

function RepresentativeStocks({ stocks }: { stocks: WeightStockEntry[] }) {
  if (stocks.length === 0) {
    return <span className="meta-text">暂无代表股</span>
  }
  return (
    <div className="stock-tag-list">
      {stocks.map((stock) => (
        <div key={`${stock.code}-${stock.name}`} className="stock-tag">
          <strong>{stock.name}</strong>
          <span>{formatPrice(stock.price)}</span>
          <span className={getTrendClass(stock.changePercent)}>{formatPercent(stock.changePercent)}</span>
        </div>
      ))}
    </div>
  )
}

export default function SectorHeatmap({ data, loading }: SectorHeatmapProps) {
  const [selectedName, setSelectedName] = useState('')
  const [stocksByBoard, setStocksByBoard] = useState<Record<string, WeightStockEntry[]>>({})

  const heatmap = data?.heatmap ?? []
  const leaders = data?.leaders ?? []
  const laggards = data?.laggards ?? []

  useEffect(() => {
    if (!selectedName && heatmap[0]) {
      setSelectedName(heatmap[0].name)
    }
  }, [heatmap, selectedName])

  useEffect(() => {
    const selected = heatmap.find((item) => item.name === selectedName)
    if (!selected || (selected.topStocks?.length ?? 0) >= 2 || stocksByBoard[selected.name]) {
      return
    }

    let cancelled = false
    requestJson<WeightStockEntry[]>(`/api/a-board-stocks?board=${encodeURIComponent(selected.name)}`)
      .then((payload) => {
        if (cancelled) return
        setStocksByBoard((current) => ({ ...current, [selected.name]: payload }))
      })
      .catch(() => {
        if (cancelled) return
        setStocksByBoard((current) => ({ ...current, [selected.name]: selected.topStocks ?? [] }))
      })

    return () => {
      cancelled = true
    }
  }, [heatmap, selectedName, stocksByBoard])

  const selectedBoard = heatmap.find((item) => item.name === selectedName) ?? heatmap[0]
  const selectedStocks = selectedBoard
    ? stocksByBoard[selectedBoard.name] ?? selectedBoard.topStocks ?? []
    : []

  return (
    <section className="surface-card">
      <div className="section-heading">
        <div>
          <span className="section-kicker">A-share Sectors</span>
          <h2>领涨领跌板块热力图</h2>
        </div>
      </div>

      {loading ? (
        <SkeletonBlocks blocks={2} height={420} />
      ) : !data || heatmap.length === 0 ? (
        <EmptyState title="暂无板块数据" description="同花顺板块接口当前未返回可用结果。" />
      ) : (
        <div className="sector-layout">
          <div className="heatmap-panel">
            <div className="breadth-grid">
              <div className="breadth-chip">
                <span>上涨</span>
                <strong>{data.breadth.upCount}</strong>
              </div>
              <div className="breadth-chip">
                <span>下跌</span>
                <strong>{data.breadth.downCount}</strong>
              </div>
              <div className="breadth-chip">
                <span>平盘</span>
                <strong>{data.breadth.flatCount}</strong>
              </div>
              <div className="breadth-chip">
                <span>涨停 / 跌停</span>
                <strong>
                  {data.breadth.limitUp} / {data.breadth.limitDown}
                </strong>
              </div>
            </div>

            <div className="heatmap-grid">
              {heatmap.slice(0, 24).map((board) => (
                <button
                  key={board.name}
                  type="button"
                  className={selectedBoard?.name === board.name ? 'heatmap-cell is-selected' : 'heatmap-cell'}
                  style={highlightStyle(board.changePercent)}
                  onClick={() => setSelectedName(board.name)}
                >
                  <strong>{board.name}</strong>
                  <span className={getTrendClass(board.changePercent)}>{formatPercent(board.changePercent)}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="sector-side">
            <div className="side-panel">
              <div className="panel-header">
                <div>
                  <h3>领涨 Top 3</h3>
                  <p>按板块涨跌幅排序</p>
                </div>
              </div>
              <div className="sector-list">
                {leaders.slice(0, 3).map((board) => (
                  <article key={`leader-${board.name}`} className="sector-list__item">
                    <div className="sector-list__row">
                      <strong>{board.name}</strong>
                      <span className={getTrendClass(board.changePercent)}>{formatPercent(board.changePercent)}</span>
                    </div>
                    <RepresentativeStocks stocks={board.topStocks ?? []} />
                  </article>
                ))}
              </div>
            </div>

            <div className="side-panel">
              <div className="panel-header">
                <div>
                  <h3>领跌 Top 3</h3>
                  <p>按板块涨跌幅排序</p>
                </div>
              </div>
              <div className="sector-list">
                {laggards.slice(0, 3).map((board) => (
                  <article key={`laggard-${board.name}`} className="sector-list__item">
                    <div className="sector-list__row">
                      <strong>{board.name}</strong>
                      <span className={getTrendClass(board.changePercent)}>{formatPercent(board.changePercent)}</span>
                    </div>
                    <RepresentativeStocks stocks={board.topStocks ?? []} />
                  </article>
                ))}
              </div>
            </div>

            {selectedBoard ? (
              <div className="side-panel">
                <div className="panel-header">
                  <div>
                    <h3>{selectedBoard.name}</h3>
                    <p>当前选中板块详情</p>
                  </div>
                </div>
                <div className="key-metrics">
                  <div>
                    <span>涨跌幅</span>
                    <strong className={getTrendClass(selectedBoard.changePercent)}>
                      {formatPercent(selectedBoard.changePercent)}
                    </strong>
                  </div>
                  <div>
                    <span>资金净流入</span>
                    <strong>{formatChineseAmount(selectedBoard.netInflow ?? 0)}</strong>
                  </div>
                  <div>
                    <span>上涨 / 下跌</span>
                    <strong>
                      {selectedBoard.upCount ?? 0} / {selectedBoard.downCount ?? 0}
                    </strong>
                  </div>
                  <div>
                    <span>总成交额</span>
                    <strong>{formatChineseAmount(selectedBoard.totalTurnover ?? 0)}</strong>
                  </div>
                </div>
                <RepresentativeStocks stocks={selectedStocks} />
              </div>
            ) : null}
          </div>
        </div>
      )}
    </section>
  )
}
