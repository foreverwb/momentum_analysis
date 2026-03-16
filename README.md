# Momentum Radar 趋势动能监控系统

A full-stack application for monitoring stock momentum and ETF performance.

## Tech Stack

- **Frontend**: React 18 + TypeScript + Vite + TailwindCSS + TanStack Query
- **Backend**: FastAPI + SQLAlchemy + SQLite

## 🚀 Quick Start (一键启动)

### Linux / macOS
```bash
chmod +x start.sh
./start.sh
```

### Windows
双击运行 `start.bat`

启动后：
- 📱 前端地址: http://localhost:5173
- 🔧 后端地址: http://localhost:8000
- 📚 API文档: http://localhost:8000/docs

---

## 📁 Project Structure

```
momentum-radar/
├── start.sh                     # Linux/macOS 一键启动脚本
├── start.bat                    # Windows 一键启动脚本
├── frontend/                    # React frontend
│   ├── src/
│   │   ├── components/         # React components
│   │   │   ├── layout/        # Header, MainLayout
│   │   │   ├── stock/         # StockCard, DimensionCard
│   │   │   ├── etf/           # ETFCard
│   │   │   ├── task/          # TaskCard
│   │   │   └── common/        # Shared UI components
│   │   ├── pages/             # Page components
│   │   ├── hooks/             # React Query hooks
│   │   ├── services/          # API services
│   │   ├── types/             # TypeScript types
│   │   └── styles/            # CSS and design tokens
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
│
└── backend/                     # FastAPI backend
    ├── app/
    │   ├── api/               # API routes
    │   ├── models/            # SQLAlchemy models
    │   ├── schemas/           # Pydantic schemas
    │   ├── services/          # Business logic
    │   └── main.py           # FastAPI app
    └── requirements.txt
```

---

## 🔧 Manual Setup (手动启动)

### Backend Setup

```bash
cd backend

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload --port 8000
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

---

## ✨ Features

- **动能股池 (Momentum Pool)**: View and analyze momentum stocks with detailed scoring
- **板块 ETF (Sector ETF)**: Overview of sector ETF performance
- **行业 ETF (Industry ETF)**: Overview of industry ETF performance  
- **监控任务 (Monitoring Tasks)**: Create and manage tracking tasks

---

## 📊 ETF 评分输出（新版）

ETF 评分 `breakdown` 现在同时输出：

- `raw_features`
  - `rel_mom_raw`
  - `trend_quality_raw`
  - `breadth_raw`
  - `options_raw`
- `normalized_features`（同批候选横截面 rank/percentile 后 0~100）
  - `rel_mom_normalized`
  - `trend_quality_normalized`
  - `breadth_normalized`
  - `options_normalized`
- `weight_allocation`
  - 当某模块缺失数据时，自动对可用模块按比例重分配权重

同时保留原有模块结构（`rel_mom/trend_quality/breadth/options_confirm`），接口向后兼容。

### 权重 preset

- `balanced`（默认，兼容历史口径）
- `aggressive_short_term`
  - Price/RS: `0.55`
  - Breadth: `0.20`
  - OptionsConfirm: `0.25`
  - Price/RS 内部：`alpha * RelMom + (1-alpha) * TrendQuality`，`alpha` 默认 `0.65`

---

## 📝 Development Notes

- Frontend uses mock data by default (see `services/api.ts`)
- Set `USE_MOCK = false` in api.ts to connect to real backend
- Backend currently returns mock data; implement database logic as needed

---

## 🛑 Stopping Services

### Linux / macOS
在运行 `start.sh` 的终端中按 `Ctrl+C`

### Windows
关闭 "Momentum Radar - Backend" 和 "Momentum Radar - Frontend" 两个命令行窗口

## CLI
运行 CLI 前请先激活后端虚拟环境，并在 `backend` 目录执行一次 `./bin/install-cli-shortcuts`。该脚本会把 `refresh` / `finviz` / `mc` / `uploads` / `update` / `list-etfs` / `list-holdings` 写入当前虚拟环境的 `bin` 目录，之后可直接使用短命令。旧写法 `python -m app.cli ...` 仍兼容。

### 导入命令

| 命令 | 说明 | 关键参数 | 示例 |
| --- | --- | --- | --- |
| `uploads` | 上传 ETF holdings 文件 | `-t` ETF 类型，`-a` ETF 代码；行业 ETF 需额外提供 `-s` 父板块；文件支持位置参数 `file` 或 `-f`；`-d` 可选，默认当天 | `uploads -t sector -a XLK -f xlk.xlsx`<br>`uploads -d 2026-01-25 -t industry -s XLK -a SOXX soxx.xlsx` |
| `update` | 更新 ETF holdings，参数与 `uploads` 相同 | 同 `uploads` | `update -t industry -s XLK -a SOXX -f soxx.xlsx`<br>`update -d 2026-01-28 -t sector -a XLE xle.xlsx` |
| `finviz` | 导入 Finviz `JSON/CSV` ETF 数据；可整文件导入，也可按 ETF 覆盖范围筛选导入 | `-f` 文件名或文件路径；`-d` 可选；`-s` ETF 列表与 `-w` 覆盖范围需同时提供，`-w` 支持 `t-10` 或 `85` | `finviz -f XLC_E_F_V_Y-75%w_03-16_06_14.json`<br>`finviz -s "XLK,XLC,XLV" -w 85 -f export.csv` |
| `mc` | 导入 MarketChameleon ETF JSON 数据；支持整文件导入，也支持按 ETF 覆盖范围筛选导入 | `-f` 文件名或文件路径；`-d` 可选；`-s` ETF 列表与 `-w` 覆盖范围可选且需同时提供 | `mc -f marketchameleon_etfs.json`<br>`mc -s "XLK,XLC,XLV" -w 85 -f marketchameleon.json`<br>`mc -d 2026-03-06 -s "XLK,XLC,XLV" -w t-10 -f marketchameleon.json` |

说明：

- `finviz` / `mc` 的旧写法 `python -m app.cli finviz ...`、`python -m app.cli mc ...` 仍兼容，会自动补上 `etfs` 子命令。
- `uploads` / `update` 仍兼容旧的文件位置参数写法。

### CLI 文件配置

`cfg.yaml` 现在支持：

```yaml
cli:
  downloads_dir: '~/Downloads'
  finviz_file_prefix: 'Finviz_'
  mc_file_prefix: 'MarketChameleon_'
  holdings_file_prefix: ''
