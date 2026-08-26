# -*- coding: utf-8 -*-
"""组合参数链路:assemble 用 style 属性;main/analyze/config 接入四维参数。"""
import re

# ══ assemble.py ══
p = 'server/builder/assemble.py'
s = open(p, encoding='utf-8').read()
s = s.replace('''OVERLAP = {"solemn-red": 0.6, "academic-ink": 0.8, "modern-blue": 0.45}
PUSH_DUR = 0.4''', 'PUSH_DUR = 0.4')
s = s.replace('''        if trans == "crossfade":
            shift = OVERLAP[style_key]
        elif trans == "push_up":
            shift = PUSH_DUR''', '''        if trans == "crossfade":
            shift = style["overlap"]
        elif trans == "push_up":
            # 仅明快动效允许上推;其余动效转场退化为 cut
            if not style.get("push_up_ok"):
                trans = "cut"
                shift = 0.0
            else:
                shift = PUSH_DUR''')
assert 'OVERLAP' not in s, 'OVERLAP 残留'
open(p, 'w', encoding='utf-8').write(s)
print('assemble.py patched')

# ══ analyze.py:风格卡改为组合描述 ══
p = 'server/analyze.py'
s = open(p, encoding='utf-8').read()
old = '''def build_user_prompt(article: str, target_duration: int, style_key: str) -> str:
    style_names = {"solemn-red": "庄重肃穆·中国红", "academic-ink": "清雅学术·墨黛青", "modern-blue": "现代锐意·科技蓝"}
    style_name = style_names.get(style_key, style_key)
    cards = "\\n".join(f"- {k}:{v}" for k, v in STYLE_CARDS.items())'''
new = '''def build_user_prompt(article: str, target_duration: int, combo: dict) -> str:
    from builder.styles import combo_label
    style_card = combo_label(combo)'''
assert old in s, 'build_user_prompt 头未匹配'
s = s.replace(old, new)
old = '''- 用户选定风格:{style_name}({style_key})。请在 style_recommendation 中确认或建议更适合的风格(style 字段用键名)。
- 三套风格卡(设计约束):
{cards}'''
new = '''- 用户选定的风格组合(四个维度,设计约束):
  {style_card}
  style_recommendation.style 请填该组合最接近的预设键(solemn-red/academic-ink/modern-blue 之一)。'''
assert old in s, '风格卡段未匹配'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('analyze.py patched')

# ══ main.py:四维参数 + combo 传递 ══
p = 'server/main.py'
s = open(p, encoding='utf-8').read()

old = '''def stage_analyze(job):
    job.set(status="analyzing", progress="提取文本")
    p = job.paths()
    # 上传文件保留原扩展名(txt/md/docx);粘贴文本模式直接就是 input.txt
    upload = next(job.dir.glob("input.*"))
    text = extract.extract_text(upload)
    p["input"].write_text(text, encoding="utf-8")
    job.set(progress=f"DeepSeek 分析中(约 10-60 秒,全文 {len(text)} 字)")
    script = analyze.analyze_article(text, int(job.state["duration_sec"]), job.state["style"])
    p["script"].write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    job.set(status="analyzed", progress="")'''
new = '''def _job_combo(job) -> dict:
    """任务的四维风格组合(job.state['combo'] 持久化)。"""
    c = job.state.get("combo")
    if not c:
        c = styles.resolve_combo(job.state.get("style"), None, None, None, None)
        job.state["combo"] = c
    return c


def stage_analyze(job):
    job.set(status="analyzing", progress="提取文本")
    p = job.paths()
    # 上传文件保留原扩展名(txt/md/docx);粘贴文本模式直接就是 input.txt
    upload = next(job.dir.glob("input.*"))
    text = extract.extract_text(upload)
    p["input"].write_text(text, encoding="utf-8")
    job.set(progress=f"DeepSeek 分析中(约 10-60 秒,全文 {len(text)} 字)")
    script = analyze.analyze_article(text, int(job.state["duration_sec"]), _job_combo(job))
    p["script"].write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    job.set(status="analyzed", progress="")'''
