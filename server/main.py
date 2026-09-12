# -*- coding: utf-8 -*-
"""理论文章转视频 —— FastAPI 服务。

流水线:uploaded → analyzing → analyzed → building → preview → rendering → rendered
所有阶段在服务器本地执行(DeepSeek vLLM / CosyVoice3 TTS / hyperframes CLI)。
"""
import json
import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
import sys
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).parent))
from config import (  # noqa: E402
    AVATAR_CORNER, AVATAR_IMAGE_TYPES, AVATAR_NATIVE_SIZE, AVATAR_SIZE,
    AVATAR_SIZE_MAX, AVATAR_SIZE_MIN, AVATAR_UPLOAD_MAX, BACKEND_PORT, FPS,
    HYPERFRAMES_RUNTIME, NODE_BIN_DIR,
    OVERLAY_RT_FACTOR, RENDER_RT_FACTOR, STUDIO_LOG_DIR, TTS_VENV_DIR, VO_CHECK_FRAMES,
    VO_CHECK_MODEL_DIR, VO_CHECK_TIMEOUT, WEB_DIR,
    avatar_corner_options, avatar_size_options, resolve_avatar_image, vo_runtime_fingerprint,
)
from jobs import (  # noqa: E402
    JOBS, LOCK, create_job, get_job, normalize_title, remove_job, run_in_background,
)
import extract  # noqa: E402
import analyze  # noqa: E402
import tts  # noqa: E402
import avatar  # noqa: E402
import avatar_library  # noqa: E402
import preferences  # noqa: E402
from builder import assemble, styles  # noqa: E402

log = logging.getLogger("ttv.main")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="理论文章转视频")

# 全局代理客户端(连接池复用)。每请求新建 AsyncClient 曾在 Studio 并行加载
# 资源时耗尽文件描述符(OSError: Too many open files → 全站代理 500)。
PROXY_CLIENT = httpx.AsyncClient(
    timeout=httpx.Timeout(120.0, connect=5.0),
    limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
)

# Studio 进程按需拉起:任务状态轮询(api_job)或 Studio 代理访问时自愈启动。
# 不在启动时批量恢复——批处理会并发抢槽位,曾导致两个任务记录到同一端口。
STUDIOS: dict[str, subprocess.Popen] = {}   # job_id -> Studio 进程(--foreground 直接跟踪)
_studio_starting: set = set()                 # 正在后台拉起 Studio 的任务(防重复)
STUDIO_SLOT_USED: dict[str, int] = {}         # job_id -> Studio 端口
STUDIO_PROJECT_ID: dict[str, str] = {}        # job_id -> Studio 侧项目 id(与端口同生命周期)
STUDIO_SLOT_BASE = 4150
STUDIO_SLOTS = 4
STUDIO_LOCK = threading.Lock()                # 串行化 Studio 启动,避免槽位竞态

# 渲染全局信号量:Chrome 渲染为 CPU 密集操作,同时 ≤2 个(超出排队,不互相拖垮)
RENDER_SEM = threading.BoundedSemaphore(2)
# 同时进行中(analyzing/building/rendering)任务上限:防公网批量提交挤爆 LLM/GPU
MAX_INFLIGHT_JOBS = 4

# ───────────────────────── 流水线阶段 ─────────────────────────


def _job_combo(job) -> dict:
    """任务的四维风格组合(job.state['combo'] 持久化)。"""
    c = job.state.get("combo")
    if not c:
        c = styles.resolve_combo(job.state.get("style"), None, None, None, None)
        job.state["combo"] = c
    return c


def _job_alive(job) -> bool:
    """任务是否仍在注册表中(删除后返回 False,后台线程应尽快退出)。"""
    return JOBS.get(job.id) is job


def _auto_title(job, script: dict, article: str):
    """分析完成后自动总结项目标题(用户手动改过就绝不覆盖)。

    标题只影响项目列表的显示名,所以整条链路**失败即静默回退**:
    先问大模型要一个短标题,失败就用脚本自带标题,再失败就留空
    (留空时 Job.display_title 会退回文件名/job_id,列表不会出现空白项)。
    """
    if job.state.get("title_source") == "user":
        return
    title = None
    try:
        title = analyze.summarize_title(script, article,
                                        job.state.get("video_kind", "promo"))
    except Exception:  # noqa: BLE001 - 命名失败不该影响"分析完成"这个事实
        log.exception("job %s 自动总结项目标题失败", job.id)
    title = title or analyze.clean_title(script.get("title"))
    if not title or not _job_alive(job) or job.state.get("title_source") == "user":
        return
    try:
        title = normalize_title(title)
    except ValueError:
        return
    job.set(title=title, title_source="auto", title_at=time.time())
    log.info("job %s 项目标题自动总结为:%s", job.id, title)


def _job_avatar_image(job) -> Path:
    """本次构建要用的形象图,并把"用的是哪张"记进 job.state。

    形象是**全局**设置(库里当前默认),所以这里每次构建都重新解析一次:
    库里换了默认形象,下一个构建就用新形象,不必重启服务。记进 state 的是**审计信息**
    (这次构建到底用了谁),不是配置 —— 界面据此区分「上次构建用的形象」与「现在库里的形象」。
    """
    p = resolve_avatar_image()
    try:
        job.set(avatar_image_name=avatar_library.current_info()["name"],
                avatar_image_file=p.name)
    except Exception as e:  # noqa: BLE001 - 记录审计信息失败不该挡住构建
        log.warning("记录数字人形象信息失败: %s", e)
    return p


def stage_analyze(job):
    if not _job_alive(job):
        return
    kind = job.state.get("video_kind", "promo")
    job.set(status="analyzing", progress="提取文本")
    p = job.paths()
    # 上传文件保留原扩展名(txt/md/docx);粘贴文本模式直接就是 input.txt
    upload = next(job.dir.glob("input.*"))
    text = extract.extract_text(upload)
    p["input"].write_text(text, encoding="utf-8")
    if kind == "lecture":
        # 讲解视频:两步分析(诊断文章类型与讲解方案 → 分段并行生成逐帧脚本),耗时较长
        script = analyze.analyze_lecture_article(
            text, int(job.state["duration_sec"]), _job_combo(job),
            progress_cb=lambda msg: job.set(progress=msg))
    else:
        job.set(progress=f"DeepSeek 分析中(两阶段:论证分析 → 脚本生成,全文 {len(text)} 字)")
        script = analyze.analyze_article(text, int(job.state["duration_sec"]), _job_combo(job),
                                         progress_cb=lambda msg: job.set(progress=msg))
    p["script"].write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    job.set(status="analyzed", progress="")
    job.record_history("analyze",
                       detail=f"{len(script.get('frames') or [])} 帧脚本 · 目标 "
                              f"{int(job.state.get('duration_sec') or 0)} 秒")
    _auto_title(job, script, text)


