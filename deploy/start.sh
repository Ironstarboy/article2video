#!/bin/bash
# 启动后端(FastAPI,127.0.0.1:8015)。服务器上执行。
export PATH=/mnt/workspace/node/bin:$PATH
cd /mnt/workspace/ttv
mkdir -p logs/studio logs/tts
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "uvicorn server.main:app" 2>/dev/null || true
pkill -f "hyperframes [p]review" 2>/dev/null || true
sleep 1
nohup python3 -m uvicorn main:app --host 127.0.0.1 --port 8015 --app-dir server \
  >> /mnt/workspace/ttv/logs/backend.log 2>&1 &
# 健康检查:30 次探测,失败打印日志尾部并退出 1
for n in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8015/health >/dev/null 2>&1; then
    echo "← 后端已启动(第 ${n} 次探测)"
    exit 0
  fi
  sleep 1
done
echo "错误:后端启动失败,日志尾部:" >&2
tail -8 /mnt/workspace/ttv/logs/backend.log >&2
exit 1
