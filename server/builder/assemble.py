# -*- coding: utf-8 -*-
"""组装器:script.json + VO 时间轴 → HyperFrames 项目(index.html + assets)。

结构:
project/
├── index.html
├── assets/
│   ├── fonts/        (共享字体复制)
│   ├── vendor/gsap.min.js
│   ├── audio/vo_XX.mp3
│   └── bgm/bgm.mp3   (按总时长循环补齐 + 结尾淡出)
└── renders/
"""
import json
import shutil
import subprocess
from pathlib import Path

from config import ASSETS_DIR, BGM_DIR, FONTS_DIR, VENDOR_DIR
from builder import styles, templates
from tts import VO_OFFSET

PUSH_DUR = 0.4
CAPTION_BOTTOM = 86

FONT_SOURCES = {
    "SongHeavy": "SourceHanSerifCN-Heavy.otf",
    "Song": "SourceHanSerifCN-Regular.otf",
    "Sans": "NotoSansSC-Regular.otf",
    "SansBold": "NotoSansSC-Bold.otf",
}

# 子集化时始终保留的字符(模板固定文案 + 数字/标点/序号字)
SAFE_CHARS = (
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "一二三四五六七八九十百千万亿零壹贰叁肆伍陆柒捌玖拾"
    "，。、;:!?()()《》「」『』""''·—…%-+×/\n\t"
    "第章节帧总时长来源作者核心观点论证结构视觉化元素转场旁白画面类型"
    "庄重肃穆中国红清雅学术墨黛青现代锐意科技蓝藏蓝赭编辑部"
    "字体配色背景动效政论经典书香学术时代前沿其一其二其三其四"
    "上传文件粘贴文字开始分析构建预览渲染成片播放器编辑器已选择此风格"
    "理论文章转视频工作台分钟秒"
    "原文本段作用批注注可迁移写法注意逐句"
)


def build_font_faces(page_text: str) -> str:
    """字体子集化 + base64 内嵌。

    原因:hyperframes 内置静态服务器把一切资源按 text/html 下发,
    Chrome 严格校验字体 MIME 会拒绝加载 → 渲染全部方框;内嵌彻底绕过。
    同时按本任务实际用到的字符子集化(每个任务 1-2MB,而非全量 54MB)。
    """
    import base64
    import io
    from fontTools.subset import Subsetter, Options
    from fontTools.ttLib import TTFont
    text = page_text + SAFE_CHARS
    faces = []
    for fam, fname in FONT_SOURCES.items():
        src = FONTS_DIR / fname
        if not src.exists():
            faces.append(
                f"@font-face{{font-family:'{fam}';src:url(\"assets/fonts/{fname}\") "
                f"format(\"opentype\");font-weight:normal;font-style:normal;}}")
            continue
        f = TTFont(str(src))
        opts = Options()
        opts.flavor = "woff2"
        ss = Subsetter(opts)
        ss.populate(text=text)
        ss.subset(f)
        buf = io.BytesIO()
        f.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        faces.append(
            f"@font-face{{font-family:'{fam}';src:url(data:font/woff2;base64,{b64}) "
            f"format('woff2');font-weight:normal;font-style:normal;}}")
    return "\n".join(faces)


def _comp_id(project_dir: Path) -> str:
    """composition id 每任务唯一(Studio 以其为项目 id,供后端反查任务)。"""
    return "ttv" + project_dir.parent.name