def _vo_signature(script: dict, voice: str, provider: str) -> str:
    """配音复用指纹:逐帧台词 + 音色 + 引擎。任一变化都必须重新合成。"""
    frames = [(f.get("index"), (f.get("voiceover") or "").strip())
              for f in script.get("frames") or []]
    raw = json.dumps([frames, voice, provider], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _reuse_vo(script: dict, vo_dir: Path) -> dict | None:
    """已有配音可直接复用时重建 vo 映射(逐帧 ffprobe 时长 + 词级时间轴)。

    任一台词帧缺文件或时长异常即返回 None(调用方重新合成),不做部分复用。
    """
    out = {}
    for f in script.get("frames") or []:
        text = (f.get("voiceover") or "").strip()
        if not text:
            continue
        p = vo_dir / f"vo_{int(f['index']):02d}.mp3"
        if not p.exists():
            return None
        dur = tts.audio_duration(p)
        if dur <= 0.2:
            return None
        out[f["index"]] = {"path": str(p), "duration": dur, "engine": "cached",
                           "words": tts.word_times(text, dur)}
    return out


def _frames_signature(script: dict) -> list:
    """逐帧文本指纹:index/type/voiceover。只比"内容",不比时长(时长由真实配音回填)。"""
    return [(f.get("index"), f.get("type"), (f.get("voiceover") or "").strip())
            for f in script.get("frames") or []]


def _vo_signature(script: dict, voice: str, provider: str) -> str:
    """配音复用指纹:逐帧台词 + 音色 + 引擎 + **合成口径**(运行时钉版/合成版本)。

    最后一项是 2026-09-12 乱码事故的教训:transformers 4.52+ 会把语音 LLM 的输出打乱
    (听着是乱码,时长与峰值却全正常,验收拦不住)。运行时修好之后,已经烧坏的那批配音
    因为指纹没变而被一直复用 —— 用户听到的仍然是乱码。口径进指纹,这类"修了运行时、
    旧产物还在用"的坑才会自动作废重烧。
    """
    raw = json.dumps([_frames_signature(script), voice, provider,
                      vo_runtime_fingerprint()], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _voice_check(job, script_path: Path, vo_dir: Path) -> None:
    """刚烧出来的配音抽检一次可懂度(whisper 听写 vs 台词,见 server/voice_check.py)。

    只在**真正重新合成**之后跑:时长与峰值正常、读音却是乱码的坏样本,只有"听起来是
    什么字"能识破(2026-09-12 事故)。whisper 不可用/超时/异常一律只记日志,绝不阻塞;
    结果写进 state.voice_check,前端据此提示"这批配音可能有问题,建议重新合成"。
    """
    if VO_CHECK_FRAMES <= 0:
        return
    py = Path(TTS_VENV_DIR) / "bin" / "python"
    worker = Path(__file__).parent / "voice_check.py"
    if not py.exists() or not worker.exists():
        return
    cmd = [str(py), str(worker), "--script", str(script_path), "--audio", str(vo_dir),
           "--frames", str(VO_CHECK_FRAMES), "--model-dir", str(VO_CHECK_MODEL_DIR)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=VO_CHECK_TIMEOUT)
        out = (r.stdout or "").strip().splitlines()
        res = json.loads(out[-1]) if out else {}
    except Exception as e:  # noqa: BLE001 - 抽检是提示,永远不许影响构建
        log.info("job %s 配音抽检跳过:%s", job.id, e)
        return
    if not res.get("checked"):
        if res.get("error"):
            log.info("job %s 配音抽检跳过:%s", job.id, res["error"])
        return
    res["at"] = time.time()
    job.set(voice_check=res)
    if res.get("warn"):
        log.warning("job %s 配音抽检不合格:LCS %s(逐帧 %s)——建议重新合成配音",
                    job.id, res.get("lcs"),
                    [s.get("lcs") for s in res.get("samples") or []])
    else:
        log.info("job %s 配音抽检通过:LCS %s(%s 帧)",
                 job.id, res.get("lcs"), res.get("checked"))


def _synthesize_and_fit(job, *, reuse_vo: bool = False,
                        next_step: str = "组装 HyperFrames 项目",
                        on_tts_progress=None):
    """内容拓展 + 配音合成 + 真实时长回填(构建与「数字人播报视频」共用)。

    返回 (script, vo, eng_txt, reused);script 的 frames[].duration 已按真实配音回填;
    reused=True 表示这次没有重新合成配音(两条轨道因此共用同一版声音)。
    reuse_vo=True 且指纹未变(或上次构建用的就是这段文本)、配音文件齐全时跳过合成
    —— 播报视频重跑、以及给老任务补播报视频时不再重复烧 GPU。
    """
    kind = job.state.get("video_kind", "promo")
    p = job.paths()
    script = json.loads(p["script"].read_text(encoding="utf-8"))
    target = int(job.state.get("duration_sec", 120))
    # 旁白量不足目标时长(实测语速≈4.2字/秒)→ 构建期二次拓展内容:
    # 「选的时间长就拓展」的核心机制,加长每帧旁白并增帧,而不是拖慢画面。
    # 模型单轮扩写有上限,最多两轮;剩余缺口由构建期按帧留白分摊补满。
    article_text = p["input"].read_text(encoding="utf-8")
    vo_chars = sum(len((f.get("voiceover") or "").strip()) for f in script["frames"])
    need = target * analyze.VO_NEED_EXPAND
    for _pass in range(2):
        if vo_chars >= need * analyze.EXPAND_ACCEPT_LINE:
            break
        job.set(progress=f"{'讲解内容' if kind == 'lecture' else '旁白量'}不足目标时长,正在拓展内容(第{_pass + 1}轮:{vo_chars} 字 → 约需 {int(need)} 字)")
        try:
            script = analyze.expand_script(script, article_text, target, kind)
        except Exception as e:
            # 拓展失败不阻塞构建:模型扩写有天花板,剩余缺口由构建期留白分摊补足
            log.exception("job %s 拓展失败,跳过", job.id)
            break
        p["script"].write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
        vo_chars = sum(len((f.get("voiceover") or "").strip()) for f in script["frames"])
    # 语速保持 1.0(自然说话语速,不随内容缩放)
    speed = 1.0
    provider = job.state.get("voice_engine") or "cosyvoice3"
    voice = job.state.get("voice") or styles.get(_job_combo(job))["voice"]
    eng_names = {"cosyvoice3": "本地 CosyVoice3", "qwen3tts": "本地 Qwen3-TTS", "doubao": "豆包 seed-tts-2.0"}
    vo_dir = p["vo"]
    sig = _vo_signature(script, voice, provider)
    vo = None
    # 复用必须**指纹完全相符**:台词/音色/引擎任一变化,或**合成口径**变化(运行时钉版、
    # 合成版本),都要重新烧。宁可多花一次 GPU,也不把上一版运行时烧坏的配音接进新成片。
    if reuse_vo and job.state.get("vo_sig") == sig:
        vo = _reuse_vo(script, vo_dir)
    if vo is None:
        # 合成前清理旧配音(旧脚本帧号不同,残留文件会与新 index.html 错位)。
        # 必须在 synthesize 之前清——assemble 内的清理会把刚合成的配音删光
        # (v1.0 回归:构建产物音频被清空,渲染成片无声)。
        if vo_dir.exists():
            shutil.rmtree(vo_dir)
        vo_dir.mkdir(parents=True, exist_ok=True)
        job.set(progress=f"配音合成中({eng_names.get(provider, provider)},自然语速,多 GPU 并行)")
        vo = tts.synthesize_frames(script["frames"], voice, vo_dir, speed=speed,
                                   provider=provider, progress_cb=on_tts_progress)
        job.set(vo_sig=sig, vo_runtime=vo_runtime_fingerprint())
    elif on_tts_progress:
        # 复用:立刻把这一步报成"已完成",界面不会停在第一步
        job.set(vo_sig=sig, vo_runtime=vo_runtime_fingerprint())
        on_tts_progress(len(vo), len(vo))
    engines = {}
    for v in vo.values():
        engines[v.get("engine", "unknown")] = engines.get(v.get("engine", "unknown"), 0) + 1
    reused = bool(vo) and set(engines) == {"cached"}
    eng_txt = ("复用已有配音" if reused
               else " + ".join(f"{k}×{n}" for k, n in sorted(engines.items())))
    doubao_err = (tts.DOUBAO_LAST_ERROR if provider == "doubao" and "doubao" not in engines
                  else "")
    if reused:
        job.set(progress=f"复用已有配音({len(vo)} 帧,未重新合成);{next_step}中")
    elif doubao_err:
        job.set(progress=f"豆包引擎失败({doubao_err}),已回落 CosyVoice3;{next_step}中")
    else:
        job.set(progress=f"{next_step}(配音引擎:{eng_txt})")
        # 刚烧出来的配音抽检一次可懂度:时长/静音验收拦不住"念的是乱码"这种坏样本
        _voice_check(job, p["script"], vo_dir)
    # 目标时长为用户滑杆所选:真实配音时长与目标偏离时向目标靠拢。
    # 停顿节奏(用户反馈):旁白后留白宜短(讲解档 1.0s,读批注够用),
    # 单帧可扩展上限收紧(4s)——时长靠内容补足(段级旁白下限+构建期拓展),
    # 不靠静默停留凑时长,保持语气自然。
    tail_pad = 1.0 if kind == "lecture" else (0.9 if target <= 120 else 1.4)
    tts.apply_real_durations(script, vo, tail_pad=tail_pad, target=target,
                             extra_cap=4.0 if kind == "lecture" else 6.5)
    return script, vo, eng_txt, reused


def stage_build(job, force_voice: bool = False, preview: bool = True):
    """构建(配音 → 组装工程 → 数字人片段)。

    preview=False 是「一键出片」的构建段(见 stage_direct_render):构建完**不拉 Studio、
    不停在 preview 状态**,由调用方紧接着发起渲染。这条路不给人改时间线,省下一次 Studio
    冷启动与一个端口槽位;产物、时长与历史与分开构建完全一致。
    """
    if not _job_alive(job):
        return
    job.set(status="building", progress="生成配音")
    # 重建时先停掉旧 Studio(否则新进程换端口,旧进程泄漏占着旧端口)
    stop_studio(job)
    p = job.paths()
    # 配音复用:同一份脚本+音色+引擎只合成一次。这样「先构建后播报」与「先播报后构建」
    # 拿到的是**同一版配音**(本地 TTS 逐次结果并不稳定,重合成会让两条轨道声音不一致),
    # 顺带把每次「重新构建」的 1-3 分钟 TTS 省掉。force_voice=1 时才强制重合成。
    script, vo, eng_txt, reused_voice = _synthesize_and_fit(
        job, reuse_vo=not force_voice)
    info = assemble.build(script, _job_combo(job), vo, p["project"])
    # 数字人:逐帧出片段并落时间轴(渲染后叠加)。失败不阻塞出片,只记录原因。
    timeline_path = p["project"] / "avatar_timeline.json"
    if job.state.get("avatar"):
        try:
            job.set(progress="生成数字人片段(逐帧)")
            geom = _avatar_geom(job)
            timeline = avatar.build_frame_clips(
                script, vo, info["starts"], size=geom["size"], cutout=geom["cutout"],
                image=_job_avatar_image(job),
                progress_cb=lambda msg: job.set(progress=msg))
            avatar.write_timeline(timeline, timeline_path)
            # 抠像是要了却没成?如实写进 avatar_error:界面据此提示"已回退圆角卡片",
            # 否则用户只会看到"没生效"却不知道为什么(与数字人服务不可用同一口径)
            miss = _cutout_missing(geom, timeline)
            job.set(avatar_clips=len(timeline),
                    avatar_error=miss or None)
        except Exception as e:  # noqa: BLE001 - 数字人失败不影响正常出片
            log.warning("数字人片段生成失败: %s", e)
            timeline_path.unlink(missing_ok=True)
            job.set(avatar_clips=0, avatar_error=str(e)[:160])
    else:
        timeline_path.unlink(missing_ok=True)
    # 在标记 preview 之前同步拉起 Studio:状态一翻转,前端就能直接展示就绪的编辑器,
    # 用户看不到「启动中」等待页(Studio 冷启动时间被构建阶段的等待期吸收)
    # 一键出片(preview=False)不拉:这条路构建完就直接渲染,没人会去看编辑器。
    studio_err = None
    if preview:
        try:
            start_studio(job)
        except Exception as e:
            studio_err = str(e)[:80]
    # 直达出片时状态停在 building —— 前端据此不会去加载 Studio,由 stage_render 接手续上 rendering
    status = "preview" if preview else "building"
    if studio_err:
        # 启动失败不阻塞预览:状态轮询自愈会重试拉起
        job.set(status=status, progress=f"总时长 {info['total']:.0f} 秒(Studio 启动失败,稍后自动重试)",
                total_sec=info["total"], voice_engines=eng_txt, studio_error=studio_err)
    else:
        job.set(status=status, progress=f"总时长 {info['total']:.0f} 秒",
                total_sec=info["total"], voice_engines=eng_txt)
    job.record_history(
        "build",
        detail=f"总时长 {info['total']:.0f} 秒 · 配音 {eng_txt}"
               + ("(Studio 启动失败,稍后自动重试)" if studio_err else ""),
        total_sec=round(float(info["total"]), 1))
    # 只有**真的重新合成了配音**时,之前的播报视频才可能不一致(复用则同一版声音,仍然有效)。
    # 不删产物(它仍可播放),只打 stale 标记提示可重新生成(片段有缓存,重跑很快)。
    bc = job.state.get("avatar_broadcast") or {}
    if not reused_voice and bc.get("status") == "done" and not bc.get("stale"):
        job.set(avatar_broadcast={**bc, "stale": True})
    # 构建后异步跑质量门(hyperframes check),结果写入任务状态,不阻塞预览
    threading.Thread(target=_run_check, args=(job,), daemon=True).start()


AVATAR_BROADCAST_STEPS = ("合成配音", "生成数字人片段", "拼接播报视频")


def _avatar_geom(job) -> dict:
    """任务级数字人几何:成片里那个人像的角落、边长与是否抠像(纯读,坏值自动回默认)。

    state.avatar_geom 由创建时写入、之后可在预览页改(见 api_avatar_geom);
    老任务没有这些键 → 用当前口径的默认:位置右上 / AVATAR_SIZE / **抠像取全局偏好**
    (preferences.avatar_cutout_new_jobs),不需要迁移。
    注意抠像的默认**不再**是 config.AVATAR_CUTOUT 那个静态值 —— 那个只是出厂默认,
    用户在形象页改过之后以偏好文件为准。
    """
    g = job.state.get("avatar_geom") or {}
    return {"corner": avatar.safe_corner(g.get("corner")),
            "size": avatar.safe_size(g.get("size")),
            "cutout": avatar.safe_cutout(g.get("cutout"),
                                        preferences.avatar_cutout_new_jobs())}


def _normalize_geom(corner=None, size=None, cutout=None, base: dict | None = None) -> dict:
    """把接口传来的角落/边长/抠像收敛成 {corner, size, cutout};缺省沿用 base,非法抛 ValueError。

    做成模块级函数而不是直接写在 api_create 里:那个函数的入参就叫 `avatar`
    (表单里的出镜开关),会把模块 `avatar` 遮住。
    """
    base = base or {"corner": AVATAR_CORNER, "size": AVATAR_SIZE,
                    "cutout": preferences.avatar_cutout_new_jobs()}
    return {"corner": avatar.normalize_corner(corner, base["corner"]),
            "size": avatar.normalize_size(size, base["size"]),
            "cutout": avatar.normalize_cutout(cutout, base["cutout"])}


def _cutout_missing(geom: dict, timeline: list) -> str:
    """抠像开着却一条遮罩都没拿到时,给界面一句实话(没这情况就返回空串)。

    只有**全部**片段都没抠成才算降级(整条成片回退圆角卡片);个别缺失只是那几段
    用卡片,不影响整体观感,不占 avatar_error(它会被前端整条展示出来)。
    """
    if not geom.get("cutout") or not timeline:
        return ""
    if any(t.get("matte") for t in timeline):
        return ""
    ok, why = avatar.matte_available()
    return ("抠像不可用,已回退圆角卡片:" + (why or "遮罩生成失败"))[:160]


def _overlay_timeline(job, project_dir) -> list:
    """渲染前决定要不要叠加数字人,并返回该用的时间轴。

    **先看出镜开关**:任务可能在上一次构建后改成了「不出镜」,此时旧的
    avatar_timeline.json 还在磁盘上 —— 只按文件判断会把不该出现的人像叠回去。
    """
    if not job.state.get("avatar"):
        return []
    return avatar.read_timeline(project_dir / "avatar_timeline.json")


def stage_avatar_broadcast(job, prev_status: str = "analyzed", size: int | None = None):
    """独立生成「数字人播报视频」:配音 → 逐帧片段 → 顺序拼接(与 PPT 成片解耦)。

    产物 renders/avatar.mp4(size×size 正方形,含配音音轨,不含 BGM/PPT 画面);
    size 缺省取任务上次用的值,再回退任务的「数字人大小」(默认 config.AVATAR_SIZE)。
    失败只写 avatar_broadcast.error 并回到进入前的状态 —— 它是一条可选支线,
    不该毁掉脚本、成片或 Studio。
    """
    if not _job_alive(job):
        return
    # 尺寸在这里再收敛一次:本函数也可能被"重跑"路径直接调用,不能只信接口层
    if size is None:
        size = job.state.get("avatar_broadcast_size")
    size = avatar.safe_size(size, _avatar_geom(job)["size"])
    p = job.paths()
    out = p["renders"] / "avatar.mp4"
    started = time.time()
    bc = {"status": "running", "step_index": 1, "step": AVATAR_BROADCAST_STEPS[0],
          "size": size,
          "detail": "准备中…", "done": 0, "total": None, "eta_sec": None,
          "elapsed_sec": 0.0, "started_at": started, "updated_at": started,
          "finished_at": None, "error": None}

    def report(**kw):
        bc.update(kw)
        bc["elapsed_sec"] = round(time.time() - started, 1)
        bc["updated_at"] = time.time()
        job.set(avatar_broadcast=dict(bc))

    try:
        basis = _broadcast_basis_sec(job)
        step_started = time.time()
        report(step_index=1, step=AVATAR_BROADCAST_STEPS[0],
               detail=f"合成配音(画面 {size}×{size})",
               done=0, total=None,
               eta_sec=avatar.estimate_broadcast_sec(basis, size=size))

        def on_tts(done, total):
            report(detail=f"配音合成 {done}/{total} 帧", done=done, total=total,
                   eta_sec=avatar.broadcast_eta(1, done, total, time.time() - step_started,
                                                0.0, basis, basis, size=size))

        script, vo, eng_txt, _reused = _synthesize_and_fit(
            job, reuse_vo=True, next_step="拼接数字人播报视频", on_tts_progress=on_tts)

        frames = [f for f in script["frames"] if float(f.get("duration") or 0) > 0.1]
        starts, acc = {}, 0.0
        for f in frames:
            starts[f["index"]] = acc
            acc += float(f["duration"])
        av_total = round(acc, 2)
        step_started = time.time()
        report(step_index=2, step=AVATAR_BROADCAST_STEPS[1],
               detail=f"生成数字人片段 0/{len(frames)}", done=0, total=len(frames),
               eta_sec=avatar.broadcast_eta(2, 0, len(frames), 0.0, 0.0, av_total, av_total,
                                            size=size))
        av = {"done": 0.0}

        def on_frame(n, total, idx, dur):
            av["done"] += float(dur)
            report(detail=f"数字人片段 {n}/{total}(帧 {idx})", done=n, total=total,
                   eta_sec=avatar.broadcast_eta(2, n, total, time.time() - step_started,
                                                av["done"], av_total, av_total, size=size))

        timeline = avatar.build_frame_clips(
            script, vo, starts, size=size, on_frame=on_frame,
            image=_job_avatar_image(job),
            progress_cb=lambda msg: job.set(progress=msg))
        if not timeline:
            raise RuntimeError("脚本里没有可生成数字人的帧")

        step_started = time.time()
        report(step_index=3, step=AVATAR_BROADCAST_STEPS[2], detail="拼接片段与音轨",
               done=0, total=round(av_total, 1),
               eta_sec=avatar.broadcast_eta(3, 0, 0, 0.0, 0.0, av_total, av_total, 0.0,
                                            size=size))

        # 写临时文件、成功才 replace:重新生成失败时不能毁掉上一次的可用产物
        tmp_out = out.with_name(out.stem + ".tmp" + out.suffix)

        def on_concat(done_sec, total_sec):
            report(detail=f"拼接中 {done_sec:.0f}/{total_sec:.0f} 秒",
                   done=round(done_sec, 1), total=round(total_sec, 1),
                   eta_sec=avatar.broadcast_eta(3, 0, 0, time.time() - step_started,
                                                0.0, av_total, total_sec, done_sec,
                                                size=size))

        try:
            avatar.build_broadcast_video(timeline, vo, tmp_out, progress_cb=on_concat)
            real = avatar.video_duration(tmp_out)
            tmp_out.replace(out)
        finally:
            tmp_out.unlink(missing_ok=True)
        job._record_artifact("avatar", out)
        report(status="done",
               detail=f"完成:{len(timeline)} 段 · {size}×{size} · {real:.0f} 秒",
               done=len(timeline), total=len(timeline), eta_sec=0,
               finished_at=time.time(), duration=round(real, 1),
               bytes=out.stat().st_size)
        job.set(status=prev_status or "analyzed", progress="", avatar_broadcast_size=size)
        job.record_history("broadcast",
                           detail=f"{len(timeline)} 段 · {size}×{size} · {real:.0f} 秒",
                           artifact="avatar", size=size, duration=round(real, 1))
        log.info("job %s 数字人播报视频完成(%d×%d):%s", job.id, size, size, out)
    except Exception as e:  # noqa: BLE001 - 支线失败不影响任务主线
        log.exception("job %s 数字人播报视频失败", job.id)
        report(status="failed", error=str(e)[:200], eta_sec=None,
               finished_at=time.time())
        job.set(status=prev_status or "analyzed",
                progress=f"数字人播报视频失败({str(e)[:60]})")
        job.record_history("broadcast", status="failed", detail=str(e)[:160])


def _hf_env():
    env = dict(os.environ)
    if NODE_BIN_DIR:
        env["PATH"] = NODE_BIN_DIR + os.pathsep + env.get("PATH", "")
    return env


def _run_check(job):
    """构建后异步质量门:hyperframes check,结果写入 job.state['check']。"""
    env = _hf_env()
    try:
        r = subprocess.run(["hyperframes", "check", str(job.paths()["project"])],
                           capture_output=True, text=True, timeout=900, env=env)
        out = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"(\d+) error\(s\), (\d+) warning\(s\), (\d+) info\(s\)", out)
        summary = f"{m.group(1)}错误 {m.group(2)}警告 {m.group(3)}提示" if m else "完成"
        job.set(check=f"hyperframes check: {summary}(exit {r.returncode})")
    except Exception as e:
        log.exception("job %s hyperframes check 失败", job.id)
        job.set(check=f"check 失败: {e}")


# 与 hyperframes render --format 的实际支持对齐(mp4/webm/mov/gif/png-sequence)。
# 曾收录 mkv,但 CLI 不认这个格式 —— 选它必然失败,已移除。
RENDER_FORMATS = {"mp4", "mov", "webm"}

# 渲染进度:hyperframes 在捕获阶段往 stdout 打这些行(实测格式见 docs/数字人操作按钮前端方案.md 1.9)
_RENDER_FRAME_RE = re.compile(r"(?:Streaming|Capturing) frame (\d+)/(\d+)")
_RENDER_CALIB_RE = re.compile(r"Calibration: capturing test frame (\d+)/(\d+)")


def _iter_process_lines(stream, chunk_size: int = 8192):
    """把子进程输出按 \\n 与 \\r 双分隔切行(进度条用 \\r 原地刷新,只按 \\n 会读不到)。"""
    buf = b""
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        buf += chunk
        parts = re.split(rb"[\r\n]", buf)
        buf = parts.pop()
        for line in parts:
            line = line.strip()
            if line:
                yield line.decode("utf-8", errors="ignore")
    if buf.strip():
        yield buf.decode("utf-8", errors="ignore").strip()


def _fmt_hms(sec: float) -> str:
    sec = max(0, int(sec or 0))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _run_render(job, cmd: list, total_sec: float, timeout: int) -> tuple[int, str]:
    """跑 hyperframes render,把它的输出解析成**帧级进度**写进任务状态。

    原来用 subprocess.run 一次性收走输出 —— 5-20 分钟的渲染期间界面一个字都不变,
    用户只能看到「渲染中」然后干等。这里改成流式读取:
      phase 标定     → "Calibration: capturing test frame n/N"(渲染前的捕获成本标定)
      phase 捕获帧   → "Streaming frame n/N" / "Capturing frame n/N",按实测速率反推剩余
      phase 编码封装 → 帧数走完但进程未退出
      phase 准备中   → 编译与音频处理(只能给时间维度的粗估)
    返回 (退出码, 输出尾部)。
    """
    started = time.time()
    expect = max(1, int(round(total_sec * FPS))) if total_sec else 0
    seen = {"lines": [], "done": 0, "total": expect, "phase": "准备中", "phase_at": started}
    last_write = [0.0]

    def report(force: bool = False):
        now = time.time()
        if not force and now - last_write[0] < 1.5:   # 节流:状态每 2s 一次即可
            return
        last_write[0] = now
        elapsed = now - started
        done, total = seen["done"], seen["total"]
        eta = None
        if total and done > 0:
            phase_elapsed = now - seen["phase_at"]
            eta = max(0.0, phase_elapsed / done * (total - done))
            # 捕获之后还有编码/收尾(实测约占整段渲染的一成),给预计加回去
            eta *= 1.1
        elif total_sec:
            eta = max(0.0, total_sec / RENDER_RT_FACTOR - elapsed)
        if done and total:
            detail = f"{seen['phase']} {done}/{total}"
            percent = 20 + min(1.0, done / total) * 65
        else:
            detail = seen["phase"]
            percent = min(20.0, 2 + elapsed / max(1.0, total_sec / RENDER_RT_FACTOR) * 18)
        progress = (f"渲染中:{detail} · 已用 {_fmt_hms(elapsed)}"
                    + (f" · 预计剩余 {_fmt_hms(eta)}" if eta is not None else ""))
        job.set(progress=progress, render_progress={
            "step": 1, "step_name": "渲染 PPT 视频", "detail": detail,
            "done": done, "total": total or None, "percent": round(percent, 1),
            "elapsed_sec": round(elapsed, 1),
            "eta_sec": None if eta is None else round(eta),
        })

    report(force=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=_hf_env(), bufsize=0)
    try:
        for line in _iter_process_lines(proc.stdout):
            seen["lines"].append(line)
            if len(seen["lines"]) > 40:                 # 只留尾部用于报错
                seen["lines"].pop(0)
            m = _RENDER_FRAME_RE.search(line)
            if m:
                if seen["phase"] != "捕获帧":
                    seen["phase"], seen["phase_at"] = "捕获帧", time.time()
                seen["done"], seen["total"] = int(m.group(1)), int(m.group(2))
                report()
                continue
            m = _RENDER_CALIB_RE.search(line)
            if m:
                if seen["phase"] != "标定捕获成本":
                    seen["phase"], seen["phase_at"] = "标定捕获成本", time.time()
                seen["done"] = 0
                report()
                continue
            if seen["phase"] == "捕获帧" and seen["total"] and seen["done"] >= seen["total"]:
                seen["phase"], seen["phase_at"] = "编码封装", time.time()
                report(force=True)
    finally:
        try:
            proc.stdout.close()
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.wait(timeout=max(1, timeout - (time.time() - started)))
        code = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"渲染超时({timeout}s)")
    seen["phase"] = "编码封装"
    report(force=True)
    return code, "\n".join(seen["lines"])


