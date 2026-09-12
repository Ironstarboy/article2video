# -*- coding: utf-8 -*-
"""数字人形象库 —— assets/avatars/ 下的图片 + 一份 JSON 清单。

为什么单开一个模块:形象从「一个写死的 jinli.png」变成「可上传、可查看、可设默认、
可重命名、可删除的一库图片」之后,「库里有什么、哪个是默认」就成了一份需要**自愈**的
状态。这份状态必须与渲染链路解耦:库坏了只能是「回退内置形象」,绝不能让构建起不来。

三条硬约束(都是踩过的坑换来的):
1. **零第三方依赖**:运行环境 .venv 里没有 Pillow,图片宽高/完整性一律按**文件头**
   自行解析(PNG 的 IHDR、JPEG 的 SOFn、WebP 的三种块)。解析不出来 = 损坏图,拒收。
2. **自愈优先**:清单不是 JSON、引用了已删除的文件、目录里塞了未登记的图片,
   三种情况都当作正常输入处理,读路径不抛异常。
3. **命名即去重**:上传文件按内容 sha256 命名(av_<hash 前 16>.<ext>),
   同一张图重复上传自然命中同一个条目,不会越传越多。

纯函数 + 文件读写,没有全局可变状态,便于单测(见 smoke_test.py)。
"""
import hashlib
import json
import logging
import os
import re
import struct
import time
from pathlib import Path

from config import (
    AVATAR_BUILTIN_FILE, AVATAR_IMAGE_TYPES, AVATAR_LIBRARY_DIR, AVATAR_LIBRARY_FILE,
    AVATAR_UPLOAD_MAX,
)

log = logging.getLogger("ttv.avatar_library")

# 内置形象:随仓库分发,可设为默认但不可删除(删了就没得回退了)
BUILTIN_ID = "jinli"
BUILTIN_NAME = "金立"
BUILTIN_FILE = "jinli.png"

# 名称长度上限(界面是单行展示,不做换行)
NAME_MAX = 40
_NAME_UNSAFE = re.compile(r"[\x00-\x1f\x7f]")

# 清单结构版本:字段口径变化时递增,便于以后做迁移
SCHEMA_VERSION = 1


# ───────────────────────── 路径与清单 ─────────────────────────

def library_file() -> Path:
    """清单路径(stdlib 形式的间接层:单测/多实例靠 TTV_AVATAR_LIBRARY 换目录)。"""
    return Path(AVATAR_LIBRARY_FILE)


def avatars_dir() -> Path:
    """图片目录 = 清单所在目录(图片与清单永远在一起,便于整体备份/迁移)。"""
    return Path(AVATAR_LIBRARY_DIR)


def _blank() -> dict:
    return {"version": SCHEMA_VERSION, "default_id": "", "items": []}


def load() -> dict:
    """读清单。缺失/损坏/结构不对一律返回空白清单(自愈,不抛异常)。"""
    p = library_file()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _blank()
    except Exception as e:  # noqa: BLE001 - 清单坏了不该让服务 500
        log.warning("形象清单无法解析(%s),按空清单继续:%s", p, e)
        return _blank()
    if not isinstance(raw, dict):
        log.warning("形象清单结构不是对象(%s),按空清单继续", p)
        return _blank()
    items = raw.get("items")
    if not isinstance(items, list):
        items = []
    clean = []
    for it in items:
        if not isinstance(it, dict) or not it.get("id") or not it.get("file"):
            continue
        clean.append({
            "id": str(it["id"]),
            "name": str(it.get("name") or it["id"]),
            "file": str(it["file"]),
            "path": str(it.get("path") or ""),
            "width": int(it.get("width") or 0),
            "height": int(it.get("height") or 0),
            "bytes": int(it.get("bytes") or 0),
            "created_at": float(it.get("created_at") or 0.0),
            "builtin": bool(it.get("builtin")),
        })
    return {"version": int(raw.get("version") or SCHEMA_VERSION),
            "default_id": str(raw.get("default_id") or ""), "items": clean}


def _disk_items(items: list) -> list:
    """条目在磁盘上的形态:内置条目的绝对 path 不落盘(见 save 的说明)。"""
    return [{k: v for k, v in it.items() if k != "path"} for it in items]


