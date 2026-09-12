#!/bin/bash
# 启动数字人推理服务(CyberVerse + FlashHead,gRPC 127.0.0.1:50051)。
# 只有开启"数字人出镜"的任务才需要它;首次加载模型 + torch.compile 预热约 3-6 分钟。
#
# 覆盖项:TTV_CYBERVERSE_DIR(默认 <仓库根>/CyberVerse-main)、TTV_AVATAR_ADDR。
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CV="${TTV_CYBERVERSE_DIR:-$ROOT/CyberVerse-main}"
ADDR="${TTV_AVATAR_ADDR:-127.0.0.1:50051}"
PORT="${ADDR##*:}"

if [ ! -x "$CV/.venv/bin/python" ]; then
  echo "错误:找不到 CyberVerse 环境($CV/.venv/bin/python)。" >&2
  echo "  它作为第三方项目单独拉取,不被本仓库跟踪;可用 TTV_CYBERVERSE_DIR 指定位置。" >&2
  exit 1
fi
if [ ! -f "$CV/config/cyberverse.yaml" ]; then
  echo "错误:缺少 $CV/config/cyberverse.yaml(先在 CyberVerse 里 cp -r infra/config config)" >&2
  exit 1
fi

mkdir -p "$ROOT/logs/avatar"
pkill -f "inference.server" 2>/dev/null || true
pkill -f "scripts/generate_proto.sh" 2>/dev/null || true
sleep 2

echo "== 启动数字人服务(首次约 3-6 分钟:加载权重 + torch.compile 预热) =="
(
  cd "$CV" || exit 1
  # HOME 必须落在工作区内($HOME 可能是只读的 /root,且默认缓存会写到工作区外);
  # GOPROXY 必须指国内镜像:inference.sh 会跑 generate_proto.sh 的 Go 代码生成,
  # 走 proxy.golang.org 会超时,把整个启动卡死在这里。
  HOME="$ROOT/.home" \
  GOPROXY="${GOPROXY:-https://goproxy.cn,direct}" \
  TORCHINDUCTOR_CACHE_DIR="${TORCHINDUCTOR_CACHE_DIR:-$ROOT/.cache/torch_inductor}" \
  HF_HOME="${HF_HOME:-$ROOT/.cache/huggingface}" \
  PYTHON="$CV/.venv/bin/python" \
  nohup ./scripts/inference.sh config/cyberverse.yaml \
    >> "$ROOT/logs/avatar/inference.log" 2>&1 &
)

# 健康检查:用项目的 avatar 模块做 gRPC 探活(能区分"端口开了"与"模型真就绪")
PROBE_PY="$ROOT/.venv/bin/python"
for n in $(seq 1 90); do
  sleep 6
  if [ -x "$PROBE_PY" ]; then
    OUT=$("$PROBE_PY" -c "
import sys; sys.path.insert(0, '$ROOT/server')
import avatar
i = avatar.probe()
print(f\"{i.get('model')} {i.get('server_size')} {i.get('fps')}fps\" if i.get('available') else 'not-ready')
sys.exit(0 if i.get('available') else 1)
" 2>/dev/null)
    if [ $? -eq 0 ]; then
      echo "← 数字人服务已就绪(第 $((n * 6)) 秒):$OUT"
      exit 0
    fi
  else
    ss -ltn 2>/dev/null | grep -q ":$PORT " && { echo "← 端口 $PORT 已监听(未做 gRPC 探活)"; exit 0; }
  fi
done

echo "错误:数字人服务 540 秒内未就绪,日志尾部:" >&2
tail -12 "$ROOT/logs/avatar/inference.log" >&2
exit 1