def build(script: dict, style_key: str, vo: dict, project_dir: Path) -> dict:
    """生成 HyperFrames 项目。返回 {total, starts: {frame_index: 绝对开始秒}}。"""
    style = styles.get(style_key)
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "renders").mkdir(parents=True, exist_ok=True)
    # 重建时清理旧 BGM(renders 成片保留;配音由 stage_build 在合成前清理,
    # 这里绝不能再删 assets/audio——会把刚合成的配音删光导致成片无声)
    bgm_dir = project_dir / "assets" / "bgm"
    if bgm_dir.exists():
        shutil.rmtree(bgm_dir)
    bgm_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "assets" / "audio").mkdir(parents=True, exist_ok=True)
    _copy_shared(project_dir)

    frames = script["frames"]
    # 1) 计划开始时间(基于调整后的时长)
    starts = {}
    s = 0.0
    for f in frames:
        starts[f["index"]] = s
        s += float(f["duration"])
    total = round(s, 2)

    # 2) 逐帧渲染
    sections, captions, audios, js = [], [], [], []
    for f in frames:
        i = f["index"]
        S = starts[i]
        D = float(f["duration"])
        sec_html, cap_html, js_lines = templates.render_frame(
            f, style, S, {"title": script.get("title", ""), "total": len(frames)})

        # 转场:crossfade / push_up 提前入场
        trans = f.get("transition_in", "cut")
        shift = 0.0
        if trans == "crossfade":
            shift = style["overlap"]
        elif trans == "push_up":
            # 仅明快动效允许上推;其余动效转场退化为 cut
            if not style.get("push_up_ok"):
                trans = "cut"
                shift = 0.0
            else:
                shift = PUSH_DUR
        if shift > 0 and i != frames[0]["index"]:
            start, dur = S - shift, D + shift
            if trans == "crossfade":
                js.append(f'tl.from("#sec{i}",{{opacity:0,duration:{shift},ease:"power1.out"}},{S - shift});')
            else:
                js.append(f'tl.from("#sec{i}",{{y:1080,duration:{PUSH_DUR},ease:"power3.out"}},{S - shift});')
        else:
            start, dur = S, D
        sec_html = sec_html.replace(templates.S_PLACEHOLDER, f"{start:.2f}").replace(
            templates.D_PLACEHOLDER, f"{dur:.2f}")
        sections.append(sec_html)
        js += [ln.replace("##S##", f"{S:.2f}") for ln in js_lines]

        # 字幕(有旁白的帧)
        if i in vo and vo[i]["words"]:
            cap_html, cap_js = templates.render_caption(i, style, vo[i]["words"])
            cap_html = cap_html.replace(templates.S_PLACEHOLDER, f"{start:.2f}").replace(
                templates.D_PLACEHOLDER, f"{dur:.2f}")
            captions.append(cap_html)
            # 字幕 clip 跟随帧入场淡入
            if shift > 0 and trans == "crossfade":
                js.append(f'tl.from("#capsec{i}",{{opacity:0,duration:{shift}}},{S - shift});')
            js += [ln.replace("##S##", f"{S:.2f}") for ln in cap_js]
            audios.append(f'<audio id="vo-{i}" src="assets/audio/vo_{i:02d}.mp3" preload="auto" '
                          f'data-start="{S + VO_OFFSET:.2f}" data-volume="1"></audio>')

    # 3) BGM(循环补齐到总时长,结尾 2.5s 淡出)
    _prepare_bgm(style, total, project_dir)

    # 4) 收集页面可见文本(用于字体子集化)
    page_text = script.get("title", "") + "".join(
        (f.get("voiceover") or "") + (f.get("scene") or "")
        + json.dumps(f.get("content") or {}, ensure_ascii=False)
        for f in frames
    )
    font_faces_css = build_font_faces(page_text)

    # 5) 组装 index.html
    inner_css = f"""
.clip{{position:absolute;inset:0;}}
.inner{{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;}}
.inner.left{{align-items:flex-start;}}
.inner.center{{align-items:center;text-align:center;}}
.cap-wrap{{position:absolute;left:0;right:0;bottom:{CAPTION_BOTTOM}px;display:flex;justify-content:center;padding:0 120px;}}
.cap-pill{{border-radius:10px;padding:14px 28px;font-size:32px;font-family:{style["font_body"]};color:{style["light"]};max-width:1400px;text-align:center;line-height:1.55;}}
"""
    comp_id = _comp_id(project_dir)
    js_block = "\n  ".join(js)
    # gsap 内联(外链脚本被内置服务器按 text/html 下发会被 Chrome 拒绝执行)
    # 并把 gsap 内部的 Math.random/Date.now 替换为确定性实现(lint: non_deterministic_code)
    gsap_path = VENDOR_DIR / "gsap.min.js"
    gsap_inline = ""
    if gsap_path.exists():
        gsap_raw = gsap_path.read_text(encoding="utf-8")
        gsap_raw = gsap_raw.replace("Math.random", "_hfRand")
        gsap_raw = gsap_raw.replace("Date.now", "_hfNow")
        gsap_inline = (
            "var _hfRand=(function(){{var s=1234567;return function(){{"
            "s=(s*1664525+1013904223)>>>0;return s/4294967296;}};}})();"
            "var _hfNow=function(){{return 0;}};"
        ) + gsap_raw
    index_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=1920, height=1080"/>
