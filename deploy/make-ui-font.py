# -*- coding: utf-8 -*-
"""生成前端 UI 字体子集 assets/fonts-woff2/ui-song.woff2(思源宋体 Heavy)。

网页端(web/index.html)此前直接引用 12MB+ 完整 OTF,外网首屏需下载数十 MB;
本脚本按「页面固定文案 + 后端下发的全部固定字符串」提取用字,子集化为
woff2(约 100-300KB),缺失字由系统字体回退(unlimited fallback)。

在服务器上执行(需 fonttools):
    python3 deploy/make-ui-font.py
"""
import re
from pathlib import Path

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent

# 兜底字符集(数字/序号/标点/常见词,防止边缘文案缺字)
BASE = (
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "壹贰叁肆伍陆柒捌玖拾百千万亿零"
    "，。、;:!?()()《》「」『』“”‘’·—…%+×/↓←→│"
    "庄重肃穆中国红清雅学术墨黛青现代锐意科技蓝藏蓝赭编辑部理论文章转视频工作台"
)

chars = set(BASE)
# 扫描前端与后端源码中的全部固定文案(前端界面会展示后端的名称/进度文案)
sources = (
    [ROOT / "web" / "index.html"]
    + sorted((ROOT / "server").glob("*.py"))
    + sorted((ROOT / "server" / "builder").glob("*.py"))
)
for src in sources:
    if not src.exists():
        continue
    text = src.read_text(encoding="utf-8", errors="ignore")
    for ch in text:
        if ("一" <= ch <= "鿿") or ch.isascii():
            chars.add(ch)

subset_text = "".join(sorted(chars))
src_font = ROOT / "assets" / "fonts" / "SourceHanSerifCN-Heavy.otf"
if not src_font.exists():
    raise SystemExit(f"源字体不存在:{src_font}(请先执行 deploy/setup.sh 下载完整版字体)")

font = TTFont(str(src_font))
opts = Options()
opts.flavor = "woff2"
opts.desubroutinize = False
ss = Subsetter(opts)
ss.populate(text=subset_text)
ss.subset(font)

out_dir = ROOT / "assets" / "fonts-woff2"
out_dir.mkdir(parents=True, exist_ok=True)
out = out_dir / "ui-song.woff2"
font.save(str(out))
size_kb = out.stat().st_size / 1024
print(f"ui-song.woff2 已生成:{len(chars)} 字符,{size_kb:.0f} KB")
if size_kb > 800:
    print("警告:子集超过 800KB,建议检查字符收集范围")
