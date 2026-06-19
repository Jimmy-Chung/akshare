import { useEffect, useState, type FC } from 'react'
import { ChevronRightIcon, GlobeIcon } from './DashboardIcons'
import Sparkline from './Sparkline'
import '../styles/Carousel.css'
import { formatPercent, formatPrice, formatSignedNumber, getTrendClass } from '../utils/market'

interface IndexData {
  name: string
  code: string
  price: number
  changePercent: number
  changeAmount: number
  previousClose?: number
  intradayData?: { time: string; value: number }[]
}

interface CarouselProps {
  data: IndexData[]
  resetKey: number
}

const TICKER_ITEM_WIDTH = 122
const TICKER_INTERVAL_MS = 3000

const Carousel: FC<CarouselProps> = ({ data, resetKey }) => {
  const [activeIndex, setActiveIndex] = useState(0)
  const [withTransition, setWithTransition] = useState(true)

  useEffect(() => {
    setWithTransition(false)
    setActiveIndex(0)

    const frame = window.requestAnimationFrame(() => setWithTransition(true))
    return () => window.cancelAnimationFrame(frame)
  }, [data.length, resetKey])

  useEffect(() => {
    if (data.length <= 1) return undefined

    const timer = window.setInterval(() => {
      setWithTransition(true)
      setActiveIndex((current) => current + 1)
    }, TICKER_INTERVAL_MS)

    return () => window.clearInterval(timer)
  }, [data.length, resetKey])

  const handleTransitionEnd = () => {
    if (activeIndex < data.length) return

    setWithTransition(false)
    setActiveIndex(0)
    window.requestAnimationFrame(() => setWithTransition(true))
  }

  if (data.length === 0) {
    return (
      <div className="ticker-shell">
        <div className="ticker-globe">
          <GlobeIcon className="ticker-globe-icon" />
        </div>
        <div className="carousel-loading">暂无真实全球行情数据</div>
      </div>
    )
  }

  const tickerItems = [...data, ...data]

  return (
    <div className="ticker-shell">
      <div className="ticker-globe">
        <GlobeIcon className="ticker-globe-icon" />
      </div>
      <div className="carousel-wrapper">
        <div
          className="carousel-track"
          style={{
            transform: `translateX(-${activeIndex * TICKER_ITEM_WIDTH}px)`,
            transition: withTransition ? 'transform 520ms cubic-bezier(0.22, 0.9, 0.32, 1)' : 'none'
          }}
          onTransitionEnd={handleTransitionEnd}
        >
          {tickerItems.map((item, idx) => {
            const values = item.intradayData?.map((point) => point.value)

            return (
              <div
                key={`${item.code}-${idx}`}
                className={`carousel-item ${getTrendClass(item.changePercent)}`}
              >
                <div className="item-name">{item.name}</div>
                <div className="item-price">{formatPrice(item.price)}</div>
                <div className="item-change">
                  <span>{formatSignedNumber(item.changeAmount)}</span>
                  <span>{formatPercent(item.changePercent)}</span>
                </div>
                <Sparkline
                  values={values}
                  changePercent={item.changePercent}
                  seedKey={`${item.code}-${item.price}`}
                  height={22}
                  strokeWidth={1.4}
                />
              </div>
            )
          })}
        </div>
      </div>
      <button className="ticker-next" aria-label="查看下一组行情">
        <ChevronRightIcon className="ticker-next-icon" />
      </button>
    </div>
  )
}

export default Carousel
