# -*- coding: utf-8 -*-
"""配音合成:本地 CosyVoice3 多实例池(默认 GPU1/2/3)+ 豆包云 API 兜底 + 静音占位。

多实例池:deploy/start-tts.sh 在 GPU1@8016 / GPU2@8018 / GPU3@8019 各起一个
CosyVoice3 worker,合成按帧轮询分发、并行执行(约 ×3 吞吐);单个实例挂了自动
摘除,其余继续。池可用环境变量 TTV_TTS_POOL 覆盖(逗号分隔 URL)。
"""
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from config import CHARS_PER_SEC, LOCAL_TTS_URL

# 旁白起始偏移:帧开始后 0.25s 起念
VO_OFFSET = 0.25

# 时长验收窗口(实际/预期)。本地 CosyVoice3 在本机解码不稳定:同一句会随机给出
# 0.01× (残句) 到 3.4× (复读) 的音频,TTS 服务侧已按时长重采;这里再兜一层:
# 服务仍未给出合理时长时换实例再要一次。见 CHANGELOG v2.2「配音时长验收」。
ACCEPT_RATIO = (0.65, 1.8)
# 峰值下限(dBFS):时长正常但**整段静音**的样本也要拒(eafca9e512a8 的整组配音
# 就是 -91dB 的占位静音,时长却完全"合理",只查时长查不出来)
MIN_PEAK_DB = -45.0
TTS_LAST_RATIO: float | None = None


def duration_ratio(text: str, dur: float) -> float:
    """实际时长 / 预期时长(预期 = 字数 ÷ CHARS_PER_SEC)。"""
    n = len((text or "").replace(" ", ""))
    return dur / max(1.0, n / CHARS_PER_SEC)


def duration_plausible(text: str, dur: float) -> bool:
    r = duration_ratio(text, dur)
    return ACCEPT_RATIO[0] <= r <= ACCEPT_RATIO[1]


def audio_peak_db(path: Path) -> float | None:
    """音频峰值(dBFS);读不出来返回 None。"""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    for ln in r.stderr.splitlines():
        if "max_volume" in ln:
            try:
                return float(ln.split("max_volume:")[1].replace("dB", "").strip())
            except ValueError:
                return None
    return None


def audio_plausible(text: str, path: Path, dur: float) -> bool:
    """时长合理 **且** 不是静音。"""
    if not duration_plausible(text, dur):
        return False
    peak = audio_peak_db(path)
    return peak is None or peak >= MIN_PEAK_DB

# CosyVoice3 多实例池(默认三实例;单实例部署时只写 8016 一个即可)
TTS_POOL = [u.strip() for u in os.environ.get(
    "TTV_TTS_POOL",
    "http://127.0.0.1:8016,http://127.0.0.1:8018,http://127.0.0.1:8019",
).split(",") if u.strip()]

# 单实例健康探测的并发上限(合成并行度 = 存活实例数)
_pool_lock = threading.Lock()
_pool_alive_cache: dict = {"at": 0.0, "urls": None}


def _alive_pool() -> list[str]:
    """探测池内存活实例(结果缓存 30s,避免每帧探测)。"""
    import time as _t
    now = _t.time()
    with _pool_lock:
        if now - _pool_alive_cache["at"] < 30 and _pool_alive_cache["urls"] is not None:
            return list(_pool_alive_cache["urls"])
    alive = []
    for url in TTS_POOL:
        try:
            r = httpx.get(f"{url}/health", timeout=2.0)
            if r.status_code == 200 and r.json().get("ok"):
                alive.append(url)
        except Exception:
            continue
    if not alive:
        alive = [LOCAL_TTS_URL]   # 全挂时退回默认实例(合成失败还会落静音占位)
    with _pool_lock:
        _pool_alive_cache.update(at=_t.time(), urls=alive)
    return list(alive)


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


# ── 豆包 seed-tts-2.0(云 API 兜底,key 不入库) ──


def _load_doubao_key() -> str:
    """豆包 ARK key 不入库:优先环境变量,其次工作区内的本地密钥文件。"""
    k = os.environ.get("TTV_DOUBAO_KEY", "").strip()
    if k:
        return k
    try:
        p = Path(os.environ.get("TTV_ROOT", str(Path(__file__).resolve().parents[1]))) / ".secrets" / "doubao.key"
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


def _synth_local_url(text: str, voice: str, out: Path, speed: float, url: str,
                     attempts: int = 3) -> bool:
    """单实例 TTS 服务(CosyVoice3 8016/8018/8019 / Qwen3-TTS 8017)。成功返回 True。"""
    global TTS_LAST_RATIO
    import time as _t
    for attempt in range(attempts):
        try:
            r = httpx.post(f"{url}/tts", json={"text": text, "voice": voice, "speed": speed},
                           timeout=httpx.Timeout(600.0, connect=3.0))
            if r.status_code == 200:
                wav = out.with_suffix(".wav")
                wav.write_bytes(r.content)
                subprocess.run(["ffmpeg", "-y", "-i", str(wav), "-ar", "44100", "-ac", "1",
                                "-b:a", "128k", str(out)], capture_output=True, timeout=120)
                wav.unlink(missing_ok=True)
                hdr = r.headers.get("x-tts-ratio")
                try:
                    TTS_LAST_RATIO = float(hdr) if hdr is not None else None
                except ValueError:
                    TTS_LAST_RATIO = None
                return out.exists() and audio_duration(out) > 0.2
        except Exception:
            pass
        _t.sleep(2.0 * (attempt + 1))
    return False


