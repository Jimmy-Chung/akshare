import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type {
  AiAssistantResponse,
  AiProviderCatalog,
  AiProviderDefinition,
} from '../types/market'
import { formatError, requestJson } from '../utils/api'

const FALLBACK_PROVIDER: AiProviderDefinition = {
  id: 'deepseek',
  name: 'DeepSeek',
  apiBase: '',
  model: 'deepseek-v4-pro',
  configured: false,
  editableEndpoint: false,
}

type QuickAction = {
  label: string
  command: string
  session?: 'morning' | 'midday' | 'close' | 'us-night'
}

type AssistantStreamEvent = {
  type: 'status' | 'delta' | 'done' | 'error'
  message?: string
  content?: string
  error?: string
  response?: AiAssistantResponse
}

const QUICK_ACTIONS: QuickAction[] = [
  { label: '早报', command: '请生成早报', session: 'morning' },
  { label: '午报', command: '请生成午报', session: 'midday' },
  { label: '收盘报', command: '请生成收盘报', session: 'close' },
  { label: '夜报', command: '请生成夜报', session: 'us-night' },
]

export default function AiMarketAssistant() {
  const [provider, setProvider] = useState(FALLBACK_PROVIDER)
  const [model, setModel] = useState(FALLBACK_PROVIDER.model)
  const [message, setMessage] = useState('')
  const [lastPrompt, setLastPrompt] = useState('')
  const [result, setResult] = useState<AiAssistantResponse | null>(null)
  const [streamedContent, setStreamedContent] = useState('')
  const [streamStatus, setStreamStatus] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [configurationOpen, setConfigurationOpen] = useState(false)

  useEffect(() => {
    requestJson<AiProviderCatalog>('/api/assistant/providers')
      .then((payload) => {
        const selected = payload.providers.find((item) => item.id === 'deepseek') || FALLBACK_PROVIDER
        setProvider(selected)
        setModel(selected.model)
      })
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!configurationOpen) return undefined
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setConfigurationOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [configurationOpen])

  const submit = async (quickAction?: QuickAction) => {
    const prompt = quickAction?.command || message.trim()
    if (!prompt) {
      setError('请输入报告要求，或选择一个快捷动作')
      return
    }
    setLastPrompt(quickAction?.label || prompt)
    setResult(null)
    setStreamedContent('')
    setStreamStatus('正在连接 AI 助手…')
    setLoading(true)
    setError(null)
    try {
      const response = await fetch('/api/assistant/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({
          message: prompt,
          model,
          session: quickAction?.session,
          quickAction: Boolean(quickAction),
          stream: true,
        }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null) as { error?: string } | null
        throw new Error(payload?.error || `请求失败 ${response.status}`)
      }
      if (!response.body) {
        throw new Error('浏览器不支持流式响应')
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let completed = false
      const handleEvent = (event: AssistantStreamEvent) => {
        if (event.type === 'status') {
          setStreamStatus(event.message || '正在处理…')
        } else if (event.type === 'delta' && event.content) {
          setStreamedContent((previous) => previous + event.content)
        } else if (event.type === 'done' && event.response) {
          completed = true
          setResult(event.response)
          setStreamedContent('')
          setStreamStatus('')
          setMessage('')
        } else if (event.type === 'error') {
          throw new Error(event.error || '流式生成失败')
        }
      }
      while (true) {
        const { done, value } = await reader.read()
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
        let boundary = buffer.indexOf('\n\n')
        while (boundary >= 0) {
          const packet = buffer.slice(0, boundary)
          buffer = buffer.slice(boundary + 2)
          const data = packet
            .split('\n')
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.slice(5).trim())
            .join('\n')
          if (data) {
            handleEvent(JSON.parse(data) as AssistantStreamEvent)
          }
          boundary = buffer.indexOf('\n\n')
        }
        if (done) break
      }
      if (!completed) {
        throw new Error('流式响应意外结束，请重试')
      }
    } catch (err) {
      setError(formatError(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <section className="surface-card ai-chat-shell">
        <header className="ai-chat-header">
          <div className="ai-chat-identity">
            <span className="ai-chat-avatar">AI</span>
            <div>
              <h2>AI 助手</h2>
              <small>DeepSeek · {model || '未配置模型'}</small>
            </div>
          </div>
          <button
            type="button"
            className="ghost-button ai-config-trigger"
            onClick={() => setConfigurationOpen(true)}
          >
            配置
          </button>
        </header>

        <div className="ai-chat-messages" aria-live="polite">
          {!lastPrompt ? (
            <div className="ai-message ai-message--assistant">
              快捷动作读取当天对应时段报告。也可以用自然语言查询历史报告、指数周线、板块轨迹，或一只股票所属的一、二级行业。
            </div>
          ) : (
            <div className="ai-message ai-message--user">{lastPrompt}</div>
          )}

          {loading && streamStatus ? (
            <div className="ai-message ai-message--assistant ai-message--status">{streamStatus}</div>
          ) : null}

          {error ? (
            <div className="ai-message ai-message--error" role="alert">{error}</div>
          ) : null}

          {result ? (
            <div className="ai-message ai-message--assistant ai-message--report">
              <div className="assistant-result__meta">
                <span>{result.label}</span>
                <span>{result.provider} · {result.model}</span>
                <span>{result.dataPeriods.join('、')}</span>
              </div>
              <div className="assistant-markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.content}</ReactMarkdown>
              </div>
            </div>
          ) : null}

          {loading && streamedContent ? (
            <div className="ai-message ai-message--assistant ai-message--report">
              <div className="assistant-result__meta"><span>正在输出</span></div>
              <div className="assistant-markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamedContent}</ReactMarkdown>
                <span className="assistant-stream-caret" aria-label="正在生成" />
              </div>
            </div>
          ) : null}
        </div>

        <div className="ai-chat-composer">
          <div className="ai-assistant__quick-actions" aria-label="快捷报告">
            {QUICK_ACTIONS.map((action) => (
              <button
                type="button"
                className="ai-quick-chip"
                key={action.label}
                onClick={() => submit(action)}
                disabled={loading}
              >
                {action.label}
              </button>
            ))}
          </div>
          <div className="ai-compose">
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={(event) => {
                const isDesktop = window.matchMedia('(min-width: 769px)').matches
                if (
                  isDesktop
                  && event.key === 'Enter'
                  && !event.shiftKey
                  && !event.nativeEvent.isComposing
                  && !loading
                ) {
                  event.preventDefault()
                  submit()
                }
              }}
              placeholder="例如：贵州茅台属于哪个一、二级行业？"
              rows={2}
            />
            <button type="button" className="primary-button" onClick={() => submit()} disabled={loading}>
              {loading ? '生成中' : '发送'}
            </button>
          </div>
        </div>
      </section>

      {configurationOpen ? (
        <div className="ai-config-backdrop" role="presentation">
          <section className="ai-config-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-config-title">
            <header>
              <div>
                <h2 id="ai-config-title">AI 助手配置</h2>
                <p>{provider.configured ? '本机 API Key 已配置' : '请在服务器命令行配置 API Key'}</p>
              </div>
              <button type="button" className="ghost-button" onClick={() => setConfigurationOpen(false)}>
                关闭
              </button>
            </header>
            <div className="ai-provider-grid">
              <label>
                <span>模型</span>
                <input
                  type="text"
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  placeholder="模型名称"
                />
              </label>
            </div>
            <footer>
              <button type="button" className="primary-button" onClick={() => setConfigurationOpen(false)}>
                完成
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  )
}
