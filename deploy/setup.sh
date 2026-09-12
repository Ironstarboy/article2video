#!/bin/bash
# 一次性环境准备:目录、字体、gsap、BGM、hyperframes + Chrome。
# 根目录取脚本自身位置(仓库根),不依赖任何工作区外路径。
# 覆盖项:TTV_PYTHON(默认仓库内 .venv,回退 python3)、TTV_NODE_BIN、TTV_SKIP_NGINX=1。
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${TTV_PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY=python3
[ -n "${TTV_NODE_BIN:-}" ] && export PATH="$TTV_NODE_BIN:$PATH"

echo "== node / python =="
node --version
"$PY" --version

echo "== python 依赖 =="
"$PY" -m pip install -q -r server/requirements.txt

echo "== 目录 =="
mkdir -p jobs logs/studio logs/tts assets/fonts assets/bgm assets/vendor web/assets

echo "== 字体(必须完整版 OTF:子集版会渲染方框,历史教训见 docs/问题修复说明) =="
# 保存为代码期望的文件名(server/builder/assemble.py 的 FONT_FILES);
# 注意上游已改名:SourceHanSerifCN→SourceHanSerifSC,NotoSansSC→NotoSansCJKsc。
dl_font() { # <目标文件名> <上游 URL>
  [ -s "assets/fonts/$1" ] || curl -fL --retry 2 -o "assets/fonts/$1" "$2"
}
SH_BASE="https://raw.githubusercontent.com/adobe-fonts/source-han-serif/release/OTF/SimplifiedChinese"
NOTO_BASE="https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese"
dl_font "SourceHanSerifCN-Heavy.otf"   "$SH_BASE/SourceHanSerifSC-Heavy.otf"
dl_font "SourceHanSerifCN-Regular.otf" "$SH_BASE/SourceHanSerifSC-Regular.otf"
dl_font "NotoSansSC-Regular.otf"       "$NOTO_BASE/NotoSansCJKsc-Regular.otf"
dl_font "NotoSansSC-Bold.otf"          "$NOTO_BASE/NotoSansCJKsc-Bold.otf"
ls -la assets/fonts/
for f in assets/fonts/*.otf; do
  sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
  [ "$sz" -ge 10000000 ] || { echo "错误:$f 仅 $sz 字节,疑似子集版(必须完整版 ≥10MB)"; exit 1; }
done

echo "== gsap =="
[ -s assets/vendor/gsap.min.js ] || curl -fL --retry 2 -o assets/vendor/gsap.min.js \
  https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js
head -c 80 assets/vendor/gsap.min.js; echo

echo "== BGM(CC0 占位;可用授权曲目覆盖同名文件) =="
# 三风格 BGM:solemn-red.mp3 / academic-ink.mp3 / modern-blue.mp3
# 下载失败或源已失效时生成 60s 静音占位,渲染流程不受阻;后续人工替换正式曲目
FREEPD_BASE="${TTV_BGM_BASE:-https://freepd.com/music}"
try_dl() { curl -fL --retry 1 -s -o "$1" "$2" && [ -s "$1" ]; }
try_dl assets/bgm/solemn-red.mp3   "$FREEPD_BASE/Epic%20Boss%20Battle.mp3" || true
try_dl assets/bgm/academic-ink.mp3 "$FREEPD_BASE/Ambient%20Classical%20Guitar.mp3" || true
try_dl assets/bgm/modern-blue.mp3  "$FREEPD_BASE/In%20The%20Clouds.mp3" || true
for f in assets/bgm/*.mp3; do
  [ -s "$f" ] || ffmpeg -y -v error -f lavfi -i anullsrc=r=44100:cl=mono -t 60 -q:a 9 "$f"
done
ls -la assets/bgm/

echo "== hyperframes CLI + Chrome(版本与 BUILD.md 一致:0.8.15) =="
npm install -g hyperframes@0.8.15
hyperframes browser ensure
hyperframes doctor || true

if [ "${TTV_SKIP_NGINX:-0}" = "1" ] || [ ! -d /etc/nginx ]; then
  echo "== nginx 跳过(未安装 nginx 或 TTV_SKIP_NGINX=1) =="
  echo "== DONE =="
  exit 0
fi

echo "== nginx =="
cp deploy/nginx-ttv.conf /etc/nginx/ttv-locations.conf
"$PY" - <<'EOF'
p = "/etc/nginx/sites-enabled/comfyui-20013"
try:
    s = open(p).read()
except FileNotFoundError:
    print(f"skip: {p} 不存在(非本机站点配置)")
    raise SystemExit(0)
if "ttv-locations" not in s:
    s = s.replace("    # WebSocket 支持", "    include /etc/nginx/ttv-locations.conf;\n\n    # WebSocket 支持")
    open(p, "w").write(s)
    print("nginx config patched")
else:
    print("already patched")
EOF
nginx -t && service nginx reload && echo "nginx reloaded"

echo "== DONE =="
