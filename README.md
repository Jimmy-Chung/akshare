# 全球市场行情看板

基于 Longbridge 主行情源、统一板块快照与可配置 AI Provider 的内部市场看板。

## 当前功能

- `看板` 页: 全球概览、A/HK/US 主要指数、板块状态轨迹与 AI 市场助手
- 四时段采集器: 固化早报、午报、收盘报和夜报指数数据包，不读取热点图
- AI 市场助手: 点击快捷动作或输入报告关键词，读取对应时段数据包并按固定 Markdown 模板输出
- Provider: 支持 DeepSeek、OpenAI 和其他 OpenAI-compatible 服务
- 行情主源: Longbridge
- 看板板块热力图: Longbridge 行业排行（A 股 / 港股 / 美股）
- 日报内容: 全球指数总览、时段主要市场指数、Longbridge 一级/二级行业涨跌幅前三
- 全球市场按美洲、欧洲、亚太、南亚分组；逐项优先 Longbridge，缺失项显示备用来源标记
- 图表: TradingView `lightweight-charts`

## 技术栈

- **前端**: React + TypeScript + Vite + `lightweight-charts`
- **数据服务**: Python + Flask + Longbridge OpenAPI + AKShare + 新浪 / Yahoo / Nasdaq fallback

## 项目结构

```
akshare/
├── frontend/                 # 前端项目
│   ├── src/
│   │   ├── components/       # React组件
│   │   ├── styles/           # CSS样式
│   │   ├── App.tsx           # 主应用
│   │   └── main.tsx          # 入口文件
│   ├── package.json
│   └ vite.config.ts
│
├── backend/
│   └── data_service/         # Python数据服务
│       ├── app.py            # Flask API服务
│       └ requirements.txt
│
├── start.sh                  # 启动脚本
└ 设计需求文档.md             # UI设计需求文档
```

## 凭证配置

复制 `.env.example` 为 `.env`，至少填入以下变量：

```bash
cp .env.example .env
```

```bash
LONGBRIDGE_APP_KEY=...
LONGBRIDGE_APP_SECRET=...
LONGBRIDGE_ACCESS_TOKEN=...
CODEX_REPORT_API_TOKEN=一个独立且足够长的随机字符串
AI_ASSISTANT_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-v4-pro
```

后端会优先读取仓库根目录 `.env`，也兼容旧变量名 `LONGPORT_*`。

首次开放外网访问前，先设置网页访问凭证：

```bash
./start.sh configure-access
```

命令会隐藏输入，将密码哈希写入本机 `.env`，不会保存或回显明文。外网访问必须先
输入该凭证，验证成功后默认保持登录 30 天；重新运行命令修改凭证会立即使旧登录失效。
本机 `127.0.0.1` 上的 watcher、报告采集器和健康检查不受影响。

不想手工编辑 `.env` 时，可以使用隐藏输入的本机配置命令：

```bash
./start.sh configure-deepseek
```

该命令只在本机 `.env` 中写入 DeepSeek Provider、API 地址和 API Key，不会回显
Key，并会在服务已运行时自动重启。模型名称继续由 AI 助手页面配置。

如果没有固定 API 凭证，应用入口会显示 Longbridge OAuth 授权页。云端部署至少配置：

```bash
PUBLIC_APP_URL=https://market.example.com
PUBLIC_API_URL=https://market.example.com
LONGBRIDGE_OAUTH_REDIRECT_URI=https://market.example.com/api/auth/longbridge/callback
FLASK_SECRET_KEY=一个稳定且足够长的随机字符串
SESSION_COOKIE_SECURE=true
```

`LONGBRIDGE_OAUTH_CLIENT_ID` 可预先填写；留空时，后端会在第一次授权时自动注册 OAuth 客户端。
OAuth Token 默认保存在 `~/.longbridge/openapi/tokens/<client_id>`。Docker 或无状态云服务部署时，
必须将 `~/.longbridge/openapi/tokens` 和 `backend/data_service/runtime_cache` 挂载到持久化存储。

