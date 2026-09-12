# -*- coding: utf-8 -*-
"""全局配置:路径、模型端点、风格清单。

所有路径默认落在**仓库根目录(= 工作区根)**内,不依赖任何工作区外的绝对路径;
每项都可用 TTV_* 环境变量覆盖(生产部署只需设 TTV_ROOT 指向部署目录)。
"""
import os
import shutil
from pathlib import Path

# 仓库根目录:server/ 的上一级。生产环境可用 TTV_ROOT 覆盖。
ROOT = Path(os.environ.get("TTV_ROOT", str(Path(__file__).resolve().parents[1])))
JOBS_DIR = ROOT / "jobs"
WEB_DIR = ROOT / "web"
ASSETS_DIR = ROOT / "assets"          # 共享资产:字体/BGM/vendor
FONTS_DIR = ASSETS_DIR / "fonts"
BGM_DIR = ASSETS_DIR / "bgm"
VENDOR_DIR = ASSETS_DIR / "vendor"

# 模型权重与本地运行时(全部在工作区内,不入库;见 .gitignore)
MODELS_DIR = Path(os.environ.get("TTV_MODELS_DIR", str(ROOT / "models")))
COSYVOICE_MODEL_DIR = Path(os.environ.get("TTV_COSYVOICE_DIR", str(MODELS_DIR / "CosyVoice3-0.5B")))
QWEN_TTS_MODEL_DIR = Path(os.environ.get(
    "TTV_QWEN_TTS_DIR", str(MODELS_DIR / "Qwen3-TTS-0.6B" / "Qwen3-TTS-0.6B-Base")))
COSYVOICE_SRC_DIR = Path(os.environ.get("TTV_COSYVOICE_SRC", str(ROOT / "cosyvoice-src")))
TTS_VENV_DIR = Path(os.environ.get("TTV_TTS_VENV", str(ROOT / "tts-venv")))

# CosyVoice3 锁定的运行时依赖(见 BUILD.md 第四节):语音 LLM 跑在 Qwen2 backbone 上,
# **只有**官方锁定的 transformers 能解码正确;4.52+ 会让 speech token 乱掉,听感是
# 「读音完全不正常、断断续续」,而时长与峰值全部正常 —— 时长/静音验收发现不了。
# tts 服务启动时硬校验(不符即拒启),smoke_test 另做一次环境校验。
PINNED_TTS_DEPS = {"transformers": "4.51.3", "tokenizers": "0.21.4"}

# ── 配音合成口径(进配音复用指纹,决定"旧配音还能不能接着用") ──
# 凡是会让同一段文字合成出**更正确**音频的变化(模型、运行时、解码参数、验收逻辑),
# 都要递增这个版本:它进复用指纹,旧配音因此自动作废、下次构建重新合成。
# 为什么非要有这个旋钮(2026-09-12 事故):transformers 4.52+ 会把语音 LLM 的输出打乱,
# 听起来是乱码,而**时长与峰值全正常**(时长/静音验收都拦不住)。运行时修好之后,
# 已经烧坏的那批配音因为指纹没变而被一直复用 —— 于是"运行时修好了,成片还是乱的",
# 用户听到的仍然是乱码。只有换指纹才能把烧坏的那批配音真正作废。
VO_SYNTH_VERSION = os.environ.get("TTV_VO_SYNTH_VERSION", "2")


def vo_runtime_fingerprint() -> str:
    """配音运行时口径 = 钉版依赖 + 合成版本;进 `_vo_signature`,变了就重新合成。"""
    deps = ",".join(f"{k}=={v}" for k, v in sorted(PINNED_TTS_DEPS.items()))
    return f"{deps};vo{VO_SYNTH_VERSION}"


