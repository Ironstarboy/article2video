# -*- coding: utf-8 -*-
"""批量补丁:C 时长范围 30-600 / E 帧画面丰富(页脚+关键词) / F TTS 引擎追踪+语速 / G 自动 check。"""
import re

# ══ 1. main.py ══
p = 'server/main.py'
s = open(p, encoding='utf-8').read()

s = s.replace("duration = max(60, min(600, duration))", "duration = max(30, min(600, duration))")

old_build = '''def stage_build(job):
    job.set(status="building", progress="生成配音")
    p = job.paths()
    script = json.loads(p["script"].read_text(encoding="utf-8"))
    style_key = job.state["style"]
    style = styles.get(style_key)
    job.set(progress=f"配音合成中(edge-tts,{style['name']})")
    vo = tts.synthesize_frames(script["frames"], style["voice"], p["vo"])
    job.set(progress="组装 HyperFrames 项目")
    tts.apply_real_durations(script, vo)
    info = assemble.build(script, style_key, vo, p["project"])
    job.set(status="preview", progress=f"总时长 {info['total']:.0f} 秒", total_sec=info["total"])
    start_player(job)'''
new_build = '''def stage_build(job):
    job.set(status="building", progress="生成配音")
    p = job.paths()
    script = json.loads(p["script"].read_text(encoding="utf-8"))
    style_key = job.state["style"]
    style = styles.get(style_key)
    target = int(job.state.get("duration_sec", 120))
    speed = 0.9 if target > 240 else 1.0   # 长视频语速稍缓,更庄重
    job.set(progress=f"配音合成中(本地 CosyVoice3,语速 {speed})")
    vo = tts.synthesize_frames(script["frames"], style["voice"], p["vo"], speed=speed)
    engines = {}
    for v in vo.values():
        engines[v.get("engine", "unknown")] = engines.get(v.get("engine", "unknown"), 0) + 1
    eng_txt = " + ".join(f"{k}×{n}" for k, n in sorted(engines.items()))
    job.set(progress=f"组装 HyperFrames 项目(配音引擎:{eng_txt})")
    tts.apply_real_durations(script, vo)
    info = assemble.build(script, style_key, vo, p["project"])
    job.set(status="preview", progress=f"总时长 {info['total']:.0f} 秒", total_sec=info["total"],
            voice_engines=eng_txt)
    start_player(job)
    # 构建后异步跑质量门(hyperframes check),结果写入任务状态,不阻塞预览
    threading.Thread(target=_run_check, args=(job,), daemon=True).start()'''
assert old_build in s, 'stage_build 未匹配'
s = s.replace(old_build, new_build)

s = s.replace("import shutil\nimport subprocess", "import shutil\nimport subprocess\nimport threading")
old_imp = "import subprocess\nimport sys"
new_imp = "import subprocess\nimport sys\nimport threading"
if old_imp in s:
    s = s.replace(old_imp, new_imp, 1)

# _run_check 函数加在 stage_render 之前
old_anchor = "def stage_render(job):"
new_check = '''def _run_check(job):
    """构建后异步质量门:hyperframes check,结果写入 job.state['check']。"""
    env = dict(os.environ)
    env["PATH"] = NODE_BIN_DIR + os.pathsep + env.get("PATH", "")
    try:
        r = subprocess.run(["hyperframes", "check", str(job.paths()["project"])],
                           capture_output=True, text=True, timeout=900, env=env)
        out = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"(\\d+) error\\(s\\), (\\d+) warning\\(s\\), (\\d+) info\\(s\\)", out)
        summary = f"{m.group(1)}错误 {m.group(2)}警告 {m.group(3)}提示" if m else "完成"
        job.set(check=f"hyperframes check: {summary}(exit {r.returncode})")
    except Exception as e:
        job.set(check=f"check 失败: {e}")


def stage_render(job):'''
assert old_anchor in s, 'stage_render anchor 未匹配'
s = s.replace(old_anchor, new_check, 1)
# 需要 re 与 os 导入
if "\nimport re\n" not in s:
    s = s.replace("import os\n", "import os\nimport re\n", 1)