def stage_render(job, fmt: str = "mp4"):
    if not _job_alive(job):
        return
    job.set(status="rendering", progress="排队等待渲染槽位…")
    with RENDER_SEM:
        p = job.paths()
        total_sec = float(job.state.get("total_sec") or 0)
        job.set(progress=f"HyperFrames 渲染中({fmt})", render_progress={
            "step": 1, "step_name": "渲染 PPT 视频", "detail": "准备中",
            "done": 0, "total": None, "percent": 1, "elapsed_sec": 0, "eta_sec": None})
        # 两个产物(见 docs/数字人操作按钮前端方案.md 第十节):
        #   ppt.<fmt>   纯 PPT 渲染 —— 一等产物,不再被叠加覆盖
        #   final.<fmt> 叠加了数字人的最终版
        ppt = p["project"] / "renders" / f"ppt.{fmt}"
        final = p["project"] / "renders" / f"final.{fmt}"
        # 渲染期间保留 Studio,预览不中断。注意:hyperframes 会在项目里建
        # renders/work-*/ 临时目录,所以"只读项目文件"的说法不成立(实测见方案 10.6)
        # 讲解视频可长达 30 分钟,渲染超时放宽到 3 小时
        timeout = 10800 if job.state.get("video_kind") == "lecture" else 3600
        # --workers 必须显式给 1:hyperframes 的流式编码闸门要求 workerCount === 1,
        # 不传则 auto 会选到 5(本机),于是走落盘捕获并撞上磁盘预检(capture_disk),
        # 在写第一个字节前就失败。实测:auto→29 秒失败;/ --workers 1→5m03s 出片。
        # 详见 docs/数字人操作按钮前端方案.md 1.9 与 10.4。
        code, out = _run_render(job, [
            "hyperframes", "render", str(p["project"]),
            "--output", str(ppt), "--format", fmt, "--quality", "high",
            "--workers", "1",
        ], total_sec, timeout)
        if code != 0:
            raise RuntimeError(f"渲染失败:{out[-1500:]}")
        if not ppt.exists() or ppt.stat().st_size < 10000:
            raise RuntimeError(f"渲染产物缺失或过小:{out[-600:]}")
        # 数字人叠加:用 assemble 的同一时钟把各帧片段叠到任务选定的角落(默认右上)。
        # 有片段 → 叠到 final;无片段(含"不出镜")→ 纯 PPT 版本身就是最终版。
        timeline = _overlay_timeline(job, p["project"])
        overlaid = False           # 真的叠上去了才算(叠加失败要如实写进历史)
        if timeline:
            geom = _avatar_geom(job)
            # 抠像:遮罩可能还没生成(上次构建时没开抠像,或中途换了设置),渲染前补齐。
            # 遮罩有缓存,补齐通常只发生在"刚打开抠像"的第一次。
            if geom["cutout"]:
                job.set(progress="准备抠像遮罩")
                avatar.ensure_mattes(
                    timeline,
                    progress_cb=lambda msg: job.set(progress=msg))
            job.set(progress="叠加数字人片段", render_progress={
                "step": 2, "step_name": "叠加数字人片段", "detail": "准备中",
                "done": 0, "total": round(total_sec or 0), "percent": 85,
                "elapsed_sec": 0,
                "eta_sec": round(total_sec / max(0.5, OVERLAY_RT_FACTOR)) if total_sec else None})
            overlay_started = time.time()

            def on_overlay(done_sec, total_out):
                elapsed = time.time() - overlay_started
                pct = (done_sec / total_out) if total_out else 0
                eta = (elapsed / pct - elapsed) if pct > 0.02 else None
                job.set(
                    progress=(f"叠加数字人片段 {pct * 100:.0f}% · 已用 {_fmt_hms(elapsed)}"
                              + (f" · 预计剩余 {_fmt_hms(eta)}" if eta is not None else "")),
                    render_progress={
                        "step": 2, "step_name": "叠加数字人片段",
                        "detail": f"{done_sec:.0f}/{total_out:.0f} 秒",
                        "done": round(done_sec, 1), "total": round(total_out, 1),
                        "percent": round(85 + pct * 14, 1),
                        "elapsed_sec": round(elapsed, 1),
                        "eta_sec": None if eta is None else round(eta)})

            try:
                avatar.composite_onto_video(ppt, timeline, final,
                                            size=geom["size"], corner=geom["corner"],
                                            cutout=geom["cutout"],
                                            fps=FPS, progress_cb=on_overlay)
                job.set(avatar_clips=len(timeline),
                        avatar_error=_cutout_missing(geom, timeline) or None)
                overlaid = True
            except Exception as e:  # noqa: BLE001 - 叠加失败保留纯 PPT 版成片
                log.warning("数字人叠加失败: %s", e)
                final.unlink(missing_ok=True)
                job.set(avatar_error=str(e)[:160])
        if not final.exists():
            # 未开数字人,或叠加失败 → 最终版就是纯 PPT 版
            ppt.replace(final)
        # 产物路径显式记进任务状态(has_video / 下载入口 / 过期判定都以 artifacts 为准;
        # 此前只有 final 靠 render_format 反推,artifacts 里始终没有 ppt/final)
        if final.exists():
            job._record_artifact("final", final)
        if ppt.exists():
            job._record_artifact("ppt", ppt)
    # 成片就绪后回收 Studio(前端此时展示成片播放,不再需要编辑器;槽位留给其他任务)
    stop_studio(job)
    job.set(status="rendered", progress="", render_format=fmt,
            render_progress={"step": 1, "step_name": "渲染 PPT 视频", "detail": "完成",
                             "done": 1, "total": 1, "percent": 100,
                             "elapsed_sec": 0, "eta_sec": 0})
    # 历史记录:这一步出了什么、多大、带不带数字人(项目列表据此直达成片)
    try:
        size_mb = final.stat().st_size / 1048576 if final.exists() else 0.0
    except OSError:
        size_mb = 0.0
    job.record_history("render",
                       detail=f"{fmt.upper()} · {float(job.state.get('total_sec') or 0):.0f} 秒"
                              + (f" · {size_mb:.1f} MB" if size_mb else "")
                              + (f" · 已叠加数字人({len(timeline)} 段)"
                                 + ("·抠像" if _avatar_geom(job).get("cutout") else "")
                                 if overlaid else " · 纯 PPT"),
                       artifact="final", fmt=fmt,
                       avatar_clips=len(timeline) if overlaid else 0,
                       avatar_cutout=bool(_avatar_geom(job).get("cutout")) if overlaid else False)


