import { useEffect, useRef, useState } from 'react'
import Carousel from './components/Carousel'
import DailyReport from './components/DailyReport'
import { RefreshIcon } from './components/DashboardIcons'
import MarketTabs from './components/MarketTabs'
import IndexOverview from './components/IndexOverview'
import HeatmapSection from './components/HeatmapSection'
import './styles/App.css'
import { formatDashboardTime } from './utils/market'

type Market = 'A股' | '港股' | '美股'
type ViewMode = 'dashboard' | 'report'

interface GlobalIndex {
  name: string
  code: string
  price: number
  changePercent: number
  changeAmount: number
  previousClose?: number
  intradayData?: { time: string; value: number }[]
}

interface MarketIndex {
  name: string
  code: string
  price: number
  changePercent: number
  changeAmount: number
  open?: number
  high?: number
  low?: number
  previousClose?: number
  intradayData?: { time: string; value: number }[]
}

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

function App() {
  const initialMarketLoad = useRef(true)
  const marketRef = useRef<Market>('A股')
  const [viewMode, setViewMode] = useState<ViewMode>('dashboard')
  const [market, setMarket] = useState<Market>('A股')
  const [globalIndices, setGlobalIndices] = useState<GlobalIndex[]>([])
  const [marketIndices, setMarketIndices] = useState<MarketIndex[]>([])
  const [boardData, setBoardData] = useState<BoardData[]>([])
  const [stockData, setStockData] = useState<StockData[]>([])
  const [selectedBoard, setSelectedBoard] = useState<BoardData | null>(null)
  const [selectedIndex, setSelectedIndex] = useState<MarketIndex | null>(null)
  const [loading, setLoading] = useState(false)
  const [lastUpdate, setLastUpdate] = useState<string>('')
  const [carouselResetKey, setCarouselResetKey] = useState(0)

  useEffect(() => {
    fetchAllData()
    const timer = window.setInterval(fetchAllData, 5 * 60 * 1000)

    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    marketRef.current = market
    if (initialMarketLoad.current) {
      initialMarketLoad.current = false
      return
    }

    fetchMarketData(market)
  }, [market])

  const pickDefaultBoard = (boards: BoardData[]) => {
    return boards.find((board) => board.name.includes('电子')) || boards[0] || null
  }

  const fetchAllData = async () => {
    setLoading(true)
    try {
      const globalRes = await fetch('/api/global-indices')
      const globalData = await globalRes.json()
      setGlobalIndices(globalData)

      await fetchMarketData(marketRef.current)
      setCarouselResetKey((current) => current + 1)
      setLastUpdate(formatDashboardTime())
    } catch (error) {
      console.error('获取数据失败:', error)
    } finally {
      setLoading(false)
    }
  }

  const fetchJson = async <T,>(url: string): Promise<T[]> => {
    const response = await fetch(url)
    return response.json()
  }

  const fetchMarketData = async (targetMarket = marketRef.current) => {
    try {
      if (targetMarket === 'A股') {
        const indices = await fetchJson<MarketIndex>('/api/a-indices')
        if (marketRef.current !== targetMarket) return
        setMarketIndices(indices)
        setBoardData([])
        setStockData([])
        if (indices.length > 0) setSelectedIndex(indices[0])

        const boards = await fetchJson<BoardData>('/api/a-boards')
        if (marketRef.current !== targetMarket) return
        setBoardData(boards)
        setStockData([])
        setSelectedBoard(pickDefaultBoard(boards))
      } else if (targetMarket === '港股') {
        const indices = await fetchJson<MarketIndex>('/api/hk-indices')
        if (marketRef.current !== targetMarket) return
        setMarketIndices(indices)
        setStockData([])
        setBoardData([])
        setSelectedBoard(null)
        if (indices.length > 0) setSelectedIndex(indices[0])

        const stocks = await fetchJson<StockData>('/api/hk-stocks')
        if (marketRef.current !== targetMarket) return
        setStockData(stocks)
      } else {
        const indices = await fetchJson<MarketIndex>('/api/us-indices')
        if (marketRef.current !== targetMarket) return
        setMarketIndices(indices)
        setStockData([])
        setBoardData([])
        setSelectedBoard(null)
        if (indices.length > 0) setSelectedIndex(indices[0])

        const stocks = await fetchJson<StockData>('/api/us-stocks')
        if (marketRef.current !== targetMarket) return
        setStockData(stocks)
      }
      setLastUpdate(formatDashboardTime())
    } catch (error) {
      console.error('获取市场数据失败:', error)
    }
  }

  const handleRefresh = () => {
    fetchAllData()
  }

  const handleBoardClick = (board: BoardData) => {
    setSelectedBoard(board)
  }

  const handleStockClick = (stock: StockData) => {
    console.log('选中股票:', stock)
  }

  const handleIndexClick = (index: MarketIndex) => {
    setSelectedIndex(index)
  }

  if (viewMode === 'report') {
    return (
      <div className="app">
        <div className="market-bar">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button
              className="tab-btn active"
              onClick={() => setViewMode('report')}
              style={{ minWidth: 'auto', padding: '0 18px' }}
            >
              📊 日报
            </button>
            <button
              className="tab-btn"
              onClick={() => setViewMode('dashboard')}
              style={{ minWidth: 'auto', padding: '0 18px' }}
            >
              📈 看板
            </button>
          </div>
        </div>
        <DailyReport />
      </div>
    )
  }

  return (
    <div className="app">
      <div className="top-section">
        <Carousel data={globalIndices} resetKey={carouselResetKey} />
      </div>

      <div className="market-bar">
        <MarketTabs market={market} onChange={setMarket} />
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <button
            className="tab-btn"
            onClick={() => setViewMode('report')}
            style={{ minWidth: 'auto', padding: '0 14px', fontSize: 13 }}
          >
            📊 日报
          </button>
          <div className="refresh-area">
            <button className="refresh-btn" onClick={handleRefresh} disabled={loading}>
              <RefreshIcon className="refresh-icon" />
              <span className="refresh-text">{loading ? '刷新中' : '刷新数据'}</span>
            </button>
            {lastUpdate && <span className="last-update">更新于 {lastUpdate}</span>}
          </div>
        </div>
      </div>

      <div className="index-section">
        <IndexOverview
          indices={marketIndices}
          selectedIndex={selectedIndex}
          onIndexClick={handleIndexClick}
        />
      </div>

      <div className="heatmap-wrapper">
        <HeatmapSection
          market={market}
          boardData={boardData}
          stockData={stockData}
          selectedBoard={selectedBoard}
          onBoardClick={handleBoardClick}
          onStockClick={handleStockClick}
        />
      </div>
    </div>
  )
}

export default App
