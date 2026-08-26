# -*- coding: utf-8 -*-
"""三引擎 TTS:cosyvoice3(本地) / qwen3tts(本地) / doubao(云 API)+ 前端选择器。"""
import re

# ══ 1. tts.py:提供方抽象 ══
p = 'server/tts.py'
s = open(p, encoding='utf-8').read()

old = '''def _synth_local(text: str, voice: str, out: Path, speed: float = 1.0) -> bool:'''
new = '''DOUBAO_KEY = "<KEY_IN_SECRETS_FILE>"
DOUBAO_URL = "https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional"
DOUBAO_HEADERS = {
    "Authorization": f"Bearer;{DOUBAO_KEY}",
    "X-Api-App-Key": DOUBAO_KEY,
    "X-Api-Access-Key": DOUBAO_KEY,
    "X-Api-Resource-Id": "seed-tts-2.0",
    "Content-Type": "application/json",
}
# 豆包 seed-tts-2.0 常用音色候选(账号开通后若个别不可用,可自行增删)
DOUBAO_VOICES = [
    "zh_female_vv_uranus_bigtts",       # 女声沉稳(新闻播报)
    "zh_male_qingrun_moon_bigtts",      # 男声清润
    "zh_female_shuangkuaisisi_moon_bigtts",  # 女声轻快
    "zh_male_wennuanahu_moon_bigtts",   # 男声温暖
]


def _synth_local_url(text: str, voice: str, out: Path, speed: float, url: str) -> bool:
    """本地 TTS 服务(CosyVoice3:8016 / Qwen3-TTS:8017)。成功返回 True。"""
    import time as _t
    for attempt in range(3):
        try:
            import httpx
            r = httpx.post(f"{url}/tts", json={"text": text, "voice": voice, "speed": speed},
                           timeout=httpx.Timeout(300.0, connect=3.0))
            if r.status_code == 200:
                wav = out.with_suffix(".wav")
                wav.write_bytes(r.content)
                subprocess.run(["ffmpeg", "-y", "-i", str(wav), "-ar", "44100", "-ac", "1",
                                "-b:a", "128k", str(out)], capture_output=True, timeout=120)
                wav.unlink(missing_ok=True)
                return out.exists() and audio_duration(out) > 0.2
        except Exception:
            pass
        _t.sleep(2.0 * (attempt + 1))
    return False


def _synth_local(text: str, voice: str, out: Path, speed: float = 1.0) -> bool:
    return _synth_local_url(text, voice, out, speed, LOCAL_TTS_URL)'''
assert old in s, '_synth_local 未匹配'
s = s.replace(old, new)

old = '''def _synth_with_fallback(text: str, voice: str, out: Path, speed: float = 1.0) -> str:
    """合成引擎:仅使用本地 CosyVoice3(重试 3 次),失败则静音占位并标记 silence。
    不使用任何外部 TTS 服务(edge-tts 已移除)。"""
    for attempt in range(3):
        if _synth_local(text, voice, out, speed):
            return "cosyvoice3"
        import time
        time.sleep(2.0 * (attempt + 1))
    # 静音占位(时长按 3.0 字/秒估算),保证渲染流程不中断;状态中标记 silence
    est = max(2.0, len(text) / 3.0 + 1.0)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                    "-t", f"{est:.2f}", "-ar", "44100", "-ac", "1", str(out)],
                   capture_output=True, timeout=60)
    return "silence"'''
new = '''def _synth_doubao(text: str, voice: str, out: Path) -> bool:
    """豆包 seed-tts-2.0 云 API(HTTP 单向流)。"""
    try:
        import httpx
        body = {
            "model": "seed-tts-2.0",
            "audio": {"voice_type": voice, "encoding": "mp3", "rate": 24000},
            "input": {"text": text},
        }
        r = httpx.post(DOUBAO_URL, headers=DOUBAO_HEADERS, json=body,
                       timeout=httpx.Timeout(120.0, connect=10.0))
        if r.status_code != 200:
            return False
        raw = out.with_suffix(".raw.mp3")
        raw.write_bytes(r.content)
        subprocess.run(["ffmpeg", "-y", "-i", str(raw), "-ar", "44100", "-ac", "1",
                        "-b:a", "128k", str(out)], capture_output=True, timeout=120)
        raw.unlink(missing_ok=True)
        return out.exists() and audio_duration(out) > 0.2
    except Exception:
        return False


def _silence_placeholder(text: str, out: Path) -> str:
    est = max(2.0, len(text) / 3.0 + 1.0)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                    "-t", f"{est:.2f}", "-ar", "44100", "-ac", "1", str(out)],
                   capture_output=True, timeout=60)
    return "silence"


def _synth_with_fallback(text: str, voice: str, out: Path, speed: float = 1.0,
                         provider: str = "cosyvoice3") -> str:
    """按选定引擎合成;失败回落本地 CosyVoice3;再失败静音占位。"""
    if provider == "doubao":
        if _synth_doubao(text, voice, out):
            return "doubao"
    elif provider == "qwen3tts":
        if _synth_local_url(text, voice, out, speed, "http://127.0.0.1:8017"):
            return "qwen3tts"
    else:
        if _synth_local(text, voice, out, speed):
            return "cosyvoice3"
    # 回落到本地 CosyVoice3(除非本来就是它)
    if provider != "cosyvoice3" and _synth_local(text, voice, out, speed):
        return "cosyvoice3"
    return _silence_placeholder(text, out)'''
