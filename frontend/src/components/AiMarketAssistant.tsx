import { useEffect, useMemo, useState } from 'react'
import type {
  AiAssistantResponse,
  AiProviderCatalog,
  AiProviderDefinition,
} from '../types/market'
import { formatError, requestJson } from '../utils/api'

const FALLBACK_PROVIDERS: AiProviderDefinition[] = [
  {
    id: 'deepseek',
    name: 'DeepSeek',
    apiBase: 'https://api.deepseek.com',
    model: 'deepseek-chat',
    configured: false,
    editableEndpoint: true,
  },
  {
    id: 'openai',
    name: 'OpenAI',
    apiBase: 'https://api.openai.com/v1',
    model: 'gpt-4.1-mini',
    configured: false,
    editableEndpoint: true,
  },
  {
    id: 'custom',
    name: 'OpenAI-compatible',
    apiBase: '',
    model: '',
    configured: false,
    editableEndpoint: true,
  },
]

type QuickAction = {
  label: string
  command: string
  session?: 'morning' | 'midday' | 'close' | 'us-night'
}

const QUICK_ACTIONS: QuickAction[] = [
  { label: '早报', command: '请生成早报', session: 'morning' },
  { label: '午报', command: '请生成午报', session: 'midday' },
  { label: '收盘报', command: '请生成收盘报', session: 'close' },
  { label: '夜报', command: '请生成夜报', session: 'us-night' },
  { label: '日报', command: '请生成日报' },
  { label: '周报', command: '请生成周报' },
]

export default function AiMarketAssistant() {
  const [providers, setProviders] = useState(FALLBACK_PROVIDERS)
  const [providerId, setProviderId] = useState('deepseek')
  const [apiBase, setApiBase] = useState(FALLBACK_PROVIDERS[0].apiBase)
  const [model, setModel] = useState(FALLBACK_PROVIDERS[0].model)
  const [apiKey, setApiKey] = useState('')
  const [message, setMessage] = useState('日报')
  const [result, setResult] = useState<AiAssistantResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    requestJson<AiProviderCatalog>('/api/assistant/providers')
      .then((payload) => {
        const available = payload.providers.length ? payload.providers : FALLBACK_PROVIDERS
        const selected = available.find((item) => item.id === payload.defaultProvider) || available[0]
        setProviders(available)
        setProviderId(selected.id)
        setApiBase(selected.apiBase)
        setModel(selected.model)
      })
      .catch(() => undefined)
  }, [])

  const selectedProvider = useMemo(
    () => providers.find((item) => item.id === providerId) || providers[0],
    [providerId, providers],
  )

  const changeProvider = (nextId: string) => {
    const next = providers.find((item) => item.id === nextId)
    setProviderId(nextId)
    setApiBase(next?.apiBase || '')
    setModel(next?.model || '')
    setApiKey('')
    setError(null)
  }

  const submit = async (quickAction?: QuickAction) => {
    const prompt = quickAction?.command || message.trim()
    if (!prompt) {
      setError('请输入“日报”、“周报”或具体报告要求')
      return
    }
    if (quickAction) setMessage(quickAction.command)
    setLoading(true)
    setError(null)
    try {
      const payload = await requestJson<AiAssistantResponse>('/api/assistant/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: prompt,
          providerId,
          apiBase,
          model,
          apiKey,
          session: quickAction?.session,
        }),
      })
      setResult(payload)
    } catch (err) {
      setError(formatError(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="surface-card ai-assistant">
      <div className="section-heading ai-assistant__heading">
        <div>
          <span className="section-kicker">AI Market Assistant</span>
          <h2>AI 市场助手</h2>
          <p>读取四时段固化指数数据包，通过可配置模型生成固定格式报告。</p>
        </div>
      </div>

      <details className="ai-provider-config" open>
        <summary>
          <span>Provider 配置</span>
          <small>{selectedProvider?.configured ? '服务端已配置 API Key' : 'API Key 仅用于本次请求'}</small>
        </summary>
        <div className="ai-provider-grid">
          <label>
            <span>Provider</span>
            <select value={providerId} onChange={(event) => changeProvider(event.target.value)}>
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>{provider.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span>API 地址</span>
            <input
              type="url"
              value={apiBase}
              onChange={(event) => setApiBase(event.target.value)}
              placeholder="https://api.example.com/v1"
            />
          </label>
          <label>
            <span>模型</span>
            <input
              type="text"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              placeholder="模型名称"
            />
          </label>
          <label>
            <span>API Key</span>
            <input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={selectedProvider?.configured ? '已由服务端配置，可留空' : '仅保留在当前页面内存中'}
              autoComplete="off"
            />
          </label>
        </div>
      </details>

      <div className="ai-quick-action-bar">
        <div>
          <strong>快捷动作</strong>
          <small>直接读取对应时段已经固化的数据包并发送</small>
        </div>
        <div className="ai-assistant__quick-actions" aria-label="快捷报告">
          {QUICK_ACTIONS.map((action) => (
            <button
              type="button"
              className="ghost-button"
              key={action.label}
              onClick={() => submit(action)}
              disabled={loading}
            >
              {action.label}
            </button>
          ))}
        </div>
      </div>

      <div className="ai-compose">
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="输入“早报”、“午报”、“收盘报”、“夜报”、“日报”或“周报”"
          rows={3}
        />
        <button type="button" className="primary-button" onClick={() => submit()} disabled={loading}>
          {loading ? '正在读取快照并生成' : '发送'}
        </button>
      </div>

      {error ? <div className="assistant-error" role="alert">{error}</div> : null}
      {result ? (
        <div className="assistant-result" aria-live="polite">
          <div className="assistant-result__meta">
            <span>{result.label}</span>
            <span>{result.provider} · {result.model}</span>
            <span>数据日期 {result.dataPeriods.join('、')}</span>
          </div>
          <pre>{result.content}</pre>
        </div>
      ) : (
        <div className="assistant-placeholder">
          点击快捷动作后，助手会读取对应时段已经固化的指数数据包，再按预设结构生成报告。
        </div>
      )}
    </section>
  )
}