# ── 配音可懂度抽检(合成后 whisper 听写 1-2 帧 vs 台词) ──
# 时长/静音验收发现不了"念的是乱码"(见 VO_SYNTH_VERSION 的注释),唯一能识破的是"听出
# 来是什么字"。抽检只在**真正重新合成**后跑一次,约 30-60 秒,失败一律跳过、不阻塞构建。
# TTV_VO_CHECK_FRAMES=0 可完全关掉;whisper 装在配音 venv 里(见 tts-venv)。
VO_CHECK_FRAMES = int(os.environ.get("TTV_VO_CHECK_FRAMES", "2"))
VO_CHECK_TIMEOUT = float(os.environ.get("TTV_VO_CHECK_TIMEOUT", "900"))
VO_CHECK_MODEL_DIR = Path(os.environ.get(
    "TTV_VO_CHECK_MODEL_DIR", str(MODELS_DIR / "whisper")))


def pinned_dep_mismatch(versions: dict) -> list:
    """[versions] 为实际版本(缺失传 None);返回与钉版不符的描述(空列表=相符)。

    纯函数,便于回归:这是唯一能在坏音上线前拦住它的检查。
    """
    bad = []
    for name, want in PINNED_TTS_DEPS.items():
        got = (versions or {}).get(name) or "缺失"
        if got != want:
            bad.append(f"{name}=={got}(应为 {want})")
    return bad

# ── 数字人形象库 ──
# 形象不再是「一个写死的文件」,而是**一个目录**里的一个库:
#   图片本体 + 清单 library.json(纯 JSON,与图片同目录,一起备份/迁移)。
# 库的增删改查、图片头解析、自愈都在 server/avatar_library.py(零第三方依赖)。
def _avatar_library_dir() -> Path:
    """形象库目录。TTV_AVATAR_LIBRARY 既可指向目录,也可指向目录下的 library.json。

    只允许一个目录的含义:图片与清单必须同处一地 —— 否则「清单指向的图片」与
    「回退用的内置形象」会落在两个目录,覆盖路径时内置形象就会解析到一个空目录
    (第一版实现踩过,见 CHANGELOG)。
    """
    raw = os.environ.get("TTV_AVATAR_LIBRARY") or str(ASSETS_DIR / "avatars")
    p = Path(raw)
    if p.suffix == ".json" or p.is_file():
        p = p.parent
    return p


AVATAR_LIBRARY_DIR = _avatar_library_dir()
AVATAR_LIBRARY_FILE = AVATAR_LIBRARY_DIR / "library.json"
# 内置(随仓库分发)的形象文件:它是「最后一个可回退的人」,所以路径**不跟随**库目录 ——
# 库目录被覆盖成空目录(单测/多实例)时,仍然应该能回退到它。
AVATAR_BUILTIN_FILE = Path(os.environ.get(
    "TTV_AVATAR_BUILTIN", str(ASSETS_DIR / "avatars" / "jinli.png")))
# 单张形象图上限:与文章上传保持一致(20MB)
AVATAR_UPLOAD_MAX = int(os.environ.get("TTV_AVATAR_UPLOAD_MAX", str(20 * 1024 * 1024)))
# 允许的图片扩展名 → MIME(前端 accept、上传校验、取图响应头共用一份)
AVATAR_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def resolve_avatar_image() -> Path:
    """当前生效的形象图片路径(每次调用都重新解析,不在 import 时固化)。

    优先级:TTV_AVATAR_IMAGE 环境变量 > 形象库里的默认形象 > 内置 jinli.png。
    库文件损坏/条目指向的文件丢失都由 avatar_library 自愈;整条链路失败时
    回退到内置形象,绝不因为「形象库坏了」让构建起不来。
    """
    env = os.environ.get("TTV_AVATAR_IMAGE")
    if env:
        return Path(env)
    try:
        from avatar_library import resolve_default_image
        return resolve_default_image()
    except Exception:  # noqa: BLE001 - 形象库异常不该拖垮构建
        return AVATAR_BUILTIN_FILE


