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
运行 CLI 前请先激活后端虚拟环境，并在 `backend` 目录执行一次 `./bin/install-cli-shortcuts`。该脚本会把 `Actualiser` / `finviz` / `mc` / `uploads` / `update` / `list-etfs` / `list-holdings` 写入当前虚拟环境的 `bin` 目录，之后可直接使用短命令。旧写法 `python -m app.cli refresh ...` 仍兼容。

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
| `Actualiser etfs` | 后台串行刷新多个 ETF；`--source` 支持 `all` / `ibkr` / `futu`，默认 `all`；省略 `-s` 时默认刷新全部 ETF | `Actualiser etfs -s "XLK,XLF,SOXX"`<br>`Actualiser etfs -s "XLK,SOXX" --source ibkr`<br>`Actualiser etfs -s "XLK,SOXX" --source futu`<br>`Actualiser etfs --source futu` |
| `Actualiser holdings` | 后台串行刷新多个 ETF holdings；支持 `t-20` / `85` / `all`；`--source` 支持 `all` / `ibkr` / `futu`，默认 `all` | `Actualiser holdings -s "XLK,SOXX" -w t-20`<br>`Actualiser holdings -s "XLK,SOXX" -w t-20 --source ibkr`<br>`Actualiser holdings -s "XLK,SOXX" -w t-20 --source futu` |
| `Actualiser status` | 查询单个后台刷新任务状态 | `Actualiser status 12` |
| `Actualiser list` | 查看最近的后台刷新任务 | `Actualiser list --status running` |

说明：

- 多个 ETF / holdings job 在服务端按入队顺序串行执行，避免对 IBKR / Futu 形成并发冲击。
- `Actualiser holdings` 内部仍保留已有的 IBKR 并发限制与 Futu 批量抓取逻辑。
- 串行 job 之间会按 `cfg.yaml -> refresh.serial_gap_seconds` 留出间隔，默认 `2` 秒。

### Actualiser 评分触发规则

- `Actualiser etfs --source ibkr`
  - 只刷新 IBKR 提供的价格、RelMom、TrendQuality 数据。
  - 不触发 ETF 评分重算；命令完成后仍返回当前已落库的 ETF 分数视图。
- `Actualiser etfs --source futu`
  - 只有“这次成功拿到可用的 Futu 期权数据”或“冷却窗口内已有可复用的 Futu 期权数据”时，才触发 ETF 评分重算。
  - 如果没有可用于评分的期权数据，本次只刷新数据状态，不重算 ETF 评分。
- `Actualiser etfs --source all`
  - 保持全量刷新行为；在本次刷新流程结束后重算 ETF 评分。

- `Actualiser holdings --source ibkr`
  - 只刷新并落库 ETF 与覆盖范围内 holdings 的 IBKR 价格数据。
  - 不触发 stock 评分，也不触发最终 ETF 汇总评分。
  - 不要求当前 coverage 先具备最新的 Finviz / MarketChameleon 导入数据。
- `Actualiser holdings --source futu`
  - 只有当前 coverage 内至少有一个 ticker 具备“可用于评分的 Futu 期权数据”时，才会打开整条评分链路。
  - 这里的“可用于评分”包括两种情况：本次成功抓取到 Futu 期权数据，或该 ticker 在冷却窗口内已有可复用的 Futu 数据。
  - 如果当前 coverage 完全拿不到可用期权数据，本次只刷新期权数据状态，不触发任何评分计算。
- `Actualiser holdings --source all`
  - 保持全量刷新行为；在 stock 评分完成后继续汇总重算 ETF 评分。

### 评分实现规则

- ETF 评分由四个维度组成：`rel_mom`、`trend_quality`、`breadth`、`options_confirm`。
- `rel_mom` 与 `trend_quality` 依赖 IBKR 价格数据。
- `options_confirm` 依赖 Futu 期权 / IV 数据。
- `breadth` 依赖当前 ETF 最新 holdings 对应的 Finviz 导入数据。

- `Actualiser holdings --source futu|all` 在进入评分前，会先校验当前覆盖范围内的 `Finviz + MarketChameleon` 是否都是“北京时间 08:00 起算后的最新导入数据”；缺任何一项都会先报错，不进入评分流程。
- `Actualiser holdings --source ibkr` 是纯价格刷新路径，不做这一步导入校验。
- 单只 stock 真正开始评分时，还必须同时满足：
  - 有可用价格数据。
  - 有 `finviz` 与 `marketchameleon` 导入数据。
- `Actualiser holdings --source futu` 会额外要求该 ticker 具备可用于评分的 Futu 期权数据；没有期权数据的 ticker 不会产出新的 stock 评分。
- `Actualiser holdings --source all` 保持当前全量模式实现：只要价格数据可用，就会进入 stock 评分；Futu / IV 数据作为附加输入参与评分与指标落库，但不是每只 stock 的硬性前置条件。
- `Actualiser holdings --source futu` 本身不会拉取 IBKR 价格；因此它依赖本地已存在的 `PriceHistory` 缓存。没有价格缓存的 ticker 即使拿到了期权数据，也不会产出新的 stock 评分。
- stock 评分实际调用 `calculate_momentum_pool_score(...)`，结果会写回 `Stock` 和 `ScoreSnapshot`。
- holdings 维度的 stock 评分全部完成后，系统才会基于最新 stock / IV / holdings / 导入数据汇总重算 ETF 评分。

### 便捷入口

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `./bin/install-cli-shortcuts` | 将短命令安装到当前虚拟环境的 `bin` 目录 | `cd backend && ./bin/install-cli-shortcuts` |
| `./bin/finviz ...` | 在 `backend` 目录下直接调用 Finviz 便捷脚本 | `./bin/finviz -f export.csv`<br>`./bin/finviz -s "XLK,XLC,XLV" -w 85 -f export.csv` |
| `./bin/mc ...` | 在 `backend` 目录下直接调用 MarketChameleon 便捷脚本 | `./bin/mc -f marketchameleon_etfs.json`<br>`./bin/mc -s "XLF" -w 85 -f marketchameleon_06_03_10_18.json` |