def save(data: dict) -> None:
    """原子写清单:先写临时文件再 os.replace,避免半个 JSON 文件。

    内置条目的绝对路径**不落盘**(它是从 config 现算的):清单里存绝对路径会让
    「整目录拷走就搬家」失效 —— 拷到别的机器后那些路径全指向不存在的文件。
    """
    p = library_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({**data, "items": _disk_items(data.get("items", []))},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


# ───────────────────────── 内置形象 ─────────────────────────

def builtin_path() -> Path:
    """内置形象的**绝对**路径(不跟随库目录,见 config.AVATAR_BUILTIN_FILE 的注释)。"""
    return Path(AVATAR_BUILTIN_FILE)


def _builtin_item() -> dict:
    """内置形象条目:宽高/体积按磁盘上的真实文件探测(探测失败就留 0,界面显示占位)。"""
    p = builtin_path()
    w = h = size = 0
    if p.exists():
        try:
            data = p.read_bytes()
            size = len(data)
            w, h = image_size(data, p.suffix)
        except Exception:  # noqa: BLE001 - 内置图缺失/损坏时零信息即可
            pass
    return {"id": BUILTIN_ID, "name": BUILTIN_NAME, "file": BUILTIN_FILE,
            "path": str(p), "width": w, "height": h, "bytes": size,
            "created_at": p.stat().st_mtime if p.exists() else 0.0, "builtin": True}


# ───────────────────────── 发现与自愈 ─────────────────────────

def _scan_images() -> dict:
    """扫目录里的图片文件:{文件名 → (mtime, 体积)}。排除清单/临时文件与非图片扩展名。"""
    out = {}
    d = avatars_dir()
    if not d.is_dir():
        return out
    for p in sorted(d.iterdir()):
        if not p.is_file() or p.name.endswith(".tmp") or p.name.startswith("."):
            continue
        if p.suffix.lower() not in AVATAR_IMAGE_TYPES:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        out[p.name] = (st.st_mtime, st.st_size)
    return out


def _default_name(existing: list, idx: int = 1) -> str:
    used = {str(i.get("name")) for i in existing}
    while f"形象 {idx}" in used:
        idx += 1
    return f"形象 {idx}"


def _register(existing: list, fname: str, mtime: float, size: int) -> dict:
    """为磁盘上的图片补一条登记信息(id 取文件名主干,保证重启后稳定)。"""
    item = {"id": Path(fname).stem, "name": _default_name(existing, len(existing) + 1),
            "file": fname, "path": "", "width": 0, "height": 0, "bytes": int(size),
            "created_at": float(mtime), "builtin": False}
    try:
        data = (avatars_dir() / fname).read_bytes()
        item["width"], item["height"] = image_size(data, Path(fname).suffix)
    except Exception:  # noqa: BLE001 - 探测失败不影响登记
        pass
    return item


def _is_upload(fname: str) -> bool:
    """上传文件一律叫 av_<hash>;其余(含内置 jinli.png)不是本次上传的条目。"""
    return Path(fname).stem.startswith("av_")


def list_avatars() -> dict:
    """返回自愈后的完整库状态:{version, default_id, items[]}。

    自愈动作有四(全是「输入不可信」的兜底):
      1. 清单里的条目指向已丢失的文件 → 丢弃该条;
      2. 目录里出现未登记的上传图片 → 按文件名补登记;
      3. 内置形象条目缺失/文件信息过期 → 用磁盘上的真实文件重建;
      4. 默认位指向不存在的条目(含删掉默认形象之后)→ 换成第一个可用条目。
    """
    data = load()
    files = _scan_images()
    stored = {it["file"]: it for it in data["items"]}
    items = [stored[f] for f in sorted(files) if _is_upload(f) and f in stored]
    for fname in (f for f in sorted(files) if _is_upload(f) and f not in stored):
        items.append(_register(items, fname, files[fname][0], files[fname][1]))
    if builtin_path().exists():
        items.insert(0, _builtin_item())          # 内置形象永远在库里(可设默认、不可删)
    default_id = data["default_id"] if any(it["id"] == data["default_id"] for it in items) else ""
    if not items:
        raise RuntimeError(f"形象库为空且内置形象缺失:{builtin_path()}")
    if not default_id:
        default_id = items[0]["id"]
    state = {"version": SCHEMA_VERSION, "default_id": default_id, "items": items}
    # 与**磁盘形态**逐条比对(不能拿内存里的 items 比:内置条目带绝对 path,而落盘时被剥掉,
    # 拿内存比会让"该写回"永远判成不 stale,清单于是永远建不出来 —— 实测踩过)
    stale = _disk_items(items) != _disk_items(data["items"]) or default_id != data["default_id"]
    if stale:
        try:
            save(state)
        except OSError as e:  # 只读目录等:内存态照常用,不 500
            log.warning("形象清单写回失败(只读?):%s", e)
    return state


def find(item_id: str):
    """按 id 取条目(不存在返回 None)。id 与文件名主干一致,便于老文件直接命中。"""
    data = list_avatars()
    for it in data["items"]:
        if it["id"] == item_id:
            return it
    return None


def item_path(item: dict) -> Path:
    """条目的图片绝对路径:内置条目自带绝对 path(不跟随库目录),上传条目按库目录拼。"""
    p = item.get("path")
    return Path(p) if p else avatars_dir() / item["file"]


def hash_file(path: Path) -> str:
    """文件内容 sha256(文件不存在返回空串)。"""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def list_payload() -> dict:
    """给接口用的完整载荷:条目 + 当前生效形象 + 是否被环境变量覆盖。"""
    data = list_avatars()
    cur = current_info(data)
    return {"items": data["items"], "default_id": data["default_id"],
            "current": cur, "max_bytes": AVATAR_UPLOAD_MAX,
            "accept": sorted(AVATAR_IMAGE_TYPES)}


# ───────────────────────── 当前生效形象 ─────────────────────────

def current_info(data: dict | None = None) -> dict:
    """当前生效形象:{id, name, file, path, env_override}。

    环境变量优先于库默认(与 config.resolve_avatar_image 同一口径),这样运维可以用
    TTV_AVATAR_IMAGE 钉住一个形象,界面如实标注「由环境变量指定」而不是骗人。
    """
    env = os.environ.get("TTV_AVATAR_IMAGE")
    if env:
        p = Path(env)
        return {"id": "", "name": p.stem or p.name, "file": p.name,
                "path": str(p), "env_override": True}
    data = data if data is not None else list_avatars()
    for it in data["items"]:
        if it["id"] == data["default_id"]:
            return {"id": it["id"], "name": it["name"], "file": it["file"],
                    "path": str(item_path(it)), "env_override": False}
    # 理论上到不了(自愈后必有默认),兜底成内置形象
    return {"id": BUILTIN_ID, "name": BUILTIN_NAME, "file": BUILTIN_FILE,
            "path": str(builtin_path()), "env_override": False}


def resolve_default_image() -> Path:
    """默认形象图片路径(供 config.resolve_avatar_image 调用,绝不在 import 时固化)。"""
    return Path(current_info()["path"])


# ───────────────────────── 图片头解析(零依赖) ─────────────────────────

def _png_size(data: bytes):
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    if data[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", data[16:24])
    return (w, h) if w and h else None


def _jpeg_size(data: bytes):
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i, n = 2, len(data)
    while i + 3 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:   # 填充/无载荷段
            i += 2
            continue
        if i + 4 > n:
            return None
        seglen = struct.unpack(">H", data[i + 2:i + 4])[0]
        # SOF0..SOF15(排除 DHT=C4 / JPG=C8 / DAC=CC)里带真实宽高
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 9 > n:
                return None
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return (w, h) if w and h else None
        i += 2 + max(seglen, 2)
    return None


def _webp_size(data: bytes):
    # 最短的 WebP 是 VP8L 无损:12 字节 RIFF 头 + 5 字节 VP8L 载荷 = 25 字节(别按 30 卡)
    if len(data) < 25 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8X":
        w = int.from_bytes(data[24:27], "little") + 1
        h = int.from_bytes(data[27:30], "little") + 1
        return (w, h) if w and h else None
    if chunk == b"VP8L":
        if len(data) < 25 or data[20] != 0x2F:
            return None
        bits = int.from_bytes(data[21:25], "little")
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if chunk == b"VP8 ":
        i = data.find(b"\x9d\x01\x2a", 20, 40)   # VP8 关键帧起始码
        if i < 0 or i + 7 > len(data):
            return None
        w, h = struct.unpack("<HH", data[i + 3:i + 7])
        return (w & 0x3FFF, h & 0x3FFF) if w and h else None
    return None


def image_size(data: bytes, ext: str = "") -> tuple:
    """按文件头解析宽高;不支持的格式/损坏文件返回 (0, 0)。

    ext 只影响优先尝试哪种解析器(魔数仍是最终判据):扩展名与内容不符时按内容走。
    """
    parsers = {"png": _png_size, "jpg": _jpeg_size, "jpeg": _jpeg_size, "webp": _webp_size}
    order = []
    e = (ext or "").lower().lstrip(".")
    if e in parsers:
        order.append(parsers[e])
    order += [p for p in (_png_size, _jpeg_size, _webp_size) if p not in order]
    for parse in order:
        try:
            got = parse(data)
        except Exception:  # noqa: BLE001 - 坏字节流不该让校验炸掉
            got = None
        if got:
            return got
    return (0, 0)


def sniff_ext(data: bytes) -> str:
    """按魔数判断真实格式,返回规范扩展名(无法识别返回空串)。"""
    if _png_size(data):
        return ".png"
    if _jpeg_size(data):
        return ".jpg"
    if _webp_size(data):
        return ".webp"
    return ""


# ───────────────────────── 增删改 ─────────────────────────

def sanitize_name(raw: str, fallback: str) -> str:
    """名称清洗:去控制字符、压空白、截断(空则用 fallback)。"""
    s = _NAME_UNSAFE.sub("", str(raw or "")).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:NAME_MAX] or fallback


def add_avatar(data: bytes, filename: str, name: str = "") -> tuple:
    """上传一张形象图,返回 (item, duplicate)。校验不过抛 ValueError。

    校验三重:扩展名白名单 → 体积上限 → 文件头能解析出宽高(解析不出即损坏图)。
    文件内容 sha256 命名,同图重复上传返回既有条目而不是新增。
    """
    ext = Path(filename or "").suffix.lower()
    if ext not in AVATAR_IMAGE_TYPES:
        raise ValueError("仅支持 " + " / ".join(sorted(AVATAR_IMAGE_TYPES)) + " 格式的图片")
    if not data:
        raise ValueError("图片内容为空")
    if len(data) > AVATAR_UPLOAD_MAX:
        raise ValueError(f"图片超过 {AVATAR_UPLOAD_MAX // (1024 * 1024)}MB 上限")
    w, h = image_size(data, ext)
    if not w or not h:
        raise ValueError("图片无法解析(文件完整性与格式校验不通过)")
    real_ext = sniff_ext(data) or ext
    digest = hashlib.sha256(data).hexdigest()[:16]
    item_id = f"av_{digest}"
    state = list_avatars()
    for it in state["items"]:
        if it["id"] == item_id:
            return it, True                       # 同一张图已经在库里
        if it.get("builtin") and hash_file(item_path(it)).startswith(digest):
            return it, True                       # 上传的就是内置那张图
    fname = f"{item_id}{real_ext}"
    d = avatars_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / (fname + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, d / fname)
    item = {"id": item_id, "name": sanitize_name(name, _default_name(state["items"])),
            "file": fname, "path": "", "width": w, "height": h, "bytes": len(data),
            "created_at": time.time(), "builtin": False}
    state["items"].append(item)
    state["default_id"] = state["default_id"] or item["id"]
    save(state)
    log.info("形象入库:%s(%s, %dx%d, %d 字节)", item["name"], item["id"], w, h, len(data))
    return item, False


def delete_avatar(item_id: str) -> dict:
    """删除一个形象(内置条目拒绝)。删掉当前默认时,默认位落到剩余条目。"""
    state = list_avatars()
    target = next((it for it in state["items"] if it["id"] == item_id), None)
    if target is None:
        raise KeyError(item_id)
    if target.get("builtin"):
        raise PermissionError("内置形象不可删除")
    state["items"] = [it for it in state["items"] if it["id"] != item_id]
    try:
        item_path(target).unlink()
    except FileNotFoundError:
        pass
    except OSError as e:  # 文件删不掉(占用/只读)也要把登记去掉,不 500
        log.warning("形象文件删除失败:%s", e)
    if state["default_id"] == item_id:
        state["default_id"] = state["items"][0]["id"] if state["items"] else ""
    save(state)
    return state


def rename_avatar(item_id: str, name: str) -> dict:
    state = list_avatars()
    target = next((it for it in state["items"] if it["id"] == item_id), None)
    if target is None:
        raise KeyError(item_id)
    target["name"] = sanitize_name(name, target["name"])
    save(state)
    return target


def set_default(item_id: str) -> dict:
    state = list_avatars()
    target = next((it for it in state["items"] if it["id"] == item_id), None)
    if target is None:
        raise KeyError(item_id)
    state["default_id"] = item_id
    save(state)
    return target