# 日志统一收在 ROOT/logs 下(不污染项目根目录;deploy/*.sh 的重定向路径与此一致)
LOG_DIR = Path(os.environ.get("TTV_LOG_DIR", str(ROOT / "logs")))
BACKEND_LOG = LOG_DIR / "backend.log"      # 后端 uvicorn(由 deploy/start.sh 重定向)
STUDIO_LOG_DIR = LOG_DIR / "studio"        # 每任务一个 <job_id>.log(hyperframes preview 输出)
TTS_LOG_DIR = LOG_DIR / "tts"              # CosyVoice3 多实例 / Qwen3-TTS 服务日志

# 本地 DeepSeek(vLLM,OpenAI 兼容,纯 HTTP 走网关)
DEEPSEEK_LOCAL_URL = os.environ.get("TTV_DEEPSEEK_URL", "http://8.130.213.80:20001/v1")
DEEPSEEK_MODEL = os.environ.get("TTV_DEEPSEEK_MODEL", "DeepSeek-V4-Flash")
# 可选:本地端点需要鉴权时(如指向 paratera 等 OpenAI 兼容网关)填 Bearer key。
# 生产 vLLM 不校验鉴权,留空即可保持原行为。
DEEPSEEK_LOCAL_KEY = os.environ.get("TTV_DEEPSEEK_KEY", "")
# 上面三项是**出厂默认**:网页「设置」页写过之后以网页里的为准(server/settings.py,
# 保存即生效,不用重启后端)。analyze.py 也因此在**每次调用时**读设置,而不是 import 时固化。
# 成片保存位置(出厂默认):空 = 不额外另存,只在项目目录里留一份;网页「设置」页可改。
EXPORT_DIR = os.environ.get("TTV_EXPORT_DIR", "")
# 云 API 备份(工作区内的 key 文件,不存在则跳过)
DEEPSEEK_CLOUD_KEYFILE = os.environ.get(
    "TTV_DEEPSEEK_KEYFILE", str(ROOT / ".secrets" / "deepseek.env"))
DEEPSEEK_CLOUD_URL = "https://api.deepseek.com/v1"
DEEPSEEK_CLOUD_MODEL = "deepseek-chat"

BACKEND_PORT = int(os.environ.get("TTV_PORT", "8015"))

# 本地 CosyVoice2 TTS 服务(首选;不可用时回退 edge-tts)
LOCAL_TTS_URL = os.environ.get("TTV_TTS_URL", "http://127.0.0.1:8016")

# 风格键 → 名称
STYLES = {
    "solemn-red": "庄重肃穆·中国红",
    "academic-ink": "清雅学术·墨黛青",
    "modern-blue": "现代锐意·科技蓝",
}

# 视频规格
WIDTH, HEIGHT, FPS = 1920, 1080, 30


def _resolve_node_bin_dir() -> str:
    """node 可执行文件所在目录:显式覆盖 > 当前 node > 空(不改动 PATH)。

    服务器上 node 不在 PATH,故服务调用 hyperframes 时会把该目录前置到 PATH。
    """
    explicit = os.environ.get("TTV_NODE_BIN")
    if explicit:
        return explicit
    node = shutil.which("node")
    return str(Path(node).resolve().parent) if node else ""


NODE_BIN_DIR = _resolve_node_bin_dir()


def _resolve_hyperframes_runtime() -> Path:
    """hyperframes 的预览运行时脚本,按 node 全局包布局推导(可用 TTV_HYPERFRAMES_RUNTIME 覆盖)。"""
    explicit = os.environ.get("TTV_HYPERFRAMES_RUNTIME")
    if explicit:
        return Path(explicit)
    node = shutil.which("node")
    if node:
        prefix = Path(node).resolve().parents[1]
        return prefix / "lib" / "node_modules" / "hyperframes" / "dist" / "hyperframe-runtime.js"
    return Path("hyperframe-runtime.js")


HYPERFRAMES_RUNTIME = _resolve_hyperframes_runtime()

