#!/usr/bin/env bash
# CyberVerse 一键启动 / 停止 / 看状态
#
#   ./cyberverse.sh start    启动（已在运行的会自动跳过，可重复执行）
#   ./cyberverse.sh stop     停止
#   ./cyberverse.sh status   看状态（端口 + 健康检查 + 显存）
#   ./cyberverse.sh logs     跟踪日志（Ctrl+C 退出，不停止服务）
#
# 启动顺序：推理服务 → Go API → 前端。Go API 依赖推理服务的 50051。
set -uo pipefail

ROOT=/data/Avatar
REPO=$ROOT/CyberVerse-main
TOOLS=$ROOT/.tools
RUN=$REPO/.run
LOGS=$RUN/logs
VENV=$REPO/.venv

export HOME=$ROOT/.home
export HF_HOME=$ROOT/.cache/huggingface
export TORCHINDUCTOR_CACHE_DIR=$ROOT/.cache/torch_inductor
export UV_CACHE_DIR=$ROOT/.cache/uv
export PATH=$TOOLS/bin:$PATH

INFER_PORT=50051
API_PORT=8080
WEB_PORT=5173

mkdir -p "$LOGS" "$HOME"

c_ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m%s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m%s\033[0m\n' "$*"; }

port_busy() { ss -ltn 2>/dev/null | grep -q ":${1} "; }

wait_port() { # port, seconds
  local i=0
  while [ "$i" -lt "$2" ]; do
    port_busy "$1" && return 0
    sleep 1; i=$((i+1))
  done
  return 1
}

spawn() { # name, port, process-pattern, workdir, command...
  local name="$1" port="$2" pattern="$3" dir="$4"; shift 4
  # 端口可能还没开始监听（模型加载中），所以进程模式也要判断，否则会重复启动
  if port_busy "$port" || pgrep -f "$pattern" >/dev/null 2>&1; then
    c_ok  "[跳过] $name 已在运行"
    return 0
  fi
  ( cd "$dir" && setsid nohup "$@" >"$LOGS/$name.log" 2>&1 & echo $! >"$RUN/$name.pid" )
  printf '[启动] %-10s 端口 %-5s 日志 %s\n' "$name" "$port" "$LOGS/$name.log"
}

cmd_start() {
  echo "=== 启动 CyberVerse ==="

  spawn inference "$INFER_PORT" "inference.server --config" "$REPO" \
    env PYTHON="$VENV/bin/python" ./scripts/inference.sh config/cyberverse.yaml

  # 首次运行需要先编译 Go 服务
  if [ ! -x "$REPO/bin/cyberverse-server" ]; then
    c_warn "[编译] 未找到 bin/cyberverse-server，开始编译…"
    ( cd "$REPO" && GOPROXY=https://goproxy.cn,direct PROTOC=/usr/local/bin/protoc \
        ./scripts/generate_proto.sh >/dev/null 2>&1
      cd server && GOPROXY=https://goproxy.cn,direct \
        go build -tags livekit -o ../bin/cyberverse-server ./cmd/cyberverse-server/ ) \
      && c_ok "[编译] 完成" || { c_err "[编译] 失败，看上面的输出"; return 1; }
  fi

  spawn server "$API_PORT" "cyberverse-server --config" "$REPO/server" \
    bash -c 'set -a; . ../config/env; set +a; exec ../bin/cyberverse-server --config ../config/cyberverse.yaml'

  spawn frontend "$WEB_PORT" "vite" "$REPO/frontend" \
    bash -c 'CHOKIDAR_USEPOLLING=true exec npm run dev'

  echo
  echo "等待推理服务加载模型（首次含 torch.compile，可能 3-5 分钟）…"
  if wait_port "$INFER_PORT" 240; then c_ok "推理服务已就绪"; else c_warn "推理服务 240s 内未监听，请看 $LOGS/inference.log"; fi
  wait_port "$API_PORT" 60 && c_ok "API 已就绪" || c_warn "API 未就绪"
  wait_port "$WEB_PORT" 60 && c_ok "前端已就绪" || c_warn "前端未就绪"

  echo
  cmd_status
  echo
  echo "浏览器打开： http://localhost:$WEB_PORT"
}

cmd_stop() {
  echo "=== 停止 CyberVerse ==="
  for name in frontend server inference; do
    pidfile="$RUN/$name.pid"
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
      pkill -P "$(cat "$pidfile")" 2>/dev/null
      kill "$(cat "$pidfile")" 2>/dev/null
      c_ok "[停止] $name (pid $(cat "$pidfile"))"
    else
      c_warn "[跳过] $name 没有记录 pid（可能不是本脚本启动的）"
    fi
    rm -f "$pidfile"
  done
  echo
  c_warn "若端口仍被占用，说明服务是别的方式启动的，例如："
  echo "  sudo ss -ltnp | grep -E ':(50051|8080|5173)'    # 找到 pid 后 kill 掉"
}

cmd_status() {
  echo "=== 状态 ==="
  for pair in "推理服务:$INFER_PORT" "Go API:$API_PORT" "前端:$WEB_PORT" "TURN/WebRTC:8443"; do
    name="${pair%%:*}"; port="${pair##*:}"
    if port_busy "$port"; then printf '  %-12s 端口 %-5s \033[32m监听中\033[0m\n' "$name" "$port"
    else printf '  %-12s 端口 %-5s \033[31m未监听\033[0m\n' "$name" "$port"; fi
  done
  echo
  printf '  健康检查  '
  curl -s -m 5 "http://localhost:$API_PORT/api/v1/health" || echo "(API 未响应)"
  echo
  if command -v nvidia-smi >/dev/null 2>&1; then
    printf '  GPU       '
    nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "(不可见)"
  fi
}

cmd_logs() {
  echo "跟踪日志（Ctrl+C 退出，不会停止服务）："
  tail -n 20 -f "$LOGS/inference.log" "$LOGS/server.log" "$LOGS/frontend.log"
}

case "${1:-}" in
  start)  cmd_start  ;;
  stop)   cmd_stop   ;;
  status) cmd_status ;;
  logs)   cmd_logs   ;;
  *) cat <<EOF
CyberVerse 控制脚本

  $0 start     启动全部（可重复执行，已在运行的会跳过）
  $0 stop      停止全部
  $0 status    查看状态
  $0 logs      跟踪日志

启动后浏览器打开： http://localhost:5173
EOF
     exit 1 ;;
esac
