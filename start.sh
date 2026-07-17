#!/bin/bash
# akshare 服务启动与健康检查脚本
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT/logs"
PYTHON_BIN="${AKSHARE_PYTHON_BIN:-/Users/enjoychan/.venvs/akshare/bin/python}"
WATCHER_PYTHON_BIN="${AKSHARE_WATCHER_PYTHON_BIN:-/opt/homebrew/bin/python3}"
NODE_BIN="${AKSHARE_NODE_BIN:-/opt/homebrew/bin/node}"
VITE_BIN="$ROOT/frontend/node_modules/vite/bin/vite.js"
BACKEND_SESSION="akshare-backend"
FRONTEND_SESSION="akshare-frontend"
HEATMAP_WATCHER_PREFIX="akshare-heatmap"
REPORT_COLLECTOR_SESSION="akshare-report-collector"
mkdir -p "$LOG_DIR"

heatmap_watcher_pids() {
  local market=$1
  pgrep -f "[Pp]ython .*${ROOT}/tools/market_heatmap_timeline.py --market ${market}" 2>/dev/null || true
}

stop_heatmap_watcher_processes() {
  local market=$1
  local pids
  pids="$(heatmap_watcher_pids "$market")"
  if [ -n "$pids" ]; then
    echo "  停止 ${market} 热力图采集进程: ${pids//$'\n'/ }"
    kill $pids 2>/dev/null || true
  fi
}

start_backend() {
  echo "[$(date '+%H:%M:%S')] 启动后端..."
  screen -S "$BACKEND_SESSION" -X quit > /dev/null 2>&1 || true
  screen -dmS "$BACKEND_SESSION" /bin/zsh -lc \
    "unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY; cd '$ROOT/backend/data_service' && exec '$PYTHON_BIN' -c \"from waitress import serve; from app import app; serve(app, host='127.0.0.1', port=5001)\" >> '$LOG_DIR/backend.log' 2>&1"
}

start_frontend() {
  echo "[$(date '+%H:%M:%S')] 启动前端..."
  screen -S "$FRONTEND_SESSION" -X quit > /dev/null 2>&1 || true
  screen -dmS "$FRONTEND_SESSION" /bin/zsh -lc \
    "unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY; cd '$ROOT/frontend' && exec '$NODE_BIN' '$VITE_BIN' --host 127.0.0.1 --port 3005 --strictPort >> '$LOG_DIR/frontend.log' 2>&1"
}

start_heatmap_watcher() {
  local market=$1
  local session=$2
  local port=$3
  local lower_market
  lower_market="$(echo "$market" | tr '[:upper:]' '[:lower:]')"
  local screen_session="${HEATMAP_WATCHER_PREFIX}-${lower_market}"
  local pids
  local pid_count
  pids="$(heatmap_watcher_pids "$market")"
  pid_count="$(printf '%s\n' "$pids" | sed '/^$/d' | wc -l | tr -d ' ')"

  if screen -ls | grep -q "$screen_session" && [ "$pid_count" -eq 1 ]; then
    echo "热力图采集器 ${market} 已运行"
    return 0
  fi

  if [ "$pid_count" -gt 0 ]; then
    stop_heatmap_watcher_processes "$market"
    sleep 1
  fi

  echo "[$(date '+%H:%M:%S')] 启动热力图采集器 ${market}..."
  screen -S "$screen_session" -X quit > /dev/null 2>&1 || true
  screen -dmS "$screen_session" /bin/zsh -lc \
    "unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY; cd '$ROOT' && exec '$WATCHER_PYTHON_BIN' '$ROOT/tools/market_heatmap_timeline.py' --market '$market' --session '$session' --port '$port' watch --poll-seconds 10 --grace-seconds 180 >> '$LOG_DIR/heatmap-${lower_market}.log' 2>&1"
}

start_heatmap_watchers() {
  start_heatmap_watcher "CN" "close" "9231"
  start_heatmap_watcher "HK" "close" "9232"
  start_heatmap_watcher "US" "us-night" "9233"
}

report_collector_pids() {
  pgrep -f "[Pp]ython .*${ROOT}/tools/market_report_collector.py" 2>/dev/null || true
}

start_report_collector() {
  local pids
  pids="$(report_collector_pids)"
  if screen -ls | grep -q "$REPORT_COLLECTOR_SESSION" && [ "$(printf '%s\n' "$pids" | sed '/^$/d' | wc -l | tr -d ' ')" -eq 1 ]; then
    echo "报告采集器已运行"
    return 0
  fi
  [ -n "$pids" ] && kill $pids 2>/dev/null || true
  screen -S "$REPORT_COLLECTOR_SESSION" -X quit > /dev/null 2>&1 || true
  echo "[$(date '+%H:%M:%S')] 启动报告采集器..."
  screen -dmS "$REPORT_COLLECTOR_SESSION" /bin/zsh -lc \
    "unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY; cd '$ROOT' && exec '$WATCHER_PYTHON_BIN' '$ROOT/tools/market_report_collector.py' >> '$LOG_DIR/report-collector.log' 2>&1"
}

