#!/bin/bash
# 启动后端(FastAPI,127.0.0.1:8015)。
# 根目录取脚本自身位置(仓库根),不再依赖任何工作区外路径。
# 可用环境变量覆盖:TTV_PORT(默认 8015)、TTV_PYTHON(默认用仓库内 .venv,回退 python3)、TTV_NODE_BIN。
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

if [ -n "$TTV_NODE_BIN" ]; then
  export PATH="$TTV_NODE_BIN:$PATH"
fi
# 本地密钥/端点(不入库):存在则加载,便于本机直接 restart 而不必每次手传环境变量
if [ -f "$ROOT/.secrets/llm.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.secrets/llm.env"
  set +a
fi
PORT="${TTV_PORT:-8015}"
PY="${TTV_PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY=python3

mkdir -p logs/studio logs/tts
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "uvicorn server.main:app" 2>/dev/null || true
pkill -f "hyperframes [p]review" 2>/dev/null || true
sleep 1
nohup "$PY" -m uvicorn main:app --host 127.0.0.1 --port "$PORT" --app-dir server \
  >> "$ROOT/logs/backend.log" 2>&1 &
# 健康检查:30 次探测,失败打印日志尾部并退出 1
for n in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "← 后端已启动(第 ${n} 次探测,端口 $PORT)"
    exit 0
  fi
  sleep 1
done
echo "错误:后端启动失败,日志尾部:" >&2
tail -8 "$ROOT/logs/backend.log" >&2
exit 1
