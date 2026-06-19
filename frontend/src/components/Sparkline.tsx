import { useId, useMemo } from 'react'
import { getTrendColor } from '../utils/market'

interface SparklineProps {
  values?: number[]
  changePercent: number
  seedKey?: string
  height?: number
  strokeWidth?: number
  className?: string
}

const Sparkline = ({
  values,
  changePercent,
  height = 42,
  strokeWidth = 1.8,
  className = ''
}: SparklineProps) => {
  const reactId = useId().replace(/:/g, '')
  const color = getTrendColor(changePercent)
  const series = values && values.length > 1 ? values : []

  const { linePath, areaPath } = useMemo(() => {
    if (series.length < 2) {
      return { linePath: '', areaPath: '' }
    }

    const width = 120
    const padding = 3
    const min = Math.min(...series)
    const max = Math.max(...series)
    const range = max - min || 1
    const points = series.map((value, index) => {
      const x = (index / (series.length - 1)) * width
      const y = padding + (1 - (value - min) / range) * (height - padding * 2)
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    const line = `M ${points.join(' L ')}`
    const area = `${line} L ${width},${height} L 0,${height} Z`

    return { linePath: line, areaPath: area }
  }, [height, series])

  if (series.length < 2) {
    return <div className={`sparkline sparkline-empty ${className}`} />
  }

  return (
    <svg className={`sparkline ${className}`} viewBox={`0 0 120 ${height}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id={`spark-area-${reactId}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.34" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#spark-area-${reactId})`} />
      <path d={linePath} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" />
    </svg>
  )
}

export default Sparkline