health_check() {
  local name=$1 url=$2
  if curl --silent --show-error --fail --max-time 3 "$url" > /dev/null; then
    echo "  ✅ $name"
    return 0
  else
    echo "  ❌ $name"
    return 1
  fi
}

wait_for_service() {
  local name=$1 url=$2
  local attempts=${3:-30}
  local attempt=1

  while [ "$attempt" -le "$attempts" ]; do
    if curl --silent --fail --max-time 2 "$url" > /dev/null 2>&1; then
      echo "  ✅ $name 已就绪"
      return 0
    fi
    sleep 1
    attempt=$((attempt + 1))
  done

  echo "  ❌ $name 在 ${attempts} 秒内未就绪"
  return 1
}

kill_port_listener() {
  local port=$1
  local label=$2
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -z "$pids" ]; then
    return 0
  fi

  echo "  停止 ${label} 端口 ${port}: ${pids}"
  kill $pids 2>/dev/null || true
}

stop_all() {
  echo "[$(date '+%H:%M:%S')] 停止所有服务..."
  screen -S "$BACKEND_SESSION" -X quit > /dev/null 2>&1 || true
  screen -S "$FRONTEND_SESSION" -X quit > /dev/null 2>&1 || true
  screen -S "${HEATMAP_WATCHER_PREFIX}-cn" -X quit > /dev/null 2>&1 || true
  screen -S "${HEATMAP_WATCHER_PREFIX}-hk" -X quit > /dev/null 2>&1 || true
  screen -S "${HEATMAP_WATCHER_PREFIX}-us" -X quit > /dev/null 2>&1 || true
  screen -S "$REPORT_COLLECTOR_SESSION" -X quit > /dev/null 2>&1 || true
  stop_heatmap_watcher_processes "CN"
  stop_heatmap_watcher_processes "HK"
  stop_heatmap_watcher_processes "US"
  report_pids="$(report_collector_pids)"
  [ -n "$report_pids" ] && kill $report_pids 2>/dev/null || true
  kill_port_listener 5001 "后端"
  kill_port_listener 3005 "前端"
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

    if lsof -iTCP:5001 -sTCP:LISTEN > /dev/null 2>&1; then
      echo "后端已运行"
    else
      start_backend
      sleep 3
    fi

    if lsof -iTCP:3005 -sTCP:LISTEN > /dev/null 2>&1; then
      echo "前端已运行"
    else
      start_frontend
      sleep 4
    fi

    echo ""
    echo "等待服务就绪:"
    wait_for_service "后端 Flask" "http://127.0.0.1:5001/api/system/status" 60
    wait_for_service "前端 Vite" "http://127.0.0.1:3005/" 60

    start_heatmap_watchers
    start_report_collector

    echo ""
    echo "本地:  http://localhost:3005"
    echo "后端:  http://localhost:5001"
    echo "采集:  CN/HK/US 热力图 watcher 与四时段报告采集器已随应用启动"
    echo "日志:  $LOG_DIR/"
    ;;

  stop)
    stop_all
    ;;

  status)
    echo "服务状态:"
    failures=0
    health_check "后端 Flask (:5001)" "http://127.0.0.1:5001/api/system/status" || failures=$((failures + 1))
    health_check "前端 Vite (:3005)" "http://127.0.0.1:3005/" || failures=$((failures + 1))
    echo ""
    echo "热力图采集器:"
    for market in cn hk us; do
      market_label="$(echo "$market" | tr '[:lower:]' '[:upper:]')"
      pids="$(heatmap_watcher_pids "$market_label")"
      pid_count="$(printf '%s\n' "$pids" | sed '/^$/d' | wc -l | tr -d ' ')"
      if screen -ls | grep -q "${HEATMAP_WATCHER_PREFIX}-${market}" && [ "$pid_count" -eq 1 ]; then
        echo "  ✅ ${market_label} watcher"
      elif [ "$pid_count" -gt 1 ]; then
        echo "  ❌ ${market_label} watcher 重复运行 (${pid_count} 个进程)"
        failures=$((failures + 1))
      else
        echo "  ❌ ${market_label} watcher"
        failures=$((failures + 1))
      fi
    done
    report_pids="$(report_collector_pids)"
    report_count="$(printf '%s\n' "$report_pids" | sed '/^$/d' | wc -l | tr -d ' ')"
    if screen -ls | grep -q "$REPORT_COLLECTOR_SESSION" && [ "$report_count" -eq 1 ]; then
      echo "  ✅ 四时段报告采集器"
    else
      echo "  ❌ 四时段报告采集器"
      failures=$((failures + 1))
    fi
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
    for market in cn hk us; do
      market_label="$(echo "$market" | tr '[:lower:]' '[:upper:]')"
      if [ -f "$LOG_DIR/heatmap-${market}.log" ]; then
        echo ""
        echo "=== 最近日志 (热力图 ${market_label}) ==="
        tail -3 "$LOG_DIR/heatmap-${market}.log"
      fi
    done
    exit "$failures"
    ;;

  *)
    echo "用法: $0 {start|stop|status}"
    exit 1
    ;;
esac
