#!/bin/bash
# 启动 Qwen3-TTS 服务(127.0.0.1:8017,GPU2)。服务器上执行。
source /usr/local/PPU_SDK/envsetup.sh 2>/dev/null
pkill -f "tts_qwen_serve[r]" 2>/dev/null || true
sleep 1
cd /mnt/workspace/ttv
mkdir -p logs/tts
CUDA_VISIBLE_DEVICES=2 nohup tts-qwen-venv/bin/python -u -m uvicorn tts_qwen_server:app \
  --host 127.0.0.1 --port 8017 --app-dir server \
  >> /mnt/workspace/ttv/logs/tts/tts-qwen.log 2>&1 &
# 健康检查:30 次探测,失败打印日志尾部并退出 1
for n in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8017/health >/dev/null 2>&1; then
    echo "← Qwen3-TTS 服务已启动(第 ${n} 次探测)"
    exit 0
  fi
  sleep 2
done
echo "错误:Qwen3-TTS 启动失败,日志尾部:" >&2
tail -8 /mnt/workspace/ttv/logs/tts/tts-qwen.log >&2
exit 1
