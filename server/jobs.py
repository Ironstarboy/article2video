# -*- coding: utf-8 -*-
"""任务状态机:uploaded → analyzing → analyzed → building → preview → rendering → rendered / failed。

每个任务一个目录 jobs/<job_id>/,状态落盘 state.json,后台线程执行各阶段。
"""
import json
import logging
import shutil
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

    def script(self):
        """已解析的 script.json(mtime 缓存);文件不存在时为 None。"""
        return self._load_script_cached()

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

    # ── 成片产物 ──
    # 三个产物:ppt(纯 PPT 渲染,不被叠加覆盖)、final(叠加了数字人的最终版)、
    # avatar(数字人播报视频,独立于 HyperFrames 的拼接产物)。
    # 路径显式记进 state,不再靠 render_format 反推文件名 —— 反推在双产物下会静默给错版本。
    ARTIFACTS = ("ppt", "final", "avatar")

    def artifact_path(self, key: str) -> Path | None:
        """产物路径(相对任务目录解析,文件不存在时返回 None)。"""
        return self._artifact_path(key)

    def _artifact_path(self, key: str) -> Path | None:
        """按 state.artifacts 记录解析产物路径(校验存在;相对路径以任务目录为基准)。"""
        rec = (self.state.get("artifacts") or {}).get(key)
        if not isinstance(rec, dict) or not rec.get("path"):
            return None
        p = Path(rec["path"])
        if not p.is_absolute():
            p = self.dir / p
        return p if p.exists() else None

    def _record_artifact(self, key: str, path: Path) -> None:
        """写 state.artifacts 记录(path 存相对任务目录的 POSIX 路径,任务目录可迁移)。"""
        try:
            rel = path.relative_to(self.dir).as_posix()
        except ValueError:
            rel = path.as_posix()
        try:
            st = path.stat()
        except OSError:
            return
        with LOCK:
            arts = dict(self.state.get("artifacts") or {})
            arts[key] = {"path": rel, "bytes": st.st_size, "at": st.st_mtime,
                         "fmt": path.suffix.lstrip(".")}
            self.state["artifacts"] = arts
            self._save()

    def _migrate_legacy_render(self) -> bool:
        """旧任务/中断渲染的产物补录(只在 load_from_disk() 调用,GET 路径不写盘)。

        ① 产物文件已在但 state 里没记录 —— v2.2 之前的渲染不写 artifacts,
           或渲染写完产物后进程被杀;此时**只补记录**,不动文件。
        ② 更老的任务:唯一的 out.<fmt> 就地变成 final + ppt。
           没有 `it is the composited one` 的信息可用,所以不伪造纯 PPT 版 ——
           两个产物暂时内容一致,并由 state.artifacts_migrated 标记出来。
        """
        if self._artifact_path("final") is not None:
            return False
        if self._backfill_artifacts():
            return True
        if self.state.get("artifacts_migrated"):
            return False
        fmt = self.state.get("render_format") or "mp4"
        legacy = self.paths()["renders"] / f"out.{fmt}"
        if not legacy.exists():
            legacy = self.paths()["render"]          # 兼容硬编码的 out.mp4
        if not legacy.exists():
            return False
        final = self.paths()["renders"] / f"final.{fmt}"
        ppt = self.paths()["renders"] / f"ppt.{fmt}"
        try:
            if not final.exists():
                shutil.copy2(legacy, final)          # 它就是叠加后的最终版
            if not ppt.exists():
                shutil.copy2(legacy, ppt)
            legacy.unlink(missing_ok=True)
        except OSError as e:
            log.warning("任务 %s 旧成片迁移失败,保留原文件: %s", self.id, e)
            return False
        self._record_artifact("final", final)
        self._record_artifact("ppt", ppt)
        with LOCK:
            self.state["artifacts_migrated"] = True
            self._save()
        log.info("任务 %s 旧成片已迁移为 final + ppt", self.id)
        return True

    def _backfill_artifacts(self) -> bool:
        """final/ppt 文件已在磁盘但 state.artifacts 没记录时补记录(不动文件)。"""
        fmt = self.state.get("render_format") or "mp4"
        renders = self.paths()["renders"]
        found = []
        for key in ("final", "ppt"):
            p = renders / f"{key}.{fmt}"
            try:
                if p.exists() and p.stat().st_size > 10000:
                    found.append((key, p))
            except OSError:
                continue
        if not found:
            return False
        for key, p in found:
            self._record_artifact(key, p)
        log.info("任务 %s 产物补录:%s", self.id, ", ".join(k for k, _ in found))
        return True

    def video_path(self) -> Path | None:
        """最终版路径(**纯只读**,GET 轮询会高频调用它)。

        顺序:显式产物记录 → final.<fmt> → ppt.<fmt>(未开数字人时最终版就是纯 PPT 版)
              → 旧任务的 out.<fmt> / out.mp4(迁移只发生在启动时,见 _migrate_legacy_render)
        """
        explicit = self._artifact_path("final")
        if explicit is not None:
            return explicit
        return self._legacy_video_path()

    def _legacy_video_path(self) -> Path | None:
        """未记录 artifacts 时的文件名兜底(纯只读)。"""
        fmt = self.state.get("render_format") or "mp4"
        renders = self.paths()["renders"]
        for cand in (renders / f"final.{fmt}", renders / f"ppt.{fmt}",
                     renders / f"out.{fmt}", self.paths()["render"]):
            if cand.exists():
                return cand
        return None

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
        # 各产物各自的格式与大小,供前端并列下载入口(见前端方案 4.4)
        arts = {}
        for key in self.ARTIFACTS:
            p = self._artifact_path(key)
            if p is None:
                continue
            try:
                arts[key] = {"fmt": p.suffix.lstrip("."), "bytes": p.stat().st_size,
                             "at": p.stat().st_mtime}
            except OSError:
                continue
        d["artifacts"] = arts
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
            # 任务已删除(注册表移除)则不再写状态——避免 _save 重建目录复活
            if JOBS.get(job.id) is job:
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
            # avatar_building 是"仅重跑数字人片段"的进行中状态,同样无法恢复
            if data.get("status") in ("uploaded", "analyzing", "building",
                                      "avatar_building", "rendering"):
                job.state["status"] = "failed"
                job.state["error"] = "服务重启中断,请重新触发该步骤"
                job.state["progress"] = ""
            with LOCK:
                JOBS[job.id] = job
            # 旧任务的两个产物迁移(写操作,只在这里做,不在 GET 路径里)
            try:
                job._migrate_legacy_render()
            except Exception:  # noqa: BLE001 - 迁移失败不影响任务加载
                log.exception("任务 %s 旧产物迁移异常", job.id)
        except Exception:
            continue


load_from_disk()