# ── 数字人(avatar)片段 ──
# 由 CyberVerse 的 AvatarService(gRPC)按每帧台词音频驱动出帧,再烘焙成卡片片段。
# 默认关闭:只有任务显式开启数字人时才生成,不影响既有出片流程。
AVATAR_ENABLED = os.environ.get("TTV_AVATAR", "0") == "1"
AVATAR_ADDR = os.environ.get("TTV_AVATAR_ADDR", "127.0.0.1:50051")
# 形象:默认取 builder.styles.AVATARS 注册表里的默认形象;TTV_AVATAR_IMAGE 可覆盖
def _default_avatar_image() -> Path:
    try:
        from builder.styles import avatar_file
        return ASSETS_DIR / avatar_file()
    except Exception:
        return ASSETS_DIR / "avatars" / "jinli.png"


AVATAR_IMAGE = Path(os.environ.get("TTV_AVATAR_IMAGE", str(_default_avatar_image())))
# 数字人卡片的边长(正方形,故一个数即尺寸)。生成端可能更高,烘焙时缩放。
# 这一个值同时是:成片里叠加的那个人像的默认大小、以及「数字人播报视频」的默认边长。
AVATAR_SIZE = int(os.environ.get("TTV_AVATAR_SIZE", "300"))
# 可选边长(前端快捷档位;逗号分隔可覆盖)。默认值由 avatar_size_options() 并进去。
AVATAR_SIZE_CHOICES = tuple(
    int(x) for x in os.environ.get(
        "TTV_AVATAR_SIZE_CHOICES", "240,300,400,464,640").split(",") if x.strip())
# 允许的边长区间:偶数才能过 H.264 yuv420p;低于 160 看不清人脸,高于 1080 无意义。
AVATAR_SIZE_MIN = int(os.environ.get("TTV_AVATAR_SIZE_MIN", "160"))
AVATAR_SIZE_MAX = int(os.environ.get("TTV_AVATAR_SIZE_MAX", "1080"))
# 服务端原生输出边长(FlashHead 464×464):超过它只是放大,不会再增加细节,
# 前端据此对超限档位标注「放大」。
AVATAR_NATIVE_SIZE = int(os.environ.get("TTV_AVATAR_NATIVE_SIZE", "464"))
# 成片里数字人的四角锚点:tl 左上 / tr 右上 / br 右下 / bl 左下。默认右上。
AVATAR_CORNERS = {"tl": "左上", "tr": "右上", "br": "右下", "bl": "左下"}
AVATAR_CORNER = os.environ.get("TTV_AVATAR_CORNER", "tr")
if AVATAR_CORNER not in AVATAR_CORNERS:      # 配置写坏就回默认,别让服务起不来
    AVATAR_CORNER = "tr"


def avatar_size_options() -> list:
    """前端下拉用的边长清单:默认值必在首位之后去重升序,非法项直接剔除。

    纯函数,便于回归:环境变量写错(奇数/超界)时界面不能出现一个点了必报 400 的档位。
    """
    seen = []
    for s in (AVATAR_SIZE, *AVATAR_SIZE_CHOICES):
        try:
            s = int(s)
        except (TypeError, ValueError):
            continue
        if s % 2 or not (AVATAR_SIZE_MIN <= s <= AVATAR_SIZE_MAX):
            continue
        if s not in seen:
            seen.append(s)
    return sorted(seen) or [AVATAR_SIZE]   # 配置写坏了也保证界面有档位可选


def avatar_corner_options() -> list:
    """前端位置选择器的四角清单(网格顺序:左上/右上/右下/左下)。

    默认角由 AVATAR_CORNER 单独给出 —— 清单顺序保持稳定,界面用「(默认)」标注,
    比把默认项挪到第一项更好认。
    """
    return [{"key": k, "name": name} for k, name in AVATAR_CORNERS.items()]

