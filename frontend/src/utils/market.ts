import type { ChartPoint, IndexSnapshot, SessionKey } from '../types/market'

export const UP_COLOR = '#e5484d'
export const DOWN_COLOR = '#16a34a'
export const FLAT_COLOR = '#94a3b8'
export const ACCENT_COLOR = '#1f6feb'

export const getTrendColor = (changePercent: number) => {
  if (changePercent > 0) return UP_COLOR
  if (changePercent < 0) return DOWN_COLOR
  return FLAT_COLOR
}

export const getTrendClass = (changePercent: number) => {
  if (changePercent > 0) return 'is-up'
  if (changePercent < 0) return 'is-down'
  return 'is-flat'
}

export const formatPrice = (value: number, digits = 2) => {
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export const formatPercent = (value: number) => {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

export const formatSignedNumber = (value: number, digits = 2) => {
  const sign = value > 0 ? '+' : ''
  return `${sign}${formatPrice(value, digits)}`
}

export const formatChineseAmount = (value: number) => {
  const absValue = Math.abs(value)
  const sign = value < 0 ? '-' : ''

  if (absValue >= 1000000000000) {
    return `${sign}${(absValue / 1000000000000).toFixed(2)}万亿`
  }

  if (absValue >= 100000000) {
    return `${sign}${(absValue / 100000000).toFixed(2)}亿`
  }

  if (absValue >= 10000) {
    return `${sign}${(absValue / 10000).toFixed(2)}万`
  }

  return `${sign}${absValue.toFixed(2)}`
}

export const formatDashboardTime = (value?: string) => {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export const formatReportDate = (value?: string) => {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export const formatShortDate = (value?: string) => {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export const buildChartPoints = (entry: Pick<IndexSnapshot, 'intradayData' | 'price' | 'previousClose'>): ChartPoint[] => {
  const intraday = entry.intradayData?.filter((item) => Number.isFinite(item.value))
  if (intraday && intraday.length >= 2) {
    return intraday
  }
  return []
}

export const sessionLabel = (session: SessionKey) => {
  if (session === 'morning') return '早盘 09:30'
  if (session === 'midday') return '午盘 12:30'
  if (session === 'close') return '收盘 16:30'
  return '美股夜盘 22:30'
}
