# -*- coding: utf-8 -*-
"""全局配置:路径、模型端点、风格清单。"""
import os
from pathlib import Path

# 部署根目录(服务器:/mnt/workspace/ttv)
ROOT = Path(os.environ.get("TTV_ROOT", "/mnt/workspace/ttv"))
JOBS_DIR = ROOT / "jobs"
WEB_DIR = ROOT / "web"
ASSETS_DIR = ROOT / "assets"          # 共享资产:字体/BGM/vendor
FONTS_DIR = ASSETS_DIR / "fonts"
BGM_DIR = ASSETS_DIR / "bgm"
VENDOR_DIR = ASSETS_DIR / "vendor"

# 日志统一收在 ROOT/logs 下(不污染项目根目录;deploy/*.sh 的重定向路径与此一致)
LOG_DIR = Path(os.environ.get("TTV_LOG_DIR", str(ROOT / "logs")))
BACKEND_LOG = LOG_DIR / "backend.log"      # 后端 uvicorn(由 deploy/start.sh 重定向)
STUDIO_LOG_DIR = LOG_DIR / "studio"        # 每任务一个 <job_id>.log(hyperframes preview 输出)
TTS_LOG_DIR = LOG_DIR / "tts"              # CosyVoice3 多实例 / Qwen3-TTS 服务日志

# 本地 DeepSeek(vLLM,OpenAI 兼容,纯 HTTP 走网关)
DEEPSEEK_LOCAL_URL = os.environ.get("TTV_DEEPSEEK_URL", "http://8.130.213.80:20001/v1")
DEEPSEEK_MODEL = os.environ.get("TTV_DEEPSEEK_MODEL", "DeepSeek-V4-Flash")
# 云 API 备份(读取服务器上已有 key 文件,key 文件不存在则跳过)
DEEPSEEK_CLOUD_KEYFILE = "/mnt/workspace/wsh/cot/.env"
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

# Node(服务器上不在 PATH)
NODE_BIN_DIR = "/mnt/workspace/node/bin"

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
