# -*- coding: utf-8 -*-
"""Qwen3-TTS 服务(FastAPI,127.0.0.1:8017,GPU2)。

接口与 CosyVoice 服务(8016)一致:
  GET  /health
  POST /tts {text, voice, speed} → audio/wav(24kHz)

音色:male / female / male_narrator(与 CosyVoice 相同的三份种子音频做零样本克隆)。
"""
import io
import threading

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from qwen_tts import Qwen3TTSModel

MODEL_DIR = "/mnt/models/Qwen3-TTS-0.6B/Qwen3-TTS-0.6B-Base"
REF_DIR = "/mnt/models/CosyVoice3-0.5B/asset-v2"   # 复用三份新闻腔种子音频
SAMPLE_RATE = 24000

app = FastAPI(title="Qwen3-TTS")
_lock = threading.Lock()

VOICES = {
    "male": ("male.wav", "各位观众大家好,欢迎收看今天的节目。当前我国经济社会发展稳中有进,高质量发展扎实推进,各项事业取得新的重大成就。"),
    "female": ("female.wav", "大家好,欢迎来到今天的节目。理论创新每前进一步,理论武装就要跟进一步。让我们共同思考,共同学习。"),
    "male_narrator": ("male_narrator.wav", "新时代赋予新使命,新征程呼唤新作为。让我们坚定信心、真抓实干,在新赛道上跑出加速度。"),
}

model = None


def _get_model():
    global model
    if model is None:
        model = Qwen3TTSModel.from_pretrained(MODEL_DIR)
        model = model.to("cuda")
    return model


@app.get("/health")
def health():
    return {"ok": True, "model_loaded": model is not None}


class TTSRequest(BaseModel):
    text: str
    voice: str = "male"
    speed: float = 1.0


@app.post("/tts")
def tts(req: TTSRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "text 为空")
    if len(text) > 400:
        raise HTTPException(400, f"text 过长({len(text)} 字,最多 400)")
    if req.voice not in VOICES:
        raise HTTPException(400, f"未知音色 {req.voice}")
    import os
    ref_name, ref_text = VOICES[req.voice]
    ref_wav = os.path.join(REF_DIR, ref_name)
    if not os.path.exists(ref_wav):
        raise HTTPException(500, f"参考音频缺失:{ref_wav}")
    with _lock:
        m = _get_model()
        try:
            audios, sr = m.generate_voice_clone(
                text=text, language="zh", ref_audio=ref_wav, ref_text=ref_text,
                non_streaming_mode=True)
        except Exception as e:
            raise HTTPException(500, f"合成失败:{str(e)[:120]}")
        if not audios:
            raise HTTPException(500, "合成失败:无输出")
        wav = np.concatenate(audios) if len(audios) > 1 else audios[0]
        buf = io.BytesIO()
        sf.write(buf, wav, sr if sr else SAMPLE_RATE, format="wav")
    return Response(content=buf.getvalue(), media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8017, log_level="info")
