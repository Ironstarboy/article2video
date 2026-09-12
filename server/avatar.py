# -*- coding: utf-8 -*-
"""数字人片段生成:把每帧台词变成一段"人像卡片"视频(仅画面,不含音轨)。

链路:台词音频 → CyberVerse AvatarService(gRPC,FlashHead 已在服务端加载) → RGB24 原始帧
      → ffmpeg 烘焙(缩放到目标尺寸 + 圆角 + 投影) → 片段 mp4

约定(见 CONTEXT.md):
- 数字人片段**只提供画面**;成片音轨始终是项目自身的配音,保证只有一套时间轴。
- 片段长度精确裁剪/补齐到该帧总时长,避免误差逐帧累积成可见漂移。
- "闭嘴静默"待机片段每个形象只生成一段,全局缓存复用。

独立自测:
  python server/avatar.py --image assets/avatars/jinli.png --audio /tmp/x.wav \
      --duration 8 --out /tmp/clip.mp4
"""
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import grpc  # noqa: E402

import avatar_pb2  # noqa: E402
import avatar_pb2_grpc  # noqa: E402
import common_pb2  # noqa: E402
from config import (  # noqa: E402
    AVATAR_ADDR, AVATAR_CACHE_DIR, AVATAR_CLIP_VERSION, AVATAR_CONCAT_BASE_SIZE,
    AVATAR_CONCAT_RT_FACTOR, AVATAR_CORNERS, AVATAR_CORNER, AVATAR_CUTOUT,
    AVATAR_CUTOUT_BOTTOM_MARGIN, AVATAR_IDLE_SECONDS,
    AVATAR_IMAGE, AVATAR_RT_FACTOR, AVATAR_SIZE, AVATAR_SIZE_MAX, AVATAR_SIZE_MIN,
    AVATAR_TTS_RT_FACTOR, AVATAR_X, AVATAR_Y, HEIGHT, MATTE_CRF, MATTE_MODEL,
    MATTE_MODEL_TAG, MATTE_PYTHON, MATTE_REF, MATTE_TIMEOUT, MATTE_VERSION,
    WIDTH, resolve_avatar_image,
)
from tts import VO_OFFSET  # noqa: E402

# ── 烘焙参数(改动需递增 AVATAR_CLIP_VERSION 以失效缓存) ──
_RADIUS_RATIO = 0.09      # 圆角半径 = 边长 × 该比例
_MARGIN = 8               # 四周留白,给投影留位置
_SHADOW_ALPHA = 0.38
_SHADOW_BLUR = 7
_SHADOW_DX, _SHADOW_DY = 2, 3
_INPUT_SAMPLE_RATE = 16000
_AUDIO_STEP_BYTES = _INPUT_SAMPLE_RATE  # 每次送 0.5s(16bit 单声道 → 16000 字节)
_MAX_RECV_BYTES = 128 * 1024 * 1024      # 单块 464×464×28 帧 RGB24 ≈ 18MB,默认 4MB 不够


# ─────────────────────────── 尺寸口径 ───────────────────────────
#
# 「数字人大小」= 卡片边长(正方形)。它同时决定三件事:gRPC 出帧的烘焙缩放、
# 片段缓存键、以及播报视频的画面边长。默认 config.AVATAR_SIZE,成片叠加与
# 「数字人播报视频」都按任务的设置走;非法值一律在接口层拦成 400,不静默改写。

def normalize_size(value=None, default: int = AVATAR_SIZE) -> int:
    """把接口/前端传来的边长收敛成合法值(纯函数)。

    None / 空串 → default;必须是**偶数**(奇数过不了 H.264 yuv420p),
    且落在 [AVATAR_SIZE_MIN, AVATAR_SIZE_MAX] 内。不合法抛 ValueError:
    静默改成别的尺寸,用户拿到的是"不是我选的那个大小",比报错更难排查。
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return int(default)
    try:
        size = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"数字人尺寸必须是整数:{value!r}") from None
    if size % 2:
        raise ValueError(f"数字人尺寸必须是偶数:{size}")
    if not (AVATAR_SIZE_MIN <= size <= AVATAR_SIZE_MAX):
        raise ValueError(
            f"数字人尺寸需在 {AVATAR_SIZE_MIN}-{AVATAR_SIZE_MAX} 之间:{size}")
    return size


def safe_size(value=None, default: int = AVATAR_SIZE) -> int:
    """读路径用的宽松版:历史 state 里的坏值退回 default,绝不抛错(轮询不能被它打断)。"""
    try:
        return normalize_size(value, default)
    except ValueError:
        return int(default)


def concat_rt_factor(size: int = AVATAR_SIZE) -> float:
    """拼接编码速度系数(秒视频/秒墙钟),按**面积比**从实测基准边长外推。

    编码耗时基本与像素数成正比(AVATAR_CONCAT_BASE_SIZE=320 实测 ≈15×),
    所以 640 只有 ≈3.75×。注意基准是 320 这个**实测值**,不是当前默认边长 ——
    默认边长改成 300 以后,系数不该被解释成"300 的实测值"。
    只影响界面上的「预计时间」,不参与任何产物生成;step 2 生成中会用实测速率覆盖。
    """
    base = max(0.5, AVATAR_CONCAT_RT_FACTOR)
    ref = max(1, int(AVATAR_CONCAT_BASE_SIZE or AVATAR_SIZE))
    s = max(1, int(size or AVATAR_SIZE))
    return base * (ref / s) ** 2


# ── 四角位置(成片里那个人像放在哪个角) ──

_CORNER_ALIASES = {
    "tl": "tl", "左上": "tl", "left-top": "tl", "top-left": "tl",
    "tr": "tr", "右上": "tr", "right-top": "tr", "top-right": "tr",
    "br": "br", "右下": "br", "right-bottom": "br", "bottom-right": "br",
    "bl": "bl", "左下": "bl", "left-bottom": "bl", "bottom-left": "bl",
}


def normalize_corner(value=None, default: str = AVATAR_CORNER) -> str:
    """把接口/前端传来的角落收敛成 'tl'|'tr'|'br'|'bl'(纯函数)。

    接受键名与中文名(「右上」等);None/空串 → default。不合法抛 ValueError,
    由接口层转 400 —— 位置写错比尺寸更隐蔽(成片出来才发现人像不见了)。
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return default if default in AVATAR_CORNERS else "tr"
    key = _CORNER_ALIASES.get(str(value).strip().lower())
    if key is None:
        raise ValueError(
            f"数字人位置只能是 {'/'.join(AVATAR_CORNERS)}(或 左上/右上/右下/左下):{value!r}")
    return key