## 启动方式

```bash
./start.sh start
```

## 访问地址

- 前端界面: http://localhost:3005
- 数据API: http://localhost:5001

`./start.sh` 统一管理前端、后端、CN/HK/US 三个板块快照 watcher 以及四时段报告采集器。

## 主要接口

| 接口 | 说明 |
|------|------|
| `/api/dashboard/overview` | Dashboard 聚合数据 |
| `/api/assistant/providers` | 可用 Provider 与默认配置（不返回密钥） |
| `/api/assistant/chat` | 基于统一市场快照生成日报或周报 |
| `/api/reports/latest` | 最新时段日报 |
| `/api/reports/history` | 历史日报 |
| `/api/reports/generate` | 手动重生成日报 |
| `/api/reports/schedule` | 四个日报时点及对应市场 |
| `/api/codex/reports/latest` | 凭证保护的最新日报查询 |
| `/api/codex/reports/config` | Codex Automation 机器可读任务配置 |
| `/api/codex/reports/history` | 凭证保护的历史日报查询 |
| `/api/codex/reports/generate` | 凭证保护的定时生成入口 |
| `/api/news` | 标准化新闻列表 |
| `/api/system/status` | 凭证与主源状态诊断 |
| `/api/auth/longbridge/status` | OAuth / 固定凭证状态 |
| `/api/auth/longbridge/login` | 发起 Longbridge OAuth 授权 |
| `/api/auth/longbridge/callback` | OAuth 授权回调 |

Codex/定时任务接口使用 Bearer 凭证，例如：

```bash
curl -H "Authorization: Bearer $CODEX_REPORT_API_TOKEN" \
  "https://market.example.com/api/codex/reports/latest?session=close"
```

Codex 可读取任务配置了解历史任务定义，但四个 GPT Automation 当前保持停用：

```bash
curl -H "Authorization: Bearer $CODEX_REPORT_API_TOKEN" \
  "https://market.example.com/api/codex/reports/config"
```

配置会声明每个任务的北京时间、工作日、市场范围、生成/读取接口、鉴权变量和输出板块，
同时返回 `enabled: false`。日报与夜报由微应用读取本地固化数据包并展示；GPT Automation
不再负责生成或投递。Automation 的停用不会停止独立的四时段报告采集器。

四个 `session` 值依次为 `morning`、`midday`、`close`、`us-night`。云端定时任务可在
Asia/Shanghai 时区的 09:30、12:30、16:30、22:30 调用对应的受保护生成接口。

## AI 助手 Benchmark

分段测量查询规划、Provider 答案生成、本地查询和总耗时：

```bash
/Users/enjoychan/.venvs/akshare/bin/python tools/benchmark_ai_assistant.py \
  --scenario stock \
  --runs 3 \
  --output tmp/benchmarks/ai-assistant-stock.json
```

内置场景包括 `stock`、`sector`、`weekly` 和 `quick-midday`。Benchmark 使用当前本机
Provider 配置并产生真实模型请求，但不会打印 API Key 或完整 Prompt。输出包含各阶段的
`minMs`、`meanMs`、`p50Ms`、`p95Ms`、`maxMs`，以及每次请求的输入、输出字符数。

## 诊断

Longbridge 是否接通，可直接看：

```bash
curl http://127.0.0.1:5001/api/system/status
```

关键字段：

- `configured`: 是否已读到凭证
- `quoteContextReady`: SDK 是否成功建立报价上下文
- `usingLiveSource`: 当前是否可以直接走长桥实时源

## 注意事项

- 当前环境若未配置 Longbridge 凭证，市场数据会自动降级到 fallback 源
- A 股板块与代表股仍依赖公开补源，稳定性弱于长桥主行情
- `start.sh` 在某些受控执行环境里不稳定，优先用上面的手动启动命令
