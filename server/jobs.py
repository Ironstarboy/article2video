# -*- coding: utf-8 -*-
"""任务状态机:uploaded → analyzing → analyzed → building → preview → rendering → rendered / failed。

每个任务一个目录 jobs/<job_id>/,状态落盘 state.json,后台线程执行各阶段。
"""
import json
import logging
import threading
import time
import uuid
from pathlib import Path

from config import JOBS_DIR

log = logging.getLogger("ttv.jobs")

LOCK = threading.Lock()
JOBS: dict[str, "Job"] = {}


class Job:
    def __init__(self, job_id: str, style: str, duration: int, filename: str,
                 kind: str = "promo"):
        self.id = job_id
        self.dir = JOBS_DIR / job_id
        self.state_path = self.dir / "state.json"
        self.state = {
            "job_id": job_id,
            "status": "uploaded",
            "style": style,
            "duration_sec": duration,
            "filename": filename,
            "video_kind": kind,   # promo(宣传)/lecture(讲解)
            "error": None,
            "progress": "",
            "created_at": time.time(),
        }
        # script.json 解析缓存:(mtime_ns, size) → 解析结果(轮询高频,避免每轮全量解析)
        self._script_cache = None

    @property
    def status(self):
        return self.state["status"]

    def set(self, **kw):
        with LOCK:
            self.state.update(kw)
            self._save()

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=1), encoding="utf-8")

    def paths(self):
        return {
            "input": self.dir / "input.txt",
            "script": self.dir / "script.json",
            "project": self.dir / "project",
            "render": self.dir / "project" / "renders" / "out.mp4",   # 兼容旧产物名
            "renders": self.dir / "project" / "renders",
            "vo": self.dir / "project" / "assets" / "audio",
        }

    def _load_script_cached(self):
        p = self.paths()["script"]
        try:
            st = p.stat()
        except OSError:
            return None
        key = (st.st_mtime_ns, st.st_size)
        if self._script_cache is None or self._script_cache[0] != key:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                data = None
            self._script_cache = (key, data)
        return self._script_cache[1]

    def video_path(self) -> Path | None:
        """按 state.render_format 定位成片(兼容旧产物名 out.mp4)。"""
        fmt = self.state.get("render_format", "mp4")
        out = self.paths()["renders"] / f"out.{fmt}"
        if not out.exists():
            out = self.paths()["render"]
        return out if out.exists() else None

    def to_dict(self, brief: bool = False):
        with LOCK:
            d = dict(self.state)
        vp = self.video_path()
        d["has_video"] = vp is not None
        if vp is not None:
            try:
                d["video_size"] = vp.stat().st_size
            except OSError:
                pass
        sp = self.paths()["script"]
        try:
            # 脚本变更时间戳:前端轻量轮询凭此决定是否拉取全量脚本
            d["script_updated_at"] = sp.stat().st_mtime_ns
        except OSError:
            pass
        if not brief:
            d["script"] = self._load_script_cached()
        return d


def create_job(style: str, duration: int, filename: str, kind: str = "promo") -> Job:
    job = Job(uuid.uuid4().hex[:12], style, duration, filename, kind)
    job.dir.mkdir(parents=True, exist_ok=True)
    job._save()
    with LOCK:
        JOBS[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return JOBS.get(job_id)


def remove_job(job: Job):
    """从内存注册表移除任务(目录清理由调用方负责)。"""
    with LOCK:
        JOBS.pop(job.id, None)


def run_in_background(job: Job, fn, *args):
    def runner():
        try:
            fn(job, *args)
        except Exception as e:  # noqa: BLE001
            log.exception("job %s 阶段失败: %s", job.id, e)
            job.set(status="failed", error=str(e), progress="")
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t


def load_from_disk():
    """服务重启后从磁盘恢复所有任务(进行中/未开始任务标为 failed 需重试)。"""
    if not JOBS_DIR.exists():
        return
    for state_file in JOBS_DIR.glob("*/state.json"):
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            job_id = data["job_id"]
            job = Job(job_id, data.get("style", "solemn-red"),
                      int(data.get("duration_sec", 120)), data.get("filename", ""),
                      data.get("video_kind", "promo"))
            job.state = data
            # 重启时无法恢复后台线程 → 置为 failed,允许重新触发
            # (uploaded 同样失效:其分析线程已随进程消失,永远到不了 analyzing)
            if data.get("status") in ("uploaded", "analyzing", "building", "rendering"):
                job.state["status"] = "failed"
                job.state["error"] = "服务重启中断,请重新触发该步骤"
                job.state["progress"] = ""
            with LOCK:
                JOBS[job.id] = job
        except Exception:
            continue


load_from_disk()