def safe_corner(value=None, default: str = AVATAR_CORNER) -> str:
    """读路径用的宽松版:历史 state 里的坏值退回 default,绝不抛错。"""
    try:
        return normalize_corner(value, default)
    except ValueError:
        return default if default in AVATAR_CORNERS else "tr"


def corner_xy(corner: str = AVATAR_CORNER, size: int = AVATAR_SIZE,
              margin_x: int = AVATAR_X, margin_y: int = AVATAR_Y,
              video_w: int = WIDTH, video_h: int = HEIGHT,
              pad: int = _MARGIN) -> tuple[int, int]:
    """四角锚点 → ffmpeg overlay 坐标(纯函数)。

    叠加的输入是**带留白的卡片画布**(边长 = size + 2×pad,留白给投影),
    所以四个角都按整块画布离边 margin 来摆 —— 这样圆角卡片的**视觉**边距
    四角一致,投影也不会被画面边缘裁掉。
    """
    c = normalize_corner(corner)
    canvas = int(size) + 2 * int(pad)
    x = margin_x if c in ("tl", "bl") else max(0, int(video_w) - canvas - margin_x)
    y = margin_y if c in ("tl", "tr") else max(0, int(video_h) - canvas - margin_y)
    return x, y


# ─────────────────────── 抠像(透明背景出镜) ───────────────────────
#
# 「只保留人像」= 不用圆角卡片遮罩,改用片段自己的 alpha(由 server/matte.py 逐帧算出)。
# 口径(见 cutout_xy):
# 1. 四个角落都能摆:左右按角落的 左/右,纵向按 上/下,与圆角卡片一致;
# 2. 只有**下排**默认贴画面下缘 —— 片段是齐胸特写、底边整行都是躯干(alpha≈1),
#    让那道平切口落在画面外沿才不像"悬浮的半身像";上排留出头顶空间(同圆角卡片的 AVATAR_Y)。

def normalize_cutout(value=None, default: bool = AVATAR_CUTOUT) -> bool:
    """把接口/前端传来的抠像开关收敛成布尔(纯函数,便于回归)。

    只认真正的布尔:字符串 "false" 在 JSON 里是"没传",在这里也不能当假值用 ——
    否则前端少传一个字段就会静默关掉抠像。
    """
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    raise ValueError(f"抠像开关需要 true 或 false:{value!r}")


def safe_cutout(value=None, default: bool = AVATAR_CUTOUT) -> bool:
    """读路径用的宽松版:历史 state 里的坏值退回 default,绝不抛错(轮询不能被它打断)。"""
    try:
        return normalize_cutout(value, default)
    except ValueError:
        return bool(default)


def cutout_xy(corner: str = AVATAR_CORNER, size: int = AVATAR_SIZE,
              margin_x: int = AVATAR_X, margin_y: int = AVATAR_Y,
              bottom_margin: int = AVATAR_CUTOUT_BOTTOM_MARGIN,
              video_w: int = WIDTH, video_h: int = HEIGHT) -> tuple[int, int]:
    """抠像模式下人像的 overlay 坐标(纯函数)—— **四个角落都能摆**。

    输入是**片段本身**(size×size,没有卡片留白):左右按角落的 左/右,纵向按 上/下。
    上下留白口径不同,而且是有意的:

    - 上排(tl/tr):`margin_y`,和圆角卡片一样留出头顶空间;
    - 下排(bl/br):**贴画面下缘**(`bottom_margin` 默认 0 = 与下边缘齐平)。片段本是齐胸特写、
      底边整行都是躯干,让那道平切口落在画面外沿才不像"悬浮的半身像";想让它离下缘一点,
      把 `TTV_AVATAR_CUTOUT_BOTTOM_MARGIN` 调大即可(代价就是那道切口会露出来)。
    """
    c = normalize_corner(corner)
    x = margin_x if c in ("tl", "bl") else max(0, int(video_w) - int(size) - margin_x)
    y = (int(margin_y) if c in ("tl", "tr")
         else max(0, int(video_h) - int(size) - int(bottom_margin)))
    # 上排也可能因为尺寸过大而溢出画面,统一夹一次,别把画面顶出去
    y = max(0, min(y, max(0, int(video_h) - int(size))))
    return x, y


def matte_name(clip_name: str) -> str:
    """片段文件名 → 遮罩文件名(纯函数)。

    遮罩与片段一一对应、同目录同名,只加「模型标识 + 遮罩版本」后缀:
    换模型或改预处理时递增版本即可失效旧遮罩,而**片段缓存不受影响**(不必重跑数字人推理)。
    """
    stem = Path(clip_name).stem
    return f"{stem}.{MATTE_MODEL_TAG}{MATTE_VERSION}.mp4"


def matte_path(clip) -> Path:
    """片段路径 → 遮罩路径(与片段同目录)。"""
    clip = Path(clip)
    return clip.with_name(matte_name(clip.name))


