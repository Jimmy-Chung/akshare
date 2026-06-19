# 全球市场行情看板

基于公开真实行情源的全球股票市场行情可视化看板。

## 功能特性

- **顶部轮播**: 全球主要指数实时涨跌轮播展示
- **市场切换**: A股 / 港股 / 美股 三市场切换
- **指数概览**: 主要指数涨跌卡片 + 分时走势图
- **热力图**: Treemap 热力图展示板块/个股涨跌
- **详情面板**: 点击方块后右侧展示龙头股列表

## 技术栈

- **前端**: React + TypeScript + Vite + ECharts
- **数据服务**: Python + Flask + AKShare + Nasdaq/Yahoo 公开行情接口

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

## 启动方式

### 方式一: 使用启动脚本

```bash
chmod +x start.sh
./start.sh
```

### 方式二: 手动启动

1. 启动Python数据服务:
```bash
cd backend/data_service
pip install -r requirements.txt
python app.py
```

2. 启动前端服务:
```bash
cd frontend
npm install
npm run dev
```

## 访问地址

- 前端界面: http://localhost:3005
- 数据API: http://localhost:5001

## API接口

| 接口 | 说明 |
|------|------|
| `/api/global-indices` | 全球主要指数 |
| `/api/a-indices` | A股主要指数 |
| `/api/hk-indices` | 港股主要指数 |
| `/api/us-indices` | 美股主要指数 |
| `/api/a-boards` | A股板块热力图数据 |
| `/api/hk-stocks` | 港股个股数据 |
| `/api/us-stocks` | 美股个股数据 |

## 数据刷新

每5分钟自动刷新全量数据。

## 注意事项

- AKShare 数据来源于公开网站爬取，可能有延迟
- 部分接口在网络受限环境下可能无法正常获取数据
- 数据接口失败时返回空数据，不生成模拟行情
