# -*- coding: utf-8 -*-
"""理论文章转视频 —— FastAPI 服务。

流水线:uploaded → analyzing → analyzed → building → preview → rendering → rendered
所有阶段在服务器本地执行(DeepSeek vLLM / edge-tts / hyperframes CLI)。
"""
import json
import os
import re
import shutil
import subprocess
import threading
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

sys.path.insert(0, str(Path(__file__).parent))
from config import (BACKEND_PORT, JOBS_DIR, NODE_BIN_DIR, PLAYER_SLOT_BASE,
                    PLAYER_SLOTS, STYLES, WEB_DIR)  # noqa: E402
from jobs import JOBS, create_job, get_job, run_in_background  # noqa: E402
import extract  # noqa: E402
import analyze  # noqa: E402
import tts  # noqa: E402
from builder import assemble, styles  # noqa: E402

app = FastAPI(title="理论文章转视频")


@app.on_event("startup")
def _restore_players():
    """服务重启后,为处于 preview 状态的任务重建 play 与 Studio 服务器。"""
    for job in JOBS.values():
        if job.status == "preview":
            try:
                start_player(job)
            except Exception:
                pass
            try:
                start_studio(job)
            except Exception:
                pass

PLAYERS: dict[str, subprocess.Popen] = {}   # job_id -> play 进程
SLOT_USED: dict[str, int] = {}              # job_id -> play 端口槽
STUDIOS: dict[str, int] = {}                # job_id -> Studio 端口(preview --background 为托管会话)
_studio_starting: set = set()                 # 正在后台拉起 Studio 的任务(防重复)
STUDIO_SLOT_USED: dict[str, int] = {}
STUDIO_SLOT_BASE = 4150
STUDIO_SLOTS = 4

# ───────────────────────── 流水线阶段 ─────────────────────────


def _job_combo(job) -> dict:
    """任务的四维风格组合(job.state['combo'] 持久化)。"""
    c = job.state.get("combo")
    if not c:
        c = styles.resolve_combo(job.state.get("style"), None, None, None, None)
        job.state["combo"] = c
    return c


def stage_analyze(job):
    job.set(status="analyzing", progress="提取文本")
    p = job.paths()
    # 上传文件保留原扩展名(txt/md/docx);粘贴文本模式直接就是 input.txt
    upload = next(job.dir.glob("input.*"))
    text = extract.extract_text(upload)
    p["input"].write_text(text, encoding="utf-8")
    job.set(progress=f"DeepSeek 分析中(约 10-60 秒,全文 {len(text)} 字)")
    script = analyze.analyze_article(text, int(job.state["duration_sec"]), _job_combo(job))
    p["script"].write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    job.set(status="analyzed", progress="")


def stage_build(job):
    job.set(status="building", progress="生成配音")
    p = job.paths()
    script = json.loads(p["script"].read_text(encoding="utf-8"))
    style = styles.get(_job_combo(job))
    target = int(job.state.get("duration_sec", 120))
    # 语速保持 1.0(自然说话语速,不随内容缩放)
    speed = 1.0
    provider = job.state.get("voice_engine") or "cosyvoice3"
    voice = job.state.get("voice") or style["voice"]
    eng_names = {"cosyvoice3": "本地 CosyVoice3", "qwen3tts": "本地 Qwen3-TTS", "doubao": "豆包 seed-tts-2.0"}
    job.set(progress=f"配音合成中({eng_names.get(provider, provider)},自然语速)")
    vo = tts.synthesize_frames(script["frames"], voice, p["vo"], speed=speed, provider=provider)
    engines = {}
    for v in vo.values():
        engines[v.get("engine", "unknown")] = engines.get(v.get("engine", "unknown"), 0) + 1
    eng_txt = " + ".join(f"{k}×{n}" for k, n in sorted(engines.items()))
    doubao_err = tts.DOUBAO_LAST_ERROR if provider == "doubao" and "doubao" not in engines else ""
    if doubao_err:
        job.set(progress=f"豆包引擎失败({doubao_err}),已回落 CosyVoice3;组装项目中")
    else:
        job.set(progress=f"组装 HyperFrames 项目(配音引擎:{eng_txt})")
    tts.apply_real_durations(script, vo, tail_pad=0.9 if target <= 120 else 1.4)
    info = assemble.build(script, _job_combo(job), vo, p["project"])
    job.set(status="preview", progress=f"总时长 {info['total']:.0f} 秒", total_sec=info["total"],
            voice_engines=eng_txt)
    start_player(job)
    try:
        start_studio(job)
    except Exception as e:
        # Studio 启动失败不阻塞构建与预览(播放器已可用)
        job.set(progress=f"总时长 {info['total']:.0f} 秒(Studio 启动失败,稍后可重试)", total_sec=info["total"],
                voice_engines=eng_txt, studio_error=str(e)[:80])
        return
    # 构建后异步跑质量门(hyperframes check),结果写入任务状态,不阻塞预览
    threading.Thread(target=_run_check, args=(job,), daemon=True).start()