def _log(msg: str) -> None:
    print(f"[avatar] {msg}", flush=True)


# ─────────────────────────── 工具 ───────────────────────────

def hash_file(path: Path, chunk: int = 1 << 20) -> str:
    """文件内容摘要(缓存键用)。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()[:16]


def _ffprobe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float((r.stdout or "0").strip())
    except ValueError:
        return 0.0


def read_wav_16k(path: Path) -> tuple[bytes, int]:
    """读成 16k 单声道 s16 PCM(WAV 且规格已匹配则直读,否则先用 ffmpeg 转)。"""
    try:
        with wave.open(str(path), "rb") as w:
            if (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2):
                return w.readframes(w.getnframes()), 16000
    except (wave.Error, EOFError):
        pass  # 非 WAV(如 mp3)→ 交给 ffmpeg
    tmp = Path(str(path) + ".16k.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-ac", "1", "-ar",
                    "16000", "-c:a", "pcm_s16le", str(tmp)], check=True)
    with wave.open(str(tmp), "rb") as w:
        data = w.readframes(w.getnframes())
    tmp.unlink(missing_ok=True)
    return data, 16000


def _silence_pcm(seconds: float) -> bytes:
    return b"\x00" * int(_INPUT_SAMPLE_RATE * 2 * max(0.1, seconds))


# ─────────────────────── gRPC 客户端 ───────────────────────

class AvatarService:
    """一次连接内复用同一个形象(SetAvatar 只调用一次)。"""

    def __init__(self, image: Path, addr: str = AVATAR_ADDR):
        self.image = Path(image)
        self.addr = addr
        self.channel = grpc.insecure_channel(
            addr, options=[("grpc.max_receive_message_length", _MAX_RECV_BYTES)])
        self.stub = avatar_pb2_grpc.AvatarServiceStub(self.channel)
        self.session_id = "ttv-" + hash_file(self.image)
        self.info = None

    def available(self, timeout: float = 5.0) -> bool:
        try:
            self.info = self.stub.GetInfo(avatar_pb2.GetInfoRequest(), timeout=timeout)
            return True
        except Exception:
            return False

    def set_avatar(self) -> None:
        r = self.stub.SetAvatar(avatar_pb2.SetAvatarRequest(
            session_id=self.session_id,
            image_data=self.image.read_bytes(),
            image_format=self.image.suffix.lstrip(".").lower() or "png",
            use_face_crop=False,
        ))
        if not r.success:
            raise RuntimeError(f"SetAvatar 失败:{r.message}")

    def stream_frames(self, pcm: bytes):
        """把 PCM 送进去,逐个 yield (num_frames, width, height, fps, rgb_bytes)。"""
        def audio_iter():
            for i in range(0, len(pcm), _AUDIO_STEP_BYTES):
                piece = pcm[i:i + _AUDIO_STEP_BYTES]
                yield common_pb2.AudioChunk(
                    data=piece, sample_rate=_INPUT_SAMPLE_RATE, channels=1,
                    format="pcm_s16le", is_final=(i + _AUDIO_STEP_BYTES >= len(pcm)))

        for vc in self.stub.GenerateStream(audio_iter()):
            if vc.num_frames and vc.data:
                yield vc.num_frames, vc.width, vc.height, vc.fps, vc.data
            if vc.is_final:
                break

    def close(self) -> None:
        try:
            self.channel.close()
        except Exception:
            pass


# ─────────────────────── 卡片烘焙(圆角+投影) ───────────────────────

def mask_name(size: int) -> str:
    """圆角遮罩文件名(纯函数,便于测试;含版本号,改烘焙参数即失效)。"""
    radius = max(4, int(size * _RADIUS_RATIO))
    return f"mask_{size}_{radius}_v{AVATAR_CLIP_VERSION}.png"


def _mask_path(size: int) -> Path:
    """圆角矩形遮罩(灰度图,按尺寸缓存)。

    必须用**亮度**编码形状:ffmpeg 的 alphamerge 取的是第二路输入的亮度,
    不是它的 alpha 通道;若遮罩 RGB 全白(亮度 255)则等价于处处不透明,圆角会失效。
    """
    radius = max(4, int(size * _RADIUS_RATIO))
    out = AVATAR_CACHE_DIR / mask_name(size)
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    half = size / 2.0
    inner = half - radius
    # 圆角矩形 SDF:到内缩矩形的最短距离 ≤ 半径即为卡片内部(白),否则外部(黑)
    lum = (f"if(lte(hypot(max(abs(X-{half:.1f})-{inner:.1f},0),"
           f"max(abs(Y-{half:.1f})-{inner:.1f},0)),{radius}),255,0)")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=c=black:s={size}x{size}",
        "-vf", f"format=gray,geq=lum='{lum}'",
        "-frames:v", "1", str(out),
    ], check=True)
    return out


def _bake_filter(size: int, fps: int) -> str:
    """把任意尺寸的 RGB24 帧流缩放成目标尺寸的普通片段。

    注意:H.264 不支持 alpha,所以圆角与投影**不能**烘焙进片段(透明区会变黑底)。
    片段保持纯净的 size×size 画面;圆角/投影由叠加步骤用同一张遮罩完成
    (见 card_overlay_filter),这样片段小 30 倍且叠加仍只是一次 ffmpeg 滤镜图。
    """
    return f"[0:v]scale={size}:{size}:flags=lanczos,format=yuv420p[out]"


def card_overlay_filter(label_in: str, mask_in: str, label_out: str, size: int,
                        fps: int) -> str:
    """把 size×size 的数字人画面变成"圆角卡片+投影",输出可直接 overlay 的流。

    label_in: 数字人画面输入标签(如 "1:v");mask_in: 圆角遮罩输入标签(如 "2:v");
    label_out: 输出标签。内部标签带前缀,避免与调用方的标签冲突。
    """
    canvas = size + 2 * _MARGIN
    p = f"ac{size}_"
    return (
        f"[{label_in}]format=rgba,scale={size}:{size}:flags=lanczos[{p}av];"
        f"[{p}av][{mask_in}]alphamerge[{p}card];"
        f"[{p}card]pad={canvas}:{canvas}:{_MARGIN}:{_MARGIN}:color=0x00000000[{p}pc];"
        f"[{p}pc]split[{p}c1][{p}c2];"
        f"[{p}c2]colorchannelmixer=aa={_SHADOW_ALPHA},boxblur={_SHADOW_BLUR}:1[{p}sh];"
        f"color=c=black@0:s={canvas}x{canvas}:r={fps},format=rgba[{p}bg];"
        f"[{p}bg][{p}sh]overlay={_SHADOW_DX}:{_SHADOW_DY}:shortest=1[{p}withsh];"
        f"[{p}withsh][{p}c1]overlay=0:0:shortest=1[{label_out}]"
    )


def cutout_overlay_filter(label_in: str, matte_in: str, label_out: str, size: int,
                          fps: int = 30) -> str:
    """把 size×size 的数字人画面 + 灰度遮罩变成"只有人像"的流(背景全透明)。

    label_in: 数字人画面输入标签;matte_in: 该片段的灰度遮罩输入标签;label_out: 输出标签。

    与圆角卡片的分工:卡片是**几何形状**(圆角矩形),抠像是**画面内容**(人像 alpha)。
    两者都靠 ffmpeg 的 alphamerge 取第二路输入的**亮度**当 alpha —— 所以遮罩必须是灰度
    (见 _mask_path 的注释;这也正是 matte.py 输出 gray mp4 的原因)。

    注意:遮罩是跟着**片段**缓存的(片段多大就多大),而叠加要的是任务选的 `size` ——
    `alphamerge` 要求两路输入尺寸完全一致,所以遮罩这一路必须一起缩放,否则直接报
    "Input frame sizes do not match"。
    """
    p = f"co{size}_"
    return (
        f"[{label_in}]format=rgba,scale={size}:{size}:flags=lanczos[{p}av];"
        f"[{matte_in}]scale={size}:{size}:flags=bilinear[{p}m];"
        f"[{p}av][{p}m]alphamerge[{label_out}]"
    )


# ─────────────────── 抠像遮罩:生成、缓存、批量 ───────────────────

def matte_available() -> tuple:
    """抠像能不能跑:返回 (可否, 原因)。判据是**解释器与模型文件**都在。

    真正跑不动(onnxruntime 缺失等)会在 worker 里报错,由 ensure_mattes 回退;
    这里只拦"一眼就知道不行"的情况,省得每次都拉起一个必然失败的进程。
    """
    py = Path(MATTE_PYTHON)
    if not py.exists():
        return False, f"抠像解释器不存在:{py}(见 TTV_MATTE_PYTHON)"
    if not Path(MATTE_MODEL).exists():
        return False, f"抠像模型不存在:{MATTE_MODEL}(跑 bash deploy/setup.sh 下载)"
    return True, ""


def _run_matte_worker(pairs: list, on_progress=None) -> dict:
    """一次进程处理**一批**片段:模型只加载一次,顺带把逐段进度读回来。

    pairs: [{"clip": Path, "out": Path}, ...]
    返回 {"done": n, "failed": n};worker 的 stdout 是 JSON 行,stderr 是日志。
    """
    import json
    import tempfile

    manifest = Path(tempfile.mkstemp(prefix="ttv_matte_", suffix=".json")[1])
    manifest.write_text(json.dumps(
        [{"clip": str(Path(p["clip"])), "out": str(Path(p["out"]))} for p in pairs],
        ensure_ascii=False), encoding="utf-8")
    worker = Path(__file__).parent / "matte.py"
    cmd = [str(MATTE_PYTHON), str(worker), "--manifest", str(manifest),
           "--model", str(MATTE_MODEL), "--ref", str(MATTE_REF),
           "--crf", str(MATTE_CRF), "--timeout", str(MATTE_TIMEOUT)]
    total = len(pairs)
    done, failed, err_lines = 0, 0, []
    proc = None
    # 看门狗:worker 自己会对每段超时(见 matte.py),这里再兜一层**进程级**硬上限 ——
    # 抠像再慢也只是"这段没抠成",绝不允许它把构建/渲染线程永远挂住。
    def _kill():
        try:
            if proc and proc.poll() is None:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                _log("抠像进程超时,已强杀(该批遮罩视为失败)")
        except Exception:  # noqa: BLE001 - 看门狗自身不许抛错
            pass

    watchdog = threading.Timer(MATTE_TIMEOUT * total + 120.0, _kill)
    watchdog.daemon = True
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        watchdog.start()
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("event") in ("clip_end", "clip_failed"):
                done = int(ev.get("done") or done)
                if ev.get("event") == "clip_failed":
                    failed += 1
                if on_progress:
                    on_progress(done, total)
        err_lines = (proc.stderr.read() or "").strip().splitlines()[-6:]
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            _kill()
    finally:
        watchdog.cancel()
        manifest.unlink(missing_ok=True)
    if done == 0 and failed == 0:
        raise RuntimeError("抠像进程没有回报任何进度:" + " / ".join(err_lines))
    if err_lines:
        _log("抠像进程日志:" + " / ".join(err_lines))
    return {"done": done, "failed": failed}


def ensure_mattes(timeline: list, progress_cb=None, on_progress=None) -> list:
    """把时间轴里缺遮罩的片段补齐(已有的直接复用),返回**补过遮罩字段**的时间轴。

    - 逐条填 "matte";生成不出来的条目保留 matte=None → 叠加时自动回退圆角卡片;
    - 一批一次进程(模型只加载一次);
    - 失败只记日志并返回原时间轴,绝不抛错打断出片。
    """
    items = [t for t in timeline if t.get("clip") and Path(t["clip"]).exists()]
    for t in timeline:
        t.pop("matte", None)
    if not items:
        return timeline
    ok, why = matte_available()
    if not ok:
        _log(f"抠像不可用({why}),这段成片仍用圆角卡片")
        return timeline
    pending = []
    for t in items:
        m = matte_path(t["clip"])
        if m.exists() and _ffprobe_duration(m) > 0.1:
            t["matte"] = str(m)
        else:
            pending.append({"clip": Path(t["clip"]), "out": m, "item": t})
    if not pending:
        return timeline
    if progress_cb:
        progress_cb(f"生成抠像遮罩 0/{len(pending)}")
    try:
        _run_matte_worker(pending, on_progress=on_progress)
    except Exception as e:  # noqa: BLE001 - 抠像是增强项:失败退回圆角卡片
        _log(f"抠像失败,回退圆角卡片:{e}")
        return timeline
    for p in pending:
        if p["out"].exists() and _ffprobe_duration(p["out"]) > 0.1:
            p["item"]["matte"] = str(p["out"])
    return timeline


def generate_talking(svc: AvatarService, pcm: bytes, out: Path, size: int,
                     fps_hint: int = 20) -> tuple[float, int]:
    """驱动数字人念这段 PCM,产出 size×size 的纯净片段。返回 (时长秒, 帧数)。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = None
    frames = 0
    fps = fps_hint
    try:
        for num, w, h, f, data in svc.stream_frames(pcm):
            if proc is None:
                fps = f or fps_hint
                cmd = [
                    "ffmpeg", "-y", "-v", "error",
                    "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0",
                    "-filter_complex", _bake_filter(size, fps),
                    "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "18", "-preset", "veryfast", str(out),
                ]
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            proc.stdin.write(data)
            frames += num
        if proc is None:
            raise RuntimeError("数字人服务没有返回任何帧")
    finally:
        if proc is not None:
            proc.stdin.close()
            if proc.wait() != 0:
                raise RuntimeError("ffmpeg 编码失败")
    return frames / float(fps), frames