def stage_direct_render(job, fmt: str = "mp4"):
    """「一键出片」:按当前脚本与数字人设置构建,完成后立即渲染,中途不停在预览态。

    与「构建预览 → 渲染成片」两次点击只差两件事:① 构建段不拉 Studio(见 stage_build 的
    preview=False);② 构建完不等用户再点一次。产物、时长、历史与失败口径与分步走完全一致
    (两个阶段原样复用),所以状态机不需要第二套状态:building → rendering → rendered / failed。

    失败的账各记各的(build 的失败记 build、render 的记 render),与分步走时看到的完全一样;
    dispatch 处传 step=None,避免 run_in_background 再按"渲染失败"记一遍。
    """
    try:
        try:
            stage_build(job, preview=False)
        except Exception as e:  # noqa: BLE001 - 账记在 build 上,再交给 run_in_background 收尾
            job.record_history("build", status="failed", detail=str(e)[:160])
            raise
        try:
            stage_render(job, fmt)
        except Exception as e:  # noqa: BLE001
            job.record_history("render", status="failed", detail=str(e)[:160])
            raise
    finally:
        # 标记只表示"正在直达出片",成功或失败都清掉:前端据此决定要不要画构建段
        job.set(direct_render=False)


# ───────────────────────── Studio 服务器(hyperframes preview) ─────────────────────────


def _port_free(port: int) -> bool:
    import socket as _sock
    try:
        with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as sk:
            sk.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _studio_slot(job_id: str) -> int:
    used = set(STUDIO_SLOT_USED.values())
    for n in range(STUDIO_SLOTS):
        port = STUDIO_SLOT_BASE + n
        if port not in used and _port_free(port):
            STUDIO_SLOT_USED[job_id] = port
            return port
    # 槽满:回收最旧的,并确认端口真正释放(进程退出可能滞后),
    # 否则新会话绑定失败会被误判为「就绪」,导致两个任务记录到同一端口
    oldest_job_id = next(iter(STUDIOS), None)
    if oldest_job_id:
        oldest_port = STUDIO_SLOT_USED.get(oldest_job_id)
        if oldest_port:
            stop_studio(get_job(oldest_job_id))
            import time as _t
            for _ in range(30):
                if _port_free(oldest_port):
                    break
                _t.sleep(1.0)
        # 清理已回收的槽位
        STUDIOS.pop(oldest_job_id, None)
        STUDIO_SLOT_USED.pop(oldest_job_id, None)
        # 重新分配该端口
        if oldest_port and _port_free(oldest_port):
            STUDIO_SLOT_USED[job_id] = oldest_port
            return oldest_port
    raise RuntimeError("Studio 槽位回收失败(端口未释放)")


def studio_log_path(job_id: str) -> Path:
    """Studio 日志统一落在 logs/studio/<job_id>.log(旧版散落在项目根目录)。"""
    STUDIO_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return STUDIO_LOG_DIR / f"{job_id}.log"


def start_studio(job):
    """启动 HyperFrames Studio(串行化,防槽位竞态)。"""
    with STUDIO_LOCK:
        return _start_studio_locked(job)


def _start_studio_locked(job):
    """以 --foreground 直接拉起 Studio 进程并跟踪(不走 CLI 托管会话注册表——
    注册表会残留死会话,CLI 复用死会话时不监听新端口,是「偶发一直启动中」的根源)。
    """
    # 自愈线程可能已为本任务拉起存活 Studio:直接复用,避免进程/端口双开
    # (否则旧进程不被 terminate、旧端口永久占用,槽位缓慢耗尽)
    existing = STUDIOS.get(job.id)
    if existing is not None and existing.poll() is None:
        port = STUDIO_SLOT_USED.get(job.id)
        if port is not None and not _port_free(port):
            return port
    proj = str(job.paths()["project"])
    with open(studio_log_path(job.id), "a") as log:
        import time as _t
        for retry in range(2):
            port = _studio_slot(job.id)
            log.write(f"[{_t.time()}] starting studio for {job.id} on {port}\n")
            log.flush()
            proc = subprocess.Popen(
                ["hyperframes", "preview", "--port", str(port), "--foreground", "--no-open"],
                cwd=proj, stdout=log, stderr=log, env=_hf_env(),
            )
            # 等待端口就绪(最多 90s);进程提前退出则换端口重试
            for _ in range(90):
                if proc.poll() is not None:
                    log.write(f"studio 进程提前退出 code={proc.returncode}\n")
                    break
                if not _port_free(port):
                    STUDIOS[job.id] = proc
                    log.write(f"studio ready on {port}\n")
                    return port
                _t.sleep(1.0)
            log.write(f"端口 {port} 未就绪,重试下一端口\n")
    raise RuntimeError("Studio 启动超时(两个端口均未就绪)")


