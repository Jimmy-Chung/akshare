import AiMarketAssistant from '../components/AiMarketAssistant'

const FLOW_STEPS = [
  ['选择报告', '通过早报、午报、收盘报、夜报、日报或周报快捷动作选择数据时段。'],
  ['读取快照', '只读取已经固化的指数数据包，不在点击时重新采集行情。'],
  ['组装 Prompt', '把固定报告格式、用户指令和结构化指数快照一起发送给 Provider。'],
  ['返回报告', '模型仅根据快照生成中文 Markdown，并标注数据日期、来源和缺口。'],
]

export default function AssistantPage() {
  return (
    <div className="page-layout assistant-page">
      <section className="page-hero assistant-page__hero">
        <div>
          <span className="page-hero__kicker">AI Report Workspace</span>
          <h2>AI 助手</h2>
          <p>配置模型 Provider，读取固定时点行情数据包并生成早、午、收盘、夜报或周报。</p>
        </div>
        <div className="source-pills">
          <span className="pill">数据 固化快照</span>
          <span className="pill">输出 Markdown</span>
          <span className="pill">热点图 已解耦</span>
        </div>
      </section>

      <section className="assistant-flow" aria-label="报告生成流程">
        {FLOW_STEPS.map(([title, description], index) => (
          <article className="assistant-flow__step" key={title}>
            <span>{index + 1}</span>
            <div>
              <strong>{title}</strong>
              <p>{description}</p>
            </div>
          </article>
        ))}
      </section>

      <AiMarketAssistant />
    </div>
  )
}
