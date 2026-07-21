export type SessionKey = 'morning' | 'midday' | 'close' | 'us-night'

export interface ChartPoint {
  time: string
  value: number
}

export interface IndexSnapshot {
  name: string
  code: string
  price: number
  changePercent: number
  changeAmount: number
  open?: number | null
  high?: number | null
  low?: number | null
  previousClose?: number | null
  volume?: number | null
  turnover?: number | null
  marketValue?: number | null
  intradayData?: ChartPoint[]
  tradeDate?: string
  tradeTime?: string
  source?: string
  isFallback?: boolean
}

export interface WeightStockEntry extends IndexSnapshot {}

export interface SectorHeatmapEntry {
  name: string
  code: string
  changePercent: number
  netInflow?: number | null
  marketValue?: number | null
  eventCount?: number | null
  upCount?: number | null
  downCount?: number | null
  totalTurnover?: number | null
  topStocks?: WeightStockEntry[]
  source?: string
}

export interface MarketBreadth {
  upCount: number
  downCount: number
  flatCount: number
  limitUp: number
  limitDown: number
  totalStocks: number
  winRate: number
  updateTime?: string
}

export interface NewsArticle {
  id: string
  title: string
  source: string
  publishedAt: string
  url: string
  marketTags: string[]
  summary: string
  isFallback?: boolean
}

export interface SessionCommentary {
  session: SessionKey
  title: string
  generatedAt: string
  overview: string
  highlights: string[]
  newsSummary: string[]
}

export interface MarketIndexGroup {
  key: string
  title: string
  subtitle: string
  indices: IndexSnapshot[]
}

export interface GlobalMarketGroup extends MarketIndexGroup {}

export interface DashboardOverview {
  globalIndices: IndexSnapshot[]
  globalMarketGroups: GlobalMarketGroup[]
  majorIndices: {
    aShares: IndexSnapshot[]
    hk: IndexSnapshot[]
    us: IndexSnapshot[]
  }
  aShareSectors: {
    breadth: MarketBreadth
    heatmap: SectorHeatmapEntry[]
    leaders: SectorHeatmapEntry[]
    laggards: SectorHeatmapEntry[]
  }
  latestCommentary?: SessionCommentary
  newsDigest: NewsArticle[]
  updatedAt: string
  sources?: Record<string, string>
  sourceSummary?: {
    global: SourceSummary
    majorIndices: SourceSummary
  }
  sourceStatus?: {
    longbridge?: {
      provider: string
      sdkAvailable: boolean
      configured: boolean
      missingKeys: string[]
      quoteContextReady: boolean
      usingLiveSource: boolean
    }
  }
}

export interface SourceSummary {
  total: number
  longbridge: number
  fallback: number
}

export interface AiProviderDefinition {
  id: string
  name: string
  apiBase: string
  model: string
  configured: boolean
  editableEndpoint: boolean
}

export interface AiProviderCatalog {
  defaultProvider: string
  providers: AiProviderDefinition[]
}

export interface AiAssistantResponse {
  content: string
  responseType?: 'query'
  reportType: 'daily' | 'weekly' | 'query'
  session: SessionKey | 'weekly' | 'query'
  label: string
  provider: string
  model: string
  generatedAt: string
  dataPeriods: string[]
  targetDate?: string
  period?: {
    startDate: string
    endDate: string
    anchorDate: string
    timezone: string
    isCurrentWeek: boolean
  }
  coverage?: {
    requestedIndexCount: number
    availableIndexCount: number
    unavailableIndexCount: number
    sourceCounts: Record<string, number>
    unavailableIndices: Array<{
      name: string
      code: string
      scope: string
      reason: string
    }>
    complete: boolean
  }
  query?: Record<string, unknown>
  result?: Record<string, unknown>
}

export interface SessionReport {
  schemaVersion: number
  session: SessionKey
  snapshotId: string
  label: string
  scheduledAt: string
  date: string
  generatedAt: string
  captureMode?: 'historical-minute-recovery'
  dataAsOf?: string
  recoveryNote?: string
  markets: Array<'CN' | 'HK' | 'US'>
  marketLabels: string[]
  globalOverview: GlobalMarketGroup[]
  majorMarkets: Array<{
    market: 'CN' | 'HK' | 'US'
    title: string
    subtitle: string
    indices: IndexSnapshot[]
  }>
  sectorRankings: SectorRankingGroup[]
  chartExports: ChartExportTarget[]
  sources: {
    globalIndices: string
    majorIndices: string
    sectorRankings: string
  }
}

export interface ChartExportTarget {
  id: string
  kind: 'trend' | 'heatmap'
  title: string
  pageUrl: string
  chartId: string
  exportButtonId: string
  captureSelector: string
  filename: string
  market: 'CN' | 'HK' | 'US'
  contentRequirements: string[]
  renderMode: 'index-summary-card' | 'full-market-hierarchy'
  minimumImageWidth: number
  minimumImageHeight: number
  groupKey?: string
  indexCode?: string
  sourceSnapshotId?: string
  artifactPath?: string
  artifactWidth?: number
  artifactHeight?: number
}

export interface SectorRankingItem {
  name: string
  code: string
  parentName?: string
  changePercent: number
  marketValue: number
  source: string
  dayLeader?: {
    name: string
    code: string
    price?: number | null
    changePercent: number
  }
}

export interface HeatmapSnapshotIndustry {
  name: string
  code: string
  parentName: string
  changePercent: number
  marketValue: number
  turnover?: number | null
}

export interface HeatmapSnapshotGroup {
  name: string
  code: string
  changePercent: number
  marketValue: number
  turnover?: number | null
  industries: HeatmapSnapshotIndustry[]
}

export interface HeatmapSnapshot {
  schemaVersion: number
  snapshotId: string
  market: 'CN' | 'HK' | 'US'
  scheduledAt?: string
  capturedAt?: string
  updatedAt?: string
  groups?: HeatmapSnapshotGroup[]
  industries: HeatmapSnapshotIndustry[]
  turnoverCoverage?: {
    industryCount: number
    totalIndustryCount: number
    selection: string
  }
}

export interface HeatmapSnapshotHistoryItem {
  snapshotId: string
  label: string
  scheduledAt?: string
  capturedAt?: string
  trigger: 'scheduled' | 'session-close'
}

export interface HeatmapSnapshotHistoryResponse {
  market: 'CN' | 'HK' | 'US'
  date: string
  snapshotCount: number
  snapshots: HeatmapSnapshotHistoryItem[]
}

export interface HeatmapSnapshotDatesResponse {
  market: 'CN' | 'HK' | 'US'
  timezone: string
  timezoneLabel: string
  latestDate: string
  dates: Array<{
    date: string
    snapshotCount: number
  }>
}

export interface SectorRankingPair {
  leaders: SectorRankingItem[]
  laggards: SectorRankingItem[]
}

export interface SectorRankingGroup {
  market: 'CN' | 'HK' | 'US'
  title: string
  source: string
  primary: SectorRankingPair
  secondary: SectorRankingPair
}
