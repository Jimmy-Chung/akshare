import type { SessionCommentary } from '../types/market'
import { formatReportDate } from '../utils/market'
import { EmptyState, SkeletonBlocks } from './StateBlocks'

interface CommentaryPanelProps {
  commentary?: SessionCommentary
  title?: string
  loading?: boolean
}

export default function CommentaryPanel({ commentary, title = '自动点评', loading }: CommentaryPanelProps) {
  return (
    <section className="surface-card">
      <div className="section-heading">
        <div>
          <span className="section-kicker">Commentary</span>
          <h2>{title}</h2>
        </div>
        {commentary ? <span className="meta-text">{formatReportDate(commentary.generatedAt)}</span> : null}
      </div>
      {loading ? (
        <SkeletonBlocks blocks={2} height={140} />
      ) : !commentary ? (
        <EmptyState title="暂无点评" description="当前时段的自动点评尚未生成。" />
      ) : (
        <div className="commentary-layout">
          <p className="commentary-overview">{commentary.overview}</p>
          <div className="commentary-list">
            {commentary.highlights.map((item) => (
              <div key={item} className="commentary-item">
                {item}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
