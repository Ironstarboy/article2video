# -*- coding: utf-8 -*-
"""网页「设置」页写入、**保存即生效**的运行参数。

只放两件使用者真的要改的事(面向非技术用户,不暴露环境变量与路径细节):
  1. 分析服务:网关地址 / 模型名 / 密钥 —— 文本分析走这里;
  2. 成片保存位置:成片渲染完成后额外复制一份过去(空 = 不复制,只留在项目目录)。

为什么单开一个模块而不是塞进 preferences:preferences 记的是「新建任务的默认勾选」,
这里记的是**运行参数**,必须能被 analyze.py 在**每次调用时**读到 —— 原来这些值在
config.py 里是 import 时固化的常量,改一次要改 .secrets/llm.env 并重启后端。

三条口径与 preferences / avatar_library 一致(它们面对的是同一类问题):
1. **落盘 JSON + 原子写**:先写临时文件再 os.replace,不会留下半个文件;
2. **读坏自愈**:文件缺失/损坏/字段非法时回退出厂默认(环境变量 TTV_*),读路径不抛异常;
3. **写不致命**:写盘失败只记日志并回一句人话 —— 设置是增强项,不能拖垮接口。

密钥**只写不读**:public() 只回掩码和「填没填」,明文永远不出后端。设置页是最容易
变成泄密面的地方,这条必须在模块里钉死,而不是靠前端自觉。
"""
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path

import httpx

from config import (
    DEEPSEEK_LOCAL_KEY, DEEPSEEK_LOCAL_URL, DEEPSEEK_MODEL, EXPORT_DIR, JOBS_DIR,
    SETTINGS_FILE,
)

log = logging.getLogger("ttv.settings")

SCHEMA_VERSION = 1
MASK_TAIL = 4

# 网关地址必须是完整 URL —— 只填 "8.130.213.80:20001" 是新手最常见的错,
# 所以在写入前就拦下来,并给一句带例子的提示。
_URL_RE = re.compile(r"^https?://\S+$")


def settings_file() -> Path:
    return Path(SETTINGS_FILE)


# ── 出厂默认 / 清洗 ──

def _factory_defaults() -> dict:
    """出厂默认(环境变量口径):设置文件还没写过这一项时用它。"""
    return {
        "llm_url": (DEEPSEEK_LOCAL_URL or "").strip().rstrip("/"),
        "llm_model": (DEEPSEEK_MODEL or "").strip(),
        "llm_key": (DEEPSEEK_LOCAL_KEY or "").strip(),
        "export_dir": (EXPORT_DIR or "").strip(),
    }


def _clean_url(raw: str) -> str:
    """规范化网关地址:去空白、去结尾斜杠。非法值返回空串(调用方决定回退)。"""
    url = (raw or "").strip()
    if not url or not _URL_RE.match(url):
        return ""
    return url.rstrip("/")


def _clean_dir(raw: str) -> str:
    """规范化保存位置:去空白、展开 ~。相对路径等非法值返回空串。"""
    d = (raw or "").strip()
    if not d:
        return ""
    try:
        p = Path(d).expanduser()
    except Exception:  # noqa: BLE001 - 路径里含非法字符时按"没写"处理
        return ""
    return str(p) if p.is_absolute() else ""


def _require_str(payload: dict, key: str) -> str:
    val = payload.get(key)
    if not isinstance(val, str):
        raise ValueError(f"{key} 需要是文本")
    return val


# ── 读 / 写 ──