def _start_studio_bg(job):
    try:
        start_studio(job)
    except Exception as e:
        # 失败留痕(自愈循环会重试,但要能在日志里查到原因)
        log.exception("job %s Studio 自愈拉起失败", job.id)
        try:
            with open(studio_log_path(job.id), "a") as logf:
                logf.write(f"self-heal start failed: {e}\n")
        except Exception:
            pass
    finally:
        _studio_starting.discard(job.id)


def stop_studio(job):
    if job and job.id in STUDIOS:
        proc = STUDIOS.pop(job.id, None)
        STUDIO_SLOT_USED.pop(job.id, None)
        STUDIO_PROJECT_ID.pop(job.id, None)
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def _studio_id_from_dir(project_dir: Path) -> str:
    """兜底推导 Studio 侧项目 id。

    hyperframes 用**工作区根目录名**当项目 id:文档里的部署是 /mnt/workspace/ttv/…
    → "ttv",本工作区根是 /data/Avatar → "Avatar"。所以这个值不能写死。
    """
    try:
        return project_dir.resolve().parents[2].name or "ttv"
    except Exception:  # noqa: BLE001
        return "ttv"


async def _studio_project_id(job_id: str, port: int, project_dir: Path) -> str:
    """问 Studio 它自己的项目 id(按 dir 匹配本项目),问不到就按目录名兜底。

    不能沿用写死的 "ttv":本工作区里 Studio 报的是 "Avatar",写死会让
    /api/projects/<id>/* 全部 404,编辑器界面能加载但内容空转。
    """
    cached = STUDIO_PROJECT_ID.get(job_id)
    if cached:
        return cached
    sid = ""
    try:
        r = await PROXY_CLIENT.get(f"http://127.0.0.1:{port}/api/projects")
        items = (r.json() or {}).get("projects") or []
        want = project_dir.resolve()
        for item in items:
            d = str(item.get("dir") or "")
            try:
                if d and Path(d).resolve() == want:
                    sid = str(item.get("id") or "")
                    break
            except Exception:  # noqa: BLE001
                continue
        if not sid and len(items) == 1:
            sid = str(items[0].get("id") or "")   # 单项目部署:直接采用
    except Exception:  # noqa: BLE001 - 探测失败不影响兜底
        sid = ""
    sid = sid or _studio_id_from_dir(project_dir)
    STUDIO_PROJECT_ID[job_id] = sid
    return sid


def _live_studio_port(job_id: str) -> int | None:
    """Studio 存活且端口在监听时返回端口,否则返回 None。"""
    port = STUDIO_SLOT_USED.get(job_id)
    proc = STUDIOS.get(job_id)
    if proc is not None and proc.poll() is None and port is not None and not _port_free(port):
        return port
    return None


def _inflight_count() -> int:
    """计入并发闸门的进行中状态。avatar_building 是分钟级 GPU 推理(重跑数字人/播报视频),
    不计入就等于开了一个绕过 MAX_INFLIGHT_JOBS 的口子。"""
    return sum(1 for j in list(JOBS.values())
               if j.status in ("analyzing", "building", "avatar_building", "rendering"))


def _avatar_library_payload() -> dict:
    """形象库的读侧载荷(列表接口与 /api/styles 共用)。

    形象库整条链路失败(目录不可读、清单损坏到自愈都救不回来)时给一个**只含当前生效形象**
    的最小载荷:形象管理页会显示"读不到库",但出片链路照旧 —— 形象库是增强项,
    绝不能让一次读失败连累创作页与出片。
    """
    try:
        return avatar_library.list_payload()
    except Exception as e:  # noqa: BLE001
        log.warning("形象库读取失败,按最小载荷返回:%s", e)
        cur = resolve_avatar_image()
        return {"items": [], "default_id": "", "max_bytes": AVATAR_UPLOAD_MAX,
                "accept": sorted(AVATAR_IMAGE_TYPES),
                "current": {"id": "", "name": cur.stem, "file": cur.name,
                            "path": str(cur), "env_override": False},
                "error": f"形象库读取失败:{e}"}


# ───────────────────────── API ─────────────────────────


@app.get("/health")
@app.get("/api/health")
def health():
    return {"ok": True, "studios": len(STUDIOS)}


@app.get("/api/styles")
def api_styles():
    """四维度选项 + 预设组合(前端选择器)。"""
    def dim(d):
        return [{"key": k, "name": v["name"], "desc": v.get("desc", "")} for k, v in d.items()]
    return {
        "presets": [{"key": k, "name": v["name"], "combo": {kk: vv for kk, vv in v.items() if kk in ("font", "palette", "bg", "motion")}}
                    for k, v in styles.PRESETS.items()],
        "fonts": dim(styles.FONTS),
        "palettes": dim(styles.PALETTES),
        "backgrounds": dim(styles.BACKGROUNDS),
        "motions": dim(styles.MOTIONS),
        "voice_engines": [
            {"key": "cosyvoice3", "name": "本地 CosyVoice3", "voices": ["male", "female", "male_narrator"]},
            {"key": "qwen3tts", "name": "本地 Qwen3-TTS", "voices": ["male", "female", "male_narrator"]},
            {"key": "doubao", "name": "豆包 seed-tts-2.0(云)", "voices": tts.DOUBAO_VOICES},
        ],
        # 「数字人」的尺寸档位与四角位置(默认值 + 可选项 + 原生清晰上限),
        # 由后端下发:前端不再硬编码,改配置只改 config.py 一处
        "avatar_sizes": {
            "default": AVATAR_SIZE,
            "native": AVATAR_NATIVE_SIZE,
            "min": AVATAR_SIZE_MIN,
            "max": AVATAR_SIZE_MAX,
            "choices": avatar_size_options(),
        },
        "avatar_corners": avatar_corner_options(),
        "avatar_corner_default": AVATAR_CORNER,
        # 「抠像(只保留人像、背景透明)」的默认值:前端两个页面都用它兜底。
        # 取**全局偏好**(形象页可改、持久化),不是 config 里那个静态出厂默认。
        "avatar_cutout_default": preferences.avatar_cutout_new_jobs(),
        # 形象库:当前生效形象(名称 + 是否被 TTV_AVATAR_IMAGE 钉住)+ 上传规格。
        # 创作页只用 current/accept/max_bytes 做提示,形象管理页另走 /api/avatars。
        "avatar_library": _avatar_library_payload(),
        "preferences": preferences.payload(),
    }


# ── 全局偏好 ──
# 跨任务记住的设置。目前只有「新任务默认是否抠背景」一项 —— 它原来是任务级选项且默认关,
# 用户在形象页改一次就该一直生效,不该每次新建任务都去创作页勾。

@app.get("/api/preferences")
def api_preferences():
    """当前全局偏好(含出厂默认,便于界面解释环境变量钉住时是什么)。"""
    return preferences.payload()