def _synth_pool(text: str, voice: str, out: Path, speed: float) -> bool:
    """池内轮询合成:优先本帧分配实例(1 次),失败逐个尝试其余存活实例。"""
    pool = _alive_pool()
    first = pool[0]
    if _synth_local_url(text, voice, out, speed, first, attempts=1):
        return True
    for url in pool[1:]:
        if _synth_local_url(text, voice, out, speed, url, attempts=1):
            return True
    return False


def _synth_local(text: str, voice: str, out: Path, speed: float = 1.0) -> bool:
    """本地 CosyVoice3 多实例池合成。"""
    return _synth_pool(text, voice, out, speed)


DOUBAO_LAST_ERROR = ""


def _synth_doubao(text: str, voice: str, out: Path) -> bool:
    """豆包 seed-tts-2.0 云 API(HTTP 单向流)。"""
    global DOUBAO_LAST_ERROR
    try:
        import uuid as _uuid
        import base64 as _b64
        import json as _json
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
        chunks = []
        for line in r.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
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


def word_times(text: str, dur: float) -> list:
    """词级时间轴(帧内按字数均分):[(word, t0, t1), ...],起点含 VO_OFFSET。"""
    words = split_words(text)
    n_chars = max(1, len(text.replace(" ", "")))
    t0 = VO_OFFSET
    out = []
    for w in words:
        wdur = dur * len(w) / n_chars
        out.append((w, t0, t0 + wdur))
        t0 += wdur
    return out


def _synth_frame(idx: int, text: str, voice: str, audio_dir: Path, speed: float,
                 provider: str, pool_url: str | None) -> tuple[int, dict]:
    """单帧完整链路(合成 → ffmpeg 转码 → 时长 → 分词),供线程池并行调用。"""
    out = audio_dir / f"vo_{idx:02d}.mp3"
    engine = None
    if provider == "doubao":
        if _synth_doubao(text, voice, out):
            engine = "doubao"
    elif provider == "qwen3tts":
        if _synth_local_url(text, voice, out, speed, "http://127.0.0.1:8017"):
            engine = "qwen3tts"
    elif pool_url:
        if _synth_local_url(text, voice, out, speed, pool_url, attempts=1):
            engine = "cosyvoice3"
    # 回落到本地 CosyVoice3 池(除非本来就是它;doubao/qwen 失败走这里)
    if engine is None:
        if _synth_pool(text, voice, out, speed):
            engine = "cosyvoice3"
    dur = audio_duration(out)
    # 验收(时长 + 非静音):服务端已重采,这里再兜一层(换实例重新采样)。本地
    # CosyVoice3 的采样不稳定,同一句多要一次往往就能拿到正常样本;不通过就留痕。
    if engine and engine != "silence" and not audio_plausible(text, out, dur):
        for _try in range(3):
            if _synth_pool(text, voice, out, speed):
                d2 = audio_duration(out)
                if audio_plausible(text, out, d2):
                    dur = d2
                    break
                dur = d2
    if engine is None:
        engine = _silence_placeholder(text, out)
        dur = audio_duration(out)
    return idx, {"path": str(out), "duration": dur, "words": word_times(text, dur),
                 "engine": engine, "ratio": round(duration_ratio(text, dur), 3),
                 "peak_db": audio_peak_db(out)}


def synthesize_frames(frames: list[dict], voice: str, audio_dir: Path, speed: float = 1.0,
                      provider: str = "cosyvoice3", progress_cb=None) -> dict:
    """为所有帧合成旁白 → {frame_index: {path, duration, engine, words:[(word, t0, t1)]}}。

    多实例并行:cosyvoice3 按存活实例数并行(轮询分发,单实例串行 GPU 推理);
    其余引擎保持单路。返回后由调用方根据真实时长重算帧 duration。
    progress_cb(done, total):每完成一帧回调一次(数字人播报的步骤展示用)。
    """
    audio_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    texts = [(f["index"], (f.get("voiceover") or "").strip()) for f in frames]
    texts = [(i, t) for i, t in texts if t]
    if not texts:
        return result

    if provider == "cosyvoice3":
        pool = _alive_pool()
        workers = max(1, len(pool))
    else:
        pool, workers = None, 1

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        for n, (idx, text) in enumerate(texts):
            url = pool[n % len(pool)] if pool else None
            futs[ex.submit(_synth_frame, idx, text, voice, audio_dir, speed,
                           provider, url)] = idx
        done = 0
        for fut in as_completed(futs):
            idx, entry = fut.result()
            result[idx] = entry
            done += 1
            if progress_cb:
                progress_cb(done, len(texts))
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
