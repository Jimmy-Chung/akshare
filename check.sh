#!/bin/bash
# 服务自检清单 —— 在对外暴露 HTTPS 前确认本地服务可用
# 用法: ./check.sh 或 source check.sh && expose

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

failures=0

check_port() {
  local label=$1 port=$2
  if lsof -i ":$port" -sTCP:LISTEN > /dev/null 2>&1; then
    echo -e "  ${GREEN}✅${NC} $label (port $port) — 端口监听正常"
    return 0
  else
    echo -e "  ${RED}❌${NC} $label (port $port) — 端口未监听"
    failures=$((failures + 1))
    return 1
  fi
}

check_http() {
  local label=$1 url=$2
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 30 "$url" 2>/dev/null)
  if [ "$code" = "200" ]; then
    echo -e "  ${GREEN}✅${NC} $label — HTTP $code"
    return 0
  else
    echo -e "  ${RED}❌${NC} $label — HTTP $code (期望 200)"
    failures=$((failures + 1))
    return 1
  fi
}

echo "=========================================="
echo " 服务自检 — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

echo ""
echo "【端口检查】"
check_port "后端 Flask" 5001
check_port "前端 Vite" 3005

echo ""
echo "【HTTP 响应检查】"
check_http "后端 API"  "http://localhost:5001/api/global-indices"
check_http "前端页面"  "http://localhost:3005/"

echo ""
echo "【进程检查】"
backend_pid=$(ps aux | grep "[P]ython.*app.py" | grep -v grep | awk '{print $2}' | head -1)
frontend_pid=$(ps aux | grep "vite.*3005" | grep -v grep | awk '{print $2}' | head -1)

if [ -n "$backend_pid" ]; then
  echo -e "  ${GREEN}✅${NC} 后端进程 PID=$backend_pid"
else
  echo -e "  ${RED}❌${NC} 后端进程不存在"
  failures=$((failures + 1))
fi

if [ -n "$frontend_pid" ]; then
  echo -e "  ${GREEN}✅${NC} 前端进程 PID=$frontend_pid"
else
  echo -e "  ${RED}❌${NC} 前端进程不存在"
  failures=$((failures + 1))
fi

echo ""
if [ $failures -eq 0 ]; then
  echo -e "${GREEN}✅ 全部通过 — 可以暴露外网访问${NC}"
  exit 0
else
  echo -e "${RED}❌ $failures 项检查失败 — 请先执行 ./start.sh start 修复${NC}"
  exit 1
fi
