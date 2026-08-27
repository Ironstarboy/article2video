# -*- coding: utf-8 -*-
"""CosyVoice3 TTS 服务(FastAPI,127.0.0.1:8016,GPU1)。

接口:
  GET  /health            → {"ok": true}
  GET  /voices            → 可用音色列表
  POST /tts {text, voice, speed} → audio/wav

部署规范(与服务器其他模型一致):
  - 权重:/mnt/models/CosyVoice3-0.5B(HuggingFace FunAudioLLM/Fun-CosyVoice3-0.5B-2512)
  - 服务:venv /mnt/workspace/ttv/tts-venv,启动脚本 deploy/start-tts.sh
  - 端口:127.0.0.1:8016;GPU:PPU1(CUDA_VISIBLE_DEVICES=1,GPU0 被 ComfyUI 占用)
"""
import io
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

MODEL_DIR = "/mnt/models/CosyVoice3-0.5B"
REF_DIR = "/mnt/models/CosyVoice3-0.5B/asset-v2"   # 零样本参考音频(edge-tts 新闻腔种子)
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


def _get_model():
    global model
    if model is None:
        # CosyVoice3 构造签名与 v1/v2 不同:无 load_jit
        model = AutoModel(model_dir=MODEL_DIR, fp16=True)
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
    speed = max(0.6, min(1.8, req.speed))
    import os
    ref_name, prompt = _ref_of(req.voice)
    ref_wav = os.path.join(REF_DIR, ref_name)
    if not os.path.exists(ref_wav):
        raise HTTPException(500, f"参考音频缺失:{ref_wav}")
    with _lock:  # 模型非线程安全,串行合成
        m = _get_model()
        # prompt_wav 参数为文件路径(cosyvoice frontend 内部自行加载)
        # 短文本偶发 vocoder 卷积错误 → 补一个句号重试(仅增加停顿,不影响内容)
        chunks = None
        for candidate in (text, text + "。"):
            try:
                chunks = [o["tts_speech"] for o in
                          m.inference_zero_shot(candidate, prompt, ref_wav, stream=False, speed=speed)]
                if chunks:
                    break
            except Exception:
                chunks = None
        if not chunks:
            raise HTTPException(500, "合成失败:无输出")
        speech = torch.cat(chunks, dim=1)
        data = speech.detach().cpu().numpy()
        if data.ndim == 2:
            data = data.T
        buf = io.BytesIO()
        sf.write(buf, data, SAMPLE_RATE, format="wav")
    return Response(content=buf.getvalue(), media_type="audio/wav",
                    headers={"X-Sample-Rate": str(SAMPLE_RATE)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8016, log_level="info")
