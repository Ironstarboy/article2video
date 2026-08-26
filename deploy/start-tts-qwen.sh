#!/bin/bash
# 启动 Qwen3-TTS 服务(127.0.0.1:8017,GPU2)。服务器上执行。
source /usr/local/PPU_SDK/envsetup.sh 2>/dev/null
pkill -f "tts_qwen_serve[r]" 2>/dev/null || true
sleep 1
cd /mnt/workspace/ttv
CUDA_VISIBLE_DEVICES=2 nohup tts-qwen-venv/bin/python -u -m uvicorn tts_qwen_server:app \
  --host 127.0.0.1 --port 8017 --app-dir server \
  >> /mnt/workspace/ttv/tts-qwen.log 2>&1 &
sleep 10
curl -s http://127.0.0.1:8017/health && echo " ← Qwen3-TTS 服务已启动"
