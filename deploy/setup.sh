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

echo "== 前端 UI 字体子集(web/index.html 引用的 assets/fonts-woff2/ui-song.woff2) =="
# 不生成的话首屏字体 404,只能回退系统字体(美观度下降,不影响出片)
if "$PY" deploy/make-ui-font.py; then
  # 直连 8015(不经 nginx)时前端根目录是 web/,相对路径 ./assets/ 落在 web/assets/;
  # 走 nginx 时 /ttv/assets/ 已指向仓库根的 assets/,两份都留着才能两种访问方式都对
  mkdir -p web/assets/fonts-woff2
  cp -f assets/fonts-woff2/ui-song.woff2 web/assets/fonts-woff2/
else
  echo "⚠️  UI 字体子集生成失败(见上方报错);网页会回退系统字体,不阻塞出片"
fi

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

echo "== 数字人抠像(可选:只保留人像、背景透明) =="
# 权重约 25MB(MODNet,Apache-2.0);hf-mirror 优先 —— huggingface 直连在国内常不通。
# 失败只警告不中断:抠像是可选增强,没有它成片仍然用圆角卡片出。
MATTE_DIR="models/matte"
MATTE_ONNX="$MATTE_DIR/modnet.onnx"
mkdir -p "$MATTE_DIR"
if [ ! -s "$MATTE_ONNX" ]; then
  for u in "${TTV_MATTE_URL:-https://hf-mirror.com/Xenova/modnet/resolve/main/onnx/model.onnx}" \
           "https://huggingface.co/Xenova/modnet/resolve/main/onnx/model.onnx"; do
    if curl -fL --retry 2 -o "$MATTE_ONNX" "$u"; then break; fi
  done
fi
sz=$(stat -c%s "$MATTE_ONNX" 2>/dev/null || echo 0)
if [ "$sz" -ge 20000000 ]; then
  echo "抠像权重就绪:$MATTE_ONNX($sz 字节)"
else
  rm -f "$MATTE_ONNX"
  echo "⚠️  抠像权重未就绪(下载失败):勾选「只保留人像」时会自动回退圆角卡片"
fi

# onnxruntime 装进抠像解释器(TTV_MATTE_PYTHON,默认 tts-venv;后端自己不引入 onnx)
MATTE_PY="${TTV_MATTE_PYTHON:-$ROOT/tts-venv/bin/python}"
if [ -x "$MATTE_PY" ]; then
  if "$MATTE_PY" -c "import onnxruntime, numpy" 2>/dev/null; then
    echo "抠像运行时已就绪:$("$MATTE_PY" -c 'import onnxruntime;print("onnxruntime", onnxruntime.__version__)')"
  elif [ -x "$ROOT/.tools/bin/uv" ]; then
    "$ROOT/.tools/bin/uv" pip install -q --python "$MATTE_PY" onnxruntime \
      || echo "⚠️  onnxruntime 安装失败(可手动装到 $MATTE_PY)"
  else
    "$MATTE_PY" -m pip install -q onnxruntime \
      || echo "⚠️  onnxruntime 安装失败(可手动装到 $MATTE_PY)"
  fi
else
  echo "⚠️  抠像解释器不存在:$MATTE_PY(可用 TTV_MATTE_PYTHON 指向装有 onnxruntime 的解释器)"
fi

echo "== hyperframes CLI + Chrome =="
# 版本可用 TTV_HYPERFRAMES_VERSION 覆盖;默认与实测环境一致(见 README「从零部署」第 2 步)
HF_VERSION="${TTV_HYPERFRAMES_VERSION:-0.8.34}"
npm install -g "hyperframes@$HF_VERSION"
hyperframes browser ensure
hyperframes doctor || true

if [ "${TTV_SKIP_NGINX:-0}" = "1" ] || [ ! -d /etc/nginx ]; then
  echo "== nginx 跳过(未安装 nginx 或 TTV_SKIP_NGINX=1) =="
  echo "== DONE =="
  exit 0
fi

echo "== nginx =="
# 模板里的 alias 路径是老机器的占位(/mnt/workspace/ttv),按本次实际仓库根替换后再装
sed "s#/mnt/workspace/ttv#$ROOT#g" deploy/nginx-ttv.conf > /etc/nginx/ttv-locations.conf
"$PY" - <<'EOF'
p = "/etc/nginx/sites-enabled/comfyui-20013"
try:
    s = open(p).read()
except FileNotFoundError:
    print(f"skip: {p} 不存在(非本机站点配置)")
    print("      路由文件已生成:/etc/nginx/ttv-locations.conf ——")
    print("      请自行在你的 server 块里加一行:include /etc/nginx/ttv-locations.conf;")
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
