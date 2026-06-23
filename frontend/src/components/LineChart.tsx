import { useEffect, useRef } from 'react'
import { ColorType, LineSeries, createChart, type Time } from 'lightweight-charts'
import type { ChartPoint } from '../types/market'
import { DOWN_COLOR, FLAT_COLOR, UP_COLOR } from '../utils/market'

interface LineChartProps {
  data: ChartPoint[]
  changePercent?: number
  height?: number
  showTimeScale?: boolean
  baseline?: number
}

function toChartTime(value: string, index: number): Time {
  const normalized = /^\d{2}:\d{2}/.test(value) ? `2026-01-01T${value}:00+08:00` : value
  const timestamp = Date.parse(normalized)
  if (!Number.isNaN(timestamp)) {
    return Math.floor(timestamp / 1000) as Time
  }
  return Math.floor((Date.now() + index * 60_000) / 1000) as Time
}

function lineColor(changePercent?: number) {
  if ((changePercent ?? 0) > 0) return UP_COLOR
  if ((changePercent ?? 0) < 0) return DOWN_COLOR
  return FLAT_COLOR
}

export default function LineChart({
  data,
  changePercent = 0,
  height = 140,
  showTimeScale = false,
  baseline,
}: LineChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!containerRef.current || data.length === 0) {
      return
    }

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#6b7280',
        attributionLogo: false,
      },
      rightPriceScale: {
        visible: false,
      },
      leftPriceScale: {
        visible: false,
      },
      timeScale: {
        visible: showTimeScale,
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 2,
        barSpacing: 4,
        tickMarkFormatter: (time: Time) => {
          const timestamp = typeof time === 'number' ? time : Date.parse(String(time)) / 1000
          if (!Number.isFinite(timestamp)) return ''
          return new Intl.DateTimeFormat('zh-CN', {
            timeZone: 'Asia/Shanghai',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
          }).format(new Date(timestamp * 1000))
        },
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: '#eef2f7' },
      },
      crosshair: {
        vertLine: { visible: false },
        horzLine: { visible: false },
      },
      handleScroll: false,
      handleScale: false,
    })
    const series = chart.addSeries(LineSeries, {
      color: lineColor(changePercent),
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    series.setData(
      data.map((item, index) => ({
        time: toChartTime(item.time, index),
        value: item.value,
      })),
    )

    if (Number.isFinite(baseline)) {
      series.createPriceLine({
        price: baseline as number,
        color: '#cbd5e1',
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: false,
        title: '',
      })
    }
    chart.timeScale().fitContent()

    const observer = new ResizeObserver(([entry]) => {
      chart.applyOptions({ width: entry.contentRect.width, height })
      chart.timeScale().fitContent()
    })

    observer.observe(containerRef.current)

    return () => {
      observer.disconnect()
      chart.remove()
    }
  }, [baseline, changePercent, data, height, showTimeScale])

  return <div ref={containerRef} className="line-chart" style={{ height }} />
}
