import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { LineChart, LinesChart, ScatterChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  MarkLineComponent,
  ToolboxComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import type { EChartsOption } from 'echarts'
import { CanvasRenderer } from 'echarts/renderers'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import type {
  HeatmapSnapshot,
  HeatmapSnapshotGroup,
  HeatmapSnapshotHistoryItem,
  HeatmapSnapshotHistoryResponse,
} from '../types/market'
import { formatError, requestJson } from '../utils/api'
import { downloadChartImage, exportChartElement } from '../utils/chartExport'
import {
  formatChineseAmount,
  formatDashboardTime,
  formatPercent,
  getTrendClass,
} from '../utils/market'
import { EmptyState, InlineError, SkeletonBlocks } from './StateBlocks'

echarts.use([
  ScatterChart,
  LineChart,
  LinesChart,
  GridComponent,
  DataZoomComponent,
  MarkLineComponent,
  ToolboxComponent,
  TooltipComponent,
  CanvasRenderer,
])

type MarketKey = 'CN' | 'HK' | 'US'
type MetricMode = 'turnover' | 'momentum'
type SelectionMode = 'single' | 'multi'

interface ZoomWindow {
  xStart: number
  xEnd: number
  yStart: number
  yEnd: number
}

interface SnapshotFrame {
  frame: HeatmapSnapshotHistoryItem
  snapshot: HeatmapSnapshot
}

interface SectorStateTrajectoryProps {
  market: MarketKey
  refreshVersion?: number
  date?: string
  snapshotId?: string
  reportMode?: boolean
  generatedAt?: string
  exportFilenamePrefix?: string
}

const MARKET_LABELS: Record<MarketKey, string> = {
  CN: 'A 股',
  HK: '港股',
  US: '美股',
}

const TRACK_COLORS = ['#2563eb', '#7c3aed', '#f59e0b', '#0891b2', '#db2777']
const PLAYBACK_INTERVAL_MS = 1100
const MAX_MULTI_SELECTION = TRACK_COLORS.length
const MIN_ZOOM_SPAN = 8
const ZOOM_STATE_COMMIT_DELAY_MS = 120
const REPORT_EXPORT_CHART_HEIGHT = 1800
const FULL_ZOOM: ZoomWindow = {
  xStart: 0,
  xEnd: 100,
  yStart: 0,
  yEnd: 100,
}

function resizeZoomRange(start: number, end: number, scale: number) {
  const currentSpan = Math.max(MIN_ZOOM_SPAN, end - start)
  const nextSpan = Math.min(100, Math.max(MIN_ZOOM_SPAN, currentSpan * scale))
  const center = (start + end) / 2
  const nextStart = Math.min(100 - nextSpan, Math.max(0, center - nextSpan / 2))
  return [nextStart, nextStart + nextSpan] as const
}

function zoomWindowsEqual(left: ZoomWindow, right: ZoomWindow) {
  return Math.abs(left.xStart - right.xStart) < 0.0001
    && Math.abs(left.xEnd - right.xEnd) < 0.0001
    && Math.abs(left.yStart - right.yStart) < 0.0001
    && Math.abs(left.yEnd - right.yEnd) < 0.0001
}

function median(values: number[]) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b)
  if (!sorted.length) return 0
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2
}

function heatColor(changePercent: number) {
  if (changePercent > 0) return '#df3f45'
  if (changePercent < 0) return '#159447'
  return '#64748b'
}

