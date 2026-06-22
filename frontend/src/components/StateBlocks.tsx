interface InlineErrorProps {
  message: string
  onRetry?: () => void
}

interface EmptyStateProps {
  title: string
  description: string
}

interface SkeletonProps {
  blocks?: number
  height?: number
}

export function SkeletonBlocks({ blocks = 3, height = 112 }: SkeletonProps) {
  return (
    <div className="skeleton-grid">
      {Array.from({ length: blocks }).map((_, index) => (
        <div key={index} className="skeleton-block" style={{ height }} />
      ))}
    </div>
  )
}

export function InlineError({ message, onRetry }: InlineErrorProps) {
  return (
    <div className="inline-error">
      <span>{message}</span>
      {onRetry ? (
        <button type="button" className="inline-link" onClick={onRetry}>
          重试
        </button>
      ) : null}
    </div>
  )
}

export function EmptyState({ title, description }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  )
}
