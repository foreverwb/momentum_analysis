#!/bin/bash

# ============================================
# Momentum Radar 快速启动脚本 v1.2
# 支持 macOS Homebrew Python (PEP 668)
# ============================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_ROOT/backend/.venv"

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 清理函数 - 在脚本退出时终止所有子进程
cleanup() {
    print_info "正在停止服务..."
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    print_success "服务已停止"
    exit 0
}

# 捕获退出信号
trap cleanup SIGINT SIGTERM

# 显示启动横幅
echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║${NC}       ${GREEN}Momentum Radar 趋势动能监控系统${NC}                 ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}       快速启动脚本 v1.2                              ${BLUE}║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# 检查依赖
print_info "检查依赖..."

# 检查 Python
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    print_error "未找到 Python，请先安装 Python 3.8+"
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1)
print_info "系统 Python: $PYTHON_VERSION"

# 检查 Node.js
if ! command -v node &> /dev/null; then
    print_error "未找到 Node.js，请先安装 Node.js 18+"
    exit 1
fi

# 检查 npm
if ! command -v npm &> /dev/null; then
    print_error "未找到 npm，请先安装 npm"
    exit 1
fi

print_success "依赖检查通过"

# 设置 Python 虚拟环境
print_info "检查 Python 虚拟环境..."

if [ ! -d "$VENV_DIR" ]; then
    print_warning "正在创建虚拟环境..."
    $PYTHON_CMD -m venv "$VENV_DIR"
    print_success "虚拟环境创建完成: $VENV_DIR"
else
    print_success "虚拟环境已存在"
fi

# 激活虚拟环境并设置 Python 路径
if [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
    PYTHON_CMD="$VENV_DIR/bin/python"
    PIP_CMD="$VENV_DIR/bin/pip"
elif [ -f "$VENV_DIR/Scripts/activate" ]; then
    # Windows Git Bash
    source "$VENV_DIR/Scripts/activate"
    PYTHON_CMD="$VENV_DIR/Scripts/python"
    PIP_CMD="$VENV_DIR/Scripts/pip"
else
    print_error "无法找到虚拟环境激活脚本"
    exit 1
fi

print_info "使用虚拟环境 Python: $($PYTHON_CMD --version)"

# 安装后端依赖
print_info "检查后端依赖..."
cd "$PROJECT_ROOT/backend"

if ! $PYTHON_CMD -c "import fastapi" 2>/dev/null; then
    print_warning "正在安装后端依赖..."
    $PIP_CMD install --upgrade pip --quiet
    $PIP_CMD install -r requirements.txt --quiet
    print_success "后端依赖安装完成"
else
    print_success "后端依赖已就绪"
fi

# 安装前端依赖（如果需要）
print_info "检查前端依赖..."
cd "$PROJECT_ROOT/frontend"

if [ ! -d "node_modules" ]; then
    print_warning "正在安装前端依赖..."
    npm install --silent
    print_success "前端依赖安装完成"
else
    print_success "前端依赖已就绪"
fi

echo ""
print_info "启动服务..."
echo ""

# 启动后端服务
print_info "启动后端服务 (FastAPI)..."
cd "$PROJECT_ROOT/backend"
$PYTHON_CMD -m uvicorn app.main:app --reload --port 8000 --host 0.0.0.0 &
BACKEND_PID=$!

# 等待后端启动
sleep 2

# 检查后端是否启动成功
if kill -0 $BACKEND_PID 2>/dev/null; then
    print_success "后端服务已启动"
else
    print_error "后端服务启动失败"
    print_error "请尝试手动运行:"
    print_error "  cd $PROJECT_ROOT/backend"
    print_error "  source .venv/bin/activate"
    print_error "  pip install -r requirements.txt"
    print_error "  python -m uvicorn app.main:app --reload --port 8000"
    exit 1
fi

# 启动前端服务
print_info "启动前端服务 (Vite)..."
cd "$PROJECT_ROOT/frontend"
npm run dev -- --host 0.0.0.0 &
FRONTEND_PID=$!

# 等待前端启动
sleep 3

# 检查前端是否启动成功
if kill -0 $FRONTEND_PID 2>/dev/null; then
    print_success "前端服务已启动"
else
    print_error "前端服务启动失败"
    cleanup
    exit 1
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║${NC}  🚀 服务启动成功!                                      ${GREEN}║${NC}"
echo -e "${GREEN}╠════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║${NC}                                                        ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  📱 前端地址:  ${BLUE}http://localhost:5173${NC}                  ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  🔧 后端地址:  ${BLUE}http://localhost:8000${NC}                  ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  📚 API文档:   ${BLUE}http://localhost:8000/docs${NC}             ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}                                                        ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  按 ${YELLOW}Ctrl+C${NC} 停止所有服务                              ${GREEN}║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# 等待子进程
wait