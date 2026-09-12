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

# ── 项目历史 ──
# 流水线每一步**完成后**都往 state.history 追加一条,项目列表与项目详情页据此
# 展示「这一步的结果在不在、什么时候出的」并直达对应结果(见 api_jobs_list)。
# 纯记录,不参与任何流水线判断;因此历史写失败也不该影响出片,调用方一律不关心返回。
HISTORY_MAX = 60
HISTORY_LABELS = {
    "analyze": "分析脚本",
    "build": "构建预览",
    "render": "渲染成片",
    "broadcast": "播报视频",
    "revise": "AI 修订",
}
# 项目列表上的四步就是上面除 revise 外的四个键;revise 只在详情页的完整历史里出现。
TITLE_MAX = 60


def _one_line(raw) -> str:
    """压成单行(标题来自脚本时可能带换行)。"""
    return " ".join(str(raw or "").split())


def normalize_title(raw) -> str:
    """项目标题规范化:去首尾空白、压掉换行与连续空白、限长;空标题抛 ValueError。

    单点实现(接口层与自动标题共用),标题只影响展示,任何坏值都不该落进 state。
    """
    title = _one_line(raw)
    if not title:
        raise ValueError("项目标题不能为空")
    return title[:TITLE_MAX]


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
            "updated_at": time.time(),
            # 项目标题:title_source 为 user 时(用户手动改过)自动总结绝不覆盖
            "title": "",
            "title_source": "",
            # 每一步完成/失败的历史(见模块顶部说明)
            "history": [],
        }
        # script.json 解析缓存:(mtime_ns, size) → 解析结果(轮询高频,避免每轮全量解析)
        self._script_cache = None

    @property
    def status(self):
        return self.state["status"]

    def set(self, **kw):
        with LOCK:
            self.state.update(kw)
            self.state["updated_at"] = time.time()
            self._save()

    def record_history(self, step: str, status: str = "done", detail: str = "", **extra):
        """追加一条阶段历史(分析/构建/渲染/播报完成或失败)。

        多个步骤各记各的,同一阶段重复执行(重新构建、再次渲染)会各留一条 ——
        这是"历史",不是"当前状态";当前状态仍以 status/artifacts 为准。
        """
        with LOCK:
            hist = list(self.state.get("history") or [])
            entry = {"step": step, "label": HISTORY_LABELS.get(step, step),
                     "status": status, "detail": detail, "at": time.time()}
            entry.update(extra)
            hist.append(entry)
            del hist[:-HISTORY_MAX]
            self.state["history"] = hist
            self.state["updated_at"] = time.time()
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
            self.state["updated_at"] = time.time()
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

    def _backfill_meta(self) -> bool:
        """旧任务补上项目标题与阶段历史(只在 load_from_disk 调用,写盘一次)。

        标题从脚本标题(大模型产出的那版)或原文件名派生;历史按磁盘上已有的
        脚本/工程/产物时间戳倒推一条 —— 让 v2.5 之前建的 7 个任务一进列表就有
        「哪一步出了什么」可点,而不是空白。
        """
        changed = False
        # 标题一律单行(脚本标题常带换行;存进 state 的也压一遍)
        cur = self.state.get("title")
        if cur and _one_line(cur) != cur:
            with LOCK:
                self.state["title"] = _one_line(cur)[:TITLE_MAX]
                changed = True
        if not (self.state.get("title") or "").strip() \
                and self.state.get("title_source") != "user":
            s = self.script() or {}
            title = _one_line(s.get("title"))
            src = "auto"
            if not title:
                stem = Path(_one_line(self.state.get("filename"))).stem
                title = stem if stem.lower() not in ("input", "article") else ""
                src = "file"
            if title:
                with LOCK:
                    self.state["title"] = title[:TITLE_MAX]
                    self.state["title_source"] = src
                    changed = True
        if not self.state.get("history"):
            hist = self._derive_history()
            if hist:
                with LOCK:
                    self.state["history"] = hist
                    changed = True
        # updated_at 不早于任何一条历史/产物时间:老任务只有 created_at,
        # 列表会按"建任务的时间"排序,把刚重新渲染过的老项目排到后面去。
        latest = max(self.state.get("updated_at") or 0,
                     self.state.get("created_at") or 0)
        for h in self.history():
            latest = max(latest, h.get("at") or 0)
        for rec in (self.state.get("artifacts") or {}).values():
            if isinstance(rec, dict):
                latest = max(latest, rec.get("at") or 0)
        if latest > (self.state.get("updated_at") or 0):
            with LOCK:
                self.state["updated_at"] = latest
                changed = True
        if changed:
            with LOCK:
                self._save()
        return changed

    def _derive_history(self) -> list:
        """按磁盘现状倒推阶段历史(只读;给没有 history 的老任务用)。"""
        hist = []

        def add(step, at, detail, **extra):
            e = {"step": step, "label": HISTORY_LABELS.get(step, step),
                 "status": "done", "detail": detail, "at": at, "derived": True}
            e.update(extra)
            hist.append(e)

        sp = self.paths()["script"]
        if sp.exists():
            n = len((self.script() or {}).get("frames") or [])
            add("analyze", sp.stat().st_mtime, f"{n} 帧脚本" if n else "脚本已生成")
        proj = self.paths()["project"] / "index.html"
        if proj.exists():
            total = self.state.get("total_sec")
            add("build", proj.stat().st_mtime,
                f"总时长 {float(total):.0f} 秒" if total else "预览工程已生成")
        for key in ("final", "ppt"):
            p = self._artifact_path(key)
            if p is None:
                continue
            try:
                add("render", p.stat().st_mtime,
                    f"{key}.{p.suffix.lstrip('.')} · {p.stat().st_size / 1048576:.1f} MB",
                    artifact=key, bytes=p.stat().st_size)
            except OSError:
                pass
            break   # final 与 ppt 是同一部成片的两个版本,只记一条
        p = self._artifact_path("avatar")
        if p is not None:
            try:
                add("broadcast", p.stat().st_mtime,
                    f"avatar.{p.suffix.lstrip('.')} · {p.stat().st_size / 1048576:.1f} MB",
                    artifact="avatar", bytes=p.stat().st_size)
            except OSError:
                pass
        hist.sort(key=lambda h: h["at"])
        return hist

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

    def display_title(self) -> str:
        """项目标题(展示用,纯只读):用户/自动标题 → 脚本标题 → 原文件名 → job_id。

        老任务没有 state.title 时靠这条链兜底,不需要迁移;脚本标题常带换行,
        统一压成一行(列表/详情页都不该出现多行标题)。
        """
        t = _one_line(self.state.get("title"))
        if t:
            return t
        s = self.script() or {}
        t = _one_line(s.get("title"))
        if t:
            return t
        stem = Path(_one_line(self.state.get("filename"))).stem
        if stem and stem.lower() not in ("input", "article"):
            return stem
        return self.id

    def history(self) -> list:
        """阶段历史副本(界面只读展示,不给出内部引用)。"""
        with LOCK:
            return [dict(h) for h in (self.state.get("history") or []) if isinstance(h, dict)]

    def summary(self) -> dict:
        """项目列表项:只带列表要用的字段(不含 script,列表可能一次拉几十条)。"""
        d = self.to_dict(brief=True)
        keys = ("job_id", "title", "title_source", "status", "video_kind",
                "duration_sec", "created_at", "updated_at", "progress", "error",
                "filename", "has_video", "video_size", "artifacts", "history",
                "avatar", "avatar_geom", "avatar_broadcast", "total_sec",
                "render_format", "render_progress", "direct_render",
                "export_path", "script_updated_at")
        return {k: d[k] for k in keys if k in d}

    def to_dict(self, brief: bool = False):
        with LOCK:
            d = dict(self.state)
        d["title"] = self.display_title()
        d["history"] = self.history()
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


