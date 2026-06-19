export const UP_COLOR = '#ff4d43'
export const DOWN_COLOR = '#4caf50'
export const FLAT_COLOR = '#8a949e'

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
    maximumFractionDigits: digits
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

export const formatDashboardTime = (date = new Date()) => {
  const pad = (value: number) => value.toString().padStart(2, '0')
  const month = pad(date.getMonth() + 1)
  const day = pad(date.getDate())
  const hours = pad(date.getHours())
  const minutes = pad(date.getMinutes())
  const seconds = pad(date.getSeconds())

  return `${month}-${day} ${hours}:${minutes}:${seconds}`
}
