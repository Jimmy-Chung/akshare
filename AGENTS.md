# Project Notes

## Application Startup and Access

- 在项目根目录统一使用 `./start.sh` 管理应用，不要分别手工启动前端、后端或热力图 watcher。
- 启动或补齐缺失的服务：`./start.sh start`。该命令会启动后端 Flask（`127.0.0.1:5001`）、前端 Vite（`127.0.0.1:3005`）、CN/HK/US 三个热力图 watcher 和四时段报告采集器；已运行的服务不会重复启动。
- 检查服务、watcher 和最近日志：`./start.sh status`。
- 停止整套应用：`./start.sh stop`。
- 本地访问地址：`http://localhost:3005`；后端状态接口：`http://127.0.0.1:5001/api/system/status`；运行日志位于 `logs/`。
- 需要让用户或外部系统访问时，按 Dev Preview Tunnel 约定将前端端口注册到 Workspace Router：

  ```bash
  curl -sS -X POST http://127.0.0.1:18080/_api/expose \
    -H 'content-type: application/json' \
    -d '{"name":"akshare","port":3005}'
  ```

- 对外预览地址固定为 `https://workspace-akshare.jimmy-jam.com`。注册后必须同时验证本地与外部地址返回成功状态码；若 Router 未运行，先按全局 Dev Preview Tunnel 说明启动 Workspace Router，再重新注册。
- 仅取消外部映射时使用：`curl -X DELETE http://127.0.0.1:18080/_api/expose/akshare`；这不会停止应用本身。

## Market Report Collection

- 报告数据包与热点图完全解耦，不读取板块状态图、热点图时间轴、行业排行榜或 dayLeader。
- 四时段报告采集器使用 `tools/market_report_collector.py`，由 `./start.sh start|stop|status` 管理；按北京时间固化早报 09:30、午报 12:30、收盘报 16:30、夜报 22:30 数据包。
- 午报和收盘报覆盖 A 股与港股；夜报覆盖美股。采集器先使用 Longbridge 交易日历确认至少一个关注市场开市，再生成数据包。
- AI 助手快捷动作只能读取对应时段已经固化的数据包，不得在较晚时点用实时数据反向重建午报。数据包缺失时应明确提示尚未采集。
- 报告只展示全球指数、关注市场主要指数、数据时点与来源；指数走势图按 `pageUrl`/`exportButtonId` 导出。

## Heatmap Collection

- 板块状态图数据与 PNG 由统一快照服务生产：定时 watcher、Dashboard 和热点图时间轴必须共享同一 snapshot，不得各自重新请求和生成图表。统一使用气泡状态图（面积按市值、横轴为涨跌幅、纵轴为相对换手或相邻快照涨跌变化）并沿用各市场一级/二级行业分类；二级行业成分股继续按需加载。
- 快照 worker 生成 PNG 时必须打开 `http://localhost:3005` + 快照 `pageUrl`，等待 `captureSelector` 唯一匹配并完成渲染，点击 `data-export-chart-id=<exportButtonId>` 的页面导出按钮；导出前把目标图卡滚入视口、复位横向滚动、触发 resize 并等待 ECharts canvas 稳定。
- 应用端统一保留 ECharts 原生气泡状态图与轨迹方向；小市值板块使用缩放和平移定位，并保留扩大的透明点击命中区。完整一级/二级行业名称用图下分类索引补全，不要在截图端重写布局。
- 热力图时间轴值守采样属于 Web 应用体系内的后台 worker，由 `./start.sh start|stop|status` 管理 CN/HK/US 三个 watcher；不要使用系统级 LaunchAgent、cron 或日报 Automation 启动 watcher。
- 连续热点图播放属于 Dashboard 板块状态轨迹：报告采集器和 AI 助手不合成视频、不调用 `heatmapTimelineVideos`、不执行 `renderCommand`，也不直接调用 watcher。
- 热力图时间轴值守采样使用 `tools/market_heatmap_timeline.py watch`。交易日与盘中时段以 Longbridge `trading_days`、`half_trading_days` 和 `trading_session` 为准；固定半点调度，并额外保留 session-close 帧，不得使用“采集后 sleep 1800 秒”的漂移调度。调试或补帧时才使用 `--force`。
- Dashboard 普通刷新只读取最近统一快照；右上角“立即刷新热点图”通过同一快照管线生成 `manual` 快照。手动快照默认不进入半小时连续播放序列。