# ─────────────────────── 待机片段与帧片段 ───────────────────────

def idle_clip_path(image: Path, size: int) -> Path:
    key = f"idle_{hash_file(image)}_{size}_{AVATAR_IDLE_SECONDS}_{AVATAR_CLIP_VERSION}"
    return AVATAR_CACHE_DIR / f"{key}.mp4"


def ensure_idle_clip(image: Path, size: int = AVATAR_SIZE,
                     seconds: float = AVATAR_IDLE_SECONDS) -> Path:
    """每个形象只生成一段"闭嘴静默"片段,全局缓存。"""
    out = idle_clip_path(image, size)
    if out.exists() and _ffprobe_duration(out) > 1.0:
        return out
    global AVATAR_IDLE_SECONDS
    AVATAR_IDLE_SECONDS = seconds
    svc = AvatarService(image)
    if not svc.available():
        raise RuntimeError(f"数字人服务不可达:{svc.addr}")
    try:
        svc.set_avatar()
        _log(f"生成待机片段({seconds}s)...")
        generate_talking(svc, _silence_pcm(seconds), out, size)
    finally:
        svc.close()
    _log(f"待机片段已缓存:{out.name}")
    return out


def frame_clip_path(image: Path, audio: Path, frame_duration: float,
                    size: int) -> Path:
    key = (f"clip_{hash_file(image)}_{hash_file(audio)}_{size}_"
           f"{frame_duration:.3f}_{AVATAR_CLIP_VERSION}")
    return AVATAR_CACHE_DIR / f"{key}.mp4"


