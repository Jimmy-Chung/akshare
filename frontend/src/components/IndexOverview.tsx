import type { FC } from 'react'
import Sparkline from './Sparkline'
import '../styles/IndexOverview.css'
import {
  formatPercent,
  formatPrice,
  formatSignedNumber,
  getTrendClass,
  getTrendColor
} from '../utils/market'

interface IndexData {
  name: string
  code: string
  price: number
  changePercent: number
  changeAmount: number
  high?: number
  low?: number
  open?: number
  previousClose?: number
  intradayData?: { time: string; value: number }[]
}

interface IndexOverviewProps {
  indices: IndexData[]
  selectedIndex: IndexData | null
  onIndexClick: (index: IndexData) => void
}

const IndexOverview: FC<IndexOverviewProps> = ({ indices, selectedIndex, onIndexClick }) => {
  if (indices.length === 0) {
    return <div className="index-loading">暂无真实指数数据</div>
  }

  const getPreviousClose = (index: IndexData) => {
    if (typeof index.previousClose === 'number') {
      return index.previousClose
    }

    if (index.price && index.changePercent !== -100) {
      return index.price / (1 + index.changePercent / 100)
    }

    return index.open || index.price
  }

  return (
    <div className="index-overview">
      {indices.map((index) => {
        const values = index.intradayData?.map((item) => item.value)
        const high = typeof index.high === 'number' ? index.high : Math.max(index.price, ...(values || [index.price]))
        const low = typeof index.low === 'number' ? index.low : Math.min(index.price, ...(values || [index.price]))
        const previousClose = getPreviousClose(index)
        const trendClass = getTrendClass(index.changePercent)
        const isSelected = selectedIndex?.code === index.code

        return (
          <button
            key={index.code}
            type="button"
            className={`index-card ${trendClass} ${isSelected ? 'selected' : ''}`}
            onClick={() => onIndexClick(index)}
          >
            <div className="card-name">{index.name}</div>
            <div className="card-price" style={{ color: getTrendColor(index.changePercent) }}>
              {formatPrice(index.price)}
            </div>
            <div className="card-change" style={{ color: getTrendColor(index.changePercent) }}>
              <span>{formatSignedNumber(index.changeAmount)}</span>
              <span>{formatPercent(index.changePercent)}</span>
            </div>
            <Sparkline
              values={values}
              changePercent={index.changePercent}
              seedKey={index.code}
              height={52}
              strokeWidth={1.7}
              className="index-sparkline"
            />
            <div className="card-meta">
              <span>
                最高 <strong className="meta-up">{formatPrice(high)}</strong>
              </span>
              <span>
                最低 <strong className="meta-down">{formatPrice(low)}</strong>
              </span>
              <span>
                昨收 <strong>{formatPrice(previousClose)}</strong>
              </span>
            </div>
          </button>
        )
      })}
    </div>
  )
}

export default IndexOverview
