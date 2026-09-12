#!/bin/bash
# 启动 Qwen3-TTS 服务(默认 127.0.0.1:8017)。备用引擎,默认不启动。
# 根目录取脚本自身位置(仓库根);覆盖项 TTV_QWEN_TTS_PORT / TTV_QWEN_TTS_GPU / TTV_QWEN_TTS_VENV。
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

if [ -f /usr/local/PPU_SDK/envsetup.sh ]; then
  # shellcheck disable=SC1091
  source /usr/local/PPU_SDK/envsetup.sh
fi

pkill -f "tts_qwen_serve[r]" 2>/dev/null || true
sleep 1
mkdir -p logs/tts

PORT="${TTV_QWEN_TTS_PORT:-8017}"
GPU="${TTV_QWEN_TTS_GPU:-0}"
VENV="${TTV_QWEN_TTS_VENV:-$ROOT/tts-qwen-venv}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "错误:Qwen3-TTS venv 不存在($VENV/bin/python)" >&2
  exit 1
fi

CUDA_VISIBLE_DEVICES="$GPU" nohup "$VENV/bin/python" -u -m uvicorn tts_qwen_server:app \
  --host 127.0.0.1 --port "$PORT" --app-dir server \
  >> "$ROOT/logs/tts/tts-qwen.log" 2>&1 &

# 健康检查:30 次探测,失败打印日志尾部并退出 1
for n in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "← Qwen3-TTS 服务已启动(第 ${n} 次探测,端口 $PORT)"
    exit 0
  fi
  sleep 2
done
echo "错误:Qwen3-TTS 启动失败,日志尾部:" >&2
tail -8 "$ROOT/logs/tts/tts-qwen.log" >&2
exit 1
