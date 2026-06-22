interface SourceBadgeProps {
  source?: string
  isFallback?: boolean
}

export default function SourceBadge({ source, isFallback }: SourceBadgeProps) {
  if (!isFallback) {
    return null
  }

  return (
    <span className="source-badge source-badge--fallback" title={`备用数据源：${source || '未知'}`}>
      备用 · {source || '其他来源'}
    </span>
  )
}