def build_frame_clip(svc: AvatarService, audio: Path, frame_duration: float,
                     out: Path, size: int = AVATAR_SIZE) -> Path:
    """生成单帧的数字人片段:说话段(配音长度)+ 待机段(补齐到帧总时长)。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    pcm, _ = read_wav_16k(audio)
    talking_dur, frames = generate_talking(svc, pcm, out, size)
    tail = frame_duration - talking_dur
    if tail <= 0.08:
        return out
    # 尾部留白:接一段待机画面,长度精确到 tail
    idle = ensure_idle_clip(svc.image, size)
    tmp = out.with_name(out.stem + ".tail.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(out), "-i", str(idle),
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[out]",
        "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "18", "-preset", "veryfast",
        "-t", f"{frame_duration:.3f}", str(tmp),
    ], check=True)
    tmp.replace(out)
    return out


def ensure_frame_clip(svc: AvatarService, audio: Path, frame_duration: float,
                      size: int = AVATAR_SIZE) -> Path:
    """带全局缓存的取用:同一 (形象, 音频, 尺寸, 帧时长, 版本) 只生成一次,跨任务复用。"""
    out = frame_clip_path(svc.image, audio, frame_duration, size)
    if out.exists() and _ffprobe_duration(out) > 0.1:
        return out
    return build_frame_clip(svc, audio, frame_duration, out, size)


def blank_clip_path(image: Path, frame_duration: float, size: int) -> Path:
    key = (f"blank_{hash_file(image)}_{size}_{frame_duration:.3f}_"
           f"{AVATAR_CLIP_VERSION}")
    return AVATAR_CACHE_DIR / f"{key}.mp4"


def ensure_blank_clip(svc: AvatarService, frame_duration: float,
                      size: int = AVATAR_SIZE) -> Path:
    """无台词帧(opening/closing 等):整段用待机画面,按帧时长精确裁剪。"""
    out = blank_clip_path(svc.image, frame_duration, size)
    if out.exists() and _ffprobe_duration(out) > 0.1:
        return out
    idle = ensure_idle_clip(svc.image, size)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(idle),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "veryfast",
        "-t", f"{frame_duration:.3f}", str(out),
    ], check=True)
    return out


def composite_onto_video(base: Path, timeline: list, out: Path,
                         size: int = AVATAR_SIZE, x: int | None = None,
                         y: int | None = None, fps: int = 30, corner: str = AVATAR_CORNER,
                         cutout: bool = False, progress_cb=None) -> Path:
    """把各帧数字人片段按**帧绝对起点**叠加到成片(圆角卡片,或抠像后的纯人像)。

    timeline: [{"clip": Path, "start": float, "duration": float, "matte": Path?}, ...]
    corner: 四角锚点(默认 config.AVATAR_CORNER,现为右上);x/y 显式给出时优先用它们
    (老调用方与 deploy/verify-avatar.py 的像素校验就是这么传的)。
    cutout: true 时用条目里的 matte 遮罩做抠像叠加(贴画面下缘);该条没有可用遮罩
    就**逐条回退**圆角卡片 —— 一段遮罩没生成出来,不该毁掉整条成片。
    关键:卡片流的 PTS 必须先平移到帧起点(setpts=PTS-STARTPTS+start/TB),
    否则叠加窗口内播放的是它自己时间轴的末尾;enabled 窗口负责窗口外不显示。
    progress_cb(done_sec, total_sec):ffmpeg 已编码到第几秒(界面「叠加数字人」进度用)。
    """
    items = [t for t in timeline if t.get("clip") and Path(t["clip"]).exists()]
    out.parent.mkdir(parents=True, exist_ok=True)
    if not items:
        return base

    # 每条各自定"用抠像还是用卡片":遮罩缺失的条目退回卡片,不与整批绑定
    use_cut = [bool(cutout and t.get("matte") and Path(str(t["matte"])).exists())
               for t in items]
    if cutout and not any(use_cut):
        _log("抠像遮罩全部缺失,本次叠加仍用圆角卡片")
    if x is None or y is None:
        card_x, card_y = corner_xy(corner, size)
        cut_x, cut_y = cutout_xy(corner, size)
    else:
        card_x = cut_x = int(x)
        card_y = cut_y = int(y)

    inputs: list[str] = ["-i", str(base)]
    for it in items:
        inputs += ["-i", str(it["clip"])]
    next_idx = len(items) + 1
    matte_idx: dict = {}
    for n, t in enumerate(items, start=1):
        if use_cut[n - 1]:
            inputs += ["-i", str(t["matte"])]
            matte_idx[n] = next_idx
            next_idx += 1
    mask_idx = None
    if not all(use_cut):                      # 还有条目走卡片 → 才需要圆角遮罩输入
        inputs += ["-i", str(_mask_path(size))]
        mask_idx = next_idx
        next_idx += 1

    parts, prev = [], "0:v"
    for n, it in enumerate(items, start=1):
        s = float(it["start"])
        e = s + float(it["duration"])
        if use_cut[n - 1]:
            parts.append(cutout_overlay_filter(f"{n}:v", f"{matte_idx[n]}:v",
                                               f"card{n}", size, fps))
            ox, oy = cut_x, cut_y
        else:
            parts.append(card_overlay_filter(f"{n}:v", f"{mask_idx}:v", f"card{n}",
                                             size, fps))
            ox, oy = card_x, card_y
        parts.append(f"[card{n}]setpts=PTS-STARTPTS+{s:.3f}/TB[card{n}s]")
        parts.append(
            f"[{prev}][card{n}s]overlay={ox}:{oy}:"
            f"enable='between(t,{s:.3f},{e:.3f})':eof_action=pass[v{n}]")
        prev = f"v{n}"

    cmd = [
        "ffmpeg", "-y", "-v", "error", *inputs,
        "-filter_complex", ";".join(parts),
        "-map", f"[{prev}]", "-map", "0:a?",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
        "-c:a", "copy", str(out),
    ]
    if progress_cb:
        total = _ffprobe_duration(base) or sum(
            float(t.get("start", 0)) + float(t.get("duration", 0)) for t in items)
        _ffmpeg_with_progress(cmd, total, progress_cb)
    else:
        subprocess.run(cmd, check=True)
    return out


def build_frame_clips(script: dict, vo: dict, starts: dict,
                      size: int = AVATAR_SIZE, progress_cb=None,
                      on_frame=None, cutout: bool = False, image: Path | None = None) -> list:
    """为脚本的每一帧生成数字人片段,返回可直接喂给合成的时间轴。

    - image:形象图片;省略时按 config.resolve_avatar_image() **当场解析**
      (形象库的当前默认形象 / TTV_AVATAR_IMAGE 环境变量)。刻意不在 import 时固化,
      这样库里换了默认形象,下一个构建就用新形象,不必重启服务。
    - 有台词的帧:用该帧**最终播放的那个配音文件**驱动(保证只有一套时间轴)
    - 无台词的帧(opening/closing):整段用待机画面
    - 帧时长取自 script(frames[].duration,已由真实音频回填),
      起点取自 assemble.build 的 starts —— 与字幕/音频同一时钟
    - on_frame(n, total, frame_index, duration):结构化进度(数字人播报视频的步骤展示用)
    - cutout=true 时顺带补齐每段的抠像遮罩(timeline[].matte);失败留空、叠加时回退
    """
    image = Path(image) if image else resolve_avatar_image()
    svc = AvatarService(image)
    if not svc.available():
        raise RuntimeError(f"数字人服务不可达:{svc.addr}")
    svc.set_avatar()
    frames = [f for f in (script.get("frames") or []) if float(f.get("duration") or 0) > 0.1]
    timeline = []
    try:
        for n, f in enumerate(frames, start=1):
            idx = f["index"]
            dur = float(f["duration"])
            if progress_cb:
                progress_cb(f"数字人片段 {n}/{len(frames)}(帧 {idx})")
            if on_frame:
                on_frame(n, len(frames), idx, dur)
            entry = vo.get(idx) or vo.get(str(idx)) or {}
            audio = entry.get("path")
            has_line = bool((f.get("voiceover") or "").strip()) and audio and Path(audio).exists()
            clip = (ensure_frame_clip(svc, Path(audio), dur, size) if has_line
                    else ensure_blank_clip(svc, dur, size))
            start = float(starts.get(idx, starts.get(str(idx), 0.0)))
            timeline.append({"index": idx, "clip": str(clip),
                             "start": start, "duration": dur})
    finally:
        svc.close()
    if cutout:
        # 抠像遮罩在这里一次补齐(一批一个进程):片段有缓存,遮罩也有;
        # 生成不出来就留空,叠加时逐条回退圆角卡片(见 composite_onto_video)
        ensure_mattes(timeline, progress_cb=progress_cb)
    return timeline


# ─────────────────── 数字人播报视频(独立产物,不依赖 HyperFrames) ───────────────────
#
# 与成片的关系:成片 = PPT 渲染 + 各帧片段**叠加**(同一时钟);播报视频 = 各帧片段
# **顺序拼接** + 该帧配音拼成的连续音轨。两者共用同一批缓存片段与同一份帧时长,
# 所以画面与配音必然一致,但播报视频不需要 Chrome 渲染,也不受 `--workers` 预检影响。

def _read_pcm(path: Path, rate: int) -> bytes:
    """把任意音频解码为 rate 采样率、单声道、s16 的 PCM(管道直出,不落临时文件)。"""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le",
         "-ac", "1", "-ar", str(rate), "pipe:1"],
        capture_output=True,
    )
    return r.stdout if r.returncode == 0 else b""


def build_broadcast_audio(timeline: list, vo: dict, out: Path,
                          rate: int = 44100) -> float:
    """按时间轴顺序把每帧配音拼成一条连续音轨(帧内不足部分补静音)。

    - 每帧 = 0.25s 静音(VO_OFFSET,与成片里 audio 的 data-start 一致)+ 该帧配音
      + 补静音到帧总时长;无台词帧整段静音。
    - 时间轴顺序即播放顺序,帧时长取自 timeline(已由真实配音回填)。
    返回音轨时长(秒)。
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    # 注意单位:16bit 单声道下,1 个采样 = 2 字节。帧首静音若按"采样数"当字节数用
    # (int(rate*0.25) 是奇数),整条人声会**每个采样错位一个字节** → 听起来全是噪声。
    bytes_per_sample = 2
    head = int(rate * VO_OFFSET) * bytes_per_sample
    total = 0.0
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        for it in timeline:
            dur = float(it["duration"])
            idx = it["index"]
            entry = vo.get(idx) or vo.get(str(idx)) or {}
            src = entry.get("path")
            pcm = b""
            if src and Path(src).exists():
                try:
                    pcm = _read_pcm(Path(src).resolve(), rate)
                except Exception:  # noqa: BLE001 - 单帧音频坏了不该毁掉整条音轨
                    pcm = b""
            # 先算**采样数**再换算成字节,别写成 int(rate * 2 * dur):真实时长
            # (ffprobe 的小数尾巴)下那个乘积约有一半概率是**奇数**,wave 写出奇数
            # 长度后声明帧数比数据区少一个字节 → 从这一帧起每一帧都整体错位一个
            # 字节,整条音轨中段开始变"雪花声"(实测线上任务 -9.4 dB / max 0.0 dB)。
            need = int(rate * dur) * bytes_per_sample
            body = (b"\x00" * head) + pcm
            if len(body) > need:
                body = body[:need]
            elif len(body) < need:
                body = body + b"\x00" * (need - len(body))
            w.writeframes(body)
            total += dur
    return total


