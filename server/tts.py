# -*- coding: utf-8 -*-
"""配音合成:edge-tts(免费、无需 key)+ 词级时间轴估算。

词级高亮时间轴:edge-tts 不返回词级时间戳,采用「帧内按字符数均分」估算
(中文朗读节奏接近匀速,视觉上可接受;后续可换 whisper 对齐升级)。
"""
import asyncio
import json
import subprocess
from pathlib import Path

from config import LOCAL_TTS_URL

VOICES = {
    "solemn-red": "zh-CN-YunxiNeural",      # 男声新闻感(沉稳)
    "academic-ink": "zh-CN-XiaoxiaoNeural",  # 女声知性
    "modern-blue": "zh-CN-YunxiNeural",      # 男声干脆
}

# 旁白起始偏移:帧开始后 0.25s 起念
VO_OFFSET = 0.25


def audio_duration(path: Path) -> float:
    """ffprobe 取时长(秒)。"""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def split_words(text: str) -> list[str]:
    """中文分词:jieba(已装)优先,失败退化为逐字。"""
    try:
        import jieba
        words = [w for w in jieba.lcut(text) if w.strip()]
        return words or list(text)
    except ImportError:
        return list(text)


FALLBACK_VOICE = None  # edge-tts 已禁用(仅本地 CosyVoice3)

# edge-tts 已禁用:所有音色仅由本地 CosyVoice3 合成


import os as _os

def _load_doubao_key() -> str:
    """豆包 ARK key 不入库:优先环境变量,其次服务器本地密钥文件。"""
    k = _os.environ.get("TTV_DOUBAO_KEY", "").strip()
    if k:
        return k
    try:
        from pathlib import Path
        p = Path("/mnt/workspace/ttv/.secrets/doubao.key")
        if p.exists():
            return p.read_text().strip()
    except Exception:
        pass
    return ""

