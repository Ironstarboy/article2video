#!/bin/bash
# 启动 CosyVoice3 TTS 实例池,默认**单卡单实例** 127.0.0.1:8016(本地开发即此形态)。
# 根目录取脚本自身位置(仓库根);权重/venv/源码全部在工作区内,不依赖工作区外路径。
#
# 覆盖项:
#   TTV_TTS_GPUS="1 2 3" TTV_TTS_PORTS="8016 8018 8019"   # 多卡多实例(生产部署)
#   TTV_TTS_VENV=<venv 路径>  TTV_COSYVOICE_SRC=<CosyVoice 源码路径>
#   TTV_UVICORN_APP_DIR(默认 server)
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

# PPU 平台需先 source SDK(非 PPU 机器没有该文件,跳过即可)
if [ -f /usr/local/PPU_SDK/envsetup.sh ]; then
  # shellcheck disable=SC1091
  source /usr/local/PPU_SDK/envsetup.sh
fi

pkill -f "tts_serve[r]" 2>/dev/null || true
sleep 1
mkdir -p logs/tts

GPUS=(${TTV_TTS_GPUS:-0})
PORTS=(${TTV_TTS_PORTS:-8016})
COUNT=${#PORTS[@]}
VENV="${TTV_TTS_VENV:-$ROOT/tts-venv}"
COSYVOICE_SRC="${TTV_COSYVOICE_SRC:-$ROOT/cosyvoice-src}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "错误:TTS venv 不存在($VENV/bin/python)。先按 docs/BUILD.md 第四节创建。" >&2
  exit 1
fi

for ((i = 0; i < COUNT; i++)); do
  gpu="${GPUS[$i]:-${GPUS[0]:-0}}"
  port="${PORTS[$i]}"
  # OMP_NUM_THREADS 限制 torch CPU 线程自旋(缓解空载高 CPU 占用)
  OMP_NUM_THREADS=8 \
  PYTHONPATH="$COSYVOICE_SRC:$COSYVOICE_SRC/third_party/Matcha-TTS" \
  CUDA_VISIBLE_DEVICES="$gpu" nohup "$VENV/bin/python" -u -m uvicorn tts_server:app \
    --host 127.0.0.1 --port "$port" --app-dir server \
    >> "$ROOT/logs/tts/tts-$port.log" 2>&1 &
done

# 健康检查:逐个等待实例就绪,至少 1 个存活才算成功
ok=0
for ((i = 0; i < COUNT; i++)); do
  port="${PORTS[$i]}"
  for n in $(seq 1 45); do
    if curl -sf "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
      echo "TTS :$port 就绪(第 ${n} 次探测)"
      ok=$((ok + 1))
      break
    fi
    sleep 2
  done
done
if [ "$ok" -lt 1 ]; then
  echo "错误:TTS 实例全部启动失败,日志尾部:" >&2
  tail -5 "$ROOT"/logs/tts/tts-*.log 2>/dev/null >&2
  exit 1
fi

# 预热:触发首帧合成使模型完成加载(避免首个任务的配音等 25s+ 冷启动)
for ((i = 0; i < COUNT; i++)); do
  (curl -s -X POST "http://127.0.0.1:${PORTS[$i]}/tts" \
    -H 'Content-Type: application/json' \
    -d '{"text":"大家好,欢迎收看今天的节目。","voice":"male"}' -o /dev/null) &
done
sleep 40
echo "CosyVoice3 TTS 池启动完成($ok/$COUNT 实例就绪,预热请求已发出)"