def _hf_env():
    env = dict(os.environ)
    env["PATH"] = NODE_BIN_DIR + os.pathsep + env.get("PATH", "")
    return env


def _run_check(job):
    """构建后异步质量门:hyperframes check,结果写入 job.state['check']。"""
    env = dict(os.environ)
    env["PATH"] = NODE_BIN_DIR + os.pathsep + env.get("PATH", "")
    try:
        r = subprocess.run(["hyperframes", "check", str(job.paths()["project"])],
                           capture_output=True, text=True, timeout=900, env=env)
        out = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"(\d+) error\(s\), (\d+) warning\(s\), (\d+) info\(s\)", out)
        summary = f"{m.group(1)}错误 {m.group(2)}警告 {m.group(3)}提示" if m else "完成"
        job.set(check=f"hyperframes check: {summary}(exit {r.returncode})")
    except Exception as e:
        job.set(check=f"check 失败: {e}")


RENDER_FORMATS = {"mp4", "mkv", "mov", "webm"}


def stage_render(job, fmt: str = "mp4"):
    job.set(status="rendering", progress=f"HyperFrames 渲染中({fmt},约 5-20 分钟)")
    p = job.paths()
    out = p["project"] / "renders" / f"out.{fmt}"
    # 渲染期间保留播放器,预览不中断(渲染只读项目文件,不冲突)
    r = subprocess.run(
        ["hyperframes", "render", str(p["project"]),
         "--output", str(out), "--format", fmt, "--quality", "high"],
        capture_output=True, text=True, timeout=3600, env=_hf_env(),
    )
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "")[-1500:]
        raise RuntimeError(f"渲染失败:{tail}")
    if not out.exists() or out.stat().st_size < 10000:
        raise RuntimeError("渲染产物缺失或过小")
    job.set(status="rendered", progress="", render_format=fmt)


# ───────────────────────── 播放器(hyperframes play) ─────────────────────────


def _slot_for(job_id: str) -> int:
    used = {v for k, v in SLOT_USED.items() if k in PLAYERS and PLAYERS[k].poll() is None}
    for n in range(PLAYER_SLOTS):
        port = PLAYER_SLOT_BASE + n
        if port not in used:
            SLOT_USED[job_id] = port
            return port
    # 槽满:回收最旧的
    oldest = next(iter(PLAYERS), None)
    if oldest:
        stop_player(get_job(oldest))
    SLOT_USED[job_id] = PLAYER_SLOT_BASE
    return PLAYER_SLOT_BASE