```

说明：

- 在当前机器上，`~/Downloads` 会解析到 `/Users/bin/Downloads`。
- `-f` 只填文件名时，CLI 会优先在 `downloads_dir` 中查找。
- 若配置了对应 prefix，例如 `finviz_file_prefix: 'Finviz_'`，则 `finviz -f XLC_E_F_V_Y-75%w_03-16_06_14.json` 会自动匹配 `/Users/bin/Downloads/Finviz_XLC_E_F_V_Y-75%w_03-16_06_14.json`。

### 查询命令

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `list-etfs` | 列出所有 ETF | `list-etfs` |
| `list-holdings` | 列出指定 ETF 持仓 | `list-holdings XLK` |

### 后台刷新命令

以下命令依赖已启动的后端 API。命令执行后只负责提交 job，刷新会在 FastAPI 进程内后台串行执行，不需要在当前命令行窗口等待。

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `refresh etfs` | 后台串行刷新多个 ETF | `refresh etfs -s "XLK,XLF,SOXX"` |
| `refresh holdings` | 后台串行刷新多个 ETF holdings；支持 `t-20` / `85` / `all` | `refresh holdings -s "XLK,SOXX" -w t-20` |
| `refresh status` | 查询单个后台 refresh job 状态 | `refresh status 12` |
| `refresh list` | 查看最近的后台 refresh jobs | `refresh list --status running` |

说明：

- 多个 ETF / holdings job 在服务端按入队顺序串行执行，避免对 IBKR / Futu 形成并发冲击。
- `refresh holdings` 内部仍保留已有的 IBKR 并发限制与 Futu 批量抓取逻辑。
- 串行 job 之间会按 `cfg.yaml -> refresh.serial_gap_seconds` 留出间隔，默认 `2` 秒。

### 便捷入口

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `./bin/install-cli-shortcuts` | 将短命令安装到当前虚拟环境的 `bin` 目录 | `cd backend && ./bin/install-cli-shortcuts` |
| `./bin/finviz ...` | 在 `backend` 目录下直接调用 Finviz 便捷脚本 | `./bin/finviz -f export.csv`<br>`./bin/finviz -s "XLK,XLC,XLV" -w 85 -f export.csv` |
| `./bin/mc ...` | 在 `backend` 目录下直接调用 MarketChameleon 便捷脚本 | `./bin/mc -f marketchameleon_etfs.json`<br>`./bin/mc -s "XLF" -w 85 -f marketchameleon_06_03_10_18.json` |
