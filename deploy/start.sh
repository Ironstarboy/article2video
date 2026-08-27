#!/bin/bash
# 启动后端(FastAPI,127.0.0.1:8015)。服务器上执行。
export PATH=/mnt/workspace/node/bin:$PATH
cd /mnt/workspace/ttv
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "hyperframes [p]review" 2>/dev/null || true
sleep 1
nohup python3 -m uvicorn main:app --host 127.0.0.1 --port 8015 --app-dir server \
  >> /mnt/workspace/ttv/backend.log 2>&1 &
sleep 3
curl -s http://127.0.0.1:8015/health && echo " ← 后端已启动"