# ── 数字人抠像(「只保留人像、背景透明」) ──
# 打开后不再叠圆角卡片,而是只把人像本体叠上去:幻灯片内容从人像四周透出来。
# 做法:给每段片段额外生成一条**灰度遮罩**(server/matte.py,MODNet ONNX 本地推理),
# 叠加时 `[片段][遮罩]alphamerge` 得到带 alpha 的人像(见 ADR-0004)。
# 默认 **true** —— 上传的形象多是真实照片,带背景的圆角卡片会盖住幻灯片,抠掉才符合预期;
# 「新任务默认抠不抠」现在是**全局偏好**(server/preferences.py,形象页可改、持久化),
# 这个环境变量是**出厂默认**:偏好文件里没写过时用它。
# 抠像不可用(解释器/权重缺失)时逐条回退圆角卡片,所以默认开着是安全的。
AVATAR_CUTOUT = os.environ.get("TTV_AVATAR_CUTOUT", "1") == "1"
# 全局偏好文件(跨任务记住的设置;缺失/损坏时回退出厂默认)
PREFERENCES_FILE = Path(os.environ.get(
    "TTV_PREFERENCES", str(ROOT / ".run" / "preferences.json")))
# 网页「设置」页写入的运行参数(分析服务端点 / 成片保存位置;server/settings.py)。
# 与偏好同目录、同样不入库;里面有密钥,所以写盘时权限收紧到 0600。
SETTINGS_FILE = Path(os.environ.get(
    "TTV_SETTINGS", str(ROOT / ".run" / "settings.json")))
# 抠像模式下**下排角落**离画面下缘的留白(默认 0 = 齐平)。四个角落都能摆,上下口径不同:
# 上排(tl/tr)用 AVATAR_Y 留出头顶空间;下排贴下缘是因为片段本就是齐胸特写、底部整行都是
# 躯干(alpha≈1),让那道平切口落在画面外沿才不像"悬浮的半身像"(调大这个值切口就会露出来)。
AVATAR_CUTOUT_BOTTOM_MARGIN = int(os.environ.get("TTV_AVATAR_CUTOUT_BOTTOM_MARGIN", "0"))
# 遮罩版本:抠像模型/预处理/编码口径变化时递增,自动失效旧的遮罩缓存(片段缓存不受影响)
MATTE_VERSION = os.environ.get("TTV_MATTE_VERSION", "1")
# 模型标识(进遮罩文件名):换模型时与 MATTE_VERSION 一起决定缓存键
MATTE_MODEL_TAG = os.environ.get("TTV_MATTE_MODEL_TAG", "modnet")
MATTE_MODEL = Path(os.environ.get(
    "TTV_MATTE_MODEL", str(MODELS_DIR / "matte" / "modnet.onnx")))
# 权重下载源(顺次尝试;默认走 hf-mirror,国内直连 huggingface 常不通)
MATTE_URLS = tuple(u.strip() for u in os.environ.get("TTV_MATTE_URLS", ",".join((
    "https://hf-mirror.com/Xenova/modnet/resolve/main/onnx/model.onnx",
    "https://huggingface.co/Xenova/modnet/resolve/main/onnx/model.onnx",
))).split(",") if u.strip())
# 跑抠像的解释器:后端**不**引入 onnxruntime,只按 subprocess 调这个解释器里的 matte.py
# (默认 tts-venv —— 它已经有了 onnxruntime 与 numpy;没有就回退成不抠像)
MATTE_PYTHON = os.environ.get("TTV_MATTE_PYTHON", str(TTS_VENV_DIR / "bin" / "python"))
# 模型输入侧最短边(MODNet 官方口径 512;调小更快、边缘更糊)
MATTE_REF = int(os.environ.get("TTV_MATTE_REF", "512"))
# 遮罩编码质量:灰度 + 极低 CRF(遮罩是形状,不能像彩色画面那样压)
MATTE_CRF = int(os.environ.get("TTV_MATTE_CRF", "12"))
# 单段遮罩的墙钟上限(秒):卡死要能自己失败并回退,不能挂住整条流水线
MATTE_TIMEOUT = float(os.environ.get("TTV_MATTE_TIMEOUT", "1800"))

