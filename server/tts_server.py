# -*- coding: utf-8 -*-
"""CosyVoice3 TTS 服务(FastAPI,127.0.0.1:8016,GPU1)。

接口:
  GET  /health            → {"ok": true}
  GET  /voices            → 可用音色列表
  POST /tts {text, voice, speed} → audio/wav

部署规范:
  - 权重:工作区内 models/CosyVoice3-0.5B(FunAudioLLM/Fun-CosyVoice3-0.5B-2512,ModelScope 下载)
  - 服务:工作区内 tts-venv,启动脚本 deploy/start-tts.sh
  - 端口:127.0.0.1:8016;GPU 由 start-tts.sh 的 TTV_TTS_GPUS 指定
"""
import io
import logging
import os
import re
import threading

import soundfile as sf
import torch
import torchaudio
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

# ── torchaudio 2.10 需要 torchcodec 后端,本机 PPU 平台无 wheel ──
# 用 soundfile 替换 torchaudio.load/save(cosyvoice 的 load_wav 与我们的保存都走这里)
def _sf_load(path, **kwargs):
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return torch.from_numpy(data.T), sr


def _sf_save(path, tensor, sr, **kwargs):
    data = tensor.detach().cpu().numpy()
    if data.ndim == 2:
        data = data.T
    sf.write(str(path), data, sr)


torchaudio.load = _sf_load
torchaudio.save = _sf_save

from cosyvoice.cli.cosyvoice import AutoModel
from cosyvoice.utils.file_utils import load_wav

from config import CHARS_PER_SEC, COSYVOICE_MODEL_DIR

MODEL_DIR = str(COSYVOICE_MODEL_DIR)
REF_DIR = str(COSYVOICE_MODEL_DIR / "asset-v2")   # 零样本参考音频(edge-tts 新闻腔种子)
SAMPLE_RATE = 24000

app = FastAPI(title="CosyVoice3 TTS")
_lock = threading.Lock()

# 零样本克隆音色(键 → 参考 wav 文件名 + prompt 文本)
# 注意:CosyVoice3 的 prompt_text 必须含 <|endofprompt|> 分隔符(前为系统提示,后为参考音频逐字文本)
CV3_SYS = "You are a helpful assistant.<|endofprompt|>"
VOICES = {
    "male": ("male.wav", CV3_SYS + "各位观众大家好,欢迎收看今天的节目。当前我国经济社会发展稳中有进,高质量发展扎实推进,各项事业取得新的重大成就。"),
    "female": ("female.wav", CV3_SYS + "大家好,欢迎来到今天的节目。理论创新每前进一步,理论武装就要跟进一步。让我们共同思考,共同学习。"),
    "male_narrator": ("male_narrator.wav", CV3_SYS + "新时代赋予新使命,新征程呼唤新作为。让我们坚定信心、真抓实干,在新赛道上跑出加速度。"),
}

model = None

# ── LLM 解码参数(稳定性开关) ──
# CosyVoice3 的 Qwen2LM.inference 默认 sampling=25 / max_token_text_ratio=20 / min=2:
#   max_len = 文本 token 数 × 20 → 模型若不收尾就**顶到上限被截断**;
#   min_len = 文本 token 数 × 2  → 过早 EOS 时会**只念半句**。
# 两者在音频上就是「支离破碎」。另外 llm.sampling 默认是 ras_sampling,内部调
# nucleus_sampling(top_p=0.8, top_k=25),**完全不用 inference 传进来的 sampling 参数** ——
# 所以真正能压住方差的是这里的 top_p/top_k(可换成贪心 = top_k 1 + 禁用随机)。
# 参数可全局设(环境变量)也可**按请求覆盖**(便于 A/B,不必每次重启服务重载模型)。
_GEN = {
    "sampling": int(os.environ.get("TTV_TTS_SAMPLING", "25")),
    "max_token_text_ratio": float(os.environ.get("TTV_TTS_MAX_RATIO", "20")),
    "min_token_text_ratio": float(os.environ.get("TTV_TTS_MIN_RATIO", "2")),
}
_SAMPLING_CFG = {
    "top_p": float(os.environ.get("TTV_TTS_TOP_P", "0.8")),
    "top_k": int(os.environ.get("TTV_TTS_TOP_K", "25")),
    "greedy": os.environ.get("TTV_TTS_GREEDY", "0") == "1",
}
# 时长验收窗口:实际/预期(字数 ÷ CHARS_PER_SEC)。超出即判为截断或复读,重采。
_ACCEPT = (float(os.environ.get("TTV_TTS_ACCEPT_LO", "0.65")),
           float(os.environ.get("TTV_TTS_ACCEPT_HI", "1.8")))
_ATTEMPTS = max(1, int(os.environ.get("TTV_TTS_ATTEMPTS", "6")))
_LLM_PATCHED = False
_FP16 = os.environ.get("TTV_TTS_FP16", "1") == "1"


def _expected_sec(text: str) -> float:
    """按实测语速估算应有配音时长(秒)。"""
    n = len(re.sub(r"\s", "", text))
    return max(1.0, n / CHARS_PER_SEC)


def _make_sampling(original):
    """包一层采样函数:支持贪心与自定义 top_p/top_k(ras_sampling 内部写死了 0.8/25)。"""
    def sampling(weighted_scores, decoded_tokens, sampling_k, **kw):
        if _SAMPLING_CFG["greedy"]:
            return int(torch.argmax(weighted_scores).item())
        return original(weighted_scores, decoded_tokens, sampling_k,
                        top_p=_SAMPLING_CFG["top_p"], top_k=_SAMPLING_CFG["top_k"])
    return sampling