DOUBAO_KEY = _load_doubao_key()
DOUBAO_URL = "https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional"
DOUBAO_HEADERS = {
    "X-Api-Key": DOUBAO_KEY,
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
    return _synth_local_url(text, voice, out, speed, LOCAL_TTS_URL)
    """本地 CosyVoice3 服务(127.0.0.1:8016)。成功返回 True。"""
    import time as _t
    for attempt in range(2):
        try:
            import httpx
            r = httpx.post(f"{LOCAL_TTS_URL}/tts", json={"text": text, "voice": voice, "speed": speed},
                           timeout=httpx.Timeout(180.0, connect=3.0))
            if r.status_code == 200:
                break
        except Exception:
            pass
        if attempt == 1:
            return False
        _t.sleep(2.0)
    else:
        return False
    try:
        wav = out.with_suffix(".wav")
        wav.write_bytes(r.content)
        subprocess.run(["ffmpeg", "-y", "-i", str(wav), "-ar", "44100", "-ac", "1",
                        "-b:a", "128k", str(out)], capture_output=True, timeout=120)
        wav.unlink(missing_ok=True)
        return out.exists() and audio_duration(out) > 0.2
    except Exception:
        return False


DOUBAO_LAST_ERROR = ""


def _synth_doubao(text: str, voice: str, out: Path) -> bool:
    """豆包 seed-tts-2.0 云 API(HTTP 单向流)。"""
    global DOUBAO_LAST_ERROR
    try:
        import uuid as _uuid
        import httpx
        headers = dict(DOUBAO_HEADERS)
        headers["X-Api-Request-Id"] = str(_uuid.uuid4())
        body = {
            "req_params": {
                "text": text,
                "speaker": voice,
                "model": "seed-tts-2.0-standard",
                "audio_params": {"format": "mp3", "sample_rate": 24000, "speech_rate": 0},
            },
        }
        r = httpx.post(DOUBAO_URL, headers=headers, json=body,
                       timeout=httpx.Timeout(120.0, connect=10.0))
        if r.status_code != 200:
            DOUBAO_LAST_ERROR = f"HTTP {r.status_code}: {r.text[:200]}"
            return False
        # NDJSON 流:每行一段 JSON,音频以 base64 出现在 data 字段,拼接即 MP3
        import base64 as _b64
        chunks = []
        for line in r.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = __import__("json").loads(line)
            except Exception:
                continue
            d = obj.get("data")
            if isinstance(d, str) and d and obj.get("code") in (0, 20000000, None):
                try:
                    chunks.append(_b64.b64decode(d))
                except Exception:
                    pass
        if not chunks:
            DOUBAO_LAST_ERROR = f"接口返回无音频({r.text[:200]})"
            return False
        raw = out.with_suffix(".raw.mp3")
        raw.write_bytes(b"".join(chunks))
        subprocess.run(["ffmpeg", "-y", "-i", str(raw), "-ar", "44100", "-ac", "1",
                        "-b:a", "128k", str(out)], capture_output=True, timeout=120)
        raw.unlink(missing_ok=True)
        return out.exists() and audio_duration(out) > 0.2
    except Exception as e:
        DOUBAO_LAST_ERROR = f"异常:{str(e)[:160]}"
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
    return _silence_placeholder(text, out)


def synthesize_frames(frames: list[dict], voice: str, audio_dir: Path, speed: float = 1.0,
                       provider: str = "cosyvoice3") -> dict:
    """为所有帧合成旁白 → {frame_index: {path, duration, engine, words:[(word, t0, t1)]}}。

    返回后由调用方根据真实时长重算帧 duration。
    """
    audio_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    texts = [(f["index"], (f.get("voiceover") or "").strip()) for f in frames]
    texts = [(i, t) for i, t in texts if t]

    for idx, text in texts:
        out = audio_dir / f"vo_{idx:02d}.mp3"
        engine = _synth_with_fallback(text, voice, out, speed, provider)
        result[idx] = {"engine": engine}

    for idx, text in texts:
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
    return result


def apply_real_durations(script: dict, vo: dict, tail_pad: float = 1.4,
                         target: float | None = None, extra_cap: float = 6.5) -> None:
    """根据真实旁白时长重算每帧 duration,并向目标时长靠拢。

    每帧拿到「基准/下限/上限」三个时长:
    - 开场 7s(5-9)、结尾 4.5s(3-6)、VO 帧 = 旁白 + tail_pad(下限旁白+0.6,
      上限旁白 + max(tail_pad, min(旁白×0.5, extra_cap)+1s) 视觉留白;
      讲解视频(lecture)传更大的 tail_pad/extra_cap,讲解后留白更宽)
    - 总时长不足目标:缺口按各帧可扩展上限分摊(短片长目标时把时间变成
      旁白后的视觉停留,不空转、不编造内容)
    - 总时长超出目标:优先收紧留白与开场/结尾(长文短目标时兜底压缩)
    """
    frames = script["frames"]
    rows = []  # [frame, base, lo, hi]
    for f in frames:
        t = f["type"]
        idx = f["index"]
        if t == "opening":
            base, lo, hi = 7.0, 5.0, 10.0
        elif t == "closing":
            base, lo, hi = 4.5, 3.0, 6.5
        elif idx in vo:
            vd = max(vo[idx]["duration"], 1.0)
            base = vd + tail_pad
            lo = vd + 0.6
            hi = vd + max(tail_pad, min(vd * 0.6, extra_cap) + 1.2)
        elif t == "section":
            # 章节页:停顿收紧(章节间 6s 上限,保持语气连贯,不空转)
            d = float(f.get("duration") or 6.0)
            base, lo, hi = d, 3.0, max(d, 6.0)
        else:
            d = float(f.get("duration") or 6.0)
            base, lo, hi = d, 3.0, max(d, 9.0)
        rows.append([f, base, lo, hi])
    total = sum(r[1] for r in rows)
    if target and target > 0:
        deficit = target - total
        if deficit > 0:
            # 扩展:按上限空间比例分摊
            headroom = sum(r[3] - r[1] for r in rows)
            if headroom > 0:
                scale = min(1.0, deficit / headroom)
                for r in rows:
                    r[1] += (r[3] - r[1]) * scale
        elif deficit < 0:
            # 压缩:按可收紧空间比例分摊
            squeeze = sum(r[1] - r[2] for r in rows)
            if squeeze > 0:
                scale = min(1.0, -deficit / squeeze)
                for r in rows:
                    r[1] -= (r[1] - r[2]) * scale
    total = 0.0
    for r in rows:
        f, d = r[0], r[1]
        f["duration"] = round(d, 2)
        total += d
    script["duration_sec"] = round(total, 1)


def words_meta_json(vo: dict) -> str:
    """帧索引 → 词时间轴的 JSON(写入项目供字幕使用;构建器直接内联,此处备用)。"""
    return json.dumps({str(k): v["words"] for k, v in vo.items()}, ensure_ascii=False)
