#!/bin/bash
# ttv(理论文章转视频)全栈一键管理 —— 后端与网页(8015)+ 配音 CosyVoice3(8016)+ 数字人 CyberVerse(50051)
#
#   bash deploy/start-all.sh              一键起全栈(默认;已在跑的**自动跳过**,不重启、不打断进行中的任务)
#   bash deploy/start-all.sh --no-avatar  只起后端 + 配音(纯 PPT 视频够用,省掉数字人预热)
#   bash deploy/start-all.sh --no-wait    只负责拉起,不在前台等就绪
#   bash deploy/start-all.sh restart      强制全部重启(等价 start --force)
#   bash deploy/start-all.sh status       看状态(端口 / 健康 / 就绪度 / GPU)
#   bash deploy/start-all.sh logs         跟踪三份日志(Ctrl+C 只退出查看,不停服务)
#   bash deploy/start-all.sh stop         停全栈(会中断进行中的任务;终端下会问一次,脚本里加 --yes 跳过)
#
# 为什么默认"跳过已在跑的":三个服务互相独立,经常是"补起缺的那个"。
# 老的 start-all 每次无脑 pkill 重启,补一个就丢一个、还会把正在跑的任务打断 —— 那正是要修掉的病。
#
# 覆盖项:TTV_PORT(8015)、TTV_TTS_PORTS("8016" 或 "8016 8018 8019")、TTV_AVATAR_ADDR。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

BE_PORT="${TTV_PORT:-8015}"
TTS_PORTS=(${TTV_TTS_PORTS:-8016})
TTS_PORT="${TTS_PORTS[0]}"
AV_ADDR="${TTV_AVATAR_ADDR:-127.0.0.1:50051}"
AV_PORT="${AV_ADDR##*:}"
LOG="$ROOT/logs"
mkdir -p "$LOG/tts" "$LOG/avatar"

c_ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m%s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m%s\033[0m\n' "$*"; }
c_dim()  { printf '\033[2m%s\033[0m\n' "$*"; }

# ── 探针 ────────────────────────────────────────────────────────────────
port_busy() { ss -ltn 2>/dev/null | grep -q ":$1 "; }
proc_up()   { pgrep -f "$1" >/dev/null 2>&1; }
pid_of() {  # 端口 → pid(取不到就空)
  ss -ltnp 2>/dev/null | grep ":$1 " | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -1
}
http_ok()  { curl -sf -m 5 "$1" >/dev/null 2>&1; }

# "在跑"=端口占着或进程还在(数字人在载模型时端口还没开,只看端口会重复拉起)
be_up()  { port_busy "$BE_PORT"; }
tts_up() { local p; for p in "${TTS_PORTS[@]}"; do port_busy "$p" && return 0; done; proc_up "uvicorn tts_server:app"; }
av_up()  { port_busy "$AV_PORT" || proc_up "inference.server"; }

be_ready()  { http_ok "http://127.0.0.1:$BE_PORT/health"; }
tts_ready() { http_ok "http://127.0.0.1:$TTS_PORT/health"; }
# 数字人必须走 gRPC 探活:端口开了 != 模型就绪(载权重 + torch.compile 期间端口就已经在听)
av_ready() {
  local py="$ROOT/.venv/bin/python"
  [ -x "$py" ] || return 1
  "$py" -c "
import sys; sys.path.insert(0, '$ROOT/server')
import avatar
sys.exit(0 if avatar.probe().get('available') else 1)
" >/dev/null 2>&1
}

wait_ready() {  # <名称> <就绪函数> <超时秒> <日志提示>
  local name="$1" fn="$2" tmo="$3" logfile="${4:-}" t=0
  while :; do
    if "$fn"; then c_ok "  [就绪] $name(等待 ${t}s)"; return 0; fi
    [ "$t" -ge "$tmo" ] && break
    sleep 5; t=$((t + 5))
    [ $((t % 30)) -eq 0 ] && c_dim "         … $name 仍在加载(${t}s/$tmo s)"
  done
  c_err "  [超时] $name ${tmo}s 内未就绪"
  [ -n "$logfile" ] && { echo "        日志尾部($logfile):"; tail -4 "$logfile" 2>/dev/null | sed 's/^/          /'; }
  return 1
}

# ── start ──────────────────────────────────────────────────────────────
cmd_start() {
  local force=0 with_avatar=1 do_wait=1
  for a in "$@"; do
    case "$a" in
      --force)     force=1 ;;
      --no-avatar) with_avatar=0 ;;
      --no-wait)   do_wait=0 ;;
    esac
  done

  echo "════════ ttv 全栈启动 ════════"
  local started_tts=0 started_av=0 started_be=0

  # 配音(CosyVoice3 实例池)
  if [ "$force" -eq 0 ] && tts_up; then
    c_ok "  [跳过] 配音已在运行(端口 $TTS_PORT)"
  else
    echo "  [启动] 配音 CosyVoice3(端口 ${TTS_PORTS[*]})…"
    bash "$ROOT/deploy/start-tts.sh" >"$LOG/tts.start.log" 2>&1 &
    started_tts=1
  fi

  # 数字人(CyberVerse gRPC):载权重 + torch.compile,首次 3-6 分钟
  if [ "$with_avatar" -eq 0 ]; then
    c_warn "  [跳过] 数字人(--no-avatar):纯 PPT 视频不需要它"
  elif [ "$force" -eq 0 ] && av_up; then
    c_ok "  [跳过] 数字人已在运行/加载中(:$AV_PORT)"
  else
    echo "  [启动] 数字人 CyberVerse(:$AV_PORT,首次 3-6 分钟,后台加载中)…"
    bash "$ROOT/deploy/start-avatar.sh" >"$LOG/avatar.start.log" 2>&1 &
    started_av=1
  fi

  # 后端与网页(脚本自带 30s 健康探测,前台跑,很快)
  if [ "$force" -eq 0 ] && be_up && be_ready; then
    c_ok "  [跳过] 后端与网页已在运行(端口 $BE_PORT)"
  else
    echo "  [启动] 后端与网页(端口 $BE_PORT)…"
    bash "$ROOT/deploy/start.sh" >"$LOG/backend.start.log" 2>&1 &
    started_be=1
  fi

  if [ "$do_wait" -eq 1 ]; then
    echo
    echo "── 等待就绪(可先用网页做纯 PPT 视频,不影响) ──"
    [ "$started_be" -eq 1 ] && wait_ready "后端与网页 :$BE_PORT" be_ready 90 "$LOG/backend.start.log"
    be_ready || c_warn "  [警告] 后端未就绪,看 $LOG/backend.start.log"
    [ "$started_tts" -eq 1 ] && wait_ready "配音 :$TTS_PORT" tts_ready 300 "$LOG/tts.start.log"
    if [ "$with_avatar" -eq 1 ]; then
      av_ready || wait_ready "数字人 :$AV_PORT" av_ready 600 "$LOG/avatar/inference.log"
    fi
  else
    c_dim "  (--no-wait:已后台拉起,稍后用 '$0 status' 查看)"
  fi

  echo
  cmd_status
}