def _read_raw() -> dict:
    """磁盘上的原始设置(不做合并)。读不出来就当空 —— 自愈,不抛异常。"""
    try:
        raw = json.loads(settings_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:  # noqa: BLE001 - 设置文件坏了不该让服务 500
        log.warning("设置文件无法解析(%s),按出厂默认继续:%s", settings_file(), e)
        return {}
    if not isinstance(raw, dict):
        log.warning("设置文件结构不是对象(%s),按出厂默认继续", settings_file())
        return {}
    return raw


def load() -> dict:
    """当前生效的设置 = 出厂默认 + 文件里写过的项。

    逐字段的口径故意不同,因为它们的**空值含义**不同:
      llm_url / llm_model  空或非法 → 保留出厂默认(服务总得有个地址和模型名);
      llm_key              以文件为准,空串是合法值(= 这个网关不需要密钥);
      export_dir           以文件为准,空串是合法值(= 不额外另存一份)。
    最后两条如果也回退出厂默认,用户"清空密钥/清空保存位置"就会失效。
    """
    out = _factory_defaults()
    raw = _read_raw()
    for key in ("llm_url", "llm_model", "llm_key", "export_dir"):
        val = raw.get(key)
        if not isinstance(val, str):
            continue
        if key == "llm_url":
            cleaned = _clean_url(val)
            if val.strip() and not cleaned:
                log.warning("设置里的服务地址不合法,按出厂默认继续:%r", val[:80])
                continue
            out[key] = cleaned
        elif key == "llm_model":
            out[key] = val.strip() or out[key]
        elif key == "llm_key":
            out[key] = val.strip()
        else:
            cleaned = _clean_dir(val)
            if val.strip() and not cleaned:
                log.warning("设置里的保存位置不是绝对路径,按出厂默认继续:%r", val[:80])
                continue
            out[key] = cleaned
    return out


def _write(raw: dict) -> None:
    """原子写 + 0600(文件里有密钥,不能让同机其他用户读到)。"""
    p = settings_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:  # 某些文件系统不支持,不是致命问题
        pass
    os.replace(tmp, p)


def _prepare_dir(raw: str) -> Path:
    """校验并准备保存位置:必须绝对路径、能建目录、能写入。失败抛人话 ValueError。

    宁可在这里失败(使用者当场看到原因),也不要在渲染两小时后复制成片时才失败。
    """
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise ValueError("请填写完整路径(以 / 开头),例如 /mnt/data/成片")
    if p.exists() and not p.is_dir():
        raise ValueError(f"{p} 已经是一个文件,请换一个目录")
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ValueError(f"这个位置建不了目录({e.strerror or e}),请换一个") from None
    probe = p / ".ttv-write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        raise ValueError(f"这个位置不能写入({e.strerror or e}),请换一个或检查权限") from None
    return p


def update(payload: dict) -> dict:
    """改设置(只改传入的字段),返回新的 public()。

    校验失败抛 ValueError(中文人话),由接口层转成 400;不会写坏已有设置。
    """
    if not isinstance(payload, dict):
        raise ValueError("请求体需要是对象")
    raw = _read_raw()
    if "llm_url" in payload:
        url = _clean_url(_require_str(payload, "llm_url"))
        if not url:
            raise ValueError("服务地址要以 http:// 或 https:// 开头,"
                             "例如 https://llmapi.paratera.com/v1")
        raw["llm_url"] = url
    if "llm_model" in payload:
        model = _require_str(payload, "llm_model").strip()
        if not model:
            raise ValueError("模型名称不能为空")
        raw["llm_model"] = model
    if "llm_key" in payload:
        raw["llm_key"] = _require_str(payload, "llm_key").strip()
    if "export_dir" in payload:
        d = _require_str(payload, "export_dir").strip()
        raw["export_dir"] = str(_prepare_dir(d)) if d else ""
    raw["version"] = SCHEMA_VERSION
    raw["updated_at"] = time.time()
    try:
        _write(raw)
    except OSError as e:
        log.warning("设置写盘失败(只读?):%s", e)
        raise ValueError("保存失败:服务器上的设置文件不可写,请联系管理员") from None
    return public()


def reset_to_factory() -> dict:
    """恢复默认 = 删掉文件(不是把出厂默认写进文件)。

    写进文件会让"以后改了环境变量也不生效";删掉才能真的回到出厂口径。
    """
    try:
        settings_file().unlink(missing_ok=True)
    except OSError as e:
        log.warning("设置文件删除失败:%s", e)
        raise ValueError("恢复默认失败:设置文件不可写,请联系管理员") from None
    return public()


# ── 给其他模块用的取值口(每次调用都重新读,保证"保存即生效") ──

def llm_endpoint() -> tuple:
    """分析服务当前生效的 (url, model, key)。analyze 每次请求都读它。"""
    cur = load()
    return cur["llm_url"], cur["llm_model"], cur["llm_key"]


def export_dir() -> Path | None:
    """成片保存位置;没设置返回 None(行为与设置页出现之前完全一致)。"""
    d = load()["export_dir"]
    return Path(d) if d else None


# ── 设置页载荷 ──

def mask_key(key: str) -> str:
    """密钥掩码:只露末 4 位。空密钥回空串。"""
    k = (key or "").strip()
    if not k:
        return ""
    return "•" * 8 + (k[-MASK_TAIL:] if len(k) > MASK_TAIL else "")


def dir_capacity(path: Path) -> dict:
    """目标目录所在磁盘的容量(目录还不存在就沿父目录往上找)。"""
    q = Path(path)
    while not q.exists() and q != q.parent:
        q = q.parent
    try:
        u = shutil.disk_usage(q)
        return {"path": str(path), "total_gb": round(u.total / 2 ** 30, 1),
                "free_gb": round(u.free / 2 ** 30, 1)}
    except OSError:
        return {"path": str(path), "total_gb": None, "free_gb": None}


def public() -> dict:
    """设置页载荷。**永不含密钥明文** —— 只回掩码与是否已填。"""
    cur = load()
    dest = Path(cur["export_dir"]) if cur["export_dir"] else Path(JOBS_DIR)
    return {
        "llm_url": cur["llm_url"],
        "llm_model": cur["llm_model"],
        "llm_key_masked": mask_key(cur["llm_key"]),
        "llm_key_set": bool(cur["llm_key"]),
        "export_dir": cur["export_dir"],
        "export_dir_used": str(dest),
        "export_dir_capacity": dir_capacity(dest),
        # 出厂默认(供「恢复默认」按钮与提示文案;同样不含密钥明文)
        "factory": {k: v for k, v in _factory_defaults().items() if k != "llm_key"},
        "file": str(settings_file()),
    }


# ── 「测试连接」探针 ──

def _net_error(e: Exception) -> str:
    """把网络异常翻译成人话(设置页只有这一行位置,不能甩 traceback)。"""
    if isinstance(e, httpx.TimeoutException):
        return "连接超时:地址不通或网络太慢,请核对地址"
    if isinstance(e, httpx.ConnectError):
        return "连不上这个地址,请核对地址与网络"
    return f"连接失败({type(e).__name__}),请把这条信息发给技术同事"


def probe_llm(url: str | None = None, model: str | None = None,
              key: str | None = None) -> dict:
    """试连分析服务(设置页「测试连接」)。返回 {ok, message, latency_ms[, models]}。

    可以做在**保存之前**:传入的地址/模型/密钥优先,没传的用已保存值(key=None 用已保存)。
    先试 GET /models(便宜),不支持这个接口的网关再退回一次极短的对话请求。
    """
    cur = load()
    url = (_clean_url(url) if isinstance(url, str) else "") or cur["llm_url"]
    model = ((model or "").strip() if isinstance(model, str) else "") or cur["llm_model"]
    use_key = cur["llm_key"] if key is None else (key or "").strip()
    headers = {"Authorization": f"Bearer {use_key}"} if use_key else {}
    t0 = time.time()

    def ms() -> int:
        return int((time.time() - t0) * 1000)

    with httpx.Client(timeout=httpx.Timeout(20.0, connect=8.0)) as client:
        try:
            r = client.get(f"{url}/models", headers=headers)
        except Exception as e:  # noqa: BLE001 - 任何网络异常都翻译成人话
            return {"ok": False, "message": _net_error(e), "latency_ms": None}
        if r.status_code == 200:
            ids = []
            try:
                ids = [m.get("id") for m in (r.json().get("data") or []) if isinstance(m, dict)]
            except Exception:  # noqa: BLE001 - 网关返回非标准 JSON 也能算连通
                ids = []
            out = {"ok": True, "latency_ms": ms(), "models": [i for i in ids if i][:20]}
            if ids and model not in ids:
                out["message"] = f"能连上,但服务方没有列出「{model}」这个模型,请核对模型名称"
            else:
                out["message"] = f"连接正常(用时 {out['latency_ms'] / 1000:.1f} 秒)"
            return out
        if r.status_code in (401, 403):
            return {"ok": False, "latency_ms": ms(),
                    "message": "能连上,但密钥不对或没有权限,请核对密钥"}
        if r.status_code not in (404, 405):
            return {"ok": False, "latency_ms": ms(),
                    "message": f"能连上,但服务返回异常(HTTP {r.status_code}),"
                               "请核对地址是否写全(通常以 /v1 结尾)"}
        # 404/405:这个网关没有 /models,退回一次真实对话请求
        try:
            r2 = client.post(f"{url}/chat/completions", headers=headers,
                             json={"model": model, "max_tokens": 8,
                                   "messages": [{"role": "user", "content": "你好"}]})
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": _net_error(e), "latency_ms": None}
        if r2.status_code == 200:
            return {"ok": True, "latency_ms": ms(),
                    "message": f"连接正常(用时 {ms() / 1000:.1f} 秒)"}
        if r2.status_code in (401, 403):
            return {"ok": False, "latency_ms": ms(), "message": "密钥不对或没有权限,请核对密钥"}
        if r2.status_code == 404:
            return {"ok": False, "latency_ms": ms(),
                    "message": "这个地址上没有找到分析接口,请核对地址(通常以 /v1 结尾)"}
        return {"ok": False, "latency_ms": ms(),
                "message": f"服务返回错误(HTTP {r2.status_code}),请把这条信息发给技术同事"}
