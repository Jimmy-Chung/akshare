# Project Notes

## Market Report Heatmap Exports

- 四个市场日报 automation 的最终输出应保持精简：只展示关注市场的主要指数波动、对应指数走势图 PNG，以及每个关注市场在日报触发时点的静态热力图 PNG。不要在日报正文中恢复全球指数总览、行业排行榜或 dayLeader 长列表，除非用户明确要求。
- 日报热力图附件必须按 `chartExports` 的真实流程生成：打开 `http://localhost:3005` + `pageUrl`，等待 `captureSelector` 唯一匹配并完成渲染，点击 `data-export-chart-id=<exportButtonId>` 的页面导出按钮，保存应用生成的 PNG。
- 导出热力图前必须把目标图卡滚入视口，确保横向滚动容器位于最左侧，触发一次 resize，并等待 ECharts canvas 稳定后再点击导出按钮；否则可能导出只有色块、文字未绘制完成的错误图。
- `renderMode=full-market-hierarchy` 的热力图禁止用裸 canvas、headless 直接抽取 blob、整页截图、切片拼接或自绘 Python treemap 替代。只有页面导出下载失败时，才允许按 `captureSelector` 精确截图作为兜底，并必须通过尺寸、PNG 完整性和内容验收。
- 应用端热力图应保留 ECharts 原生 treemap 布局；小色块文字显示不全时，用图内或图下“完整行业标注索引”补全，不要在截图端重写布局。
- 热力图时间轴值守采样属于 Web 应用体系内的后台 worker，由 `./start.sh start|stop|status` 管理 CN/HK/US 三个 watcher；不要使用系统级 LaunchAgent、cron 或日报 Automation 启动 watcher。
- 连续热点图播放属于 Web 应用“热点图”Tab：日报 Automation 不合成视频、不调用 `heatmapTimelineVideos`、不执行 `renderCommand`，也不直接调用 watcher。
- 热力图时间轴值守采样使用 `tools/market_heatmap_timeline.py watch`。默认只在对应市场常规交易时段采样，收盘和周末跳过；调试或补帧时才使用 `--force`。