# ── status ─────────────────────────────────────────────────────────────
cmd_status() {
  local line
  echo "════════ ttv 状态 ════════"
  line="后端与网页"; if be_up; then
    if be_ready; then printf '  %-12s :%-5s \033[32m就绪\033[0m   pid %s  http://127.0.0.1:%s/\n' "$line" "$BE_PORT" "$(pid_of "$BE_PORT")" "$BE_PORT"
    else printf '  %-12s :%-5s \033[33m监听中但未就绪\033[0m  pid %s\n' "$line" "$BE_PORT" "$(pid_of "$BE_PORT")"; fi
  else printf '  %-12s :%-5s \033[31m未运行\033[0m\n' "$line" "$BE_PORT"; fi

  line="配音 TTS"; if tts_up; then
    if tts_ready; then printf '  %-12s :%-5s \033[32m就绪\033[0m   pid %s  %s\n' "$line" "$TTS_PORT" "$(pid_of "$TTS_PORT")" "$(curl -sf -m 5 "http://127.0.0.1:$TTS_PORT/health" | head -c 60)"
    else printf '  %-12s :%-5s \033[33m监听中但未就绪\033[0m  pid %s\n' "$line" "$TTS_PORT" "$(pid_of "$TTS_PORT")"; fi
  else printf '  %-12s :%-5s \033[31m未运行\033[0m\n' "$line" "$TTS_PORT"; fi

  line="数字人"; if av_up; then
    if av_ready; then printf '  %-12s :%-5s \033[32m就绪\033[0m   pid %s  avatar.flash_head\n' "$line" "$AV_PORT" "$(pid_of "$AV_PORT")"
    else printf '  %-12s :%-5s \033[33m加载中(载权重/预热)\033[0m  pid %s\n' "$line" "$AV_PORT" "$(pid_of "$AV_PORT")"; fi
  else printf '  %-12s :%-5s \033[31m未运行\033[0m\n' "$line" "$AV_PORT"; fi

  line="Studio"; local sp; sp=$(ss -ltn 2>/dev/null | sed -n 's/.*127\.0\.0\.1:\(41[5-9][0-9]\) .*/\1/p' | head -3 | tr '\n' ' ')
  if [ -n "$sp" ]; then printf '  %-12s %s \033[32m按需运行\033[0m(每任务预览,随任务开关)\n' "$line" "$sp"
  else printf '  %-12s \033[2m无(按需:打开预览时才拉起)\033[0m\n' "$line"; fi

  # nginx:对外 /ttv/ 走它;没装也能用 8015 直连
  if pgrep -x nginx >/dev/null 2>&1; then printf '  %-12s \033[32m运行中\033[0m(对外 /ttv/ 可用)\n' "nginx"
  else printf '  %-12s \033[2m未运行(对外 /ttv/ 不可用;本机 http://127.0.0.1:%s/ 照常)\033[0m\n' "nginx" "$BE_PORT"; fi

  if command -v nvidia-smi >/dev/null 2>&1; then
    printf '  %-12s %s\n' "GPU" "$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null | head -1)"
  fi
  if be_ready; then
    local j; j=$(curl -sf -m 5 "http://127.0.0.1:$BE_PORT/api/jobs" 2>/dev/null \
      | "$ROOT/.venv/bin/python" -c "import json,sys;d=json.load(sys.stdin);print(d.get('total'))" 2>/dev/null)
    [ -n "${j:-}" ] && printf '  %-12s %s 个(最近的在网页「项目历史」里)\n' "任务" "$j"
  fi
}