assert old in s, 'stage_analyze 未匹配'
s = s.replace(old, new)

old = '''    p = job.paths()
    script = json.loads(p["script"].read_text(encoding="utf-8"))
    style_key = job.state["style"]
    style = styles.get(style_key)
    target = int(job.state.get("duration_sec", 120))
    # 注意:CosyVoice3 克隆音色 speed<1 时非线性恶化(实测 0.8 → 5 倍时长怪音),仅用 1.0/1.05
    speed = 1.05 if target <= 120 else 1.0
    job.set(progress=f"配音合成中(本地 CosyVoice3,语速 {speed})")'''
new = '''    p = job.paths()
    script = json.loads(p["script"].read_text(encoding="utf-8"))
    style = styles.get(_job_combo(job))
    target = int(job.state.get("duration_sec", 120))
    # 语速保持 1.0(自然说话语速,不随内容缩放)
    speed = 1.0
    job.set(progress="配音合成中(本地 CosyVoice3,自然语速)")'''
assert old in s, 'stage_build 头未匹配'
s = s.replace(old, new)

old = '''    tts.apply_real_durations(script, vo, tail_pad=0.9 if target <= 120 else 1.4)
    info = assemble.build(script, style_key, vo, p["project"])'''
new = '''    tts.apply_real_durations(script, vo, tail_pad=0.9 if target <= 120 else 1.4)
    info = assemble.build(script, _job_combo(job), vo, p["project"])'''
assert old in s, 'assemble.build 调用未匹配'
s = s.replace(old, new)

old = '''@app.post("/api/jobs")
async def api_create(file: UploadFile = File(None), style: str = Form("solemn-red"),
                     duration: int = Form(120), text: str = Form("")):
    if style not in STYLES:
        raise HTTPException(400, f"未知风格:{style}")
    duration = max(30, min(600, duration))'''
new = '''@app.post("/api/jobs")
async def api_create(file: UploadFile = File(None), style: str = Form(None),
                     duration: int = Form(120), text: str = Form(""),
                     font: str = Form(None), palette: str = Form(None),
                     bg: str = Form(None), motion: str = Form(None)):
    combo = styles.resolve_combo(style, font, palette, bg, motion)
    duration = max(30, min(600, duration))'''
assert old in s, 'api_create 未匹配'
s = s.replace(old, new)

old = '''        job = create_job(style, duration, filename)
        ext = "." + filename.lower().rsplit(".", 1)[-1]
        (job.dir / ("input" + ext)).write_bytes(data)
    elif len(text) >= 50:
        job = create_job(style, duration, "粘贴文本.txt")'''
new = '''        job = create_job(style or "", duration, filename)
        job.state["combo"] = combo
        ext = "." + filename.lower().rsplit(".", 1)[-1]
        (job.dir / ("input" + ext)).write_bytes(data)
    elif len(text) >= 50:
        job = create_job(style or "", duration, "粘贴文本.txt")
        job.state["combo"] = combo'''
assert old in s, 'create_job 未匹配'
s = s.replace(old, new)

old = '''@app.get("/api/styles")
def api_styles():
    return {k: {"key": k, "name": v["name"], "bg": v["bg"], "primary": v["primary"],
                "deep": v["deep"], "accent2": v["accent2"]} for k, v in styles.STYLES.items()}'''
new = '''@app.get("/api/styles")
def api_styles():
    """四维度选项 + 预设组合(前端选择器)。"""
    def dim(d):
        return [{"key": k, "name": v["name"], "desc": v.get("desc", "")} for k, v in d.items()]
    return {
        "presets": [{"key": k, "name": v["name"], "combo": {kk: vv for kk, vv in v.items() if kk in ("font", "palette", "bg", "motion")}}
                    for k, v in styles.PRESETS.items()],
        "fonts": dim(styles.FONTS),
        "palettes": dim(styles.PALETTES),
        "backgrounds": dim(styles.BACKGROUNDS),
        "motions": dim(styles.MOTIONS),
    }'''
assert old in s, 'api_styles 未匹配'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('main.py patched')
print('ALL DONE')
