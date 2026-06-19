#!/bin/bash
# akshare 服务启动 & 守护脚本
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

start_backend() {
  echo "[$(date '+%H:%M:%S')] 启动后端..."
  cd "$ROOT/backend/data_service"
  nohup python3 -c "from waitress import serve; from app import app; serve(app, host='0.0.0.0', port=5001)" > "$LOG_DIR/backend.log" 2>&1 &
  echo $! > "$LOG_DIR/backend.pid"
}

start_frontend() {
  echo "[$(date '+%H:%M:%S')] 启动前端..."
  cd "$ROOT/frontend"
  nohup npx vite --host 0.0.0.0 --port 3005 --strictPort > "$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$LOG_DIR/frontend.pid"
}

health_check() {
  local name=$1 port=$2
  if lsof -i ":$port" -sTCP:LISTEN > /dev/null 2>&1; then
    echo "  ✅ $name (:$port)"
    return 0
  else
    echo "  ❌ $name (:$port)"
    return 1
  fi
}

stop_all() {
  echo "[$(date '+%H:%M:%S')] 停止所有服务..."
  for f in "$LOG_DIR"/*.pid; do
    [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null && echo "  killed $(basename "$f" .pid)"
  done
  rm -f "$LOG_DIR"/*.pid
}

case "${1:-start}" in
  start)
    echo "=========================================="
    echo " 全球市场行情看板 - 服务启动"
    echo "=========================================="

    # 检查是否已在运行
    running=false
    if lsof -i ":5001" -sTCP:LISTEN > /dev/null 2>&1; then
      echo "后端已运行"
      running=true
    fi
    if lsof -i ":3005" -sTCP:LISTEN > /dev/null 2>&1; then
      echo "前端已运行"
      running=true
    fi

    if [ "$running" = true ]; then
      echo ""
      echo "部分服务已在运行，执行 health 检查:"
      health_check "后端 Flask" 5001
      health_check "前端 Vite" 3005
      exit 0
    fi

    start_backend
    sleep 3
    start_frontend
    sleep 4

    echo ""
    echo "健康检查:"
    health_check "后端 Flask" 5001
    health_check "前端 Vite" 3005

    echo ""
    echo "本地:  http://localhost:3005"
    echo "后端:  http://localhost:5001"
    echo "日志:  $LOG_DIR/"
    ;;

  stop)
    stop_all
    ;;

  status)
    echo "服务状态:"
    health_check "后端 Flask" 5001
    health_check "前端 Vite" 3005
    if [ -f "$LOG_DIR/frontend.log" ]; then
      echo ""
      echo "=== 最近日志 (前端) ==="
      tail -5 "$LOG_DIR/frontend.log"
    fi
    if [ -f "$LOG_DIR/backend.log" ]; then
      echo ""
      echo "=== 最近日志 (后端) ==="
      tail -5 "$LOG_DIR/backend.log"
    fi
    ;;

  *)
    echo "用法: $0 {start|stop|status}"
    exit 1
    ;;
esac