open(p, 'w', encoding='utf-8').write(s)
print('main.py patched')

# ══ 2. templates.py:页脚 + 关键词 chips + ctx ══
p = 'server/builder/templates.py'
s = open(p, encoding='utf-8').read()

old_rf = '''def render_frame(frame, style, S) -> tuple[str, str, list[str]]:
    """返回 (section_html, caption_html, js_lines)。"""
    i = frame["index"]
    t = frame["type"]
    c = frame.get("content") or {}
    fn = {
        "opening": _opening, "section": _section, "statement": _statement,
        "elaboration": _elaboration, "quote": _quote, "data": _data,
        "points": _points, "process": _process, "contrast": _contrast,
        "closing": _closing,
    }[t]
    return fn(i, c, style, S)'''
new_rf = '''def render_frame(frame, style, S, ctx=None) -> tuple[str, str, list[str]]:
    """返回 (section_html, caption_html, js_lines)。ctx: {title, total} 用于页脚。"""
    i = frame["index"]
    t = frame["type"]
    c = frame.get("content") or {}
    ctx = ctx or {}
    fn = {
        "opening": _opening, "section": _section, "statement": _statement,
        "elaboration": _elaboration, "quote": _quote, "data": _data,
        "points": _points, "process": _process, "contrast": _contrast,
        "closing": _closing,
    }[t]
    sec, cap, js = fn(i, c, style, S)
    # 全帧统一页脚:《标题》 · 帧序(编辑部信息密度)
    title = (ctx.get("title") or "").replace("\\n", " ")
    foot = (f'<div style="position:absolute;left:320px;right:320px;bottom:44px;'
            f'display:flex;justify-content:space-between;font-family:{style["font_body"]};'
            f'font-size:20px;color:{style["muted"]};opacity:0.8;" id="f{i}-foot">'
            f'<span>《{title[:20]}》</span><span>{i:02d} / {ctx.get("total", 0):02d}</span></div>')
    sec = sec.replace("</section>", foot + "</section>")
    js.append(f'tl.from("#f{i}-foot",{{autoAlpha:0,duration:0.5}},{S}+0.6);')
    return sec, cap, js'''
assert old_rf in s, 'render_frame 未匹配'
s = s.replace(old_rf, new_rf)

# statement 关键词 chips
old_st = '''    if c.get("support"):
        parts.append(f'<div id="f{i}-sup" style="font-family:{style["font_body"]};font-size:29px;'
                     f'color:{style["muted"]};margin-top:32px;line-height:1.7;max-width:1200px;">{E(c["support"])}</div>')
    parts.append("</div>")
    js = [f'tl.from("#f{i}-bar",{{scaleY:0,duration:0.6,ease:"power2.out",transformOrigin:"top center"}},{S}+0.1);',
          f'tl.from("#f{i}-eyebrow",{{autoAlpha:0,duration:0.4}},{S}+0.25);']'''
new_st = '''    if c.get("support"):
        parts.append(f'<div id="f{i}-sup" style="font-family:{style["font_body"]};font-size:29px;'
                     f'color:{style["muted"]};margin-top:32px;line-height:1.7;max-width:1200px;">{E(c["support"])}</div>')
    kws = c.get("keywords") or []
    if kws:
        chips = "".join(
            f'<span id="f{i}-kw{n+1}" style="display:inline-block;padding:7px 20px;'
            f'border:1px solid {style["primary"]};border-radius:999px;'
            f'font-family:{style["font_bold"]};font-size:22px;color:{style["primary"]};'
            f'margin:0 16px 0 0;">{E(k[:4])}</span>'
            for n, k in enumerate(kws[:4]))
        parts.append(f'<div style="margin-top:40px;">{chips}</div>')
    parts.append("</div>")
    js = [f'tl.from("#f{i}-bar",{{scaleY:0,duration:0.6,ease:"power2.out",transformOrigin:"top center"}},{S}+0.1);',
          f'tl.from("#f{i}-eyebrow",{{autoAlpha:0,duration:0.4}},{S}+0.25);']
    for n in range(min(4, len(kws))):
        js.append(f'tl.from("#f{i}-kw{n+1}",{{y:10,autoAlpha:0,duration:0.4,ease:"power2.out"}},{S}+{0.9 + n * 0.12});')'''