<title>{script.get("title", "理论文章转视频")}</title>
<script>
{gsap_inline}
</script>
<style>
{font_faces_css}
html,body{{margin:0;padding:0;background:{style["bg"]};}}
#root{{position:relative;width:1920px;height:1080px;overflow:hidden;background:{style["bg"]};}}
{inner_css}
</style>
</head>
<body>
<div id="root" data-composition-id="{comp_id}" data-start="0" data-width="1920" data-height="1080" data-duration="{total}">
<audio id="bgm" src="assets/bgm/bgm.mp3" preload="auto" data-start="0" data-volume="0.12"></audio>
{chr(10).join(audios)}
{chr(10).join(sections)}
{chr(10).join(captions)}
</div>
<script>
// 时间线注册推迟到字体加载完成:hyperframes 运行时等待注册后才开始截帧,
// 否则字体(内嵌 data URL 亦需解码时间)未就绪时全部帧渲染成方框
document.fonts.ready.then(function(){{
  var tl = gsap.timeline({{paused:true}});
  {js_block}
  window.__timelines["{comp_id}"] = tl;
}});
</script>
</body>
</html>
"""
    (project_dir / "index.html").write_text(index_html, encoding="utf-8")
    (project_dir / "script.json").write_text(
        json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"total": total, "starts": starts, "style_key": style_key}


def _copy_shared(project_dir: Path):
    """复制共享字体与 gsap 到项目内(渲染机不能依赖系统字体/网络)。"""
    fonts_dst = project_dir / "assets" / "fonts"
    vendor_dst = project_dir / "assets" / "vendor"
    fonts_dst.mkdir(parents=True, exist_ok=True)
    vendor_dst.mkdir(parents=True, exist_ok=True)
    for name in ("SourceHanSerifCN-Heavy.otf", "SourceHanSerifCN-Regular.otf",
                 "NotoSansSC-Regular.otf", "NotoSansSC-Bold.otf"):
        src = FONTS_DIR / name
        if src.exists():
            shutil.copy2(src, fonts_dst / name)
    gsap = VENDOR_DIR / "gsap.min.js"
    if gsap.exists():
        shutil.copy2(gsap, vendor_dst / "gsap.min.js")


def _prepare_bgm(style: dict, total: float, project_dir: Path):
    src = BGM_DIR / style["bgm"]
    dst = project_dir / "assets" / "bgm" / "bgm.mp3"
    fade_start = max(0.0, total - 2.5)
    if src.exists():
        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(src), "-t", f"{total:.2f}",
               "-af", f"afade=t=out:st={fade_start:.2f}:d=2.5", "-ar", "44100", "-ac", "2", str(dst)]
    else:
        # 无 BGM 素材:生成静音占位,保证渲染流程可用
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
               "-t", f"{total:.2f}", "-ar", "44100", "-ac", "2", str(dst)]
    subprocess.run(cmd, capture_output=True, timeout=600, check=True)
