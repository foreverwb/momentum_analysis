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

## 🎨 Design System

The app uses a custom design system extracted from the prototype:

### Colors
- Background: `--bg-primary`, `--bg-secondary`, `--bg-tertiary`
- Text: `--text-primary`, `--text-secondary`, `--text-muted`
- Accents: `--accent-blue`, `--accent-purple`, `--accent-green`, `--accent-amber`, `--accent-red`, `--accent-orange`

### Border Radius
- Small: `--radius-sm` (6px)
- Medium: `--radius-md` (10px)
- Large: `--radius-lg` (16px)

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