assert old in s, '_synth_with_fallback 未匹配'
s = s.replace(old, new)

old = '''def synthesize_frames(frames: list[dict], voice: str, audio_dir: Path, speed: float = 1.0) -> dict:'''
new = '''def synthesize_frames(frames: list[dict], voice: str, audio_dir: Path, speed: float = 1.0,
                       provider: str = "cosyvoice3") -> dict:'''
assert old in s, 'synthesize_frames 签名未匹配'
s = s.replace(old, new)
old = '''        engine = _synth_with_fallback(text, voice, out, speed)'''
new = '''        engine = _synth_with_fallback(text, voice, out, speed, provider)'''
assert old in s, 'engine 调用未匹配'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('tts.py three-provider patched')

# ══ 2. main.py:引擎/音色参数 ══
p = 'server/main.py'
s = open(p, encoding='utf-8').read()
old = '''                     font: str = Form(None), palette: str = Form(None),
                     bg: str = Form(None), motion: str = Form(None)):
    combo = styles.resolve_combo(style, font, palette, bg, motion)'''
new = '''                     font: str = Form(None), palette: str = Form(None),
                     bg: str = Form(None), motion: str = Form(None),
                     voice_engine: str = Form("cosyvoice3"), voice: str = Form(None)):
    if voice_engine not in ("cosyvoice3", "qwen3tts", "doubao"):
        raise HTTPException(400, f"未知配音引擎:{voice_engine}")
    combo = styles.resolve_combo(style, font, palette, bg, motion)'''
assert old in s, 'api_create 未匹配'
s = s.replace(old, new)
old = '''        job = create_job(style or "", duration, filename)
        job.state["combo"] = combo
        ext = "." + filename.lower().rsplit(".", 1)[-1]
        (job.dir / ("input" + ext)).write_bytes(data)
    elif len(text) >= 50:
        if len(text) > 200000:
            raise HTTPException(400, "文本超过 20 万字上限")
        job = create_job(style or "", duration, "粘贴文本.txt")
        job.state["combo"] = combo'''
new = '''        job = create_job(style or "", duration, filename)
        job.state["combo"] = combo
        job.state["voice_engine"] = voice_engine
        job.state["voice"] = voice or ""
        ext = "." + filename.lower().rsplit(".", 1)[-1]
        (job.dir / ("input" + ext)).write_bytes(data)
    elif len(text) >= 50:
        if len(text) > 200000:
            raise HTTPException(400, "文本超过 20 万字上限")
        job = create_job(style or "", duration, "粘贴文本.txt")
        job.state["combo"] = combo
        job.state["voice_engine"] = voice_engine
        job.state["voice"] = voice or ""'''
assert old in s, 'create_job 未匹配'
s = s.replace(old, new)
old = '''    # 语速保持 1.0(自然说话语速,不随内容缩放)
    speed = 1.0
    job.set(progress="配音合成中(本地 CosyVoice3,自然语速)")
    vo = tts.synthesize_frames(script["frames"], style["voice"], p["vo"], speed=speed)'''
new = '''    # 语速保持 1.0(自然说话语速,不随内容缩放)
    speed = 1.0
    provider = job.state.get("voice_engine") or "cosyvoice3"
    voice = job.state.get("voice") or style["voice"]
    eng_names = {"cosyvoice3": "本地 CosyVoice3", "qwen3tts": "本地 Qwen3-TTS", "doubao": "豆包 seed-tts-2.0"}
    job.set(progress=f"配音合成中({eng_names.get(provider, provider)},自然语速)")
    vo = tts.synthesize_frames(script["frames"], voice, p["vo"], speed=speed, provider=provider)'''
assert old in s, 'stage_build tts 未匹配'
s = s.replace(old, new)
# api_styles 加引擎信息
old = '''        "motions": dim(styles.MOTIONS),
    }'''
new = '''        "motions": dim(styles.MOTIONS),
        "voice_engines": [
            {"key": "cosyvoice3", "name": "本地 CosyVoice3", "voices": ["male", "female", "male_narrator"]},
            {"key": "qwen3tts", "name": "本地 Qwen3-TTS", "voices": ["male", "female", "male_narrator"]},
            {"key": "doubao", "name": "豆包 seed-tts-2.0(云)", "voices": tts.DOUBAO_VOICES},
        ],
    }'''
assert old in s, 'api_styles 未匹配'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('main.py three-provider patched')
