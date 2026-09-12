#!/bin/bash
# 一键启动 article2video 本地全栈:
#   数字人服务(50051) + 配音服务(8016) + 后端与网页(8015)
#
# 三个服务互相独立:只做纯 PPT 视频时可以不起数字人;
# 需要"数字人出镜"时才必须起数字人服务(首次 3-6 分钟)。
#
# 用法:bash deploy/start-all.sh [--no-avatar]
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_AVATAR=1
[ "${1:-}" = "--no-avatar" ] && WITH_AVATAR=0

echo "════════ 启动 article2video ════════"
if [ "$WITH_AVATAR" = "1" ]; then
  echo "── 数字人服务(后台启动,首次 3-6 分钟) ──"
  bash "$ROOT/deploy/start-avatar.sh" >"$ROOT/logs/avatar.start.log" 2>&1 &
  AVATAR_PID=$!
else
  echo "── 已跳过数字人服务(--no-avatar) ──"
  AVATAR_PID=""
fi

echo "── 配音服务(后台启动) ──"
bash "$ROOT/deploy/start-tts.sh" >"$ROOT/logs/tts.start.log" 2>&1 &
TTS_PID=$!

echo "── 后端与网页 ──"
bash "$ROOT/deploy/start.sh"

PORT="${TTV_PORT:-8015}"
echo
echo "════════ 状态 ════════"
ss -ltn 2>/dev/null | grep -E ":(50051|8016|$PORT) " | awk '{print "  监听中: "$4}' || true
echo
echo "  网页入口:   http://localhost:$PORT/"
echo "  接口文档:   http://localhost:$PORT/docs"
echo "  启动日志:   $ROOT/logs/avatar.start.log · $ROOT/logs/tts.start.log"
echo

if [ "$WITH_AVATAR" = "1" ]; then
  echo "等待数字人服务就绪(可先用网页做纯 PPT 视频,不影响)…"
  wait "$AVATAR_PID" && echo "  ✅ 数字人服务已就绪,可勾选\"数字人出镜\"" \
                    || { echo "  ⚠️ 数字人服务未就绪,详见 logs/avatar/inference.log"; tail -5 "$ROOT/logs/avatar/inference.log" 2>/dev/null; }
fi