def run_in_background(job: Job, fn, *args, step: str | None = None):
    """后台跑一个阶段。step 只用于**失败时**补一条历史(界面能看到哪一步挂了)。"""
    def runner():
        try:
            fn(job, *args)
        except Exception as e:  # noqa: BLE001
            log.exception("job %s 阶段失败: %s", job.id, e)
            # 任务已删除(注册表移除)则不再写状态——避免 _save 重建目录复活
            if JOBS.get(job.id) is job:
                job.set(status="failed", error=str(e), progress="")
                if step:
                    job.record_history(step, status="failed", detail=str(e)[:160])
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
            # 老 state.json 没有这些键:补默认值,后面的排序/展示不用到处判空
            for key, val in (("updated_at", data.get("created_at")),
                             ("title", ""), ("title_source", ""),
                             ("history", []), ("artifacts", {})):
                job.state.setdefault(key, val)
            # 重启时无法恢复后台线程 → 置为 failed,允许重新触发
            # (uploaded 同样失效:其分析线程已随进程消失,永远到不了 analyzing)
            # avatar_building 是"仅重跑数字人片段"的进行中状态,同样无法恢复
            if data.get("status") in ("uploaded", "analyzing", "building",
                                      "avatar_building", "rendering"):
                job.state["status"] = "failed"
                job.state["error"] = "服务重启中断,请重新触发该步骤"
                job.state["progress"] = ""
                job.state["direct_render"] = False   # 「一键出片」的进行中标记不跨重启
            with LOCK:
                JOBS[job.id] = job
            # 旧任务的两个产物迁移(写操作,只在这里做,不在 GET 路径里)
            try:
                job._migrate_legacy_render()
            except Exception:  # noqa: BLE001 - 迁移失败不影响任务加载
                log.exception("任务 %s 旧产物迁移异常", job.id)
            # 老任务补项目标题与阶段历史(同样只在启动时写一次)
            try:
                job._backfill_meta()
            except Exception:  # noqa: BLE001 - 补录失败不影响任务加载
                log.exception("任务 %s 标题/历史补录异常", job.id)
        except Exception:
            continue


load_from_disk()