assert old_st in s, 'statement 未匹配'
s = s.replace(old_st, new_st)
open(p, 'w', encoding='utf-8').write(s)
print('templates.py patched')

# ══ 3. assemble.py:传 ctx ══
p = 'server/builder/assemble.py'
s = open(p, encoding='utf-8').read()
old = "        sec_html, cap_html, js_lines = templates.render_frame(f, style, S)"
new = ("        sec_html, cap_html, js_lines = templates.render_frame(\n"
       "            f, style, S, {\"title\": script.get(\"title\", \"\"), \"total\": len(frames)})")
assert old in s, 'assemble 未匹配'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('assemble.py patched')

# ══ 4. tts.py:speed + 引擎追踪 ══
p = 'server/tts.py'
s = open(p, encoding='utf-8').read()

old_sl = '''def _synth_local(text: str, voice: str, out: Path) -> bool:
    """本地 CosyVoice2 服务(127.0.0.1:8016)。成功返回 True。"""
    try:
        import httpx
        r = httpx.post(f"{LOCAL_TTS_URL}/tts", json={"text": text, "voice": voice},
                       timeout=httpx.Timeout(180.0, connect=3.0))
        if r.status_code != 200:
            return False
        wav = out.with_suffix(".wav")
        wav.write_bytes(r.content)
        subprocess.run(["ffmpeg", "-y", "-i", str(wav), "-ar", "44100", "-ac", "1",
                        "-b:a", "128k", str(out)], capture_output=True, timeout=120)
        wav.unlink(missing_ok=True)
        return out.exists() and audio_duration(out) > 0.2
    except Exception:
        return False'''
new_sl = '''def _synth_local(text: str, voice: str, out: Path, speed: float = 1.0) -> bool:
    """本地 CosyVoice3 服务(127.0.0.1:8016)。成功返回 True。"""
    try:
        import httpx
        r = httpx.post(f"{LOCAL_TTS_URL}/tts", json={"text": text, "voice": voice, "speed": speed},
                       timeout=httpx.Timeout(180.0, connect=3.0))
        if r.status_code != 200:
            return False
        wav = out.with_suffix(".wav")
        wav.write_bytes(r.content)
        subprocess.run(["ffmpeg", "-y", "-i", str(wav), "-ar", "44100", "-ac", "1",
                        "-b:a", "128k", str(out)], capture_output=True, timeout=120)
        wav.unlink(missing_ok=True)
        return out.exists() and audio_duration(out) > 0.2
    except Exception:
        return False'''
assert old_sl in s, '_synth_local 未匹配'
s = s.replace(old_sl, new_sl)

old_wf = '''def _synth_with_fallback(text: str, voice: str, out: Path) -> None:
    """三级容错:本地 CosyVoice2 → edge-tts(重试+换声线) → 静音占位。"""
    # 1) 本地 CosyVoice2
    if _synth_local(text, voice, out):
        return'''
new_wf = '''def _synth_with_fallback(text: str, voice: str, out: Path, speed: float = 1.0) -> str:
    """三级容错:本地 CosyVoice3 → edge-tts(重试+换声线) → 静音占位。返回引擎名。"""
    # 1) 本地 CosyVoice3
    if _synth_local(text, voice, out, speed):
        return "cosyvoice3"'''
assert old_wf in s, '_synth_with_fallback 未匹配'
s = s.replace(old_wf, new_wf)

