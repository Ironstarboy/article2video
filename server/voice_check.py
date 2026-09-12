# -*- coding: utf-8 -*-
"""配音可懂度抽检:whisper 听写几帧配音,与台词比 LCS(读音正确率)。

为什么需要它(2026-09-12 乱码事故):transformers 4.52+ 会把语音 LLM 的输出打乱 ——
听起来是乱码,而**时长与峰值全正常**,项目原有的时长/静音验收一个都拦不住。
唯一能识破的是"听起来到底是什么字",所以这里用本地 whisper 做一次抽检。

跑在**配音解释器**里(whisper 装在 tts-venv),由后端按 subprocess 调用:
  tts-venv/bin/python server/voice_check.py --script <script.json> --audio <配音目录> [--frames 2]
输出一行 JSON:
  {"checked": 2, "lcs": 0.87, "worst": 0.81, "warn": false, "samples": [...]}

它是**提示**不是门:whisper 自己也有误差(好音频的 LCS 常在 0.8~0.95),阈值取得很宽;
真出错时只写进 job.state.voice_check 并在日志里吱一声,绝不阻塞构建。
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# 低于这个 LCS 才算"读音有问题"。阈值取得很宽:好音频正常也能到 0.8+,而 whisper 自己
# 有时输出繁体(简繁差异会白白吃掉一截 LCS,实测好样本最差 0.6),乱码样本则接近 0。
WARN_LCS = 0.35

try:  # 可选依赖:装了就把繁体转简体再比,免得简繁差异被算成"念错"
    from zhconv import convert as _zh_convert
except Exception:  # noqa: BLE001 - 没装也能跑,只是阈值要更宽松
    _zh_convert = None


def normalize(text: str) -> str:
    """比对前归一:去掉空白、尽力把繁体转简体。"""
    s = "".join(c for c in (text or "") if c.strip())
    if _zh_convert and s:
        try:
            s = _zh_convert(s, "zh-cn")
        except Exception:  # noqa: BLE001
            pass
    return s


def lcs_ratio(text: str, heard: str) -> float:
    """最长公共子序列占比(只算非空白字;对"念成别的内容"最敏感)。纯函数,便于回归。"""
    a, b = normalize(text), normalize(heard)
    if not a:
        return 1.0
    if not b:
        return 0.0
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0]
        for j, cb in enumerate(b):
            cur.append(prev[j] + 1 if ca == cb else max(cur[j], prev[j + 1]))
        prev = cur
    return prev[-1] / len(a)


def pick_frames(script: dict, audio_dir: Path, limit: int = 2) -> list:
    """挑要抽检的帧:有台词、配音文件在,按台词长度取前 limit 条(长句最能暴露乱码)。"""
    cands = []
    for f in script.get("frames") or []:
        text = (f.get("voiceover") or "").strip()
        if not text:
            continue
        p = Path(audio_dir) / f"vo_{int(f['index']):02d}.mp3"
        if p.exists():
            cands.append((len(text), int(f["index"]), text, p))
    cands.sort(reverse=True)
    return cands[:max(1, int(limit))]


def _decode(path: Path, out: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path),
                    "-ac", "1", "-ar", "16000", str(out)], check=True)


def check(script_path: Path, audio_dir: Path, limit: int = 2,
          model_dir: str | None = None) -> dict:
    """抽检并返回结果字典(whisper 不可用时抛 RuntimeError,由调用方跳过)。"""
    import whisper  # 延迟导入:纯函数部分要能在没装 whisper 的解释器里被回归测试导入

    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    frames = pick_frames(script, Path(audio_dir), limit)
    if not frames:
        return {"checked": 0, "lcs": None, "warn": False, "samples": []}
    model = whisper.load_model("small", download_root=model_dir)
    samples = []
    with tempfile.TemporaryDirectory(prefix="ttv_vocheck_") as tmp:
        for _, idx, text, path in frames:
            wav = Path(tmp) / f"vo_{idx:02d}.wav"
            _decode(path, wav)
            heard = model.transcribe(str(wav), language="zh", fp16=False,
                                     condition_on_previous_text=False)["text"].strip()
            samples.append({"index": idx, "lcs": round(lcs_ratio(text, heard), 3),
                            "heard": heard[:80], "text": text[:80]})
    lcs = [s["lcs"] for s in samples]
    return {"checked": len(samples), "lcs": round(sum(lcs) / len(lcs), 3),
            "worst": min(lcs), "warn": min(lcs) < WARN_LCS, "samples": samples}


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="配音可懂度抽检(whisper 听写 vs 台词)")
    ap.add_argument("--script", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--frames", type=int, default=2)
    ap.add_argument("--model-dir", default=None, help="whisper 模型缓存目录")
    a = ap.parse_args(argv)
    try:
        res = check(Path(a.script), Path(a.audio), a.frames, a.model_dir)
    except Exception as e:  # noqa: BLE001 - 抽检失败不是错误,如实回报即可
        print(json.dumps({"checked": 0, "lcs": None, "warn": False,
                          "error": f"{type(e).__name__}: {e}"[:200]},
                         ensure_ascii=False))
        return 0
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
