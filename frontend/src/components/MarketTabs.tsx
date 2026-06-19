import type { FC } from 'react'
import '../styles/MarketTabs.css'

type Market = 'A股' | '港股' | '美股'

interface MarketTabsProps {
  market: Market
  onChange: (market: Market) => void
}

const MarketTabs: FC<MarketTabsProps> = ({ market, onChange }) => {
  const tabs: Market[] = ['A股', '港股', '美股']

  return (
    <div className="market-tabs">
      {tabs.map((tab) => (
        <button
          key={tab}
          className={`tab-btn ${market === tab ? 'active' : ''}`}
          onClick={() => onChange(tab)}
        >
          {tab}市场
        </button>
      ))}
    </div>
  )
}

export default MarketTabs