def _patch_llm_sampling():
    """把解码参数注入 llm.inference / llm.sampling(默认值来自 _GEN,可被请求临时覆盖)。"""
    global _LLM_PATCHED
    if _LLM_PATCHED or model is None:
        return
    llm = getattr(getattr(model, "model", None), "llm", None)
    if llm is None or not hasattr(llm, "inference"):
        return
    orig = llm.inference

    def inference(*args, **kwargs):
        for k, v in _GEN.items():
            kwargs.setdefault(k, v)
        return orig(*args, **kwargs)

    llm.inference = inference
    if callable(getattr(llm, "sampling", None)):
        llm.sampling = _make_sampling(llm.sampling)
    _LLM_PATCHED = True


def _get_model():
    global model
    if model is None:
        # CosyVoice3 构造签名与 v1/v2 不同:无 load_jit
        # fp16 在本机(PPU 后端)上解码不稳定:EOS 时早时晚,音频被截断/复读。
        # 可用 TTV_TTS_FP16=0 切 fp32 实测(慢一些,但数值更稳)。
        model = AutoModel(model_dir=MODEL_DIR, fp16=_FP16)
        _patch_llm_sampling()
    return model


def _ref_of(voice: str):
    return VOICES[voice][0], VOICES[voice][1]


@app.get("/health")
def health():
    return {"ok": True, "model_loaded": model is not None, "gpu": torch.cuda.is_available()}


@app.get("/voices")
def voices():
    return {"voices": list(VOICES.keys())}


class TTSRequest(BaseModel):
    text: str
    voice: str = "male"
    speed: float = 1.0
    # 可选:按请求覆盖解码参数(实测/调参用;不传则用 _GEN)
    sampling: int | None = None
    max_token_text_ratio: float | None = None
    min_token_text_ratio: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    greedy: bool | None = None


@app.post("/tts")
def tts(req: TTSRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "text 为空")
    if len(text) < 8:
        # 过短文本会使 vocoder 卷积核报错(kernel>input)
        raise HTTPException(400, f"text 过短({len(text)} 字,至少 8)")
    if len(text) > 400:
        # 超长文本会拖垮 GPU 合成(单帧旁白上限 130 字,400 已是三倍余量)
        raise HTTPException(400, f"text 过长({len(text)} 字,最多 400)")
    if req.voice not in VOICES:
        raise HTTPException(400, f"未知音色 {req.voice},可选:{list(VOICES)}")
    # 实测 speed<1 非线性恶化(0.8 即 5 倍时长怪音),下限钳位 1.0
    speed = max(1.0, min(1.8, req.speed))
    ref_name, prompt = _ref_of(req.voice)
    ref_wav = os.path.join(REF_DIR, ref_name)
    if not os.path.exists(ref_wav):
        raise HTTPException(500, f"参考音频缺失:{ref_wav}")
    with _lock:  # 模型非线程安全,串行合成
        m = _get_model()
        # 本请求的解码参数覆盖(锁内生效,不影响并发请求)
        override = {k: v for k, v in (("sampling", req.sampling),
                                      ("max_token_text_ratio", req.max_token_text_ratio),
                                      ("min_token_text_ratio", req.min_token_text_ratio))
                    if v is not None}
        override_s = {k: v for k, v in (("top_p", req.top_p), ("top_k", req.top_k),
                                        ("greedy", req.greedy))
                      if v is not None}
        saved, saved_s = dict(_GEN), dict(_SAMPLING_CFG)
        _GEN.update(override)
        _SAMPLING_CFG.update(override_s)
        expected = _expected_sec(text)
        best = None
        used = 0
        try:
            # 采样本身不稳定(同一句可能出 0.1s 的残句或 24s 的复读),所以**按时长验收重采**,
            # 取「最接近预期时长」的一次;落在窗口内就提前收工。这是音频可用的关键兜底。
            for _attempt in range(_ATTEMPTS):
                used = _attempt + 1
                chunks = None
                # prompt_wav 参数为文件路径(cosyvoice frontend 内部自行加载)
                # 短文本偶发 vocoder 卷积错误 → 补一个句号重试(仅增加停顿,不影响内容)
                for candidate in (text, text + "。"):
                    try:
                        chunks = [o["tts_speech"] for o in
                                  m.inference_zero_shot(candidate, prompt, ref_wav,
                                                        stream=False, speed=speed)]
                        if chunks:
                            break
                    except Exception:
                        chunks = None
                if not chunks:
                    continue
                speech = torch.cat(chunks, dim=1)
                ratio = (speech.shape[1] / SAMPLE_RATE) / expected
                if best is None or abs(ratio - 1) < abs(best[0] - 1):
                    best = (ratio, speech)
                if _ACCEPT[0] <= ratio <= _ACCEPT[1]:
                    break
        finally:
            _GEN.clear()
            _GEN.update(saved)
            _SAMPLING_CFG.clear()
            _SAMPLING_CFG.update(saved_s)
        if best is None:
            raise HTTPException(500, "合成失败:无输出")
        ratio, speech = best
        if not (_ACCEPT[0] <= ratio <= _ACCEPT[1]):
            logging.warning("时长仍不在验收窗口:%.2f× 预期,已重采 %d 次,文本 %s",
                            ratio, used, text[:30])
        elif used > 1:
            logging.info("重采 %d 次后通过时长验收(%.2f×)", used, ratio)
        data = speech.detach().cpu().numpy()
        if data.ndim == 2:
            data = data.T
        buf = io.BytesIO()
        sf.write(buf, data, SAMPLE_RATE, format="wav")
    return Response(content=buf.getvalue(), media_type="audio/wav",
                    headers={"X-Sample-Rate": str(SAMPLE_RATE),
                             "X-TTS-Ratio": f"{ratio:.3f}",
                             "X-TTS-Attempts": str(used)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8016, log_level="info")
