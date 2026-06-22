import type { NewsArticle } from '../types/market'
import { formatShortDate } from '../utils/market'
import SourceBadge from './SourceBadge'
import { EmptyState, SkeletonBlocks } from './StateBlocks'

interface NewsDigestPanelProps {
  articles: NewsArticle[]
  title?: string
  loading?: boolean
}

export default function NewsDigestPanel({
  articles,
  title = '金融新闻概要',
  loading,
}: NewsDigestPanelProps) {
  return (
    <section className="surface-card">
      <div className="section-heading">
        <div>
          <span className="section-kicker">News Digest</span>
          <h2>{title}</h2>
        </div>
      </div>
      {loading ? (
        <SkeletonBlocks blocks={4} height={92} />
      ) : articles.length === 0 ? (
        <EmptyState title="暂无新闻" description="当前未抓取到可用的新闻摘要。" />
      ) : (
        <div className="news-list">
          {articles.map((article) => (
            <a
              key={article.id}
              className="news-item"
              href={article.url}
              target="_blank"
              rel="noreferrer"
            >
              <div className="news-item__meta">
                <span>
                  {article.source}
                  <SourceBadge source={article.source} isFallback={article.isFallback} />
                </span>
                <span>{formatShortDate(article.publishedAt)}</span>
              </div>
              <strong>{article.title}</strong>
              <p>{article.summary}</p>
            </a>
          ))}
        </div>
      )}
    </section>
  )
}