def _ffmpeg_with_progress(cmd: list, total_sec: float, progress_cb=None) -> str:
    """跑一次 ffmpeg 并按 `-progress` 输出回报已完成秒数;失败抛错并带上 stderr 尾部。"""
    err = tempfile.TemporaryFile()
    full = cmd + ["-progress", "pipe:1", "-nostats"]
    proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=err, text=True)
    try:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_ms=") and progress_cb:
                try:
                    sec = int(line.split("=", 1)[1]) / 1_000_000.0
                except ValueError:
                    continue
                progress_cb(min(sec, total_sec), total_sec)
    finally:
        proc.stdout.close()
        code = proc.wait()
    if code != 0:
        err.seek(0)
        tail = err.read().decode("utf-8", errors="ignore")[-600:]
        err.close()
        raise RuntimeError(f"ffmpeg 失败(exit {code}):{tail}")
    err.close()
    return ""


def build_broadcast_video(timeline: list, vo: dict, out: Path,
                          progress_cb=None) -> Path:
    """把各帧数字人片段顺序拼成一条独立视频,并合上按同一时间轴拼出的配音音轨。

    timeline: [{"index", "clip", "duration", "start"}, ...](顺序即播放顺序)
    产出:单条 mp4(H.264 + AAC),画面边长 = 片段边长(默认 config.AVATAR_SIZE),不掺 BGM、不掺 PPT 画面。
    """
    items = [t for t in timeline if t.get("clip") and Path(t["clip"]).exists()]
    if not items:
        raise RuntimeError("没有可用的数字人片段,无法拼接播报视频")
    out.parent.mkdir(parents=True, exist_ok=True)
    # 音轨按**片段的真实时长**铺:声明时长(帧时长)与编码出来的时长可能有几十毫秒差,
    # 逐帧累积后会让 `-shortest` 从片尾裁掉台词 —— 音轨必须跟着画面这条时间轴走
    probed = []
    for t in items:
        real = _ffprobe_duration(Path(t["clip"]))
        e = dict(t)
        if real > 0.05:
            e["duration"] = real
        probed.append(e)
    items = probed
    total = sum(float(t["duration"]) for t in items)
    work = Path(tempfile.mkdtemp(prefix="ttv_bc_", dir=str(out.parent)))
    try:
        audio = work / "audio.wav"
        build_broadcast_audio(items, vo, audio)
        lst = work / "clips.txt"
        # concat 解复用器的清单:路径必须绝对 —— 它相对**清单文件所在目录**解析,
        # 而清单在临时目录里(相对路径会解析成临时目录下的不存在文件)
        lines = []
        for t in items:
            p = Path(t["clip"]).resolve().as_posix().replace("'", "'\\''")
            lines.append("file '" + p + "'\n")
        lst.write_text("".join(lines), encoding="utf-8")
        # concat 解复用器 + 重编码:片段虽同规格,但重编码可吃掉帧率/时间基的细微差异
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0", "-i", str(lst),
            "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", "-shortest", str(out),
        ]
        _ffmpeg_with_progress(cmd, total, progress_cb)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not out.exists() or out.stat().st_size < 10000:
        raise RuntimeError("播报视频产物缺失或过小")
    return out


