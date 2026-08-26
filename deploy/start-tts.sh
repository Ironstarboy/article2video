#!/bin/bash
# 启动 CosyVoice3 TTS 服务(127.0.0.1:8016,GPU1)。服务器上执行。
# 必须先 source PPU SDK 环境(否则 PPU 运行时内核编译报 PPU_SDK/PPU_HOME 缺失)
source /usr/local/PPU_SDK/envsetup.sh 2>/dev/null
pkill -f "tts_serve[r]" 2>/dev/null || true
sleep 1
cd /mnt/workspace/ttv
PYTHONPATH=/mnt/workspace/ttv/cosyvoice-src:/mnt/workspace/ttv/cosyvoice-src/third_party/Matcha-TTS \
CUDA_VISIBLE_DEVICES=1 nohup tts-venv/bin/python -u -m uvicorn tts_server:app \
  --host 127.0.0.1 --port 8016 --app-dir server \
  >> /mnt/workspace/ttv/tts.log 2>&1 &
sleep 25
curl -s http://127.0.0.1:8016/health && echo " ← TTS 服务已启动"
