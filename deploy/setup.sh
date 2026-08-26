#!/bin/bash
# 在 VideoLab 服务器上执行一次:安装依赖/字体/Chrome/hyperframes,配 nginx
set -e
export PATH=/mnt/workspace/node/bin:$PATH
TTV=/mnt/workspace/ttv
cd "$TTV"

echo "== node/npx =="
node --version
npx --version

echo "== python 依赖 =="
pip3 install -q -r server/requirements.txt || pip3 install -q edge-tts jieba python-multipart

echo "== 目录 =="
mkdir -p jobs assets/fonts assets/bgm assets/vendor

echo "== 字体(思源宋体 CN 子集 + 思源黑体 SC 子集) =="
[ -s assets/fonts/SourceHanSerifCN-Heavy.otf ] || curl -fL --retry 2 -o assets/fonts/SourceHanSerifCN-Heavy.otf \
  https://raw.githubusercontent.com/adobe-fonts/source-han-serif/release/SubsetOTF/CN/SourceHanSerifCN-Heavy.otf
[ -s assets/fonts/SourceHanSerifCN-Regular.otf ] || curl -fL --retry 2 -o assets/fonts/SourceHanSerifCN-Regular.otf \
  https://raw.githubusercontent.com/adobe-fonts/source-han-serif/release/SubsetOTF/CN/SourceHanSerifCN-Regular.otf
[ -s assets/fonts/NotoSansSC-Regular.otf ] || curl -fL --retry 2 -o assets/fonts/NotoSansSC-Regular.otf \
  https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf
[ -s assets/fonts/NotoSansSC-Bold.otf ] || curl -fL --retry 2 -o assets/fonts/NotoSansSC-Bold.otf \
  https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/SubsetOTF/SC/NotoSansSC-Bold.otf
ls -la assets/fonts/

echo "== gsap =="
[ -s assets/vendor/gsap.min.js ] || curl -fL --retry 2 -o assets/vendor/gsap.min.js \
  https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js
head -c 80 assets/vendor/gsap.min.js; echo

echo "== BGM(FreePD CC0 占位;可用授权曲目覆盖同名文件) =="
# 三风格 BGM 文件:solemn-red.mp3 / academic-ink.mp3 / modern-blue.mp3
# 下载失败时生成 60s 静音占位,渲染流程不受阻;后续人工替换正式曲目
try_dl() { curl -fL --retry 1 -s -o "$1" "$2" && [ -s "$1" ]; }

try_dl assets/bgm/solemn-red.mp3 "https://freepd.com/music/Epic%20Boss%20Battle.mp3" || true
try_dl assets/bgm/academic-ink.mp3 "https://freepd.com/music/Ambient%20Classical%20Guitar.mp3" || true
try_dl assets/bgm/modern-blue.mp3 "https://freepd.com/music/In%20The%20Clouds.mp3" || true
for f in assets/bgm/*.mp3; do
  [ -s "$f" ] || ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=mono -t 60 -q:a 9 "$f"
done
ls -la assets/bgm/

echo "== hyperframes CLI + Chrome =="
npx -y hyperframes@latest --version || true
npx -y hyperframes@latest browser ensure
npx -y hyperframes@latest doctor

echo "== nginx =="
cp deploy/nginx-ttv.conf /etc/nginx/ttv-locations.conf
python3 - <<'EOF'
p = "/etc/nginx/sites-enabled/comfyui-20013"
s = open(p).read()
if "ttv-locations" not in s:
    s = s.replace("    # WebSocket 支持", "    include /etc/nginx/ttv-locations.conf;\n\n    # WebSocket 支持")
    open(p, "w").write(s)
    print("nginx config patched")
else:
    print("already patched")
EOF
nginx -t && service nginx reload && echo "nginx reloaded"

echo "== DONE =="
