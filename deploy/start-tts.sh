#!/bin/bash
# 启动 CosyVoice3 TTS 多实例池(127.0.0.1:8016/8018/8019,GPU1/2/3)。服务器上执行。
# 客户端按帧轮询分发并行合成(约 ×3 吞吐);单实例故障自动摘除。
# 必须先 source PPU SDK 环境(否则 PPU 运行时内核编译报 PPU_SDK/PPU_HOME 缺失)
source /usr/local/PPU_SDK/envsetup.sh 2>/dev/null
pkill -f "tts_serve[r]" 2>/dev/null || true
sleep 1
cd /mnt/workspace/ttv
mkdir -p logs/tts

# GPU1@8016 / GPU2@8018 / GPU3@8019(8017 预留给 Qwen3-TTS 备用)
# OMP_NUM_THREADS 限制 torch CPU 线程自旋(缓解空载高 CPU 占用)
declare -a GPUS=(1 2 3)
declare -a PORTS=(8016 8018 8019)
for i in 0 1 2; do
  OMP_NUM_THREADS=8 PYTHONPATH=/mnt/workspace/ttv/cosyvoice-src:/mnt/workspace/ttv/cosyvoice-src/third_party/Matcha-TTS \
  CUDA_VISIBLE_DEVICES=${GPUS[$i]} nohup tts-venv/bin/python -u -m uvicorn tts_server:app \
    --host 127.0.0.1 --port ${PORTS[$i]} --app-dir server \
    >> /mnt/workspace/ttv/logs/tts/tts-${PORTS[$i]}.log 2>&1 &
done

# 健康检查:逐个等待实例就绪,至少 1 个存活才算成功
ok=0
for i in 0 1 2; do
  port=${PORTS[$i]}
  for n in $(seq 1 45); do
    if curl -sf http://127.0.0.1:$port/health >/dev/null 2>&1; then
      echo "TTS :$port 就绪(第 ${n} 次探测)"
      ok=$((ok+1))
      break
    fi
    sleep 2
  done
done
if [ "$ok" -lt 1 ]; then
  echo "错误:TTS 实例全部启动失败,日志尾部:" >&2
  tail -5 /mnt/workspace/ttv/logs/tts/tts-*.log 2>/dev/null >&2
  exit 1
fi

# 预热:触发首帧合成使模型完成加载(并行,避免首个任务的配音等待 25s+ 冷启动)
for i in 0 1 2; do
  ( curl -s -X POST http://127.0.0.1:${PORTS[$i]}/tts \
      -H 'Content-Type: application/json' \
      -d '{"text":"大家好,欢迎收看今天的节目。","voice":"male"}' -o /dev/null ) &
done
sleep 40
echo "CosyVoice3 TTS 池启动完成($ok/3 实例就绪,预热请求已发出)"