def estimate_broadcast_sec(video_seconds: float, include_tts: bool = True,
                           size: int = AVATAR_SIZE) -> int:
    """粗估「数字人播报视频」生成耗时(秒):配音合成 + 人像逐帧生成 + 拼接编码。

    系数取自 config(可用 TTV_AVATAR_RT_FACTOR / TTV_AVATAR_CONCAT_RT_FACTOR /
    TTV_AVATAR_TTS_RT_FACTOR 覆盖);只用于界面上的「预计时间」,不参与任何产物生成。
    include_tts=False 用于配音已缓存(重跑)的场景。
    size:画面边长。人像推理在服务端固定 464×464(与目标尺寸无关),只有拼接编码随
    像素数变化,所以只需缩放拼接系数(见 concat_rt_factor)。
    """
    v = max(1.0, float(video_seconds or 0))
    rt = max(0.05, AVATAR_RT_FACTOR)
    ct = max(0.5, concat_rt_factor(size))
    est = v / rt + v / ct
    if include_tts:
        est += v / max(0.5, AVATAR_TTS_RT_FACTOR)
    return int(round(est))


def video_duration(path: Path) -> float:
    """产物真实时长(秒):写进任务状态用于展示,避免声明时长与产物不符。"""
    return _ffprobe_duration(Path(path))


