import { useCallback, useEffect, useMemo, useRef, useState, type FC } from 'react'
import '../styles/HeatmapSection.css'
import {
  formatChineseAmount,
  formatDashboardTime,
  formatPercent,
  formatPrice,
  formatSignedNumber,
  getTrendClass,
  getTrendColor
} from '../utils/market'

type SortMode = '市值' | '涨跌幅' | '净流入'

interface BoardData {
  name: string
  changePercent: number
  netInflow?: number | null
  marketValue?: number
  eventCount?: number | null
  topStocks?: StockData[]
}

interface StockData {
  name: string
  code: string
  price: number
  changePercent: number
  changeAmount: number
  marketValue?: number | null
  netInflow?: number | null
}

interface HeatmapSectionProps {
  market: string
  boardData: BoardData[]
  stockData: StockData[]
  selectedBoard: BoardData | null
  onBoardClick: (board: BoardData) => void
  onStockClick: (stock: StockData) => void
}

interface HeatmapTile {
  name: string
  code?: string
  boardCode?: string
  price?: number
  changePercent: number
  changeAmount?: number
  netInflow?: number | null
  marketValue?: number | null
  eventCount?: number | null
  topStocks?: StockData[]
  rawStock?: StockData
  rawBoard?: BoardData
  isMore?: boolean
}

interface LayoutTile extends HeatmapTile {
  height: number
  layoutClass: string
  width: number
  x: number
  y: number
}

const getHeatColor = (changePercent: number) => {
  const absValue = Math.min(Math.abs(changePercent), 6)
  const alpha = 0.42 + absValue * 0.075

  if (changePercent > 0) {
    return {
      background: `linear-gradient(145deg, rgba(198, 59, 51, ${alpha}), rgba(91, 27, 24, 0.9))`,
      borderColor: 'rgba(255, 88, 77, 0.45)'
    }
  }

  if (changePercent < 0) {
    return {
      background: `linear-gradient(145deg, rgba(37, 115, 58, ${alpha}), rgba(20, 62, 37, 0.92))`,
      borderColor: 'rgba(96, 190, 105, 0.34)'
    }
  }

  return {
    background: 'linear-gradient(145deg, rgba(79, 89, 97, 0.58), rgba(31, 38, 44, 0.9))',
    borderColor: 'rgba(148, 163, 184, 0.28)'
  }
}

const getSortValue = (tile: HeatmapTile, sortMode: SortMode) => {
  if (sortMode === '涨跌幅') return Math.abs(tile.changePercent)
  if (sortMode === '净流入') return Math.abs(tile.netInflow || 0)
  return tile.marketValue || 0
}

const getAreaModeLabel = (sortMode: SortMode) => {
  if (sortMode === '净流入') return '净流入/流出'
  return sortMode
}

const getLayoutClass = (width: number, height: number) => {
  const area = width * height

  if (area >= 1500) return 'area-xxl'
  if (area >= 900) return 'area-xl'
  if (area >= 520) return 'area-lg'
  if (area >= 260) return 'area-md'
  return 'area-sm'
}

const getLayoutWeight = (tile: HeatmapTile, sortMode: SortMode, maxValue: number) => {
  if (tile.isMore) return maxValue * 0.045

  return Math.max(getSortValue(tile, sortMode), maxValue * 0.035)
}

const layoutTreemap = (items: HeatmapTile[], sortMode: SortMode): LayoutTile[] => {
  const maxValue = Math.max(...items.map((tile) => getSortValue(tile, sortMode)), 1)
  const weights = new Map(items.map((tile) => [tile, getLayoutWeight(tile, sortMode, maxValue)]))
  const laidOut: LayoutTile[] = []

  const sumWeights = (tiles: HeatmapTile[]) => {
    return tiles.reduce((total, tile) => total + (weights.get(tile) || 0), 0)
  }

  const place = (tiles: HeatmapTile[], x: number, y: number, width: number, height: number) => {
    if (tiles.length === 0) return

    if (tiles.length === 1) {
      const [tile] = tiles
      laidOut.push({
        ...tile,
        x,
        y,
        width,
        height,
        layoutClass: tile.isMore ? 'area-sm' : getLayoutClass(width, height)
      })
      return
    }

    const total = sumWeights(tiles)
    let splitIndex = 1
    let bestDelta = Number.POSITIVE_INFINITY
    let running = 0

    for (let index = 0; index < tiles.length - 1; index += 1) {
      running += weights.get(tiles[index]) || 0
      const delta = Math.abs(total / 2 - running)
      if (delta < bestDelta) {
        bestDelta = delta
        splitIndex = index + 1
      }
    }

    const firstGroup = tiles.slice(0, splitIndex)
    const secondGroup = tiles.slice(splitIndex)
    const firstWeight = sumWeights(firstGroup)
    const firstRatio = total > 0 ? firstWeight / total : 0.5

    if (width >= height) {
      const firstWidth = width * firstRatio
      place(firstGroup, x, y, firstWidth, height)
      place(secondGroup, x + firstWidth, y, width - firstWidth, height)
    } else {
      const firstHeight = height * firstRatio
      place(firstGroup, x, y, width, firstHeight)
      place(secondGroup, x, y + firstHeight, width, height - firstHeight)
    }
  }

  place(items, 0, 0, 100, 100)

  return laidOut
}