@app.post("/api/preferences")
async def api_set_preferences(request: Request):
    """改全局偏好。字段都可选,只认真正的 JSON 布尔(字符串 "true" 一律 400)。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - 无请求体/非 JSON 都按"没传"处理
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw = body.get("avatar_cutout_new_jobs")
    if raw is None:
        return {"ok": True, **preferences.payload()}
    if not isinstance(raw, bool):
        raise HTTPException(400, "avatar_cutout_new_jobs 需要 true 或 false")
    try:
        preferences.set_avatar_cutout_new_jobs(raw)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True, **preferences.payload()}


# ── 数字人形象库 ──
# 形象是一份**全局**设置(不是任务状态):库里有什么、哪个是默认,都落在
# assets/avatars/library.json;所有**后续**构建的数字人片段按当前默认形象生成。
# 已在磁盘上的旧片段/旧成片不受影响 —— 片段缓存键本就含形象文件的内容哈希。


def _avatar_item_or_404(item_id: str) -> dict:
    try:
        item = avatar_library.find(item_id)
    except Exception as e:  # noqa: BLE001 - 库坏了按"取不到"处理,别 500
        raise HTTPException(500, f"形象库读取失败:{e}") from None
    if item is None:
        raise HTTPException(404, "形象不存在")
    return item


@app.get("/api/avatars")
def api_avatars():
    """形象库列表:条目(名称/分辨率/体积/时间/是否内置)+ 当前生效形象。"""
    return _avatar_library_payload()


@app.post("/api/avatars")
async def api_avatar_upload(file: UploadFile = File(...), name: str = Form("")):
    """上传一张形象图。

    校验三重(都在 avatar_library.add_avatar 里):扩展名白名单 → 体积上限 → 文件头能解析出
    宽高。同一张图重复上传返回既有条目(duplicate=true),不报错也不新增副本。
    """
    filename = Path(file.filename or "").name          # 防路径穿越
    ext = Path(filename).suffix.lower()
    if ext not in AVATAR_IMAGE_TYPES:
        raise HTTPException(400, "仅支持 " + " / ".join(sorted(AVATAR_IMAGE_TYPES)) + " 格式的图片")
    data = await file.read()
    if len(data) > AVATAR_UPLOAD_MAX:
        raise HTTPException(413, f"图片超过 {AVATAR_UPLOAD_MAX // (1024 * 1024)}MB 上限")
    try:
        item, duplicate = avatar_library.add_avatar(data, filename, name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except OSError as e:
        raise HTTPException(500, f"图片写入失败:{e}") from None
    return {"ok": True, "item": item, "duplicate": duplicate,
            "current": avatar_library.current_info()}


@app.post("/api/avatars/{item_id}/default")
def api_avatar_default(item_id: str):
    """把某个形象设为当前默认(之后新构建的数字人片段都用它)。"""
    _avatar_item_or_404(item_id)
    avatar_library.set_default(item_id)
    return {"ok": True, "default_id": item_id, "current": avatar_library.current_info(),
            "items": avatar_library.list_avatars()["items"]}


@app.post("/api/avatars/{item_id}/rename")
async def api_avatar_rename(item_id: str, request: Request):
    """重命名形象(只改显示名,不动文件)。"""
    _avatar_item_or_404(item_id)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - 无请求体/非 JSON 都按"没传名字"处理
        body = {}
    raw = body.get("name") if isinstance(body, dict) else None
    item = avatar_library.rename_avatar(item_id, raw or "")
    return {"ok": True, "item": item}


@app.delete("/api/avatars/{item_id}")
def api_avatar_delete(item_id: str):
    """删除形象。内置形象(jinli)不可删除;删掉当前默认时默认位自动落到剩余条目。"""
    _avatar_item_or_404(item_id)
    try:
        avatar_library.delete_avatar(item_id)
    except PermissionError as e:
        raise HTTPException(409, str(e)) from None
    except KeyError:
        raise HTTPException(404, "形象不存在") from None
    return {"ok": True, **avatar_library.list_payload()}


@app.get("/api/avatars/{item_id}/file")
def api_avatar_file(item_id: str):
    """形象图片本体(缩略图与大图共用)。内容按哈希命名,故可长缓存。"""
    item = _avatar_item_or_404(item_id)
    p = avatar_library.item_path(item)
    if not p.exists():
        raise HTTPException(404, "形象图片文件已丢失")
    media = AVATAR_IMAGE_TYPES.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(p, media_type=media,
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/jobs")
def api_jobs_list(limit: int = 200):
    """项目历史列表(进入页):按最近更新倒序,只带列表字段(不含 script)。

    进行中的任务把 progress/render_progress 一并带出,列表上就能看到"现在到哪一步";
    每一步的结果看 history(完成/失败各一条),前端据此直达该步产物。
    """
    items = [j.summary() for j in list(JOBS.values())]
    items.sort(key=lambda d: d.get("updated_at") or d.get("created_at") or 0, reverse=True)
    limit = max(1, min(int(limit or 200), 500))
    return {"jobs": items[:limit], "total": len(items)}


@app.post("/api/jobs/{job_id}/rename")
async def api_rename_job(job_id: str, request: Request):
    """重命名项目。标题只影响展示;改成 user 之后,自动总结不再覆盖它。"""
    job = get_job(job_id) or _http404()
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - 无请求体/非 JSON 都按"没传标题"处理
        body = {}
    raw = body.get("title") if isinstance(body, dict) else None
    try:
        title = normalize_title(raw)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    job.set(title=title, title_source="user", title_at=time.time())
    return {"ok": True, "job_id": job.id, "title": title, "title_source": "user"}


@app.post("/api/jobs")
async def api_create(file: UploadFile = File(None), style: str = Form(None),
                     duration: int = Form(120), text: str = Form(""),
                     font: str = Form(None), palette: str = Form(None),
                     bg: str = Form(None), motion: str = Form(None),
                     voice_engine: str = Form("cosyvoice3"), voice: str = Form(None),
                     video_kind: str = Form("promo"), avatar: bool = Form(False),
                     avatar_corner: str = Form(None), avatar_size: int = Form(None),
                     avatar_cutout: bool = Form(False)):
    if voice_engine not in ("cosyvoice3", "qwen3tts", "doubao"):
        raise HTTPException(400, f"未知配音引擎:{voice_engine}")
    if video_kind not in ("promo", "lecture"):
        raise HTTPException(400, f"未知视频类型:{video_kind}")
    # 数字人几何(位置 + 大小 + 是否抠像):创建时的选择;之后还能在预览页改(见 api_avatar_geom)
    try:
        geom = _normalize_geom(avatar_corner, avatar_size, avatar_cutout)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    # 并发防护:进行中任务过多时拒绝新任务(公网无鉴权,防批量提交挤爆 LLM/GPU)
    if _inflight_count() >= MAX_INFLIGHT_JOBS:
        raise HTTPException(429, f"当前进行中任务过多(≥{MAX_INFLIGHT_JOBS}),请稍后再试")
    combo = styles.resolve_combo(style, font, palette, bg, motion)
    # 时长档位:宣传 30-600 秒;讲解 300-1800 秒(5 分钟一档,取整到 300)
    if video_kind == "lecture":
        duration = max(300, min(1800, round(duration / 300) * 300))
    else:
        duration = max(30, min(600, duration))
    text = (text or "").strip()
    if file is not None and file.filename:
        filename = Path(file.filename or "article.txt").name  # 防路径穿越
        if not filename.lower().endswith((".txt", ".md", ".markdown", ".docx")):
            raise HTTPException(400, "仅支持 txt / md / docx")
        data = await file.read()
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(400, "文件超过 20MB")
        job = create_job(style or "", duration, filename, kind=video_kind)
        job.state["combo"] = combo
        job.state["voice_engine"] = voice_engine
        job.state["voice"] = voice or ""
        ext = "." + filename.lower().rsplit(".", 1)[-1]
        (job.dir / ("input" + ext)).write_bytes(data)
    elif len(text) >= 50:
        if len(text) > 200000:
            raise HTTPException(400, "文本超过 20 万字上限")
        job = create_job(style or "", duration, "粘贴文本.txt", kind=video_kind)
        job.state["combo"] = combo
        job.state["voice_engine"] = voice_engine
        job.state["voice"] = voice or ""
        job.dir.joinpath("input.txt").write_text(text, encoding="utf-8")
    else:
        raise HTTPException(400, "请上传文件或粘贴不少于 50 字的文本")
    job.state["avatar"] = bool(avatar)
    job.state["avatar_geom"] = geom
    # 项目标题:先落一个"文件名"级的占位,列表立刻有名字可认;
    # 分析完成后 _auto_title 用大模型总结的短标题覆盖它(title_source=auto)。
    stem = analyze.clean_title(Path(job.state.get("filename") or "").stem, max_len=40)
    if stem and stem.lower() not in ("input", "article", "untitled"):
        job.state["title"] = stem
        job.state["title_source"] = "file"
    job._save()
    run_in_background(job, stage_analyze, step="analyze")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/analyze")
def api_reanalyze(job_id: str):
    """重新分析(提示词升级后可用)。"""
    job = get_job(job_id) or _http404()
    # 状态守卫:分析/构建/渲染中不得重入(否则并发写 script.json、状态互相覆盖)
    if job.status in ("analyzing", "building", "avatar_building", "rendering"):
        raise HTTPException(409, f"当前状态 {job.status} 不能重新分析(等待完成)")
    job.set(status="analyzing", progress="重新分析中", error=None)
    run_in_background(job, stage_analyze, step="analyze")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/script")
async def api_edit_script(job_id: str, request: Request):
    """用户直接编辑分析结果/逐帧脚本后保存(校验通过方可构建)。"""
    job = get_job(job_id) or _http404()
    # 与 revise 一致:仅 analyzed/preview/failed 可改(analyzing 会并发写覆盖、uploaded 无文件)
    if job.status not in ("analyzed", "preview", "failed"):
        raise HTTPException(409, f"当前状态 {job.status} 不能修改脚本(需先完成分析)")
    body = await request.json()
    script = body.get("script") if isinstance(body, dict) and "script" in body else body
    article = job.paths()["input"].read_text(encoding="utf-8")
    errs = analyze.validate_script(script, article, int(job.state.get("duration_sec", 120)),
                                   job.state.get("video_kind", "promo"))
    if errs:
        raise HTTPException(400, "校验失败:" + "; ".join(errs[:6]))
    job.paths()["script"].write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    job.set(status="analyzed", progress="脚本已按编辑保存,可重新构建", error=None)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/revise")
async def api_revise(job_id: str, request: Request):
    """用户用一句话描述修改要求,AI 吸纳建议修订脚本。"""
    job = get_job(job_id) or _http404()
    if job.status not in ("analyzed", "preview", "failed"):
        raise HTTPException(409, f"当前状态 {job.status} 不能修改(需先完成分析)")
    body = await request.json()
    instruction = body.get("instruction", "").strip() if isinstance(body, dict) else ""
    if len(instruction) < 5:
        raise HTTPException(400, "请描述修改要求(不少于 5 字)")
    job.set(status="analyzing", progress="AI 按建议修改脚本中", error=None)
    run_in_background(job, stage_revise, instruction, step="revise")
    return {"ok": True}


def stage_revise(job, instruction: str):
    if not _job_alive(job):
        return
    try:
        script = json.loads(job.paths()["script"].read_text(encoding="utf-8"))
        article = job.paths()["input"].read_text(encoding="utf-8")
        revised = analyze.revise_script(script, article, instruction,
                                        job.state.get("video_kind", "promo"))
        job.paths()["script"].write_text(json.dumps(revised, ensure_ascii=False, indent=1), encoding="utf-8")
        job.set(status="analyzed", progress=f"已按建议修改:{instruction[:30]}", error=None)
        job.record_history("revise", detail=f"已按建议修改:{instruction[:60]}")
    except Exception as e:
        # 修改失败不毁掉任务:保留原脚本,提示可重试或直接构建
        log.exception("job %s AI 修改失败", job.id)
        job.set(status="analyzed", progress=f"AI 修改失败({str(e)[:50]}),保留原脚本,可重试或直接构建",
                error=None)
        job.record_history("revise", status="failed", detail=str(e)[:120])


def _broadcast_basis_sec(job) -> float:
    """预估播报视频时长的依据:成片权威总时长 > 脚本草稿总时长 > 用户所选目标时长。

    只用 duration_sec(目标)会把「30 秒档实际出 75 秒」这类内容驱动的偏差算漏,
    所以优先用脚本自身估的帧时长之和。
    """
    if job.state.get("total_sec"):
        return float(job.state["total_sec"])
    s = job.script() or {}
    total = sum(float(f.get("duration") or 0) for f in (s.get("frames") or []))
    return total or float(job.state.get("duration_sec") or 0)


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str, brief: int = 0, avatar_size: int | None = None):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    d = job.to_dict(brief=bool(brief))
    # 「数字人」几何:成片里那个人像的位置(四角)与大小;前端两处控件(创作页 / 预览页)都读它
    geom = _avatar_geom(job)
    d["avatar_geom"] = geom
    # 该任务的数字人形象:state 里记的是**上次构建时**真正用的那份(审计用),
    # avatar_current 是此刻库里生效的那份 —— 两者可能不同(构建之后换了默认形象),
    # 界面据此说清"现在换形象,要重新构建才会用新的"。
    d["avatar_image_name"] = job.state.get("avatar_image_name") or ""
    d["avatar_image_file"] = job.state.get("avatar_image_file") or ""
    d["avatar_current"] = _avatar_library_payload()["current"]
    # 「数字人播报视频」的尺寸口径:前端输入框的当前值 = 任务上次用的尺寸,
    # 没生成过则跟随任务的数字人大小(默认 config.AVATAR_SIZE)
    d["avatar_broadcast_size"] = avatar.safe_size(
        job.state.get("avatar_broadcast_size"), geom["size"])
    # 事前预计耗时(界面在点击前显示「预计约 X 分钟」;生成过程中的实时 ETA 由
    # avatar_broadcast.eta_sec 给出)。avatar_size = 用户在下拉里**刚选中但还没提交**
    # 的尺寸,让预计时间跟着选择走,而不是停在任务上次用的那一档。
    est_size = d["avatar_broadcast_size"]
    if avatar_size is not None:
        est_size = avatar.safe_size(avatar_size, est_size)
    d["avatar_broadcast_est_sec"] = avatar.estimate_broadcast_sec(
        _broadcast_basis_sec(job), size=est_size)
    # 自愈:Studio 进程若已死亡则自动重建(分步渲染期间编辑器也应保持可用)。
    # 「一键出片」例外:这条路压根没有编辑器(preview=False 不拉 Studio),轮询不该把它拉起来 ——
    # 否则渲染段又白占一个槽位,与"直达出片不拉 Studio"自相矛盾。
    if job.status in ("preview", "rendering") and not job.state.get("direct_render"):
        port = _live_studio_port(job.id)
        if port is None:
            if job.id not in _studio_starting:
                _studio_starting.add(job.id)
                threading.Thread(target=_start_studio_bg, args=(job,), daemon=True).start()
        d["studio_port"] = port
    return d


@app.delete("/api/jobs/{job_id}")
def api_delete_job(job_id: str):
    """删除任务(rendered/failed 等终态可删;进行中 409)。"""
    job = get_job(job_id) or _http404()
    if job.status in ("analyzing", "building", "avatar_building", "rendering"):
        raise HTTPException(409, f"当前状态 {job.status} 不能删除(等待完成)")
    stop_studio(job)
    remove_job(job)
    shutil.rmtree(job.dir, ignore_errors=True)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/build")
def api_build(job_id: str, force_voice: int = 0):
    """构建预览。默认复用已有配音(见 stage_build);force_voice=1 强制重新合成配音。"""
    job = get_job(job_id) or _http404()
    if job.status not in ("analyzed", "preview", "rendered", "failed"):
        raise HTTPException(409, f"当前状态 {job.status} 不能构建")
    if not job.paths()["script"].exists():
        raise HTTPException(409, "脚本尚未生成,请先完成分析")
    job.set(status="building", progress="", error=None)
    run_in_background(job, stage_build, bool(force_voice), step="build")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/render")
async def api_render(job_id: str, request: Request):
    """渲染成片。

    请求体两种用法:
      {"format": "mp4"}               —— 只渲染(要求已经构建好预览)
      {"format": "mp4", "build": true} —— 「一键出片」:先按当前脚本与数字人设置构建
      (配音 / 组装 / 数字人片段),完成后立即渲染 —— 不必先点「构建预览」再点「渲染成片」。
    """
    job = get_job(job_id) or _http404()
    body = {}
    try:
        body = await request.json() or {}
    except Exception:  # noqa: BLE001 - 无请求体/非 JSON 都按默认处理
        body = {}
    if not isinstance(body, dict):
        body = {}
    fmt = body.get("format", "mp4")
    if fmt not in RENDER_FORMATS:
        raise HTTPException(400, f"不支持的格式 {fmt},可选:{sorted(RENDER_FORMATS)}")
    # 只认真正的 JSON 布尔:字符串 "false" 在这里是坏值,不能当"没传"(与 avatar/geom 同口径)
    direct = body.get("build", False)
    if not isinstance(direct, bool):
        raise HTTPException(400, "build 需要 true 或 false")
    if direct:
        # 与 api_build 同一张允许表:分析完成 / 预览就绪 / 已出片 / 失败都能一键重跑
        if job.status not in ("analyzed", "preview", "rendered", "failed"):
            raise HTTPException(409, f"当前状态 {job.status} 不能出片")
        if not job.paths()["script"].exists():
            raise HTTPException(409, "脚本尚未生成,请先完成分析")
        # 状态在 dispatch 之前翻转:构建要跑几分钟,否则连点两下会并发起两条出片流水线
        job.set(status="building", progress="", error=None, direct_render=True)
        # step=None:两个阶段的失败历史由 stage_direct_render 自己按阶段记
        run_in_background(job, stage_direct_render, fmt, step=None)
        return {"ok": True, "direct": True}
    if job.status not in ("preview", "rendered", "failed"):
        raise HTTPException(409, f"当前状态 {job.status} 不能渲染")
    run_in_background(job, stage_render, fmt, step="render")
    return {"ok": True, "direct": False}


@app.get("/api/jobs/{job_id}/video")
def api_video(job_id: str):
    job = get_job(job_id) or _http404()
    out = job.video_path()
    if out is None:
        raise HTTPException(404, "视频尚未渲染")
    return FileResponse(out, media_type=f"video/{out.suffix.lstrip('.')}",
                        filename=f"{job.id}{out.suffix}")


@app.post("/api/jobs/{job_id}/avatar/geom")
async def api_avatar_geom(job_id: str, request: Request):
    """改「成片里数字人」的出镜开关、位置、大小与是否抠像。

    请求体四个字段都可选,只传哪个就改哪个:
      avatar: true/false —— 「不出镜」也是这里的一个选项(false)
      corner: tl/tr/br/bl 或 左上/右上/右下/左下
      size:   正方形边长(偶数, 160–1080)
      cutout: true/false —— 只保留人像、背景透明(抠像不可用时自动回退圆角卡片)
    创建时的选择写在 state;这里让分析完成后的任务也能改 ——
    否则想关掉出镜、或换个角落,都得重新提交文章、重新分析。
    改动对**下一次构建/渲染**生效(关了出镜就不叠,旧片段仍留在缓存里)。
    """
    job = get_job(job_id) or _http404()
    if job.status in ("analyzing", "building", "avatar_building", "rendering"):
        raise HTTPException(409, f"当前状态 {job.status} 不能改数字人设置(等待完成)")
    body = {}
    try:
        body = await request.json() or {}
    except Exception:  # noqa: BLE001 - 无请求体/非 JSON 都按"没传"处理
        body = {}
    if not isinstance(body, dict):
        body = {}
    # 出镜开关:只认真正的 JSON 布尔,字符串 "false" 在这里是"没传",不能当假值用
    raw_on = body.get("avatar")
    if raw_on is None:
        enabled = bool(job.state.get("avatar"))
    elif isinstance(raw_on, bool):
        enabled = raw_on
    else:
        raise HTTPException(400, "avatar 需要 true 或 false")
    cur = _avatar_geom(job)
    try:
        geom = _normalize_geom(body.get("corner"), body.get("size"), body.get("cutout"), cur)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    job.set(avatar=enabled, avatar_geom=geom)
    return {"ok": True, "avatar": enabled, "avatar_geom": geom}


@app.post("/api/jobs/{job_id}/avatar/broadcast")
async def api_avatar_broadcast(job_id: str, request: Request, size: int | None = None):
    """独立生成「数字人播报视频」:分析完成后即可点,与 PPT 构建/渲染互不依赖。

    用拒绝列表(而非允许列表)守卫:这条支线最需要作用于已渲染的任务
    (改了一句台词、或想单独交付口播片),允许列表会把 rendered 挡在门外。

    size:画面边长(正方形)。可放请求体 {"size": 480},也可用 ?size=480;
    省略则沿用该任务上次选的尺寸,再回退任务的「数字人大小」(默认 config.AVATAR_SIZE)。
    """
    job = get_job(job_id) or _http404()
    if job.status in ("analyzing", "building", "avatar_building", "rendering"):
        raise HTTPException(409, f"当前状态 {job.status} 不能生成播报视频(等待完成)")
    if not job.paths()["script"].exists():
        raise HTTPException(409, "脚本尚未生成,请先完成分析")
    body = {}
    try:
        body = await request.json() or {}
    except Exception:  # noqa: BLE001 - 无请求体/非 JSON 都按"没传尺寸"处理
        body = {}
    raw = body.get("size", size) if isinstance(body, dict) else size
    if raw is None:
        raw = job.state.get("avatar_broadcast_size")
    if raw is None:
        raw = _avatar_geom(job)["size"]   # 没单独选过 → 跟随任务的数字人大小
    try:
        size = avatar.normalize_size(raw)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    prev = job.status
    # 状态在 dispatch 之前翻转:避免重复提交窗口(与 stage_render 的写法不同,这里更严)
    job.set(status="avatar_building", error=None, avatar_broadcast_size=size,
            avatar_broadcast={"status": "running", "step_index": 1,
                              "step": AVATAR_BROADCAST_STEPS[0], "size": size,
                              "detail": "准备中…", "done": 0, "total": None,
                              "eta_sec": None, "started_at": time.time(),
                              "updated_at": time.time(), "finished_at": None, "error": None})
    run_in_background(job, stage_avatar_broadcast, prev, size, step="broadcast")
    return {"ok": True, "prev_status": prev, "size": size}


@app.get("/api/jobs/{job_id}/avatar/broadcast/video")
def api_avatar_broadcast_video(job_id: str):
    """播报视频(独立预览/下载入口)。FileResponse 支持 Range,<video> 可直接拖动播放。"""
    job = get_job(job_id) or _http404()
    out = job.artifact_path("avatar")
    if out is None:
        raise HTTPException(404, "数字人播报视频尚未生成")
    return FileResponse(out, media_type="video/mp4", filename=f"{job.id}-avatar.mp4")


def _job_from_pid(pid: str):
    """Studio 项目 id = 'ttv' + job_id → 反查任务。"""
    if pid.startswith("ttv") and len(pid) > 3:
        job = get_job(pid[3:])
        if job:
            return job
    # Studio 内部 projectName 为 "ttv",前端可能直接传 "ttv"
    # 此时无法精确反查任务,交给调用链处理
    return None


@app.get("/api/runtime.js")
def api_runtime_js():
    """HyperFrames 运行时脚本(Studio 预览 iframe 加载,所有任务通用)。"""
    p = HYPERFRAMES_RUNTIME
    if not p.exists():
        raise HTTPException(404, f"runtime.js 不存在: {p}")
    return Response(content=p.read_bytes(), media_type="application/javascript")


@app.get("/api/projects")
def api_projects_list():
    """Studio 项目列表:合成所有处于 preview 状态的任务(Studio 服务器内部 id 恒为 ttv)。"""
    items = []
    for job in list(JOBS.values()):
        if job.status == "preview":
            items.append({
                "id": "ttv" + job.id,
                "dir": str(job.paths()["project"]),
                "title": job.state.get("filename", "") or "ttv" + job.id,
            })
    return {"projects": items}


@app.api_route("/api/projects/{pid}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@app.api_route("/api/projects/{pid}/", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def api_project_root(pid: str, request: Request):
    """Studio 以无斜杠(或带斜杠)根路径拉取项目信息——compositions 列表就在此响应里。

    必须显式注册两条路由:{rest:path} 匹配不到空子路径,FastAPI 会 307 重定向到带斜杠
    版本再 404(重定向 Location 还用 nginx 传来的无端口 Host,直接生成坏地址),
    导致 Studio 左上角组件列表永远为空。
    """
    # pid 可能是 "ttv123abc" 或纯 "ttv"(后端项目名无任务后缀)
    # 从 Referer 头提取 job_id
    job_id = None
    if pid.startswith("ttv") and len(pid) > 3:
        job_id = pid[3:]
    if not job_id:
        ref = str(request.headers.get("referer", ""))
        import re as _re
        # Referer 来源:主页面 /ttv/?job={job_id} 或 iframe /ttv/api/studio/{job_id}/...
        for pat in (r"/\?job=([a-f0-9]+)", r"/api/studio/([a-f0-9]+)/"):
            m = _re.search(pat, ref)
            if m:
                job_id = m.group(1)
                break
    job = get_job(job_id) if job_id else None
    if not job:
        raise HTTPException(404, "项目不存在")
    port = _live_studio_port(job.id)
    if port is None:
        if job.status == "preview" and job.id not in _studio_starting:
            _studio_starting.add(job.id)
            threading.Thread(target=_start_studio_bg, args=(job,), daemon=True).start()
        raise HTTPException(503, "Studio 启动中")
    # 转发时必须使用 Studio 自己的项目 id(本工作区是 "Avatar",/mnt/workspace/ttv 部署是
    # "ttv")—— 写死会让 /api/projects/<id> 404,编辑器组件列表与预览全空。
    sid = await _studio_project_id(job.id, port, job.paths()["project"])
    target = f"http://127.0.0.1:{port}/api/projects/{sid}"
    try:
        r = await PROXY_CLIENT.request(request.method, target)
    except Exception:
        raise HTTPException(503, "Studio 启动中")
    ctype = r.headers.get("content-type", "application/octet-stream")
    content = r.content
    if "javascript" in ctype or "text/html" in ctype or "json" in ctype:
        text = content.decode("utf-8", errors="ignore")
        # 与子路径转发一致:把响应里的 Studio 项目 id 改写为前端的任务级 id
        text = text.replace(f"/api/projects/{sid}/", f"/api/projects/ttv{job.id}/")
        content = text.encode("utf-8")
    return Response(content=content, status_code=r.status_code,
                    headers={"Content-Type": _fix_mime("", ctype)})


def _client_base(request: Request) -> str:
    """浏览器侧的应用挂载前缀:根部署 = "",nginx 的 /ttv/ 部署 = "/ttv"。

    后端自己看不到这个前缀(nginx 的 proxy_pass 会把它剥掉),但 iframe 的父页面
    (或 Studio 文档本身、Studio 的接口调用)会以 Referer/Origin 带过来:
    主页面 `.../ttv/?job=X`、文档 `.../ttv/api/studio/X/`。
    取不到时按根部署处理 —— 写死 /ttv 会让根部署下 Studio 的 JS/CSS 全部 404,
    表现就是「构建预览一直转圈」(页面壳能加载,但 bundle 永远不到)。
    """
    for raw in (request.headers.get("referer", ""), request.headers.get("origin", "")):
        m = re.match(r"^https?://[^/]+(/.*)$", raw or "")
        if not m:
            continue
        path = m.group(1)
        cut = path.find("/api/studio/")
        if cut >= 0:
            return path[:cut]
        cut = path.find("?job=")
        if cut >= 0:
            return path[:cut].rstrip("/")
    return ""


@app.api_route("/api/projects/{pid}/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def api_projects_passthrough(pid: str, rest: str, request: Request):
    """Studio 前端以源根路径调用 /api/projects/...,转发到对应任务的 Studio 服务器。"""
    if ".." in rest:
        raise HTTPException(400, "非法路径")
    # pid 可能为 "ttv{job_id}"(来自主页面)或纯 "ttv"(来自 Studio iframe 内部)
    job = _job_from_pid(pid)
    if not job:
        # 纯 "ttv" pid → 从 Referer 头提取 job_id
        ref = str(request.headers.get("referer", ""))
        import re as _re2
        for pat in (r"/\?job=([a-f0-9]+)", r"/api/studio/([a-f0-9]+)/"):
            m = _re2.search(pat, ref)
            if m:
                job = _job_from_pid("ttv" + m.group(1))
                break
    if not job:
        raise HTTPException(404, "项目不存在")
    port = _live_studio_port(job.id)
    if port is None:
        if job.status == "preview" and job.id not in _studio_starting:
            _studio_starting.add(job.id)
            threading.Thread(target=_start_studio_bg, args=(job,), daemon=True).start()
        raise HTTPException(503, "Studio 启动中")
    # 前端以任务级 id("ttv{job_id}")请求,转发时必须换成 Studio 自己的项目 id。
    sid = await _studio_project_id(job.id, port, job.paths()["project"])
    target = f"http://127.0.0.1:{port}/api/projects/{sid}/{rest}"
    if request.url.query:
        target += "?" + request.url.query
    body = await request.body()
    headers = {}
    if request.headers.get("content-type"):
        headers["Content-Type"] = request.headers["content-type"]
    r = await PROXY_CLIENT.request(request.method, target, content=body, headers=headers)
    ctype = r.headers.get("content-type", "application/octet-stream")
    content = r.content
    if "javascript" in ctype or "text/html" in ctype or "json" in ctype:
        text = content.decode("utf-8", errors="ignore")
        # Studio 侧项目 id → 前端的任务级 id(前缀按浏览器侧挂载点补,见 _client_base)
        _base = _client_base(request)
        text = text.replace(f"/api/projects/{sid}/", f"{_base}/api/projects/ttv{job.id}/")
        text = text.replace('"/assets/', f'"{_base}/api/studio/{job.id}/assets/')
        text = text.replace("'/assets/", f"'{_base}/api/studio/{job.id}/assets/")
        if "text/html" in ctype and rest.startswith("preview"):
            text = _inject_preview_audio_watchdog(text)
        content = text.encode("utf-8")
    return Response(content=content, status_code=r.status_code,
                    headers={"Content-Type": _fix_mime(rest, ctype)})


@app.api_route("/api/studio/{job_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/api/studio/{job_id}/", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/api/studio/{job_id}/{path:path}",
               methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def api_studio(job_id: str, request: Request, path: str = ""):
    """反向代理到该任务的 HyperFrames Studio(preview 完整编辑器)。

    注意:
    - 同时注册带/不带尾斜杠的根路径以及带子路径的三条路由,
      `{path:path}` 无法匹配空路径(根目录访问)。
    - **必须放开全部方法**:编辑器保存/选择类请求走 POST/PUT/PATCH,只注册 GET 会 405。
    - Studio 页面与静态资源使用绝对路径(/assets/、/favicon.svg、/api/),
      经本代理下发时改写为 <应用挂载前缀>/api/studio/<job_id>/ —— 前缀由 _client_base
      从 Referer 推断(根部署 ""、nginx /ttv/ 部署 "/ttv"),不写死。
    """
    if ".." in path:
        raise HTTPException(400, "非法路径")
    port = _live_studio_port(job_id)
    if port is None:
        job = get_job(job_id)
        if job and job.status == "preview" and job_id not in _studio_starting:
            _studio_starting.add(job_id)
            # 后台拉起(不能阻塞事件循环,否则全站 502)
            threading.Thread(target=_start_studio_bg, args=(job,), daemon=True).start()
        return Response(
            content=_retry_msg("Studio 启动中", "页面会自动重试,请稍候。"),
            status_code=503, media_type="text/html")
    return await _studio_proxy(job_id, path, request, port)


async def _studio_proxy(job_id: str, path: str, request: Request, port: int):
    query = f"?{request.url.query}" if request.url.query else ""
    job = get_job(job_id)
    project_dir = job.paths()["project"] if job else Path("/")
    sid = await _studio_project_id(job_id, port, project_dir)
    target_path = path
    path_before = target_path
    # 重写请求路径中的项目 id:前端用的是任务级 id("ttv" 或 "ttv{job_id}",来自 iframe 的
    # #project/ttv),Studio 只认自己的项目 id(本工作区 "Avatar")。
    target_path = re.sub(
        rf"^api/projects/(?:ttv{re.escape(job_id)}|ttv)(?=/|$)",
        f"api/projects/{sid}",
        target_path,
    )
    target = f"http://127.0.0.1:{port}/{target_path}{query}"
    log.warning("### STUDIO PROXY: job=%s path_before=%s path_after=%s target=%s",
                job_id, path_before, target_path, target)
    try:
        # 按原始方法与 body 转发(Studio 可能经此路径发 POST/PUT 保存类请求)
        body = await request.body() if request.method in ("POST", "PUT", "PATCH", "DELETE") else None
        headers = {}
        if request.headers.get("content-type"):
            headers["Content-Type"] = request.headers["content-type"]
        r = await PROXY_CLIENT.request(
            request.method, target, content=body, headers=headers,
            follow_redirects=request.method in ("GET", "HEAD"))
    except Exception:
        return Response(
            content=_retry_msg("Studio 启动中", "页面会自动重试,请稍候。"),
            status_code=503, media_type="text/html")
    ctype = r.headers.get("content-type", "application/octet-stream")
    content = r.content
    # 前缀必须按浏览器侧的挂载点生成:根部署是 /api/studio/<id>/,nginx /ttv/ 部署是
    # /ttv/api/studio/<id>/。写死 /ttv 会让根部署下 Studio 的 JS/CSS 全部 404(iframe 一直转圈)
    prefix = f"{_client_base(request)}/api/studio/{job_id}/"
    # 响应中的项目 id 重写:把 Studio 自己的 id 映射回前端的任务级 id,
    # 这样 iframe 里的 JS(#project/ttv)与它发出的请求始终一致
    response_pid_from = f"/api/projects/{sid}/"
    response_pid_to = f"/api/projects/ttv{job_id}/"
    if "text/html" in ctype:
        text = content.decode("utf-8", errors="ignore")
        text = text.replace('src="/', f'src="{prefix}')
        text = text.replace('href="/', f'href="{prefix}')
        # 响应中将 Studio 内部项目 id 重新映射回前端的外部 id
        text = text.replace(response_pid_from, response_pid_to)
        content = text.encode("utf-8")
    elif "javascript" in ctype:
        # JS 内窄化重写(仅 /assets/ 与 /api/ 前缀,避免破坏字符串字面量)
        text = content.decode("utf-8", errors="ignore")
        text = text.replace('"/assets/', f'"{prefix}assets/')
        text = text.replace("'/assets/", f"'{prefix}assets/")
        text = text.replace('"/api/', f'"{prefix}api/')
        text = text.replace("'/api/", f"'{prefix}api/")
        # 模板字面量中的 /api/ 前缀重写(Studio 的 _0 函数用 backtick 构造 API 路径)
        text = text.replace('`/api/', f'`{prefix}api/')
        # Studio 接口响应中的项目 id 重写
        text = text.replace(response_pid_from, response_pid_to)
        content = text.encode("utf-8")
    ctype = _fix_mime(path, ctype)
    return Response(content=content, status_code=r.status_code,
                    headers={"Content-Type": ctype})


PREVIEW_AUDIO_WATCHDOG = """<script>
/* Studio 预览音频看门狗:浏览器自动播放策略拦截或框架音频提升路径失效时,
   恢复「时间线在播放而音频静音/暂停」的死状态(偶发预览无声的修复)。
   不干扰用户手动静音——手动静音时音频仍在播放,非暂停态。 */