function compactPercent(value: number) {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

function RelativeTurnoverHelp({ tooltipId }: { tooltipId: string }) {
  return (
    <span className="metric-help">
      <span className="metric-help__trigger" aria-hidden="true">?</span>
      <span className="metric-help__tooltip" id={tooltipId} role="tooltip">
        <strong>什么是相对换手？</strong>
        <span>
          先用板块累计成交额除以板块市值，再除以当前时点所有已覆盖板块该比值的中位数。
        </span>
        <span>
          1.0x 代表市场中位水平；2.0x 约为中位数的两倍，0.5x 约为一半。它衡量相对交易活跃度，不是绝对换手率。
        </span>
      </span>
    </span>
  )
}

function frameLabel(snapshot: HeatmapSnapshot) {
  const timestamp = snapshot.scheduledAt || snapshot.capturedAt || ''
  return timestamp.length >= 16 ? timestamp.slice(11, 16) : '当前'
}

function syntheticFrame(snapshot: HeatmapSnapshot): HeatmapSnapshotHistoryItem {
  return {
    label: frameLabel(snapshot),
    capturedAt: snapshot.capturedAt || snapshot.scheduledAt || '',
    scheduledAt: snapshot.scheduledAt,
    snapshotId: snapshot.snapshotId,
    trigger: 'scheduled',
  }
}

function frameRows(
  frames: SnapshotFrame[],
  index: number,
  mode: MetricMode,
) {
  const current = frames[index]?.snapshot.industries ?? []
  const previous = frames[index - 1]?.snapshot.industries ?? []
  const previousByCode = new Map(previous.map((item) => [item.code, item]))
  const turnoverRates = current
    .map((item) => (
      item.turnover != null && item.marketValue > 0
        ? item.turnover / item.marketValue
        : 0
    ))
    .filter((value) => value > 0)
  const marketMedian = median(turnoverRates)

  return current.map((item) => {
    const previousItem = previousByCode.get(item.code)
    const momentum = previousItem
      ? item.changePercent - previousItem.changePercent
      : 0
    const turnoverRate = item.turnover != null && item.marketValue > 0
      ? item.turnover / item.marketValue
      : 0
    const activity = marketMedian > 0 ? turnoverRate / marketMedian : 0
    return {
      item,
      momentum,
      turnoverRate,
      activity,
      y: mode === 'turnover' ? activity : momentum,
    }
  })
}

function niceAxisCeiling(value: number) {
  if (!Number.isFinite(value) || value <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(value))
  const normalized = value / magnitude
  const step = [1, 1.5, 2, 3, 5, 7.5, 10].find((candidate) => normalized <= candidate) ?? 10
  return step * magnitude
}

export default function SectorStateTrajectory({
  market,
  refreshVersion = 0,
  date = '',
  snapshotId = '',
  reportMode = false,
  generatedAt = '',
  exportFilenamePrefix = '',
}: SectorStateTrajectoryProps) {
  const [frames, setFrames] = useState<SnapshotFrame[]>([])
  const [frameIndex, setFrameIndex] = useState(0)
  const [selectedCodes, setSelectedCodes] = useState<string[]>([])
  const [hoveredCode, setHoveredCode] = useState('')
  const [selectionMode, setSelectionMode] = useState<SelectionMode>('single')
  const [playing, setPlaying] = useState(false)
  const [mode, setMode] = useState<MetricMode>('momentum')
  const [categoryName, setCategoryName] = useState('')
  const [zoomWindow, setZoomWindow] = useState<ZoomWindow>(FULL_ZOOM)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [immersive, setImmersive] = useState(false)
  const relativeTurnoverHelpId = useId()
  const chartRef = useRef<ReactEChartsCore | null>(null)
  const cardRef = useRef<HTMLElement | null>(null)
  const nativeFullscreenRef = useRef(false)
  const zoomWindowRef = useRef<ZoomWindow>({ ...FULL_ZOOM })
  const zoomCommitTimerRef = useRef<number | null>(null)
  const activeChartPointersRef = useRef(new Set<number>())
  const chartZoomChangedRef = useRef(false)

  const clearZoomCommitTimer = () => {
    if (zoomCommitTimerRef.current == null) return
    window.clearTimeout(zoomCommitTimerRef.current)
    zoomCommitTimerRef.current = null
  }

  const commitPendingZoomWindow = () => {
    clearZoomCommitTimer()
    const next = zoomWindowRef.current
    setZoomWindow((current) => (
      zoomWindowsEqual(current, next) ? current : { ...next }
    ))
  }

  const applyZoomWindow = (next: ZoomWindow) => {
    clearZoomCommitTimer()
    zoomWindowRef.current = next
    setZoomWindow(next)
  }

  const scheduleZoomWindowCommit = () => {
    clearZoomCommitTimer()
    zoomCommitTimerRef.current = window.setTimeout(() => {
      zoomCommitTimerRef.current = null
      const next = zoomWindowRef.current
      setZoomWindow((current) => (
        zoomWindowsEqual(current, next) ? current : { ...next }
      ))
    }, ZOOM_STATE_COMMIT_DELAY_MS)
  }

  useEffect(() => () => {
    clearZoomCommitTimer()
    activeChartPointersRef.current.clear()
  }, [])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const exactSnapshot = snapshotId
          ? await requestJson<HeatmapSnapshot>(
              `/api/heatmap-snapshots/snapshot?snapshotId=${encodeURIComponent(snapshotId)}`,
            )
          : null
        const requestedDate = date
          || exactSnapshot?.scheduledAt?.slice(0, 10)
          || exactSnapshot?.capturedAt?.slice(0, 10)
          || 'latest'
        let eligible: HeatmapSnapshotHistoryItem[] = []
        try {
          const history = await requestJson<HeatmapSnapshotHistoryResponse>(
            `/api/heatmap-snapshots/history?market=${market}&date=${encodeURIComponent(requestedDate)}`,
          )
          eligible = history.snapshots
        } catch (historyError) {
          if (!exactSnapshot) throw historyError
        }
        if (exactSnapshot && !eligible.some((frame) => frame.snapshotId === exactSnapshot.snapshotId)) {
          eligible.push(syntheticFrame(exactSnapshot))
        }
        if (exactSnapshot) {
          const targetIndex = eligible.findIndex((frame) => frame.snapshotId === exactSnapshot.snapshotId)
          if (targetIndex >= 0) {
            eligible = reportMode
              ? eligible.slice(Math.max(0, targetIndex - 1), targetIndex + 1)
              : eligible.slice(0, targetIndex + 1)
          }
        }
        const loaded = await Promise.all(eligible.map(async (frame) => ({
          frame,
          snapshot: exactSnapshot && exactSnapshot.snapshotId === frame.snapshotId
            ? exactSnapshot
            : await requestJson<HeatmapSnapshot>(
                `/api/heatmap-snapshots/snapshot?snapshotId=${encodeURIComponent(frame.snapshotId ?? '')}`,
              ),
        })))
        if (cancelled) return
        setFrames(loaded)
        setFrameIndex(Math.max(0, loaded.length - 1))
        const latestIndustries = loaded[loaded.length - 1]?.snapshot.industries ?? []
        const largest = [...latestIndustries].sort(
          (a, b) => (b.marketValue || 0) - (a.marketValue || 0),
        )[0]
        setSelectedCodes(largest?.code ? [largest.code] : [])
        setHoveredCode('')
        setPlaying(false)
        setCategoryName('')
        applyZoomWindow({ ...FULL_ZOOM })
        const turnoverFrameCount = loaded.filter((entry) => (
          entry.snapshot.industries.some((item) => item.turnover != null)
        )).length
        setMode(reportMode ? 'momentum' : turnoverFrameCount >= 2 ? 'turnover' : 'momentum')
      } catch (nextError) {
        if (!cancelled) setError(formatError(nextError))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [date, market, refreshVersion, reportMode, snapshotId])

  useEffect(() => {
    if (!playing || frames.length < 2) return undefined
    const timer = window.setTimeout(() => {
      setFrameIndex((current) => {
        const next = current + 1
        if (next >= frames.length - 1) {
          setPlaying(false)
          return frames.length - 1
        }
        return next
      })
    }, PLAYBACK_INTERVAL_MS)
    return () => window.clearTimeout(timer)
  }, [frameIndex, frames.length, playing])

  useEffect(() => {
    if (!immersive) return undefined
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const resizeChart = () => chartRef.current?.getEchartsInstance().resize()
    const firstFrame = window.requestAnimationFrame(resizeChart)
    const resizeTimer = window.setTimeout(resizeChart, 260)
    return () => {
      document.body.style.overflow = previousOverflow
      window.cancelAnimationFrame(firstFrame)
      window.clearTimeout(resizeTimer)
    }
  }, [immersive])

  useEffect(() => {
    const handleFullscreenChange = () => {
      if (!document.fullscreenElement && nativeFullscreenRef.current) {
        nativeFullscreenRef.current = false
        setImmersive(false)
      }
      window.setTimeout(() => chartRef.current?.getEchartsInstance().resize(), 80)
    }
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [])

  const selectSector = (code: string) => {
    if (!code) return
    setSelectedCodes((current) => {
      if (selectionMode === 'single') return [code]
      if (current.includes(code)) return current.filter((item) => item !== code)
      return [...current, code].slice(-MAX_MULTI_SELECTION)
    })
  }

  const startPlayback = () => {
    if (frames.length < 2) return
    if (frameIndex >= frames.length - 1) setFrameIndex(0)
    setPlaying(true)
  }

  const selectMomentumMode = () => {
    setPlaying(false)
    setMode('momentum')
    applyZoomWindow({ ...FULL_ZOOM })
  }

  const selectTurnoverMode = () => {
    let latestTurnoverFrame = -1
    frames.forEach((entry, index) => {
      if (entry.snapshot.industries.some((item) => item.turnover != null)) {
        latestTurnoverFrame = index
      }
    })
    setPlaying(false)
    if (latestTurnoverFrame >= 0) setFrameIndex(latestTurnoverFrame)
    setMode('turnover')
    applyZoomWindow({ ...FULL_ZOOM })
  }

  const togglePlayback = () => {
    if (playing) setPlaying(false)
    else startPlayback()
  }

  const enterImmersive = async () => {
    setImmersive(true)
    try {
      if (cardRef.current?.requestFullscreen && !document.fullscreenElement) {
        await cardRef.current.requestFullscreen({ navigationUI: 'hide' })
        nativeFullscreenRef.current = true
      }
    } catch {
      nativeFullscreenRef.current = false
    }
    try {
      const orientation = window.screen.orientation as ScreenOrientation & {
        lock?: (value: string) => Promise<void>
      }
      await orientation.lock?.('landscape')
    } catch {
      // iOS Safari does not expose orientation.lock; portrait devices use the CSS fallback.
    }
    window.setTimeout(() => chartRef.current?.getEchartsInstance().resize(), 80)
  }

  const exitImmersive = async () => {
    setImmersive(false)
    try {
      const orientation = window.screen.orientation as ScreenOrientation & { unlock?: () => void }
      orientation.unlock?.()
    } catch {
      // Orientation unlock is best-effort across mobile browsers.
    }
    if (document.fullscreenElement) {
      nativeFullscreenRef.current = false
      try {
        await document.exitFullscreen()
      } catch {
        // The CSS immersive state has already been cleared.
      }
    }
    window.setTimeout(() => chartRef.current?.getEchartsInstance().resize(), 80)
  }

  const selectCategory = (nextCategory: string) => {
    setPlaying(false)
    setCategoryName(nextCategory)
    applyZoomWindow({ ...FULL_ZOOM })
    if (!nextCategory) return
    const largest = currentRows
      .filter(({ item }) => item.parentName === nextCategory)
      .sort((a, b) => (b.item.marketValue || 0) - (a.item.marketValue || 0))[0]
    if (largest?.item.code) setSelectedCodes([largest.item.code])
  }

  const changeZoom = (scale: number) => {
    const current = zoomWindowRef.current
    const [xStart, xEnd] = resizeZoomRange(current.xStart, current.xEnd, scale)
    const [yStart, yEnd] = resizeZoomRange(current.yStart, current.yEnd, scale)
    applyZoomWindow({ xStart, xEnd, yStart, yEnd })
  }

  const handleDataZoom = (params: any) => {
    const updates = Array.isArray(params?.batch) ? params.batch : [params]
    const next = { ...zoomWindowRef.current }
    updates.forEach((update: any) => {
      if (!Number.isFinite(update?.start) || !Number.isFinite(update?.end)) return
      const zoomId = String(update.dataZoomId ?? '')
      const zoomIndex = Number(update.dataZoomIndex)
      if (zoomId === 'trajectory-x-zoom' || zoomIndex === 0) {
        next.xStart = update.start
        next.xEnd = update.end
      }
      if (zoomId === 'trajectory-y-zoom' || zoomIndex === 1) {
        next.yStart = update.start
        next.yEnd = update.end
      }
    })
    if (zoomWindowsEqual(next, zoomWindowRef.current)) return
    zoomWindowRef.current = next
    chartZoomChangedRef.current = true
    if (activeChartPointersRef.current.size === 0) scheduleZoomWindowCommit()
  }

  const baselineMarketValue = useMemo(() => {
    const values = new Map<string, number>()
    frames.forEach(({ snapshot }) => {
      snapshot.industries.forEach((item) => {
        if (!values.has(item.code) && item.marketValue > 0) {
          values.set(item.code, item.marketValue)
        }
      })
    })
    return values
  }, [frames])

  const currentRows = useMemo(
    () => frameRows(frames, frameIndex, mode),
    [frames, frameIndex, mode],
  )
  const fixedYAxisRange = useMemo(() => {
    const values = frames.flatMap((_, index) => (
      frameRows(frames, index, mode)
        .map(({ y }) => y)
        .filter(Number.isFinite)
    ))
    if (mode === 'turnover') {
      const upper = niceAxisCeiling(Math.max(1, ...values) * 1.08)
      return { min: 0, max: upper }
    }
    const absoluteMax = Math.max(0.1, ...values.map((value) => Math.abs(value)))
    const bound = niceAxisCeiling(absoluteMax * 1.08)
    return { min: -bound, max: bound }
  }, [frames, mode])
  const turnoverFrameCount = useMemo(() => frames.filter((entry) => (
    entry.snapshot.industries.some((item) => item.turnover != null)
  )).length, [frames])
  const turnoverAvailable = turnoverFrameCount >= 1
  const currentFrame = frames[frameIndex]
  const currentGroups = useMemo<HeatmapSnapshotGroup[]>(() => {
    if (currentFrame?.snapshot.groups?.length) return currentFrame.snapshot.groups
    const grouped = new Map<string, HeatmapSnapshotGroup>()
    currentRows.forEach(({ item }) => {
      const existing = grouped.get(item.parentName)
      if (existing) {
        existing.industries.push(item)
        existing.marketValue += item.marketValue || 0
        return
      }
      grouped.set(item.parentName, {
        name: item.parentName,
        code: item.parentName,
        changePercent: 0,
        marketValue: item.marketValue || 0,
        industries: [item],
      })
    })
    return [...grouped.values()].map((group) => {
      const total = group.industries.reduce((sum, item) => sum + (item.marketValue || 0), 0)
      const weightedChange = total > 0
        ? group.industries.reduce(
            (sum, item) => sum + item.changePercent * (item.marketValue || 0),
            0,
          ) / total
        : 0
      return { ...group, changePercent: weightedChange }
    })
  }, [currentFrame, currentRows])
  const turnoverCoveredRows = currentRows.filter(
    ({ item }) => item.turnover != null && item.marketValue > 0,
  )
  const metricRows = currentRows
  const visibleRows = categoryName
    ? metricRows.filter(({ item }) => item.parentName === categoryName)
    : metricRows
  const currentHasTurnover = turnoverCoveredRows.length > 0
  const selectedCodeSet = new Set(selectedCodes)
  const focusCode = hoveredCode || selectedCodes[0] || visibleRows[0]?.item.code || ''
  const selectedRow = visibleRows.find(({ item }) => item.code === focusCode)
    ?? visibleRows[0]
  const peerRows = selectedRow
    ? [...visibleRows]
        .filter(({ item }) => item.parentName === selectedRow.item.parentName)
        .sort((a, b) => (b.item.marketValue || 0) - (a.item.marketValue || 0))
    : []
  const movers = [...visibleRows]
    .sort((a, b) => Math.abs(b.momentum) - Math.abs(a.momentum))
    .slice(0, 6)
  const chartId = `heatmap-${market.toLowerCase()}`
  const exportFilename = `${exportFilenamePrefix ? `${exportFilenamePrefix}-` : ''}${chartId}.png`
  const currentExportFilename = `${chartId}-${(
    currentFrame?.snapshot.scheduledAt?.slice(0, 10)
      || currentFrame?.snapshot.capturedAt?.slice(0, 10)
      || date
      || 'current'
  )}-${(currentFrame?.frame.label || 'current').replace(':', '')}.png`
  const exportCurrentChart = () => {
    const instance = chartRef.current?.getEchartsInstance()
    if (!instance) return
    downloadChartImage(instance.getDataURL({
      type: 'png',
      pixelRatio: 2,
      backgroundColor: '#ffffff',
    }), currentExportFilename)
  }
  const zoomLevel = Math.round(10000 / Math.max(
    MIN_ZOOM_SPAN,
    Math.sqrt(
      (zoomWindow.xEnd - zoomWindow.xStart)
      * (zoomWindow.yEnd - zoomWindow.yStart),
    ),
  ))
  const zoomIsFull = zoomWindow.xStart <= 0.01
    && zoomWindow.xEnd >= 99.99
    && zoomWindow.yStart <= 0.01
    && zoomWindow.yEnd >= 99.99
  const zoomIsMax = (zoomWindow.xEnd - zoomWindow.xStart) <= MIN_ZOOM_SPAN + 0.01
    && (zoomWindow.yEnd - zoomWindow.yStart) <= MIN_ZOOM_SPAN + 0.01

  const chartOption = useMemo(() => {
    if (!visibleRows.length) return {} as EChartsOption
    const marketValues = [...baselineMarketValue.values()].filter((value) => value > 0)
    const labelCodes = new Set(
      [...baselineMarketValue.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10)
        .map(([code]) => code),
    )
    selectedCodes.forEach((code) => labelCodes.add(code))
    peerRows.slice(0, 8).forEach(({ item }) => labelCodes.add(item.code))
    const maxMarketValue = Math.max(...marketValues, 1)
    const bubbleSize = (code: string) => {
      const value = baselineMarketValue.get(code) || 1
      return Math.max(
        reportMode ? 18 : 6,
        Math.sqrt(value / maxMarketValue) * (reportMode ? 180 : 72),
      )
    }
    const selectionColorMap = new Map(
      selectedCodes.map((code, index) => [code, TRACK_COLORS[index % TRACK_COLORS.length]]),
    )
    const trails = selectedCodes.map((code, selectionIndex) => {
      const name = visibleRows.find(({ item }) => item.code === code)?.item.name ?? code
      const color = TRACK_COLORS[selectionIndex % TRACK_COLORS.length]
      const points = frames.slice(0, frameIndex + 1).flatMap((_, index) => {
        const row = frameRows(frames, index, mode).find(({ item }) => item.code === code)
        return row ? [[row.item.changePercent, row.y, frames[index].frame.label]] : []
      })
      return { name, color, points }
    })
    const trailSeries = trails.map(({ name, color, points }) => {
      return {
        type: 'line',
        name,
        data: points.map((point, index) => {
          const isStart = index === 0
          const isCurrent = index === points.length - 1
          return {
            value: point,
            symbol: isStart ? 'emptyCircle' : isCurrent ? 'diamond' : 'circle',
            symbolSize: reportMode
              ? isStart ? 24 : isCurrent ? 28 : 14
              : isStart ? 11 : isCurrent ? 12 : 6,
            itemStyle: {
              color: isStart ? '#ffffff' : color,
              borderColor: color,
              borderWidth: reportMode
                ? isStart || isCurrent ? 5 : 3
                : isStart || isCurrent ? 2.5 : 1.5,
            },
            label: selectedCodes.length === 1 && (isStart || isCurrent)
              ? {
                  show: true,
                  formatter: isStart ? '起点' : '当前',
                  position: isStart ? 'left' : 'right',
                  color,
                  fontSize: reportMode ? 22 : 10,
                  fontWeight: 700,
                }
              : undefined,
          }
        }),
        showSymbol: true,
        lineStyle: { color, width: reportMode ? 5 : 2.5 },
        itemStyle: { color },
        z: 5,
      }
    })
    const directionSeries = trails.map(({ name, color, points }) => ({
      type: 'lines',
      name: `${name} · 方向`,
      coordinateSystem: 'cartesian2d',
      data: points.slice(1).map((point, index) => ({
        coords: [
          [points[index][0], points[index][1]],
          [point[0], point[1]],
        ],
      })),
      symbol: ['none', 'arrow'],
      symbolSize: [0, reportMode ? 18 : 9],
      lineStyle: { color, width: reportMode ? 4 : 1.8, opacity: 0.92 },
      silent: true,
      z: 6,
    }))
    const yReference = mode === 'turnover' ? 1 : 0
    const peerParentName = selectedRow?.item.parentName ?? ''
    const scatterData = visibleRows.map(({ item, y, momentum, activity }) => {
      const isSelected = selectedCodeSet.has(item.code)
      const isHovered = item.code === hoveredCode
      const isPeer = Boolean(peerParentName) && item.parentName === peerParentName
      const selectedColor = selectionColorMap.get(item.code)
      return {
        value: [
          item.changePercent,
          y,
          baselineMarketValue.get(item.code) || item.marketValue || 1,
          item.name,
          item.code,
          item.parentName,
          item.turnover ?? null,
          momentum,
          activity,
        ],
        itemStyle: {
          color: heatColor(item.changePercent),
          opacity: isSelected || isHovered || isPeer ? 0.82 : 0.16,
          borderColor: selectedColor ?? (isHovered ? '#0f172a' : isPeer ? '#f59e0b' : '#ffffff'),
          borderWidth: isSelected ? 4 : isHovered ? 3 : isPeer ? 2 : 1,
        },
      }
    })

    return {
      animationDurationUpdate: playing ? 760 : 420,
      grid: reportMode
        ? { left: 180, right: 90, top: 110, bottom: 150 }
        : { left: 64, right: 28, top: 58, bottom: 58 },
      toolbox: {
        show: !reportMode,
        top: 10,
        right: 18,
        itemSize: 18,
        itemGap: 12,
        feature: {
          dataZoom: {
            title: {
              zoom: '框选放大',
              back: '返回上一步',
            },
            xAxisIndex: 0,
            yAxisIndex: 0,
          },
          restore: { title: '重置缩放' },
        },
      },
      dataZoom: [
        {
          id: 'trajectory-x-zoom',
          type: 'inside',
          xAxisIndex: 0,
          filterMode: 'none',
          start: zoomWindow.xStart,
          end: zoomWindow.xEnd,
          zoomOnMouseWheel: true,
          moveOnMouseMove: true,
          moveOnMouseWheel: false,
        },
        {
          id: 'trajectory-y-zoom',
          type: 'inside',
          yAxisIndex: 0,
          filterMode: 'none',
          start: zoomWindow.yStart,
          end: zoomWindow.yEnd,
          zoomOnMouseWheel: true,
          moveOnMouseMove: true,
          moveOnMouseWheel: false,
        },
      ],
      tooltip: {
        trigger: 'item',
        formatter: (params: any) => {
          if (params.seriesType === 'line') {
            const point = params.value as [number, number, string] | undefined
            const changePercent = Number(point?.[0])
            return [
              `<strong>${params.seriesName}</strong>`,
              `时间：${point?.[2] ?? '--'}`,
              `涨跌幅：${Number.isFinite(changePercent) ? compactPercent(changePercent) : '--'}`,
            ].join('<br/>')
          }
          const data = params.value as any[]
          const turnover = data[6] as number | null
          return [
            `<strong>${data[3]}</strong> · ${data[5]}`,
            `涨跌幅：${compactPercent(data[0])}`,
            mode === 'turnover'
              ? `相对换手：${turnover == null ? '--' : `${data[1].toFixed(2)}x`}`
              : `本帧变化：${compactPercent(data[1])}`,
            `固定市值：${formatChineseAmount(data[2])}`,
            `累计成交额：${turnover == null ? '--' : formatChineseAmount(turnover)}`,
          ].join('<br/>')
        },
      },
      xAxis: {
        type: 'value',
        name: '当前涨跌幅',
        nameLocation: 'middle',
        nameGap: reportMode ? 82 : 36,
        nameTextStyle: { fontSize: reportMode ? 28 : 12 },
        axisLabel: { formatter: '{value}%', fontSize: reportMode ? 22 : 12 },
        splitLine: { lineStyle: { color: '#e5e7eb' } },
      },
      yAxis: {
        type: 'value',
        name: mode === 'turnover' ? '相对换手（市场中位数 = 1x）' : '较上一帧变化',
        nameLocation: 'middle',
        nameGap: reportMode ? 120 : 48,
        nameTextStyle: { fontSize: reportMode ? 28 : 12 },
        min: fixedYAxisRange.min,
        max: fixedYAxisRange.max,
        axisLabel: {
          formatter: mode === 'turnover' ? '{value}x' : '{value}%',
          fontSize: reportMode ? 22 : 12,
        },
        splitLine: { lineStyle: { color: '#e5e7eb' } },
      },
      series: [
        ...trailSeries,
        ...directionSeries,
        {
          type: 'scatter',
          name: '行业状态',
          data: scatterData,
          symbolSize: (data: any[]) => bubbleSize(String(data[4])),
          label: {
            show: true,
            position: 'top',
            color: '#334155',
            fontSize: reportMode ? 20 : 10,
            formatter: (params: any) => (
              labelCodes.has(String(params.value?.[4]))
                ? String(params.value?.[3] ?? '')
                : ''
            ),
          },
          markLine: {
            silent: true,
            symbol: 'none',
            label: { show: false },
            lineStyle: { color: '#94a3b8', type: 'dashed' },
            data: [{ xAxis: 0 }, { yAxis: yReference }],
          },
          z: 3,
        },
        ...(!reportMode ? [{
          type: 'scatter',
          name: '行业点击区',
          data: scatterData.map(({ value }) => ({
            value,
            itemStyle: {
              color: 'rgba(15, 23, 42, 0.002)',
              borderWidth: 0,
            },
          })),
          symbolSize: (data: any[]) => Math.max(24, bubbleSize(String(data[4]))),
          cursor: 'pointer',
          emphasis: { scale: false },
          z: 8,
        }] : []),
      ],
    } as EChartsOption
  }, [baselineMarketValue, fixedYAxisRange, frameIndex, frames, hoveredCode, mode, peerRows, playing, reportMode, selectedCodeSet, selectedCodes, selectedRow, visibleRows, zoomWindow])

  if (loading) {
    return (
      <section className="surface-card sector-state-card">
        <SkeletonBlocks blocks={1} height={520} />
      </section>
    )
  }

  if (error) {
    return <InlineError message={error} />
  }

  if (!frames.length || !currentFrame) {
    return (
      <section className="surface-card sector-state-card">
        <EmptyState title="暂无板块轨迹" description="积累两个以上定时热点图快照后，这里会显示板块状态变化。" />
      </section>
    )
  }

  if (reportMode) {
    return (
      <section className="report-heatmap-section">
        <div className="section-heading">
          <div>
            <span className="section-kicker">Report Sector State</span>
            <h2>{MARKET_LABELS[market]}板块状态图</h2>
            <p>面积按市值、横轴为涨跌幅，纵轴显示相对换手或相邻快照涨跌变化。</p>
          </div>
          <button
            type="button"
            className="chart-export-button chart-export-button--inline"
            data-export-chart-id={chartId}
            data-export-filename={exportFilename}
            aria-label={`导出图表 ${chartId}`}
            onClick={() => void exportChartElement(chartId, exportFilename)}
          >
            导出 PNG
          </button>
        </div>
        <div className="report-heatmap-export-stage">
          <div
            className="report-chart-card report-heatmap-chart-card report-sector-state-chart-card"
            data-chart-id={chartId}
            data-y-axis-min={fixedYAxisRange.min}
            data-y-axis-max={fixedYAxisRange.max}
          >
            <div className="report-chart-card__header">
              <div>
                <span>{MARKET_LABELS[market]}市场 · {currentFrame.frame.label}</span>
                <h3>{MARKET_LABELS[market]}板块交易状态与涨跌变化</h3>
                <small>
                  气泡面积按市值线性映射 · 横轴为当前涨跌幅 ·
                  纵轴为{mode === 'turnover' ? '相对交易活跃度' : '较上一快照的涨跌变化'}
                </small>
              </div>
              <div className="report-state-legend">
                <span className="is-down">下跌</span>
                <span className="is-flat">持平</span>
                <span className="is-up">上涨</span>
                <span>气泡越大，市值越高</span>
              </div>
            </div>
            <div className="report-sector-state-chart">
              <ReactEChartsCore
                ref={chartRef}
                echarts={echarts}
                option={chartOption}
                notMerge
                style={{ height: REPORT_EXPORT_CHART_HEIGHT, width: '100%' }}
              />
            </div>
            <div className="report-heatmap-annotation">
              <div className="report-heatmap-annotation__intro">
                <strong>一级分类与二级板块索引</strong>
                <span>分类按当前市场行业体系展开，列出每个二级板块的涨跌幅与市值。</span>
              </div>
              <div className="report-heatmap-annotation__grid">
                {currentGroups.map((group) => (
                  <div className="report-heatmap-annotation__group" key={group.code || group.name}>
                    <h4 className={getTrendClass(group.changePercent)}>
                      {group.name} {formatPercent(group.changePercent)}
                    </h4>
                    <ul>
                      {group.industries.map((industry) => (
                        <li key={industry.code}>
                          <span>{industry.name}</span>
                          <strong className={getTrendClass(industry.changePercent)}>
                            {formatPercent(industry.changePercent)}
                          </strong>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
            <div className="report-chart-card__footer">
              <span>
                {mode === 'turnover'
                  ? `相对换手 1.0x = 当前已覆盖板块中位数，覆盖 ${turnoverCoveredRows.length}/${currentRows.length}`
                  : '涨跌速度 = 当前涨跌幅减去上一快照涨跌幅'}
              </span>
              <span>
                共 {currentGroups.length} 个一级分类 · {currentRows.length} 个二级板块 ·
                更新于 {formatDashboardTime(generatedAt || currentFrame.snapshot.updatedAt || currentFrame.snapshot.capturedAt)}
              </span>
            </div>
          </div>
        </div>
      </section>
    )
  }

  return (
    <section
      ref={cardRef}
      className={immersive ? 'surface-card sector-state-card is-immersive' : 'surface-card sector-state-card'}
    >
      {immersive ? (
        <div className="sector-immersive-bar">
          <div className="sector-immersive-title">
            <span>{MARKET_LABELS[market]}板块轨迹</span>
            <strong>{currentFrame.frame.label}</strong>
          </div>
          <div className="sector-immersive-actions">
            <div className="heatmap-mode-switcher session-switcher" aria-label="横屏轨迹指标切换">
              <button
                type="button"
                className={mode === 'momentum' ? 'session-tab is-active' : 'session-tab'}
                onClick={selectMomentumMode}
              >
                涨跌速度
              </button>
              <button
                type="button"
                className={mode === 'turnover' ? 'session-tab session-tab--with-help is-active' : 'session-tab session-tab--with-help'}
                onClick={selectTurnoverMode}
                disabled={!turnoverAvailable}
                aria-label="相对换手"
                aria-describedby={`${relativeTurnoverHelpId}-immersive`}
              >
                相对换手
                <RelativeTurnoverHelp tooltipId={`${relativeTurnoverHelpId}-immersive`} />
              </button>
            </div>
            <button
              type="button"
              className={playing ? 'ghost-button sector-immersive-play' : 'primary-button sector-immersive-play'}
              onClick={togglePlayback}
              disabled={frames.length < 2}
            >
              {playing ? '暂停' : '播放'}
            </button>
            <button
              type="button"
              className="ghost-button sector-immersive-exit"
              onClick={() => void exitImmersive()}
              aria-label="退出横屏全屏"
            >
              退出全屏
            </button>
          </div>
        </div>
      ) : null}
      <div className="section-heading sector-state-heading">
        <div>
          <span className="section-kicker">Sector State Map</span>
          <h2>{MARKET_LABELS[market]}板块状态轨迹</h2>
          <p>
            气泡面积与首帧市值成正比并全天固定，位置随涨跌与活跃状态变化；轨迹箭头按时间前进，经过气泡可识别同类板块。
          </p>
        </div>
        <div className="sector-state-toolbar">
          <button
            type="button"
            className="chart-export-button sector-current-export-button"
            aria-label="导出当前板块轨迹截图"
            onClick={exportCurrentChart}
          >
            导出当前截图
          </button>
          <label className="sector-category-select">
            <span>展开一级分类</span>
            <select
              value={categoryName}
              onChange={(event) => selectCategory(event.target.value)}
            >
              <option value="">全部一级分类</option>
              {currentGroups.map((group) => (
                <option key={group.code || group.name} value={group.name}>
                  {group.name}（{group.industries.length}）
                </option>
              ))}
            </select>
          </label>
          <div className="heatmap-mode-switcher session-switcher" aria-label="板块轨迹指标切换">
            <button
              type="button"
              className={mode === 'momentum' ? 'session-tab is-active' : 'session-tab'}
              onClick={selectMomentumMode}
            >
              涨跌速度
            </button>
            <button
              type="button"
              className={mode === 'turnover' ? 'session-tab session-tab--with-help is-active' : 'session-tab session-tab--with-help'}
              onClick={selectTurnoverMode}
              disabled={!turnoverAvailable}
              title={turnoverAvailable ? '成交额除以市值，再与当前市场中位数比较' : '等待新格式快照积累成交额'}
              aria-label="相对换手"
              aria-describedby={`${relativeTurnoverHelpId}-toolbar`}
            >
              相对换手
              <RelativeTurnoverHelp tooltipId={`${relativeTurnoverHelpId}-toolbar`} />
            </button>
          </div>
          <div className="heatmap-mode-switcher session-switcher" aria-label="轨迹选择方式">
            <button
              type="button"
              className={selectionMode === 'single' ? 'session-tab is-active' : 'session-tab'}
              onClick={() => {
                setSelectionMode('single')
                setSelectedCodes((current) => current.slice(0, 1))
              }}
            >
              单选
            </button>
            <button
              type="button"
              className={selectionMode === 'multi' ? 'session-tab is-active' : 'session-tab'}
              onClick={() => setSelectionMode('multi')}
            >
              多选
            </button>
          </div>
          <button
            type="button"
            className={playing ? 'ghost-button sector-play-button' : 'primary-button sector-play-button'}
            onClick={togglePlayback}
            disabled={frames.length < 2}
          >
            {playing ? '暂停播放' : '播放轨迹'}
          </button>
          <button
            type="button"
            className="ghost-button sector-landscape-button"
            onClick={() => void enterImmersive()}
            aria-label="横屏全屏查看板块轨迹"
          >
            横屏全屏
          </button>
        </div>
      </div>

      <div className="sector-state-note">
        <strong>{MARKET_LABELS[market]} · {currentFrame.frame.label}</strong>
        <span>
          {categoryName ? `已展开“${categoryName}”的 ${visibleRows.length} 个二级板块；` : ''}
          面积按市值线性映射（直径按平方根计算，极小板块保留 6px）；
          纵轴范围按当前交易日已加载的全部快照统一锁定；
          {mode === 'turnover'
            ? currentHasTurnover
              ? `1.0x 代表当前已覆盖行业的换手中位数；本帧真实成交额覆盖 ${turnoverCoveredRows.length}/${currentRows.length} 个行业，未覆盖板块保留在 0 轴并标记为暂无数据。`
              : '该旧快照尚未保存行业成交额，请选择有成交额的新快照或切回“涨跌速度”。'
            : turnoverAvailable
              ? '纵轴显示本帧涨跌幅相对上一帧的变化，可切换“相对换手”查看成交活跃度。'
              : '旧快照没有行业成交额，当前先显示真实涨跌速度；新采集快照将开始积累真实成交额。'}
        </span>
      </div>

      <div className="sector-selection-summary">
        <strong>已选轨迹</strong>
        {selectedCodes.length ? selectedCodes.map((code, index) => {
          const item = currentRows.find((row) => row.item.code === code)?.item
            ?? frames.flatMap(({ snapshot }) => snapshot.industries).find((sector) => sector.code === code)
          return (
            <span className="sector-selection-chip" key={code}>
              <i style={{ background: TRACK_COLORS[index % TRACK_COLORS.length] }} />
              {item?.name ?? code}
            </span>
          )
        }) : <span className="sector-selection-empty">点击气泡或右侧板块名称开始追踪</span>}
        <span className="sector-direction-legend"><b>○</b>首帧 <em>→</em> <b>◆</b>当前帧</span>
        <span className="sector-peer-legend"><i />金色描边为同一一级分类</span>
        <small>{selectionMode === 'multi' ? `可同时追踪 ${MAX_MULTI_SELECTION} 个板块` : '单选模式下，新选择会替换当前轨迹'}</small>
      </div>

      <div className="sector-state-layout">
        <div
          className="sector-state-chart-shell"
          data-chart-id={`${chartId}-current`}
          data-y-axis-min={fixedYAxisRange.min}
          data-y-axis-max={fixedYAxisRange.max}
        >
          <div className="sector-chart-zoom-bar">
            <span>
              <strong>缩放定位</strong>
              滚轮或双指缩放 · 拖动平移 · 小气泡保留 24px 点击区
            </span>
            <div aria-label="图表缩放控制">
              <button
                type="button"
                className="ghost-button sector-zoom-button"
                onClick={() => changeZoom(1.5)}
                disabled={zoomIsFull}
              >
                缩小
              </button>
              <output aria-live="polite">{zoomLevel}%</output>
              <button
                type="button"
                className="ghost-button sector-zoom-button"
                onClick={() => changeZoom(2 / 3)}
                disabled={zoomIsMax}
              >
                放大
              </button>
              <button
                type="button"
                className="ghost-button sector-zoom-button"
                onClick={() => applyZoomWindow({ ...FULL_ZOOM })}
                disabled={zoomIsFull}
              >
                重置
              </button>
            </div>
          </div>
          {visibleRows.length ? (
            <ReactEChartsCore
              ref={chartRef}
              className="sector-state-echart"
              echarts={echarts}
              option={chartOption}
              notMerge
              lazyUpdate
              style={{ height: 520, width: '100%' }}
              onPointerDown={(event) => {
                activeChartPointersRef.current.add(event.pointerId)
                chartZoomChangedRef.current = false
                clearZoomCommitTimer()
              }}
              onPointerUp={(event) => {
                activeChartPointersRef.current.delete(event.pointerId)
                if (activeChartPointersRef.current.size > 0) return
                commitPendingZoomWindow()
                if (chartZoomChangedRef.current) setHoveredCode('')
                chartZoomChangedRef.current = false
              }}
              onPointerCancel={(event) => {
                activeChartPointersRef.current.delete(event.pointerId)
                if (activeChartPointersRef.current.size > 0) return
                commitPendingZoomWindow()
                if (chartZoomChangedRef.current) setHoveredCode('')
                chartZoomChangedRef.current = false
              }}
              onPointerLeave={(event) => {
                if (!activeChartPointersRef.current.delete(event.pointerId)) return
                if (activeChartPointersRef.current.size > 0) return
                commitPendingZoomWindow()
                if (chartZoomChangedRef.current) setHoveredCode('')
                chartZoomChangedRef.current = false
              }}
              onEvents={{
                click: (params: any) => {
                  const code = params.value?.[4]
                  if (code) selectSector(String(code))
                },
                mouseover: (params: any) => {
                  if (activeChartPointersRef.current.size > 0) return
                  const code = params.value?.[4]
                  if (code) setHoveredCode(String(code))
                },
                mouseout: () => {
                  if (activeChartPointersRef.current.size === 0) setHoveredCode('')
                },
                datazoom: handleDataZoom,
              }}
            />
          ) : (
            <EmptyState title="该时点暂无成交额" description="请选择新的快照，或切换到“涨跌速度”继续查看板块轨迹。" />
          )}
        </div>

        <aside className="sector-state-side">
          {selectedRow ? (
            <div className="sector-state-focus">
              <span>当前追踪</span>
              <h3>{selectedRow.item.name}</h3>
              <small>{selectedRow.item.parentName}</small>
              <dl>
                <div><dt>涨跌幅</dt><dd className={selectedRow.item.changePercent >= 0 ? 'is-up' : 'is-down'}>{formatPercent(selectedRow.item.changePercent)}</dd></div>
                <div><dt>本帧变化</dt><dd>{compactPercent(selectedRow.momentum)}</dd></div>
                <div><dt>固定市值</dt><dd>{formatChineseAmount(baselineMarketValue.get(selectedRow.item.code) || selectedRow.item.marketValue)}</dd></div>
                <div><dt>累计成交额</dt><dd>{selectedRow.item.turnover == null ? '--' : formatChineseAmount(selectedRow.item.turnover)}</dd></div>
                <div><dt>相对换手</dt><dd>{selectedRow.activity > 0 ? `${selectedRow.activity.toFixed(2)}x` : '--'}</dd></div>
              </dl>
            </div>
          ) : null}

          {selectedRow ? (
            <div className="sector-peer-panel">
              <div className="sector-peer-panel__header">
                <div><strong>同类板块</strong><span>{selectedRow.item.parentName}</span></div>
                <div>
                  <small>{peerRows.length} 个二级板块</small>
                  <button
                    type="button"
                    onClick={() => selectCategory(
                      categoryName === selectedRow.item.parentName
                        ? ''
                        : selectedRow.item.parentName,
                    )}
                  >
                    {categoryName === selectedRow.item.parentName ? '返回全部' : '展开分类'}
                  </button>
                </div>
              </div>
              <div className="sector-peer-list">
                {peerRows.map(({ item }) => (
                  <button
                    key={item.code}
                    type="button"
                    className={selectedCodeSet.has(item.code) ? 'is-selected' : ''}
                    onMouseEnter={() => setHoveredCode(item.code)}
                    onMouseLeave={() => setHoveredCode('')}
                    onClick={() => selectSector(item.code)}
                  >
                    <span>{item.name}</span>
                    <strong className={item.changePercent >= 0 ? 'is-up' : 'is-down'}>
                      {formatPercent(item.changePercent)}
                    </strong>
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div className="sector-state-movers">
            <div><strong>本时段变化最大</strong><span>相邻快照</span></div>
            {movers.map(({ item, momentum }) => (
              <button
                key={item.code}
                type="button"
                className={selectedCodeSet.has(item.code) ? 'is-active' : ''}
                onMouseEnter={() => setHoveredCode(item.code)}
                onMouseLeave={() => setHoveredCode('')}
                onClick={() => selectSector(item.code)}
              >
                <span>{item.name}<small>{item.parentName}</small></span>
                <strong className={momentum >= 0 ? 'is-up' : 'is-down'}>{compactPercent(momentum)}</strong>
              </button>
            ))}
          </div>
        </aside>
      </div>

      <div className="sector-state-timeline">
        <input
          type="range"
          min={0}
          max={Math.max(0, frames.length - 1)}
          value={frameIndex}
          onChange={(event) => {
            setPlaying(false)
            setFrameIndex(Number(event.target.value))
          }}
          aria-label="板块状态时间"
        />
        <div>
          {frames.map(({ frame }, index) => (
            <button
              key={frame.snapshotId}
              type="button"
              className={index === frameIndex ? 'is-active' : ''}
              onClick={() => {
                setPlaying(false)
                setFrameIndex(index)
              }}
            >
              {frame.label}
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}
