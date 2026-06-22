import type { WeightStockEntry } from '../types/market'
import { buildChartPoints, formatChineseAmount, formatPercent, formatPrice, getTrendClass } from '../utils/market'
import LineChart from './LineChart'
import SourceBadge from './SourceBadge'
import { EmptyState, SkeletonBlocks } from './StateBlocks'

interface WeightStocksSectionProps {
  title: string
  subtitle: string
  stocks: WeightStockEntry[]
  loading?: boolean
}

function formatStockName(name: string) {
  return name
    .replace(/\s+Class A Common Stock$/i, '')
    .replace(/\s+Common Stock$/i, '')
    .replace(/\s+Ordinary Shares$/i, '')
    .replace(/, Inc\.$/i, '')
    .replace(/\s+Corporation$/i, '')
    .trim()
}

export default function WeightStocksSection({ title, subtitle, stocks, loading }: WeightStocksSectionProps) {
  return (
    <section className="surface-card">
      <div className="section-heading">
        <div>
          <span className="section-kicker">Weights Snapshot</span>
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>
      </div>
      {loading ? (
        <SkeletonBlocks blocks={6} height={208} />
      ) : stocks.length === 0 ? (
        <EmptyState title="暂无权重股数据" description="当前时段未返回权重股快照。" />
      ) : (
        <div className="weights-grid">
          {stocks.map((stock) => (
            <article key={stock.code} className="weight-card">
              <div className="weight-card__head">
                <div className="weight-card__identity">
                  <strong>{formatStockName(stock.name)}</strong>
                  <span>{stock.code}</span>
                  <SourceBadge source={stock.source} isFallback={stock.isFallback} />
                </div>
                <div className="weight-card__price">
                  <strong>{formatPrice(stock.price)}</strong>
                  <span className={getTrendClass(stock.changePercent)}>{formatPercent(stock.changePercent)}</span>
                </div>
              </div>
              <div className="weight-card__metrics">
                <span>涨跌额 {stock.changeAmount ? stock.changeAmount.toFixed(2) : '0.00'}</span>
                <span>市值 {stock.marketValue && stock.marketValue > 0 ? formatChineseAmount(stock.marketValue) : '--'}</span>
              </div>
              <LineChart
                data={buildChartPoints(stock)}
                changePercent={stock.changePercent}
                height={132}
                showTimeScale
                baseline={stock.previousClose ?? undefined}
              />
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
