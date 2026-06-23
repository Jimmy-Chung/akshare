import { useEffect, useMemo, useRef, useState } from 'react'
import { TreemapChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import type { EChartsOption } from 'echarts'
import { CanvasRenderer } from 'echarts/renderers'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import {
  downloadCanvasImage,
  exportChartElement,
} from '../utils/chartExport'
import {
  formatChineseAmount,
  formatDashboardTime,
  formatPercent,
  formatPrice,
  getTrendClass,
} from '../utils/market'
import { formatError, requestJson } from '../utils/api'
import { EmptyState, InlineError, SkeletonBlocks } from './StateBlocks'

echarts.use([TreemapChart, TooltipComponent, CanvasRenderer])

type MarketKey = 'CN' | 'HK' | 'US'
type SizeMode = 'marketValue' | 'changePercent'

interface DayLeader {
  name: string
  code: string
  price?: number | null
  changePercent: number
}

interface IndustryItem {
  name: string
  code: string
  parentName: string
  changePercent: number
  marketValue: number
  delayed: boolean
  dayLeader: DayLeader
}

interface IndustryGroup {
  name: string
  code: string
  changePercent: number
  marketValue: number
  industries: IndustryItem[]
}

interface StockItem {
  name: string
  code: string
  price: number
  changePercent: number
  changeAmount: number
  marketValue?: number | null
  tradeDate: string
}

interface IndustryDetail extends IndustryItem {
  stocks: StockItem[]
  constituentCount: number
}

interface SectorHeatmapSummary {
  market: MarketKey
  source: string
  updatedAt: string
  groups: IndustryGroup[]
  industries: IndustryItem[]
}

interface IndustryDetailResponse {
  market: MarketKey
  source: string
  updatedAt: string
  industry: IndustryDetail
}

interface LongbridgeSectorHeatmapProps {
  market?: MarketKey
  showMarketTabs?: boolean
  exportFilenamePrefix?: string
  reportMode?: boolean
  generatedAt?: string
}

const MARKET_TABS: Array<{ key: MarketKey; label: string }> = [
  { key: 'CN', label: 'A 股' },
  { key: 'HK', label: '港股' },
  { key: 'US', label: '美股' },
]

const SIZE_MODES: Array<{ key: SizeMode; label: string }> = [
  { key: 'marketValue', label: '市值' },
  { key: 'changePercent', label: '板块涨幅' },
]

function heatColor(changePercent: number) {
  const intensity = Math.min(Math.abs(changePercent) / 8, 1)
  if (changePercent > 0) return `rgba(210, 52, 52, ${0.5 + intensity * 0.45})`
  if (changePercent < 0) return `rgba(22, 135, 66, ${0.5 + intensity * 0.45})`
  return '#64748b'
}

function heatmapSize(
  marketValue: number | null | undefined,
  changePercent: number,
  mode: SizeMode,
  fullReport = false,
) {
  if (mode === 'changePercent') {
    return Math.max(Math.abs(changePercent), fullReport ? 0.8 : 0.05)
  }
  return marketValue && marketValue > 0 ? marketValue : 1
}

export default function LongbridgeSectorHeatmap({
  market: controlledMarket,
  showMarketTabs = true,
  exportFilenamePrefix = '',
  reportMode = false,
  generatedAt,
}: LongbridgeSectorHeatmapProps) {
  const [internalMarket, setInternalMarket] = useState<MarketKey>('CN')
  const market = controlledMarket ?? internalMarket
  const [summary, setSummary] = useState<SectorHeatmapSummary | null>(null)
  const [detailCache, setDetailCache] = useState<Record<string, IndustryDetail>>({})
  const [drillIndustryCode, setDrillIndustryCode] = useState('')
  const [selectedStockCode, setSelectedStockCode] = useState('')
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')
  const [sizeMode, setSizeMode] = useState<SizeMode>(
    reportMode ? 'changePercent' : 'marketValue',
  )
  const requestSequence = useRef(0)
  const chartRef = useRef<ReactEChartsCore | null>(null)

  const loadSummary = async (target: MarketKey) => {
    const requestId = ++requestSequence.current
    setLoading(true)
    setError('')
    setDrillIndustryCode('')
    setSelectedStockCode('')
    try {
      const payload = await requestJson<SectorHeatmapSummary>(
        `/api/sector-heatmap?market=${target}&summary=1`,
      )
      if (requestId !== requestSequence.current) return
      setSummary(payload)
    } catch (nextError) {
      if (requestId !== requestSequence.current) return
      setError(formatError(nextError))
    } finally {
      if (requestId === requestSequence.current) setLoading(false)
    }
  }

  const loadIndustry = async (industry: IndustryItem) => {
    setDrillIndustryCode(industry.code)
    const cached = detailCache[`${market}:${industry.code}`]
    if (cached) {
      setSelectedStockCode(cached.stocks[0]?.code ?? '')
      return
    }
    setDetailLoading(true)
    setError('')
    try {
      const query = new URLSearchParams({ market, industry: industry.code })
      const payload = await requestJson<IndustryDetailResponse>(
        `/api/sector-heatmap/industry?${query}`,
      )
      setDetailCache((current) => ({
        ...current,
        [`${market}:${industry.code}`]: payload.industry,
      }))
      setSelectedStockCode(payload.industry.stocks[0]?.code ?? '')
    } catch (nextError) {
      setDrillIndustryCode('')
      setError(formatError(nextError))
    } finally {
      setDetailLoading(false)
    }
  }

  useEffect(() => {
    loadSummary(market)
  }, [market])

  const industryDetail = drillIndustryCode
    ? detailCache[`${market}:${drillIndustryCode}`]
    : undefined
  const selectedStock = industryDetail?.stocks.find((item) => item.code === selectedStockCode)
    ?? industryDetail?.stocks[0]
  const marketLabel = MARKET_TABS.find((item) => item.key === market)?.label ?? market

  const chartOption = useMemo<EChartsOption>(() => {
    const isDrilled = Boolean(industryDetail)
    return {
      backgroundColor: 'transparent',
      tooltip: {
        formatter: (params: any) => {
          const raw = params.data?.raw as
            | { kind: 'group'; item: IndustryGroup }
            | { kind: 'industry'; item: IndustryItem }
            | { kind: 'stock'; item: StockItem }
            | undefined
          if (!raw) return params.name
          if (raw.kind === 'group') {
            return `${raw.item.name}<br/>行业数：${raw.item.industries.length}<br/>综合涨跌：${formatPercent(raw.item.changePercent)}<br/>面积依据：${sizeMode === 'marketValue' ? '行业市值' : '涨跌幅绝对值'}`
          }
          if (raw.kind === 'industry') {
            return `${raw.item.parentName} / ${raw.item.name}<br/>板块涨跌：${formatPercent(raw.item.changePercent)}<br/>行业市值：${formatChineseAmount(raw.item.marketValue)}<br/>面积依据：${sizeMode === 'marketValue' ? '行业市值' : '涨跌幅绝对值'}<br/>点击查看成分股`
          }
          return `${industryDetail?.parentName} / ${industryDetail?.name}<br/>${raw.item.name}（${raw.item.code}）<br/>现价：${formatPrice(raw.item.price)}<br/>涨跌：${formatPercent(raw.item.changePercent)}<br/>市值：${raw.item.marketValue ? formatChineseAmount(raw.item.marketValue) : '--'}`
        },
      },
      series: [{
        type: 'treemap',
        roam: false,
        nodeClick: reportMode || isDrilled ? false : 'zoomToNode',
        breadcrumb: {
          show: !reportMode && !isDrilled,
          bottom: 4,
          height: 24,
        },
        width: '100%',
        height: reportMode || isDrilled ? '100%' : '95%',
        top: 0,
        left: 0,
        label: {
          show: true,
          color: '#fff',
          formatter: (params: any) => {
            const raw = params.data?.raw as
              | { kind: 'industry'; item: IndustryItem }
              | { kind: 'stock'; item: StockItem }
              | undefined
            if (!raw) return params.name
            return `${raw.item.name}\n${formatPercent(raw.item.changePercent)}`
          },
          overflow: 'truncate',
          fontSize: reportMode ? 16 : 12,
          fontWeight: reportMode ? 600 : 400,
          lineHeight: reportMode ? 23 : 18,
        },
        upperLabel: {
          show: true,
          height: reportMode ? 48 : 38,
          color: '#334155',
          fontWeight: 700,
          fontSize: reportMode ? 20 : 12,
          formatter: (params: any) => {
            const raw = params.data?.raw as { kind: 'group'; item: IndustryGroup } | undefined
            if (!raw || raw.kind !== 'group') return params.name
            return `${raw.item.name}  ${formatPercent(raw.item.changePercent)}`
          },
        },
        itemStyle: {
          borderColor: '#fff',
          borderWidth: 2,
          gapWidth: 2,
        },
        levels: [
          {
            itemStyle: { borderColor: '#cbd5e1', borderWidth: 4, gapWidth: 4 },
            upperLabel: { show: true, height: reportMode ? 48 : 30 },
          },
          {
            itemStyle: { borderColor: '#e2e8f0', borderWidth: 3, gapWidth: 3 },
            upperLabel: { show: true, height: reportMode ? 42 : 27 },
          },
          {
            itemStyle: { borderColor: '#fff', borderWidth: 1, gapWidth: 1 },
          },
        ],
        data: industryDetail
          ? [{
              name: industryDetail.name,
              value: industryDetail.stocks.reduce(
                (sum, stock) => sum + heatmapSize(stock.marketValue, stock.changePercent, sizeMode),
                0,
              ),
              children: industryDetail.stocks.map((stock) => ({
                name: stock.name,
                value: heatmapSize(stock.marketValue, stock.changePercent, sizeMode),
                itemStyle: { color: heatColor(stock.changePercent) },
                raw: { kind: 'stock', item: stock },
              })),
            }]
          : (summary?.groups ?? []).map((group) => ({
              name: group.name,
              value: group.industries.reduce(
                (sum, industry) => sum + heatmapSize(industry.marketValue, industry.changePercent, sizeMode),
                0,
              ),
              raw: { kind: 'group', item: group },
              children: group.industries.map((industry) => ({
                name: industry.name,
                value: heatmapSize(
                  industry.marketValue,
                  industry.changePercent,
                  sizeMode,
                  reportMode,
                ),
                itemStyle: { color: heatColor(industry.changePercent) },
                raw: { kind: 'industry', item: industry },
              })),
            })),
      }],
    }
  }, [summary, industryDetail, sizeMode, reportMode])

  const chartId = `heatmap-${market.toLowerCase()}`
  const exportFilename = `${exportFilenamePrefix ? `${exportFilenamePrefix}-` : ''}${chartId}.png`
  const exportReportHeatmap = () => {
    const instance = chartRef.current?.getEchartsInstance()
    const sourceCanvas = instance?.getDom().querySelector('canvas')
    if (!sourceCanvas || !summary) return

    const width = 1440
    const headerHeight = 142
    const chartHeight = 980
    const footerHeight = 64
    const pixelRatio = 1
    const canvas = document.createElement('canvas')
    canvas.width = width * pixelRatio
    canvas.height = (headerHeight + chartHeight + footerHeight) * pixelRatio
    const context = canvas.getContext('2d')
    if (!context) return

    context.scale(pixelRatio, pixelRatio)
    context.fillStyle = '#ffffff'
    context.fillRect(0, 0, width, headerHeight + chartHeight + footerHeight)
    context.fillStyle = '#64748b'
    context.font = '24px sans-serif'
    context.fillText(`${marketLabel}市场`, 28, 36)
    context.fillStyle = '#111827'
    context.font = '700 34px sans-serif'
    context.fillText(`${marketLabel}全量一级分类与二级行业热力图`, 28, 82)
    context.fillStyle = '#64748b'
    context.font = '20px sans-serif'
    context.fillText(
      '全量可读模式 · 面积按涨跌幅绝对值并设置最小可视面积 · 颜色表示涨跌方向',
      28,
      116,
    )

    const legends = [
      { label: '下跌', color: '#16a34a' },
      { label: '持平', color: '#94a3b8' },
      { label: '上涨', color: '#e5484d' },
    ]
    legends.forEach((item, index) => {
      const x = 1138 + index * 92
      context.fillStyle = item.color
      context.fillRect(x, 26, 18, 18)
      context.fillStyle = '#475569'
      context.font = '18px sans-serif'
      context.fillText(item.label, x + 26, 42)
    })

    context.drawImage(sourceCanvas, 14, headerHeight, width - 28, chartHeight)
    context.fillStyle = '#64748b'
    context.font = '18px sans-serif'
    context.fillText(
      `共 ${summary.groups.length} 个一级分类 · ${summary.industries.length} 个二级行业`,
      28,
      headerHeight + chartHeight + 40,
    )
    context.textAlign = 'right'
    context.fillText(
      `更新于 ${formatDashboardTime(generatedAt || summary.updatedAt)}`,
      width - 28,
      headerHeight + chartHeight + 40,
    )
    context.textAlign = 'left'
    downloadCanvasImage(canvas, exportFilename)
  }
  const exportChart = () => (
    reportMode
      ? exportReportHeatmap()
      : exportChartElement(chartId, exportFilename)
  )

  return (
    <section className={reportMode ? 'report-heatmap-section' : 'surface-card'}>
      <div className="section-heading">
        <div>
          <span className="section-kicker">
            {reportMode ? 'Report Sector Heatmap' : 'Longbridge Sector Map'}
          </span>
          <h2>{marketLabel}板块热力图</h2>
          <p>
            {sizeMode === 'marketValue'
              ? '面积按市值，颜色按涨跌幅；点击分类逐级放大。'
              : '面积按涨跌幅绝对值，颜色表示涨跌方向；点击分类逐级放大。'}
          </p>
        </div>
        <div className="lb-heatmap-controls">
          <button
            type="button"
            className="chart-export-button chart-export-button--inline"
            data-export-chart-id={chartId}
            data-export-filename={exportFilename}
            aria-label={`导出图表 ${chartId}`}
            onClick={() => void exportChart()}
            disabled={loading || !summary?.groups.length}
          >
            导出 PNG
          </button>
          {!reportMode ? (
          <div className="session-switcher heatmap-mode-switcher" aria-label="面积模式">
            {SIZE_MODES.map((mode) => (
              <button
                key={mode.key}
                type="button"
                className={sizeMode === mode.key ? 'session-tab is-active' : 'session-tab'}
                onClick={() => setSizeMode(mode.key)}
              >
                {mode.label}
              </button>
            ))}
          </div>
          ) : null}
          {showMarketTabs ? (
            <div className="session-switcher" aria-label="板块市场">
              {MARKET_TABS.map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  className={market === tab.key ? 'session-tab is-active' : 'session-tab'}
                  onClick={() => setInternalMarket(tab.key)}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      {loading ? (
        <SkeletonBlocks blocks={2} height={420} />
      ) : error && !summary ? (
        <InlineError message={error} onRetry={() => loadSummary(market)} />
      ) : !summary?.groups.length ? (
        <EmptyState title="暂无板块分类数据" description="Longbridge 行业排行当前未返回可用数据。" />
      ) : (
        <>
          {industryDetail ? (
            <div className="lb-heatmap-breadcrumb">
              <button type="button" onClick={() => setDrillIndustryCode('')}>全部分类</button>
              <span>/</span>
              <span>{industryDetail.parentName}</span>
              <span>/</span>
              <strong>{industryDetail.name}</strong>
            </div>
          ) : null}

          {error ? <InlineError message={error} onRetry={() => loadSummary(market)} /> : null}

          <div className={reportMode ? 'lb-sector-layout lb-sector-layout--report' : 'lb-sector-layout'}>
            <div className={reportMode ? 'report-heatmap-export-stage' : undefined}>
            <div
              className={reportMode
                ? 'report-chart-card report-heatmap-chart-card report-heatmap-chart-card--full'
                : 'lb-treemap lb-treemap--hierarchy'}
              data-chart-id={reportMode ? chartId : undefined}
            >
              {reportMode ? (
                <div className="report-chart-card__header">
                  <div>
                    <span>{marketLabel}市场</span>
                    <h3>{marketLabel}全量一级分类与二级行业热力图</h3>
                    <small>
                      全量可读模式 · 面积按涨跌幅绝对值并设置最小可视面积 · 颜色表示涨跌方向
                    </small>
                  </div>
                  <div className="report-heatmap-legend">
                    <span className="is-down">下跌</span>
                    <span className="is-flat">持平</span>
                    <span className="is-up">上涨</span>
                  </div>
                </div>
              ) : null}
              <div
                className={reportMode ? 'lb-treemap lb-treemap--report' : undefined}
                data-chart-id={reportMode ? undefined : chartId}
              >
              <ReactEChartsCore
                ref={chartRef}
                echarts={echarts}
                option={chartOption}
                style={{ height: reportMode ? 980 : 590, width: '100%' }}
                onEvents={{
                  click: (params: any) => {
                    const raw = params.data?.raw as
                      | { kind: 'industry'; item: IndustryItem }
                      | { kind: 'stock'; item: StockItem }
                      | undefined
                    if (raw?.kind === 'industry') loadIndustry(raw.item)
                    if (raw?.kind === 'stock') setSelectedStockCode(raw.item.code)
                  },
                }}
                notMerge
              />
              </div>
              {reportMode ? (
                <div className="report-chart-card__footer">
                  <span>一级分类标题包含综合涨跌幅，色块为二级行业</span>
                  <span>
                    共 {summary.groups.length} 个一级分类 · {summary.industries.length} 个二级行业 ·
                    更新于 {formatDashboardTime(generatedAt || summary.updatedAt)}
                  </span>
                </div>
              ) : null}
              {detailLoading ? (
                <div className="lb-heatmap-loading">正在加载行业成分股…</div>
              ) : null}
            </div>
            </div>

            {!reportMode ? (
            <aside className="lb-sector-side lb-sector-side--compact">
              {industryDetail && selectedStock ? (
                <div className="side-panel">
                  <div className="panel-header">
                    <div>
                      <h3>{selectedStock.name}</h3>
                      <p>{selectedStock.code} · {industryDetail.name}</p>
                    </div>
                    <strong className={getTrendClass(selectedStock.changePercent)}>
                      {formatPercent(selectedStock.changePercent)}
                    </strong>
                  </div>
                  <div className="key-metrics">
                    <div>
                      <span>现价</span>
                      <strong>{formatPrice(selectedStock.price)}</strong>
                    </div>
                    <div>
                      <span>市值</span>
                      <strong>{selectedStock.marketValue ? formatChineseAmount(selectedStock.marketValue) : '--'}</strong>
                    </div>
                  </div>
                  <div className="lb-leading-stock">
                    <span>行业当日领涨</span>
                    <strong>{industryDetail.dayLeader.name || '--'}</strong>
                    <small>{industryDetail.dayLeader.code || '--'}</small>
                    <div>
                      <span>{industryDetail.dayLeader.price == null ? '--' : formatPrice(industryDetail.dayLeader.price)}</span>
                      <span className={getTrendClass(industryDetail.dayLeader.changePercent)}>
                        {formatPercent(industryDetail.dayLeader.changePercent)}
                      </span>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="side-panel">
                  <div className="panel-header">
                    <div>
                      <h3>分层浏览</h3>
                      <p>{summary.groups.length} 个一级分类 · {summary.industries.length} 个二级行业</p>
                    </div>
                  </div>
                  <div className="lb-heatmap-guide">
                    <span>1</span><p>点击一级分类，在热力图内放大查看二级行业。</p>
                    <span>2</span><p>点击二级行业，按需加载并展示真实成分股。</p>
                    <span>3</span><p>使用图内面包屑或顶部“全部分类”逐级返回。</p>
                  </div>
                </div>
              )}
            </aside>
            ) : null}
          </div>
        </>
      )}
    </section>
  )
}
