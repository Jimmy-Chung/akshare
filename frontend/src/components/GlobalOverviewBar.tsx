import type { GlobalMarketGroup } from '../types/market'
import { formatDashboardTime, formatPercent, formatPrice, getTrendClass } from '../utils/market'
import { SkeletonBlocks } from './StateBlocks'
import SourceBadge from './SourceBadge'

interface GlobalOverviewBarProps {
  groups: GlobalMarketGroup[]
  updatedAt?: string
  loading?: boolean
}

export default function GlobalOverviewBar({ groups, updatedAt, loading }: GlobalOverviewBarProps) {
  return (
    <section className="surface-card surface-card--compact">
      <div className="section-heading">
        <div>
          <span className="section-kicker">Global Overview</span>
          <h2>全球市场概览</h2>
        </div>
        <span className="meta-text">更新于 {formatDashboardTime(updatedAt)}</span>
      </div>
      {loading ? (
        <SkeletonBlocks blocks={8} height={76} />
      ) : (
        <div className="global-region-list">
          {groups.map((group) => (
            <section key={group.key} className="global-region">
              <div className="global-region__heading">
                <div>
                  <h3>{group.title}</h3>
                  <p>{group.subtitle}</p>
                </div>
                <span>{group.indices.length} 个市场</span>
              </div>
              <div className="global-overview-row">
                {group.indices.map((item) => (
                  <article key={item.code} className="ticker-chip">
                    <div>
                      <strong>{item.name}</strong>
                      <span>{item.code}</span>
                      <SourceBadge source={item.source} isFallback={item.isFallback} />
                    </div>
                    <div className="ticker-chip__value">
                      <strong>{formatPrice(item.price)}</strong>
                      <span className={getTrendClass(item.changePercent)}>{formatPercent(item.changePercent)}</span>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </section>
  )
}