s = s.replace('''        try:
            asyncio.run(try_synth(text, edge_voice))
            if audio_duration(out) > 0.2:
                return
        except Exception:
            pass
        import time
        time.sleep(1.5)
    # 3) edge-tts 备选声线
    try:
        asyncio.run(try_synth(text, FALLBACK_VOICE))
        if audio_duration(out) > 0.2:
            return
    except Exception:
        pass''', '''        try:
            asyncio.run(try_synth(text, edge_voice))
            if audio_duration(out) > 0.2:
                return "edge-tts"
        except Exception:
            pass
        import time
        time.sleep(1.5)
    # 3) edge-tts 备选声线
    try:
        asyncio.run(try_synth(text, FALLBACK_VOICE))
        if audio_duration(out) > 0.2:
            return "edge-tts"
    except Exception:
        pass''')

s = s.replace('''    # 4) 静音占位(时长按 4.2 字/秒估算),保证渲染流程不中断
    est = max(2.0, len(text) / 4.2 + 1.0)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                    "-t", f"{est:.2f}", "-ar", "44100", "-ac", "1", str(out)],
                   capture_output=True, timeout=60)''', '''    # 4) 静音占位(时长按 4.2 字/秒估算),保证渲染流程不中断
    est = max(2.0, len(text) / 4.2 + 1.0)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                    "-t", f"{est:.2f}", "-ar", "44100", "-ac", "1", str(out)],
                   capture_output=True, timeout=60)
    return "silence"''')

old_syn = '''def synthesize_frames(frames: list[dict], voice: str, audio_dir: Path) -> dict:
    """为所有帧合成旁白 → {frame_index: {path, duration, words:[(word, t0, t1)]}}。

    返回后由调用方根据真实时长重算帧 duration。
    """
    audio_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    texts = [(f["index"], (f.get("voiceover") or "").strip()) for f in frames]
    texts = [(i, t) for i, t in texts if t]

    for idx, text in texts:
        out = audio_dir / f"vo_{idx:02d}.mp3"
        _synth_with_fallback(text, voice, out)'''
new_syn = '''def synthesize_frames(frames: list[dict], voice: str, audio_dir: Path, speed: float = 1.0) -> dict:
    """为所有帧合成旁白 → {frame_index: {path, duration, engine, words:[(word, t0, t1)]}}。

    返回后由调用方根据真实时长重算帧 duration。
    """
    audio_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    texts = [(f["index"], (f.get("voiceover") or "").strip()) for f in frames]
    texts = [(i, t) for i, t in texts if t]

    for idx, text in texts:
        out = audio_dir / f"vo_{idx:02d}.mp3"
        engine = _synth_with_fallback(text, voice, out, speed)
        result[idx] = {"engine": engine}'''
assert old_syn in s, 'synthesize_frames 未匹配'
s = s.replace(old_syn, new_syn)

s = s.replace('''    for idx, text in texts:
        out = audio_dir / f"vo_{idx:02d}.mp3"
        dur = audio_duration(out)
        words = split_words(text)
        n_chars = max(1, len(text.replace(" ", "")))
        t0 = VO_OFFSET
        word_times = []
        for w in words:
            wdur = dur * len(w) / n_chars
            word_times.append((w, t0, t0 + wdur))
            t0 += wdur
        result[idx] = {"path": str(out), "duration": dur, "words": word_times}
    return result''', '''    for idx, text in texts:
        out = audio_dir / f"vo_{idx:02d}.mp3"
        dur = audio_duration(out)
        words = split_words(text)
        n_chars = max(1, len(text.replace(" ", "")))
        t0 = VO_OFFSET
        word_times = []
        for w in words:
            wdur = dur * len(w) / n_chars
            word_times.append((w, t0, t0 + wdur))
            t0 += wdur
        entry = result.get(idx, {})
        entry.update({"path": str(out), "duration": dur, "words": word_times})
        result[idx] = entry
    return result''')
open(p, 'w', encoding='utf-8').write(s)
print('tts.py patched')

# ══ 5. 前端:时长范围 30-600 ══
p = 'web/index.html'
s = open(p, encoding='utf-8').read()
old = '<input type="range" id="dur" min="60" max="300" step="30" value="120"/>'
new = '<input type="range" id="dur" min="30" max="600" step="30" value="120"/>'
assert old in s, 'slider 未匹配'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('index.html patched')
print('ALL DONE')
