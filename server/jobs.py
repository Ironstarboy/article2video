# -*- coding: utf-8 -*-
"""任务状态机:uploaded → analyzing → analyzed → building → preview → rendering → rendered / failed。

每个任务一个目录 jobs/<job_id>/,状态落盘 state.json,后台线程执行各阶段。
"""
import json
import threading
import time
import uuid
from pathlib import Path

from config import JOBS_DIR

LOCK = threading.Lock()
JOBS: dict[str, "Job"] = {}


class Job:
    def __init__(self, job_id: str, style: str, duration: int, filename: str):
        self.id = job_id
        self.dir = JOBS_DIR / job_id
        self.state_path = self.dir / "state.json"
        self.state = {
            "job_id": job_id,
            "status": "uploaded",
            "style": style,
            "duration_sec": duration,
            "filename": filename,
            "error": None,
            "progress": "",
            "created_at": time.time(),
        }

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
            "render": self.dir / "project" / "renders" / "out.mp4",
            "vo": self.dir / "project" / "assets" / "audio",
        }

    def to_dict(self):
        with LOCK:
            d = dict(self.state)
        p = self.paths()
        d["has_video"] = p["render"].exists()
        if p["script"].exists():
            try:
                d["script"] = json.loads(p["script"].read_text(encoding="utf-8"))
            except Exception:
                d["script"] = None
        else:
            d["script"] = None
        return d


def create_job(style: str, duration: int, filename: str) -> Job:
    job = Job(uuid.uuid4().hex[:12], style, duration, filename)
    job.dir.mkdir(parents=True, exist_ok=True)
    job._save()
    with LOCK:
        JOBS[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return JOBS.get(job_id)


def run_in_background(job: Job, fn, *args):
    def runner():
        try:
            fn(job, *args)
        except Exception as e:  # noqa: BLE001
            job.set(status="failed", error=str(e), progress="")
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t


def load_from_disk():
    """服务重启后从磁盘恢复所有任务(处理中任务标为 failed 需重试)。"""
    if not JOBS_DIR.exists():
        return
    for state_file in JOBS_DIR.glob("*/state.json"):
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            job_id = data["job_id"]
            job = Job(job_id, data.get("style", "solemn-red"),
                      int(data.get("duration_sec", 120)), data.get("filename", ""))
            job.state = data
            # 重启时处于进行中的任务,无法恢复线程 → 置为 failed,允许重新触发
            if data.get("status") in ("analyzing", "building", "rendering"):
                job.state["status"] = "failed"
                job.state["error"] = "服务重启中断,请重新触发该步骤"
                job.state["progress"] = ""
            with LOCK:
                JOBS[job.id] = job
        except Exception:
            continue


load_from_disk()
