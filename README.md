# 全球市场行情看板

基于 Longbridge 主行情源 + 同花顺板块补源的内部市场看板与日报工具。

## 当前功能

- `看板` 页: 全球概览、A/HK/US 主要指数、A 股板块热力图、港美权重股、自动点评、新闻摘要
- `日报` 页: `早盘 09:30 / 午盘 12:30 / 收盘 16:30 / 美股夜盘 22:30` 四档结构化报告
- 行情主源: Longbridge
- 看板板块热力图: Longbridge 行业排行（A 股 / 港股 / 美股）
- 日报内容: 全球指数总览、时段主要市场指数、Longbridge 一级/二级行业涨跌幅前三
- 全球市场按美洲、欧洲、亚太、南亚分组；逐项优先 Longbridge，缺失项显示备用来源标记
- 新闻优先 Longbridge，数量不足时以 Google News 补齐并标记
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
```

后端会优先读取仓库根目录 `.env`，也兼容旧变量名 `LONGPORT_*`。

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

当前建议先手动启动，不依赖 `start.sh`：

1. 启动后端

```bash
cd /Users/jimmychung/Desktop/finogeeks/akshare/backend/data_service
python3 -m pip install -r requirements.txt
python3 -c "from waitress import serve; from app import app; serve(app, host='0.0.0.0', port=5001)"
```

2. 启动前端

```bash
cd /Users/jimmychung/Desktop/finogeeks/akshare/frontend
npm install
npx vite --host 0.0.0.0 --port 3005 --strictPort
```

## 访问地址

- 前端界面: http://localhost:3005
- 数据API: http://localhost:5001

日常可从项目根目录执行 `./start.sh start`。脚本通过两个独立的 `screen` 会话承载服务，
仅补启动缺失服务，并等待后端 API 和前端页面完成就绪；已经可用的服务不会重启。

## 主要接口

| 接口 | 说明 |
|------|------|
| `/api/dashboard/overview` | Dashboard 聚合数据 |
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

Codex 可先读取任务配置，再据此创建或同步 Automation：

```bash
curl -H "Authorization: Bearer $CODEX_REPORT_API_TOKEN" \
  "https://market.example.com/api/codex/reports/config"
```

配置会声明每个任务的北京时间、工作日、市场范围、生成/读取接口、鉴权变量和输出板块。
配置修改后，需要再次让 Codex 执行 Automation 同步。

四个 `session` 值依次为 `morning`、`midday`、`close`、`us-night`。云端定时任务可在
Asia/Shanghai 时区的 09:30、12:30、16:30、22:30 调用对应的受保护生成接口。

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
