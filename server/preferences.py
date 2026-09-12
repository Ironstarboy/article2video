# -*- coding: utf-8 -*-
"""全局偏好 —— 跨任务记住的设置(目前只有一项:新任务默认是否抠背景)。

为什么要有这个模块:抠像原来是**任务级**选项,默认关、而且不记住 —— 换完数字人
形象之后新建任务还得再去创作页勾一次「只保留人像(背景透明)」,忘了就是"背景没抠掉"
(用户真实反馈,见 CHANGELOG v2.12)。这类"我希望以后都这样"的开关属于**全局偏好**,
不该塞进某个任务的状态里,也不该只有改环境变量才能变。

三条口径与形象库(avatar_library)保持一致,因为它们面对的是同一类问题:
1. **落盘 JSON + 原子写**:先写临时文件再 os.replace,不会留下半个文件;
2. **读坏自愈**:文件缺失/损坏/类型不对时回退到「环境变量给的出厂默认」,读路径不抛异常;
3. **写不致命**:目录只读之类导致写失败,只记日志 —— 偏好是增强项,不能拖垮接口。

环境变量 `TTV_*` 依然是**出厂默认**,用户改过的偏好存在文件里、优先于它。
"""
import json
import logging
import os
import time
from pathlib import Path

from config import PREFERENCES_FILE

log = logging.getLogger("ttv.preferences")

SCHEMA_VERSION = 1


def prefs_file() -> Path:
    return Path(PREFERENCES_FILE)


def _factory_defaults() -> dict:
    """出厂默认(环境变量口径):偏好文件还没有或读不出来时用它。"""
    # 延迟 import:config 在模块级已经导入本模块的函数(用),这里再 import 回 config 会成环
    from config import AVATAR_CUTOUT
    return {"avatar_cutout_new_jobs": bool(AVATAR_CUTOUT)}


def load() -> dict:
    """读偏好。缺失/损坏/字段类型不对一律回退出厂默认(自愈,不抛异常)。"""
    out = _factory_defaults()
    try:
        raw = json.loads(prefs_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return out
    except Exception as e:  # noqa: BLE001 - 偏好文件坏了不该让服务 500
        log.warning("偏好文件无法解析(%s),按出厂默认继续:%s", prefs_file(), e)
        return out
    if not isinstance(raw, dict):
        log.warning("偏好文件结构不是对象(%s),按出厂默认继续", prefs_file())
        return out
    cut = raw.get("avatar_cutout_new_jobs")
    if isinstance(cut, bool):
        out["avatar_cutout_new_jobs"] = cut
    return out


def save(data: dict) -> None:
    """原子写偏好。只写认识的键,避免把任意输入带进文件。"""
    current = load()
    clean = {**current,
             "version": SCHEMA_VERSION,
             "updated_at": time.time()}
    if isinstance(data.get("avatar_cutout_new_jobs"), bool):
        clean["avatar_cutout_new_jobs"] = data["avatar_cutout_new_jobs"]
    p = prefs_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def avatar_cutout_new_jobs() -> bool:
    """新任务(以及没存过几何的老任务)默认是否抠背景。"""
    return bool(load()["avatar_cutout_new_jobs"])


def set_avatar_cutout_new_jobs(value: bool) -> dict:
    """设置默认抠像;返回写盘后的完整偏好(写失败只记日志,内存值照回)。"""
    if not isinstance(value, bool):
        raise ValueError("avatar_cutout_new_jobs 需要 true 或 false")
    try:
        save({"avatar_cutout_new_jobs": value})
    except OSError as e:  # 只读目录等:不 500
        log.warning("偏好写盘失败(只读?):%s", e)
    return load()


def payload() -> dict:
    """给接口用的完整偏好载荷(附出厂默认,便于界面解释"环境变量钉住时是什么")。"""
    cur = load()
    return {**cur, "factory": _factory_defaults(), "file": str(prefs_file())}