# 片段缓存(跨任务复用;与形象/音频/规格/版本共同决定键)
AVATAR_CACHE_DIR = Path(os.environ.get("TTV_AVATAR_CACHE", str(ROOT / ".cache" / "avatar")))
# 待机片段时长:每个形象只生成一段,用于填充帧内无台词的时间
AVATAR_IDLE_SECONDS = float(os.environ.get("TTV_AVATAR_IDLE_SECONDS", "6.0"))
# 片段规格版本:烘焙/编码参数变化时递增,自动失效旧缓存
AVATAR_CLIP_VERSION = os.environ.get("TTV_AVATAR_CLIP_VERSION", "2")
# 数字人卡片距画面边缘的留白(像素):四个角落锚点都由它推出坐标(见 avatar.corner_xy)
AVATAR_X = int(os.environ.get("TTV_AVATAR_X", "40"))
AVATAR_Y = int(os.environ.get("TTV_AVATAR_Y", "36"))
# 速度系数(用于「生成步骤 + 预计时间」,只影响展示,不影响产物):
# AVATAR_RT_FACTOR = 人像出片速度(秒视频 / 秒墙钟)。5090 + FlashHead 实测 ≈0.85
#   (23.9s 音频 → 28.6s 墙钟);AVATAR_CONCAT_RT_FACTOR = 拼接编码速度(秒视频/秒墙钟),
# 实测 **320×320** 约 56×,取 15× 留足音轨解码/探长的余量(宁高估不低估);
# AVATAR_TTS_RT_FACTOR = 配音合成速度(秒音频/秒墙钟),单实例实测 ≈2.5×。
# 事前预计把配音也算进去(首次生成必须合成配音;配音已缓存时会略微高估)。
AVATAR_RT_FACTOR = float(os.environ.get("TTV_AVATAR_RT_FACTOR", "0.85"))
AVATAR_CONCAT_RT_FACTOR = float(os.environ.get("TTV_AVATAR_CONCAT_RT_FACTOR", "15.0"))
# 上面那个拼接系数是在哪个边长实测的:换尺寸时按面积比外推(见 avatar.concat_rt_factor),
# 所以默认边长改成 300 后,系数不会跟着被"解释成 300 的实测值"。
AVATAR_CONCAT_BASE_SIZE = int(os.environ.get("TTV_AVATAR_CONCAT_BASE_SIZE", "320"))
AVATAR_TTS_RT_FACTOR = float(os.environ.get("TTV_AVATAR_TTS_RT_FACTOR", "2.5"))
# 渲染与叠加的速度系数(秒视频/秒墙钟),用于「渲染中」的预计剩余(只影响展示)。
# 实测 1080p + --workers 1 流式捕获:81s 片 ≈85s(0.95)、152s 片 ≈200s(0.76),
# 取 0.8;叠加(libx264 medium,1080p):81s 片 15s(5.4)、152s 片 ≈40s(3.8),取 4.5。
# 捕获阶段一旦有帧数,预计剩余改用实测速率反推,比这两个静态系数准。
RENDER_RT_FACTOR = float(os.environ.get("TTV_RENDER_RT_FACTOR", "0.8"))
OVERLAY_RT_FACTOR = float(os.environ.get("TTV_OVERLAY_RT_FACTOR", "4.5"))
# CyberVerse(数字人推理服务)所在目录,供 deploy/start-avatar.sh 启动
CYBERVERSE_DIR = Path(os.environ.get("TTV_CYBERVERSE_DIR", str(ROOT / "CyberVerse-main")))

# 单帧旁白语速校准:字数/秒(用于 DeepSeek 提示与时长估算)
CHARS_PER_SEC = 4.2

def read_cloud_api_key() -> str | None:
    """从 wsh/cot/.env 读取 DEEPSEEK_API_KEY(云 API 备份用)。"""
    p = Path(DEEPSEEK_CLOUD_KEYFILE)
    if not p.exists():
        return None
    for line in p.read_text(errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("DEEPSEEK_API_KEY"):
            _, _, val = line.partition("=")
            return val.strip().strip('"').strip("'") or None
    return None