def start_player(job):
    port = _slot_for(job.id)
    proc = subprocess.Popen(
        ["hyperframes", "play", str(job.paths()["project"]), "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=_hf_env(),
    )
    PLAYERS[job.id] = proc
    return port


def stop_player(job):
    if job and job.id in PLAYERS:
        proc = PLAYERS.pop(job.id)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        SLOT_USED.pop(job.id, None)


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
    oldest = next(iter(STUDIOS), None)
    if oldest:
        stop_studio(get_job(oldest))
    STUDIO_SLOT_USED[job_id] = STUDIO_SLOT_BASE
    return STUDIO_SLOT_BASE


def start_studio(job):
    """启动 HyperFrames Studio(preview --background 是 CLI 托管会话,命令返回后服务仍在)。

    以端口可达性判定存活,不再跟踪包装进程。
    启动前先 --stop 清理可能残留的托管会话(否则 CLI 会「复用」死会话而不监听新端口)。
    """
    proj = str(job.paths()["project"])
    log = open(f"/mnt/workspace/ttv/studio-{job.id}.log", "a")
    try:
        subprocess.run(["hyperframes", "preview", proj, "--stop"],
                       stdout=log, stderr=log, env=_hf_env(), timeout=60)
    except Exception:
        pass
    import time as _t
    for retry in range(2):
        port = _studio_slot(job.id)
        log.write(f"[{_t.time()}] starting studio for {job.id} on {port}\n")
        log.flush()
        try:
            subprocess.run(
                ["hyperframes", "preview", "--background", "--port", str(port)],
                cwd=proj,
                stdout=log, stderr=log, env=_hf_env(),
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            log.write("preview 命令超时\n")
        # 等待端口就绪(冷启动含大页面解析,最多 90s)
        for _ in range(90):
            if not _port_free(port):
                STUDIOS[job.id] = port
                log.write(f"studio ready on {port}\n")
                log.close()
                return port
            _t.sleep(1.0)
        log.write(f"端口 {port} 未就绪,重试下一端口\n")
    log.close()
    raise RuntimeError("Studio 启动超时(两个端口均未就绪)")


def _start_studio_bg(job):
    try:
        start_studio(job)
    except Exception:
        pass
    finally:
        _studio_starting.discard(job.id)


def stop_studio(job):
    if job and job.id in STUDIOS:
        STUDIOS.pop(job.id, None)
        STUDIO_SLOT_USED.pop(job.id, None)
        try:
            subprocess.run(["hyperframes", "preview", str(job.paths()["project"]), "--stop"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           env=_hf_env(), timeout=60)
        except Exception:
            pass


# ───────────────────────── API ─────────────────────────


@app.get("/health")
@app.get("/api/health")
def health():
    return {"ok": True, "players": len(PLAYERS)}


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
    }


@app.post("/api/jobs")
async def api_create(file: UploadFile = File(None), style: str = Form(None),
                     duration: int = Form(120), text: str = Form(""),
                     font: str = Form(None), palette: str = Form(None),
                     bg: str = Form(None), motion: str = Form(None),
                     voice_engine: str = Form("cosyvoice3"), voice: str = Form(None)):
    if voice_engine not in ("cosyvoice3", "qwen3tts", "doubao"):
        raise HTTPException(400, f"未知配音引擎:{voice_engine}")
    combo = styles.resolve_combo(style, font, palette, bg, motion)
    duration = max(30, min(600, duration))
    text = (text or "").strip()
    if file is not None and file.filename:
        filename = Path(file.filename or "article.txt").name  # 防路径穿越
        if not filename.lower().endswith((".txt", ".md", ".markdown", ".docx")):
            raise HTTPException(400, "仅支持 txt / md / docx")
        data = await file.read()
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(400, "文件超过 20MB")
        job = create_job(style or "", duration, filename)
        job.state["combo"] = combo
        job.state["voice_engine"] = voice_engine
        job.state["voice"] = voice or ""
        ext = "." + filename.lower().rsplit(".", 1)[-1]
        (job.dir / ("input" + ext)).write_bytes(data)
    elif len(text) >= 50:
        if len(text) > 200000:
            raise HTTPException(400, "文本超过 20 万字上限")
        job = create_job(style or "", duration, "粘贴文本.txt")
        job.state["combo"] = combo
        job.state["voice_engine"] = voice_engine
        job.state["voice"] = voice or ""
        job.dir.joinpath("input.txt").write_text(text, encoding="utf-8")
    else:
        raise HTTPException(400, "请上传文件或粘贴不少于 50 字的文本")
    run_in_background(job, stage_analyze)
    return job.to_dict()


@app.post("/api/jobs/{job_id}/analyze")
def api_reanalyze(job_id: str):
    """重新分析(提示词升级后可用)。"""
    job = get_job(job_id) or _http404()
    job.set(status="analyzing", progress="重新分析中", error=None)
    run_in_background(job, stage_analyze)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/script")
async def api_edit_script(job_id: str, request: Request):
    """用户直接编辑分析结果/逐帧脚本后保存(校验通过方可构建)。"""
    job = get_job(job_id) or _http404()
    body = await request.json()
    script = body.get("script") if isinstance(body, dict) and "script" in body else body
    article = job.paths()["input"].read_text(encoding="utf-8")
    errs = analyze.validate_script(script, article, int(job.state.get("duration_sec", 120)))
    if errs:
        raise HTTPException(400, "校验失败:" + "; ".join(errs[:6]))
    job.paths()["script"].write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    job.set(status="analyzed", progress="脚本已按编辑保存,可重新构建", error=None)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/revise")
async def api_revise(job_id: str, request: Request):
    """用户用一句话描述修改要求,AI 吸纳建议修订脚本。"""
    job = get_job(job_id) or _http404()
    body = await request.json()
    instruction = (body or {}).get("instruction", "").strip()
    if len(instruction) < 5:
        raise HTTPException(400, "请描述修改要求(不少于 5 字)")
    job.set(status="analyzing", progress="AI 按建议修改脚本中", error=None)
    run_in_background(job, stage_revise, instruction)
    return {"ok": True}


def stage_revise(job, instruction: str):
    script = json.loads(job.paths()["script"].read_text(encoding="utf-8"))
    article = job.paths()["input"].read_text(encoding="utf-8")
    revised = analyze.revise_script(script, article, instruction)
    job.paths()["script"].write_text(json.dumps(revised, ensure_ascii=False, indent=1), encoding="utf-8")
    job.set(status="analyzed", progress=f"已按建议修改:{instruction[:30]}", error=None)


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    d = job.to_dict()
    if job.status == "preview":
        # 自愈:播放器进程若已死亡则自动重建
        proc = PLAYERS.get(job.id)
        if proc is None or proc.poll() is not None:
            try:
                start_player(job)
            except Exception:
                pass
        d["player_port"] = SLOT_USED.get(job.id)
        sp = STUDIOS.get(job.id)
        if sp is None or _port_free(sp):
            if job.id not in _studio_starting:
                _studio_starting.add(job.id)
                threading.Thread(target=_start_studio_bg, args=(job,), daemon=True).start()
        d["studio_port"] = STUDIOS.get(job.id)
    return d


@app.post("/api/jobs/{job_id}/build")
def api_build(job_id: str):
    job = get_job(job_id) or _http404()
    if job.status not in ("analyzed", "preview", "rendered", "failed"):
        raise HTTPException(409, f"当前状态 {job.status} 不能构建")
    stop_player(job)
    job.set(status="building", progress="", error=None)
    run_in_background(job, stage_build)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/render")
async def api_render(job_id: str, request: Request):
    job = get_job(job_id) or _http404()
    if job.status not in ("preview", "rendered", "failed"):
        raise HTTPException(409, f"当前状态 {job.status} 不能渲染")
    fmt = "mp4"
    try:
        body = await request.json()
        fmt = (body or {}).get("format", "mp4")
    except Exception:
        pass
    if fmt not in RENDER_FORMATS:
        raise HTTPException(400, f"不支持的格式 {fmt},可选:{sorted(RENDER_FORMATS)}")
    run_in_background(job, stage_render, fmt)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/video")
def api_video(job_id: str):
    job = get_job(job_id) or _http404()
    fmt = job.state.get("render_format", "mp4")
    out = job.paths()["project"] / "renders" / f"out.{fmt}"
    if not out.exists():
        # 兼容旧产物名
        out = job.paths()["render"]
    if not out.exists():
        raise HTTPException(404, "视频尚未渲染")
    return FileResponse(out, media_type=f"video/{fmt}",
                        filename=f"{job.id}.{fmt}")


@app.get("/api/player/{job_id}/{path:path}")
async def api_player(job_id: str, path: str, request: Request):
    """反向代理到该任务的 hyperframes play 服务器。

    play 页面与 player.js 使用绝对路径(/composition/、/player.js),经本代理
    下发时改写为 /ttv/api/player/<job_id>/ 前缀,保证 iframe 内资源正确解析。
    """
    if ".." in path:
        raise HTTPException(400, "非法路径")
    if job_id not in PLAYERS or PLAYERS[job_id].poll() is not None:
        return Response(
            content=_player_msg("预览服务未启动", "等待构建完成或稍后刷新,服务会自动恢复。"),
            status_code=404, media_type="text/html")
    port = SLOT_USED[job_id]
    query = f"?{request.url.query}" if request.url.query else ""
    target = f"http://127.0.0.1:{port}/{path}{query}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(target, follow_redirects=True)
    except Exception:
        # 播放器进程在启动/重启间隙,给用户友好提示页而非 500
        return Response(
            content=_player_msg("预览服务启动中", "页面会自动重试,请稍候。"),
            status_code=503, media_type="text/html")
    ctype = r.headers.get("content-type", "application/octet-stream")
    content = r.content
    # 只重写 HTML(play 页面里 <hyperframes-player src="/composition/..."> 与
    # <script src="/player.js"> 的绝对路径);player.js 本身无绝对路径引用,原样透传,
    # 避免改写破坏其中的 SVG 字符串字面量。
    if "text/html" in ctype:
        text = content.decode("utf-8", errors="ignore")
        text = text.replace('src="/', f'src="/ttv/api/player/{job_id}/')
        # 去掉播放器默认静音,否则用户听不到解说音频
        text = text.replace(" controls muted>", " controls>")
        text = text.replace(" muted controls>", " controls>")
        text = text.replace(" controls muted ", " controls ")
        content = text.encode("utf-8")
    ctype = _fix_mime(path, ctype)
    return Response(content=content, status_code=r.status_code,
                    headers={"Content-Type": ctype})


def _job_from_pid(pid: str):
    """Studio 项目 id = 'ttv' + job_id → 反查任务。"""
    if pid.startswith("ttv") and len(pid) > 3:
        job = get_job(pid[3:])
        if job:
            return job
    return None


@app.get("/api/runtime.js")
def api_runtime_js():
    """HyperFrames 运行时脚本(Studio 预览 iframe 加载,所有任务通用)。"""
    from pathlib import Path as _P
    p = _P("/mnt/workspace/node/lib/node_modules/hyperframes/dist/hyperframe-runtime.js")
    if not p.exists():
        raise HTTPException(404, "runtime.js 不存在")
    return Response(content=p.read_bytes(), media_type="application/javascript")


@app.get("/api/projects")
def api_projects_list():
    """Studio 项目列表:合成所有处于 preview 状态的任务(Studio 服务器内部 id 恒为 ttv)。"""
    items = []
    for job in JOBS.values():
        if job.status == "preview":
            items.append({
                "id": "ttv" + job.id,
                "dir": str(job.paths()["project"]),
                "title": job.state.get("filename", "") or "ttv" + job.id,
            })
    return {"projects": items}


@app.api_route("/api/projects/{pid}/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def api_projects_passthrough(pid: str, rest: str, request: Request):
    """Studio 前端以源根路径调用 /api/projects/...,转发到对应任务的 Studio 服务器。"""
    job = _job_from_pid(pid)
    if not job:
        raise HTTPException(404, "项目不存在")
    port = STUDIOS.get(job.id)
    if port is None or _port_free(port):
        if job.status == "preview" and job.id not in _studio_starting:
            _studio_starting.add(job.id)
            threading.Thread(target=_start_studio_bg, args=(job,), daemon=True).start()
        raise HTTPException(503, "Studio 启动中")
    # Studio 服务器内部项目 id 恒为 "ttv"(与 composition id 无关),转发时改写回
    target = f"http://127.0.0.1:{port}/api/projects/ttv/{rest}"
    if request.url.query:
        target += "?" + request.url.query
    body = await request.body()
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.request(request.method, target, content=body,
                                 headers={"Content-Type": request.headers.get("content-type", "application/json")})
    ctype = r.headers.get("content-type", "application/octet-stream")
    content = r.content
    if "javascript" in ctype or "text/html" in ctype or "json" in ctype:
        text = content.decode("utf-8", errors="ignore")
        # Studio 服务器内部项目 id 恒为 ttv:把响应里的引用改写为带任务 id 的形式
        text = text.replace("/api/projects/ttv/", f"/api/projects/ttv{job.id}/")
        text = text.replace('"/assets/', f'"/ttv/api/studio/{job.id}/assets/')
        text = text.replace("'/assets/", f"'/ttv/api/studio/{job.id}/assets/")
        content = text.encode("utf-8")
    return Response(content=content, status_code=r.status_code,
                    headers={"Content-Type": _fix_mime(rest, ctype)})


@app.get("/api/studio/{job_id}/{path:path}")
async def api_studio(job_id: str, path: str, request: Request):
    """反向代理到该任务的 HyperFrames Studio(preview 完整编辑器)。

    Studio 页面与静态资源使用绝对路径(/assets/、/favicon.svg、/api/),
    经本代理下发时改写为 /ttv/api/studio/<job_id>/ 前缀。
    """
    if ".." in path:
        raise HTTPException(400, "非法路径")
    if job_id not in STUDIOS or _port_free(STUDIOS[job_id]):
        job = get_job(job_id)
        if job and job.status == "preview" and job_id not in _studio_starting:
            _studio_starting.add(job_id)
            # 后台拉起(不能阻塞事件循环,否则全站 502)
            threading.Thread(target=_start_studio_bg, args=(job,), daemon=True).start()
        return Response(
            content=_player_msg("Studio 启动中", "页面会自动重试,请稍候。"),
            status_code=503, media_type="text/html")
    return await _studio_proxy(job_id, path, request, STUDIO_SLOT_USED[job_id])


async def _studio_proxy(job_id: str, path: str, request: Request, port: int):
    query = f"?{request.url.query}" if request.url.query else ""
    target = f"http://127.0.0.1:{port}/{path}{query}"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.get(target, follow_redirects=True)
    except Exception:
        return Response(
            content=_player_msg("Studio 启动中", "页面会自动重试,请稍候。"),
            status_code=503, media_type="text/html")
    ctype = r.headers.get("content-type", "application/octet-stream")
    content = r.content
    prefix = f"/ttv/api/studio/{job_id}/"
    if "text/html" in ctype:
        text = content.decode("utf-8", errors="ignore")
        text = text.replace('src="/', f'src="{prefix}')
        text = text.replace('href="/', f'href="{prefix}')
        content = text.encode("utf-8")
    elif "javascript" in ctype:
        # JS 内窄化重写(仅 /assets/ 与 /api/ 前缀,避免破坏字符串字面量)
        text = content.decode("utf-8", errors="ignore")
        text = text.replace('"/assets/', f'"{prefix}assets/')
        text = text.replace("'/assets/", f"'{prefix}assets/")
        text = text.replace('"/api/', f'"{prefix}api/')
        text = text.replace("'/api/", f"'{prefix}api/")
        content = text.encode("utf-8")
    ctype = _fix_mime(path, ctype)
    return Response(content=content, status_code=r.status_code,
                    headers={"Content-Type": ctype})


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


def _player_msg(title: str, note: str) -> str:
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"/>
<meta http-equiv="refresh" content="8"/><title>{title}</title></head>
<body style="margin:0;display:flex;align-items:center;justify-content:center;height:100vh;
background:#101820;color:#8CA0B3;font-family:'PingFang SC','Microsoft YaHei',sans-serif;">
<div style="text-align:center;"><div style="font-size:15px;color:#fff;margin-bottom:8px;">{title}</div>
<div style="font-size:12.5px;">{note}</div></div></body></html>"""


def _http404():
    raise HTTPException(404, "任务不存在")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=BACKEND_PORT, log_level="info")