(function(){
  var iv = setInterval(function(){
    var tls = window.__timelines || {};
    var t = null;
    for (var k in tls) {
      var tl = tls[k];
      if (tl && typeof tl.time === 'function') {
        var now = tl.time();
        if (now > 0.05) { t = now; break; }
      }
    }
    if (t === null) return;
    document.querySelectorAll('audio[data-start], audio#bgm').forEach(function(a){
      var s = parseFloat(a.getAttribute('data-start') || '0') || 0;
      var end = a.id === 'bgm' ? 1e9
        : (isFinite(a.duration) && a.duration > 0 ? s + a.duration : s + 60);
      if (t < s || t >= end) return;  // 不在播放窗口内,不动
      var p;
      if (a.muted && a.paused) {      // 提升路径死状态:静音且停着 → 恢复
        a.muted = false;
        p = a.play();
        if (p && p.catch) p.catch(function(){});
      } else if (!a.muted && a.paused && !a.error) {  // play 曾被拒:持续重试等待激活
        p = a.play();
        if (p && p.catch) p.catch(function(){});
      }
    });
  }, 1000);
})();
</script>
"""


def _inject_preview_audio_watchdog(html: str) -> str:
    """向 Studio 预览页注入音频看门狗(修复偶发预览无声)。"""
    if "</body>" in html:
        return html.replace("</body>", PREVIEW_AUDIO_WATCHDOG + "</body>", 1)
    return html + PREVIEW_AUDIO_WATCHDOG


EXT_MIME = {
    ".js": "application/javascript", ".mjs": "application/javascript",
    ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".woff2": "font/woff2",
    ".otf": "font/otf", ".ttf": "font/ttf", ".map": "application/json",
    ".html": "text/html",
    # 音频/视频:内置服务器按 text/plain 下发,Chrome 拒载导致播放器与 Studio 无声
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".ogg": "audio/ogg", ".mp4": "video/mp4", ".webm": "video/webm",
}


def _fix_mime(path: str, ctype: str) -> str:
    """按扩展名覆盖 content-type(内置服务器把所有资源当 text/html)。"""
    from pathlib import PurePosixPath
    ext = PurePosixPath(path).suffix.lower()
    if ext in EXT_MIME:
        return EXT_MIME[ext]
    return ctype


def _retry_msg(title: str, note: str) -> str:
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"/>
<meta http-equiv="refresh" content="8"/><title>{title}</title></head>
<body style="margin:0;display:flex;align-items:center;justify-content:center;height:100vh;
background:#101820;color:#8CA0B3;font-family:'PingFang SC','Microsoft YaHei',sans-serif;">
<div style="text-align:center;"><div style="font-size:15px;color:#fff;margin-bottom:8px;">{title}</div>
<div style="font-size:12.5px;">{note}</div></div></body></html>"""


def _http404():
    raise HTTPException(404, "任务不存在")


# ── 本地/独立部署:后端直接托管前端(生产由 nginx 托管 /ttv/,两条路径下前端都用相对 ./api/)
# 必须放在所有 API 路由之后挂载,否则 "/" 会抢先吃掉 /api/*。
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=BACKEND_PORT, log_level="info")