const HeatmapSection: FC<HeatmapSectionProps> = ({
  market,
  boardData,
  stockData,
  selectedBoard,
  onBoardClick,
  onStockClick
}) => {
  const [sortMode, setSortMode] = useState<SortMode>('市值')
  const [pendingSortMode, setPendingSortMode] = useState<SortMode | null>(null)
  const [selectedStock, setSelectedStock] = useState<StockData | null>(null)
  const [boardStocks, setBoardStocks] = useState<StockData[]>([])
  const [loadingStocks, setLoadingStocks] = useState(false)
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const loadedBoardRef = useRef<string | null>(null)

  // 响应式检测
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth <= 768)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  useEffect(() => {
    setPendingSortMode(market === 'A股' ? '涨跌幅' : '市值')
    setSelectedStock(null)
    setBoardStocks([])
    setLoadingStocks(false)
    loadedBoardRef.current = null
  }, [market])

  const tiles = useMemo<HeatmapTile[]>(() => {
    const source =
      market === 'A股'
        ? boardData.map((board) => ({
            name: board.name,
            boardCode: (board as any).code || '',
            changePercent: board.changePercent,
            netInflow: board.netInflow,
            marketValue: board.marketValue,
            eventCount: board.eventCount,
            topStocks: board.topStocks,
            rawBoard: board
          }))
        : stockData.map((stock) => ({
            name: stock.name,
            code: stock.code,
            price: stock.price,
            changePercent: stock.changePercent,
            changeAmount: stock.changeAmount,
            netInflow: stock.netInflow,
            marketValue: stock.marketValue,
            rawStock: stock
          }))

    return [...source].sort((a, b) => getSortValue(b, sortMode) - getSortValue(a, sortMode))
  }, [boardData, market, sortMode, stockData])

  const availableSortModes = useMemo<SortMode[]>(() => {
    const modes: SortMode[] = []

    if (tiles.some((tile) => typeof tile.marketValue === 'number' && tile.marketValue > 0)) {
      modes.push('市值')
    }
    modes.push('涨跌幅')
    if (tiles.some((tile) => typeof tile.netInflow === 'number')) {
      modes.push('净流入')
    }

    return modes
  }, [tiles])

  useEffect(() => {
    if (pendingSortMode) {
      if (availableSortModes.includes(pendingSortMode)) {
        setSortMode(pendingSortMode)
        setPendingSortMode(null)
      }
      return
    }

    if (availableSortModes.length > 0 && !availableSortModes.includes(sortMode)) {
      setSortMode(availableSortModes[0])
    }
  }, [availableSortModes, pendingSortMode, sortMode])

  const baseVisibleTiles = tiles.slice(0, tiles.length > 29 ? 28 : 29)
  const negativeSupplements =
    baseVisibleTiles.some((tile) => tile.changePercent < 0)
      ? []
      : tiles
          .filter((tile) => tile.changePercent < 0 && !baseVisibleTiles.some((base) => base.name === tile.name))
          .slice(0, 5)
  const visibleTilesWithoutMore =
    negativeSupplements.length > 0
      ? [
          ...baseVisibleTiles.slice(0, Math.max(0, 28 - negativeSupplements.length)),
          ...negativeSupplements
        ].slice(0, 28)
      : baseVisibleTiles
  const moreTile: HeatmapTile = {
    name: '...',
    changePercent: 0,
    netInflow: 0,
    marketValue: 0,
    isMore: true
  }
  const visibleTiles = tiles.length > visibleTilesWithoutMore.length
    ? [...visibleTilesWithoutMore, moreTile]
    : visibleTilesWithoutMore
  const selectableTiles = visibleTiles.filter((tile) => !tile.isMore)
  const activeTile =
    market === 'A股'
      ? selectableTiles.find((tile) => tile.name === selectedBoard?.name) ||
        selectableTiles.find((tile) => tile.name.includes('电子')) ||
        selectableTiles[0]
      : selectableTiles.find((tile) => tile.code === selectedStock?.code) || selectableTiles[0]
  const layoutTiles = layoutTreemap(visibleTiles, sortMode)
  const isBoardMarket = market === 'A股'
  const loadBoardStocks = useCallback(async (boardName: string) => {
    if (loadedBoardRef.current === boardName || loadingStocks) return
    setLoadingStocks(true)
    loadedBoardRef.current = boardName
    try {
      const res = await fetch(`/api/a-board-stocks?board=${encodeURIComponent(boardName)}`)
      const stocks = await res.json()
      if (loadedBoardRef.current === boardName) {
        setBoardStocks(Array.isArray(stocks) ? stocks : [])
      }
    } catch {
      setBoardStocks([])
    } finally {
      setLoadingStocks(false)
    }
  }, [loadingStocks])

  const activeTopStocks = useMemo(() => {
    if (!activeTile) return []
    if (activeTile.topStocks && activeTile.topStocks.length > 0) return activeTile.topStocks
    return boardStocks
  }, [activeTile, boardStocks])

  useEffect(() => {
    if (isBoardMarket && activeTile && (!activeTile.topStocks || activeTile.topStocks.length === 0)) {
      const query = activeTile.boardCode || activeTile.name
      loadBoardStocks(query)
    }
  }, [isBoardMarket, activeTile, loadBoardStocks])

  const detailStocks =
    isBoardMarket
      ? activeTopStocks || []
      : stockData.slice(0, 10)

  const handleTileClick = (tile: HeatmapTile) => {
    if (market === 'A股' && tile.rawBoard) {
      onBoardClick(tile.rawBoard)
      setMobileDetailOpen(true)
      return
    }

    if (tile.rawStock) {
      setSelectedStock(tile.rawStock)
      onStockClick(tile.rawStock)
      setMobileDetailOpen(true)
    }
  }

  const showDetail = !isMobile || mobileDetailOpen

  return (
    <div className="heatmap-section">
      <div className="heatmap-panel heatmap-main">
        <div className="heatmap-header">
          <div className="heatmap-title-group">
            <h2>板块热力图</h2>
            <span className="info-dot">i</span>
            <span className="area-mode">面积: 按{getAreaModeLabel(sortMode)}⌄</span>
          </div>

          <div className="sort-options">
            {availableSortModes.map((mode) => (
              <button
                key={mode}
                type="button"
                className={`sort-btn ${sortMode === mode ? 'active' : ''}`}
                onClick={() => setSortMode(mode as SortMode)}
              >
                按{mode}
              </button>
            ))}
          </div>
        </div>

        <div className="heatmap-grid">
          {layoutTiles.length === 0 && <div className="heatmap-empty">暂无真实热力图数据</div>}
          {layoutTiles.map((tile, index) => {
            const heatColor = getHeatColor(tile.changePercent)
            const isActive = !tile.isMore && activeTile?.name === tile.name

            return tile.isMore ? (
              <div
                key="more"
                className="heat-tile more-tile"
                style={{
                  left: `${tile.x}%`,
                  top: `${tile.y}%`,
                  width: `${tile.width}%`,
                  height: `${tile.height}%`
                }}
              >
                ...
              </div>
            ) : (
              <button
                key={`${tile.name}-${tile.code || index}`}
                type="button"
                className={`heat-tile ${tile.layoutClass} ${getTrendClass(tile.changePercent)} ${
                  isActive ? 'selected' : ''
                }`}
                style={{
                  ...heatColor,
                  left: `${tile.x}%`,
                  top: `${tile.y}%`,
                  width: `${tile.width}%`,
                  height: `${tile.height}%`
                }}
                onClick={() => handleTileClick(tile)}
              >
                <span className="tile-name">{tile.name}</span>
                <strong>{formatPercent(tile.changePercent)}</strong>
              <span className="tile-flow">
                {typeof tile.netInflow === 'number'
                  ? `净流入 ${formatChineseAmount(tile.netInflow)}`
                  : typeof tile.marketValue === 'number'
                    ? `市值 ${formatChineseAmount(tile.marketValue)}`
                    : '真实数据'}
              </span>
              </button>
            )
          })}
        </div>

        <div className="heatmap-scale">
          <span>-3%</span>
          <div className="scale-gradient" />
          <span>+3%</span>
        </div>
        <div className="heatmap-note">提示：板块热力图中数据按对应维度值，点击板块查看个股明细</div>
      </div>

      {showDetail && (
          <aside className="heatmap-panel detail-panel">
            {activeTile ? (
              <>
                <div className="detail-header">
                  <div>
                    <h2>{activeTile.name}</h2>
                    <strong style={{ color: getTrendColor(activeTile.changePercent) }}>
                      {formatPercent(activeTile.changePercent)}
                    </strong>
                  </div>
                  {isMobile && (
                    <button
                      type="button"
                      className="detail-close"
                      onClick={() => setMobileDetailOpen(false)}
                      aria-label="关闭详情"
                    >
                      ×
                    </button>
                  )}
                </div>

            {isBoardMarket ? (
              <div className="detail-metrics">
                {typeof activeTile.netInflow === 'number' && (
                  <span>净流入 {formatChineseAmount(activeTile.netInflow)}</span>
                )}
                {typeof activeTile.marketValue === 'number' && (
                  <span>总市值 {formatChineseAmount(activeTile.marketValue)}</span>
                )}
                {typeof activeTile.eventCount === 'number' && (
                  <span>异动次数 {formatPrice(activeTile.eventCount, 0)}</span>
                )}
                <span>数据源 AKShare</span>
              </div>
            ) : (
              <div className="detail-metrics stock-detail-metrics">
                <span>代码 {activeTile.code}</span>
                <span>最新价 {activeTile.price ? formatPrice(activeTile.price) : '-'}</span>
                <span style={{ color: getTrendColor(activeTile.changeAmount || 0) }}>
                  涨跌额 {formatSignedNumber(activeTile.changeAmount || 0)}
                </span>
                {typeof activeTile.marketValue === 'number' && (
                  <span>市值 {formatChineseAmount(activeTile.marketValue)}</span>
                )}
                {typeof activeTile.netInflow === 'number' && (
                  <span>净流入 {formatChineseAmount(activeTile.netInflow)}</span>
                )}
              </div>
            )}

            <div className="leader-title">{isBoardMarket ? '成分股明细' : `${market}主要个股`}</div>
            <div className="stock-table">
              <div className="stock-row table-head">
                <span>名称</span>
                <span>最新价</span>
                <span>涨跌幅</span>
                <span>市值</span>
                <span>净流入</span>
              </div>
              {loadingStocks ? (
                <div className="empty-table">正在加载成分股数据...</div>
              ) : detailStocks.length > 0 ? (
                detailStocks.slice(0, 10).map((stock, index) => (
                  <div className="stock-row" key={stock.code || `${stock.name}-${index}`}>
                    <span className="stock-name-cell">
                      <b>{index + 1}</b>
                      <span>
                        {stock.name}
                        <small>{stock.code}</small>
                      </span>
                    </span>
                    <span>{formatPrice(stock.price)}</span>
                    <span style={{ color: getTrendColor(stock.changePercent) }}>
                      {formatPercent(stock.changePercent)}
                    </span>
                    <span>{typeof stock.marketValue === 'number' ? formatChineseAmount(stock.marketValue) : '-'}</span>
                    <span style={{ color: getTrendColor(stock.netInflow || 0) }}>
                      {typeof stock.netInflow === 'number' ? formatChineseAmount(stock.netInflow) : '-'}
                    </span>
                  </div>
                ))
              ) : (
                <div className="empty-table">暂无真实成分股数据</div>
              )}
            </div>

            <div className="detail-foot">* 数据截至 {formatDashboardTime()}</div>
              </>
            ) : (
              <div className="panel-empty">暂无真实数据</div>
            )}
          </aside>
        )}
    </div>
  )
}

export default HeatmapSection