def broadcast_eta(step_index: int, done: int | None, total: int | None,
                  elapsed_in_step: float, av_done_sec: float, av_total_sec: float,
                  concat_total_sec: float, concat_done_sec: float = 0.0,
                  size: int = AVATAR_SIZE) -> int | None:
    """生成过程中的「预计剩余秒数」(纯函数,便于回归)。

    步骤:1 合成配音 / 2 生成数字人片段 / 3 拼接播报视频。
    步骤 2 已产生的片段时间可反算真实速率,所以比静态系数更准。
    size 只影响步骤 1/2 里对**尚未开始**的拼接段的估计(见 concat_rt_factor)。
    """
    rt = max(0.05, AVATAR_RT_FACTOR)
    ct = max(0.5, concat_rt_factor(size))
    concat_left = max(0.0, concat_total_sec - concat_done_sec) / ct
    if step_index == 1:
        if not done:
            return None                     # 还没有一帧完成,给不出可信口径
        tts_left = elapsed_in_step / done * max(0, (total or 0) - done)
        return int(round(tts_left + max(0.0, av_total_sec - av_done_sec) / rt + concat_left))
    if step_index == 2:
        if av_done_sec > 0 and elapsed_in_step > 0.5:
            rt = max(0.05, av_done_sec / elapsed_in_step)
        return int(round(max(0.0, av_total_sec - av_done_sec) / rt + concat_left))
    if step_index == 3:
        return int(round(concat_left))
    return None



def write_timeline(timeline: list, path: Path) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")


def read_timeline(path: Path) -> list:
    import json
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")) or []
    except Exception:
        return []


def probe() -> dict:
    """自检:服务是否可达、服务端规格是什么。"""
    svc = AvatarService(AVATAR_IMAGE)
    try:
        if not svc.available():
            return {"available": False, "addr": svc.addr}
        i = svc.info
        return {"available": True, "addr": svc.addr, "model": i.model_name,
                "server_size": f"{i.output_width}x{i.output_height}",
                "fps": i.output_fps, "frames_per_chunk": i.frames_per_chunk}
    finally:
        svc.close()


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="生成单段数字人片段")
    ap.add_argument("--image", default=str(AVATAR_IMAGE))
    ap.add_argument("--audio", help="台词音频;省略则生成待机片段")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="帧总时长;省略则等于音频长度")
    ap.add_argument("--size", type=int, default=AVATAR_SIZE)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    image, out = Path(a.image), Path(a.out)
    svc = AvatarService(image)
    if not svc.available():
        print(f"数字人服务不可达:{svc.addr}")
        return 2
    print("服务规格:", probe())
    try:
        svc.set_avatar()
        if not a.audio:
            clip = ensure_idle_clip(image, a.size)
        else:
            pcm, _ = read_wav_16k(Path(a.audio))
            dur = a.duration or (len(pcm) / 2 / _INPUT_SAMPLE_RATE)
            clip = build_frame_clip(svc, Path(a.audio), dur, out, a.size)
        print(f"完成:{clip}  时长 {_ffprobe_duration(clip):.2f}s")
    finally:
        svc.close()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