# ── stop ───────────────────────────────────────────────────────────────
cmd_stop() {
  local assume_yes=0
  for a in "$@"; do [ "$a" = "--yes" ] || [ "$a" = "-y" ] && assume_yes=1; done
  echo "════════ ttv 停止 ════════"
  local busy=0
  if be_ready; then
    busy=$(curl -sf -m 5 "http://127.0.0.1:$BE_PORT/api/jobs" 2>/dev/null \
      | "$ROOT/.venv/bin/python" -c "import json,sys;d=json.load(sys.stdin);print(sum(1 for j in d.get('jobs',[]) if j.get('status') in ('analyzing','building','avatar_building','rendering')))" 2>/dev/null)
  fi
  if [ "${busy:-0}" != "0" ]; then
    c_warn "  有 $busy 个任务正在进行中,停服务会把它们标为 failed(可重新分析)"
  fi
  # 交互式终端下确认一次;非交互(脚本/管道)直接执行,别让自动化卡在提示上
  if [ "$assume_yes" -eq 0 ] && [ -t 0 ]; then
    read -r -p "  确认停止全栈?[y/N] " _ans
    case "$_ans" in y|Y|yes|YES) ;; *) c_warn "  已取消"; return 0 ;; esac
  fi

  stop_pat() { # <显示名> <pkill 模式>
    if pgrep -f "$2" >/dev/null 2>&1; then
      pkill -TERM -f "$2" 2>/dev/null
      c_ok "  [停止] $1"
    else
      c_dim "  [跳过] $1(没在跑)"
    fi
  }
  stop_pat "后端与网页" "uvicorn main:app"
  stop_pat "后端与网页(备用名)" "uvicorn server.main:app"
  stop_pat "配音 TTS" "tts_serve[r]"
  stop_pat "数字人" "inference.server"
  stop_pat "Studio 预览" "hyperframes [p]review"
  sleep 3
  echo
  cmd_status
}

# ── logs ───────────────────────────────────────────────────────────────
cmd_logs() {
  echo "跟踪日志(Ctrl+C 只退出查看,不会停服务):"
  c_dim "  $LOG/backend.log · $LOG/tts/tts-$TTS_PORT.log · $LOG/avatar/inference.log"
  touch "$LOG/backend.log" "$LOG/tts/tts-$TTS_PORT.log" "$LOG/avatar/inference.log"
  tail -n 20 -f "$LOG/backend.log" "$LOG/tts/tts-$TTS_PORT.log" "$LOG/avatar/inference.log"
}

usage() {
  sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
}

case "${1:-start}" in
  start)   shift || true; cmd_start "$@" ;;
  restart) cmd_start --force "${@:2}" ;;
  status)  cmd_status ;;
  stop)    shift || true; cmd_stop "$@" ;;
  logs)    cmd_logs ;;
  -h|--help|help) usage ;;
  --no-avatar|--no-wait|--force) cmd_start "$@" ;;
  *) c_err "未知子命令:$1"; echo; usage; exit 1 ;;
esac
