# -*- coding: utf-8 -*-
"""数字人抠像:给已生成的数字人片段逐帧算人像遮罩(alpha matting)。

链路:片段 mp4 → ffmpeg 解码 RGB24 → MODNet(ONNX,本机推理)→ 每帧 alpha
      → ffmpeg 编码成**灰度**遮罩 mp4(与片段同尺寸、同帧率、同时长)

为什么遮罩是独立的灰度文件:
- H.264 不支持 alpha;ProRes 4444/qtrle 这类中间格式体积要大 30 倍以上(见 ADR-0002);
- 灰度只有亮度一维,压缩率极高(300×300、16 秒的遮罩约 100KB);
- 叠加时 `[片段][遮罩]alphamerge` 就能还原带 alpha 的人像,仍是一次 ffmpeg 滤镜图。

模型:MODNet(人像抠图,Apache-2.0),ONNX 约 25MB。
- 权重落在 models/matte/modnet.onnx(deploy/setup.sh 或本文件 --fetch-model 下载,
  可用 TTV_MATTE_MODEL 指向别处);
- 依赖 onnxruntime(CPU/GPU 都行)+ numpy;本文件跑在独立解释器里(默认 tts-venv),
  后端只按 subprocess 调它 —— 不给 FastAPI 进程加 onnx/模型依赖。

独立自测:
  tts-venv/bin/python server/matte.py --clip .cache/avatar/clip_x.mp4 --out /tmp/m.matte.mp4
  tts-venv/bin/python server/matte.py --manifest /tmp/pairs.json   # 批量,模型只加载一次
  tts-venv/bin/python server/matte.py --fetch-model                # 只下权重
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import (  # noqa: E402
    MATTE_CRF, MATTE_MODEL, MATTE_REF, MATTE_URLS,
)

# numpy 只在真正跑抠像时才需要:后端 venv 没有它,但本模块的纯函数
# (provider 选择、规格探长)仍要能被 .venv 里的冒烟回归导入。
np = None


def _np():
    global np
    if np is None:
        try:
            import numpy
        except ImportError as e:  # pragma: no cover - 取决于解释器装了什么
            raise RuntimeError(
                "抠像需要 numpy:请把它装到跑 matte.py 的解释器里"
                "(deploy/setup.sh 会装到 tts-venv;见 TTV_MATTE_PYTHON)") from e
        np = numpy
    return np


# MODNet 预处理口径(与权重配套,改这三个值等于换模型预处理,必须一起改)
_MEAN = 0.5
_STD = 0.5
_DIVISOR = 32          # 输入边长需被 32 整除(MODNet 下采样 32 倍)
_FETCH_MIN_BYTES = 20 * 1024 * 1024   # 权重至少 20MB:下到半截的 HTML 错误页据此拦掉


def _log(msg: str) -> None:
    print(f"[matte] {msg}", file=sys.stderr, flush=True)


def _emit(payload: dict) -> None:
    """结构化进度走 stdout(父进程逐行解析);日志/报错走 stderr。"""
    print(json.dumps(payload, ensure_ascii=False), flush=True)


# ─────────────────────────── 模型 ───────────────────────────

def resolve_providers(available) -> list:
    """按「GPU 优先、CPU 兜底」挑 onnxruntime provider(纯函数,便于回归)。"""
    avail = list(available or [])
    picked = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in avail]
    return picked or ["CPUExecutionProvider"]


def load_session(model: Path = MATTE_MODEL):
    """加载 MODNet ONNX。模型缺失/onnxruntime 不可用时抛 RuntimeError(调用方回退)。"""
    import onnxruntime as ort  # 延迟导入:--fetch-model 不需要它

    model = Path(model)
    if not model.exists():
        raise RuntimeError(
            f"抠像模型不存在:{model}(先跑 bash deploy/setup.sh,"
            f"或 {Path(__file__).name} --fetch-model)")
    providers = resolve_providers(ort.get_available_providers())
    so = ort.SessionOptions()
    so.log_severity_level = 3          # 只报错,别把 onnxruntime 的 INFO 灌进日志
    sess = ort.InferenceSession(str(model), sess_options=so, providers=providers)
    _log(f"模型 {model.name} · provider={sess.get_providers()[0]}")
    return sess


def fetch_model(target: Path = MATTE_MODEL, urls=None) -> Path:
    """下载权重(多源顺次尝试,校验体积)。已存在且够大就直接复用。"""
    target = Path(target)
    urls = list(urls or MATTE_URLS)
    if target.exists() and target.stat().st_size >= _FETCH_MIN_BYTES:
        _log(f"权重已就绪:{target}({target.stat().st_size // 1048576}MB)")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    errors = []
    for url in urls:
        try:
            _log(f"下载权重:{url}")
            with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as fh:
                while True:
                    block = r.read(1 << 20)
                    if not block:
                        break
                    fh.write(block)
            size = tmp.stat().st_size
            if size < _FETCH_MIN_BYTES:
                raise RuntimeError(f"只下到 {size} 字节,疑似不是权重文件")
            tmp.replace(target)
            _log(f"权重就绪:{target}({size // 1048576}MB)")
            return target
        except Exception as e:  # noqa: BLE001 - 换下一个源继续试
            errors.append(f"{url} → {e}")
            tmp.unlink(missing_ok=True)
    raise RuntimeError("抠像权重下载失败:\n  " + "\n  ".join(errors))


# ─────────────────────────── 单段抠像 ───────────────────────────

def _probe(path: Path) -> tuple:
    """片段规格 → (宽, 高, 帧率)。帧率缺失时回 25(只影响遮罩的 PTS 密度)。"""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    parts = (r.stdout or "").strip().split(",")
    try:
        w, h = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        raise RuntimeError(f"读不出片段规格:{path}:{r.stdout!r} {r.stderr[-200:]}") from None
    try:
        num, den = (parts[2].split("/") + ["1"])[:2]
        fps = float(num) / float(den) if float(den) else 25.0
    except (IndexError, ValueError, ZeroDivisionError):
        fps = 25.0
    return w, h, (fps or 25.0)


def model_size(w: int, h: int, ref: int = MATTE_REF) -> tuple:
    """源尺寸 → 送进模型解码尺寸(等比缩放,最短边 = ref)。纯函数,便于回归。"""
    scale = float(ref) / max(1, min(int(w), int(h)))
    return max(1, int(round(int(w) * scale))), max(1, int(round(int(h) * scale)))


def _pad_multiple(arr, divisor: int = _DIVISOR) -> tuple:
    """右下补边到 divisor 的整数倍(MODNet 下采样 32 倍,边长不对会崩)。

    返回 (补边后的数组, 原宽, 原高) —— 推理后要按原宽高裁回去。
    """
    numpy = _np()
    h, w = arr.shape[:2]
    ph, pw = (-h) % divisor, (-w) % divisor
    if ph or pw:
        arr = numpy.pad(arr, ((0, ph), (0, pw), (0, 0)), mode="edge")
    return arr, w, h


def matte_clip(sess, clip: Path, out: Path, ref: int = MATTE_REF,
               crf: int = MATTE_CRF, timeout: float = 1800.0,
               progress=None) -> Path:
    """给一段片段生成灰度遮罩:输出与片段同尺寸、同帧率、同时长。"""
    np = _np()
    clip, out = Path(clip), Path(out)
    if not clip.exists():
        raise RuntimeError(f"片段不存在:{clip}")
    w, h, fps = _probe(clip)
    nw, nh = model_size(w, h, ref)
    out.parent.mkdir(parents=True, exist_ok=True)

    dec = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(clip), "-an",
         "-vf", f"scale={nw}:{nh}:flags=bilinear",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{nw}x{nh}", "-r", f"{fps:.6f}",
         "-i", "pipe:0",
         "-vf", f"scale={w}:{h}:flags=bilinear",
         "-c:v", "libx264", "-pix_fmt", "gray", "-crf", str(int(crf)),
         "-preset", "veryfast", str(out)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    iname = sess.get_inputs()[0].name
    frame_bytes = nw * nh * 3
    frames = 0
    started = time.time()
    deadline = started + float(timeout) if timeout and timeout > 0 else None
    try:
        while True:
            buf = dec.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            if deadline and time.time() > deadline:
                raise RuntimeError(f"单段抠像超时(>{timeout:.0f}s):{clip}")
            rgb = np.frombuffer(buf, np.uint8).reshape(nh, nw, 3)
            x = (np.asarray(rgb, np.float32) / 255.0 - _MEAN) / _STD
            x, cw, ch = _pad_multiple(x)
            y = sess.run(None, {iname: x.transpose(2, 0, 1)[None]})[0]
            a = np.clip(y[0, 0, :ch, :cw], 0.0, 1.0)
            enc.stdin.write((a * 255.0 + 0.5).astype(np.uint8).tobytes())
            frames += 1
            if progress and frames % 10 == 0:
                progress(frames)
    finally:
        # 收尾必须**有上限**:超时/异常路径上若 ffmpeg 无视关闭的管道,直接杀了它,
        # 不能让一个坏片段挂住整批(父进程另有一层进程级看门狗)
        if dec.stdout:
            dec.stdout.close()
        if enc.stdin:
            enc.stdin.close()
        for child in (dec, enc):
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    if frames == 0:
        raise RuntimeError(f"片段没有可解码的帧:{clip}")
    if enc.returncode != 0:
        tail = (enc.stderr.read().decode("utf-8", "ignore")[-400:] if enc.stderr else "")
        out.unlink(missing_ok=True)
        raise RuntimeError(f"遮罩编码失败(exit {enc.returncode}):{tail}")
    dt = time.time() - started
    _emit({"event": "clip_done", "clip": str(clip), "out": str(out),
           "frames": frames, "fps": round(frames / dt, 2) if dt > 0 else None})
    return out


# ─────────────────────────── CLI ───────────────────────────

def _run_manifest(sess, pairs: list, ref: int, crf: int, timeout: float) -> int:
    total = len(pairs)
    failed = 0
    for n, pair in enumerate(pairs, start=1):
        clip, out = Path(pair["clip"]), Path(pair["out"])
        _emit({"event": "clip_start", "done": n - 1, "total": total, "clip": str(clip)})
        try:
            matte_clip(sess, clip, out, ref=ref, crf=crf, timeout=timeout)
        except Exception as e:  # noqa: BLE001 - 单段失败不该毁掉整批
            failed += 1
            _log(f"失败:{clip} → {e}")
            _emit({"event": "clip_failed", "clip": str(clip), "error": str(e)[:300]})
        _emit({"event": "clip_end", "done": n, "total": total, "clip": str(clip)})
    _emit({"event": "done", "total": total, "failed": failed})
    return 1 if failed else 0


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="数字人片段抠像(生成灰度遮罩视频)")
    ap.add_argument("--clip", help="输入片段;单段模式")
    ap.add_argument("--out", help="输出灰度遮罩;单段模式")
    ap.add_argument("--manifest", help='批量:JSON 文件 [{"clip":..,"out":..}, ...]')
    ap.add_argument("--model", default=str(MATTE_MODEL))
    ap.add_argument("--ref", type=int, default=MATTE_REF, help="最短边缩放(模型输入侧)")
    ap.add_argument("--crf", type=int, default=MATTE_CRF)
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--fetch-model", action="store_true", help="只下载权重后退出")
    a = ap.parse_args(argv)

    if a.fetch_model:
        fetch_model(Path(a.model))
        return 0
    if a.manifest:
        pairs = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
        if not isinstance(pairs, list) or not pairs:
            _log("manifest 为空")
            return 2
    elif a.clip and a.out:
        pairs = [{"clip": a.clip, "out": a.out}]
    else:
        _log("要么给 --clip/--out,要么给 --manifest")
        return 2

    sess = load_session(Path(a.model))
    return _run_manifest(sess, pairs, a.ref, a.crf, a.timeout)


if __name__ == "__main__":
    sys.exit(_main())
