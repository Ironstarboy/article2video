# -*- coding: utf-8 -*-
"""文本提取:txt / md / docx(纯标准库)。"""
import re
import zipfile
from pathlib import Path

ALLOWED_EXTS = {".txt", ".md", ".markdown", ".docx"}


def extract_text(path: str | Path) -> str:
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(f"不支持的文件类型:{ext}(仅支持 txt / md / docx)")
    raw = p.read_bytes()
    if ext == ".docx":
        text = _extract_docx(raw)
    else:
        text = _decode(raw)
        if ext in (".md", ".markdown"):
            text = _strip_markdown(text)
    text = _clean(text)
    if len(text) < 100:
        raise ValueError(f"正文太短({len(text)} 字),请确认文件内容")
    if len(text) > 200000:
        raise ValueError("正文超过 20 万字上限")
    return text


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


ZIP_BOMB_LIMIT = 50 * 1024 * 1024   # 解压总量上限 50MB
ZIP_ENTRY_LIMIT = 2000


def _extract_docx(raw: bytes) -> str:
    """解包 word/document.xml,按段落提取 w:t 文本(含 zip 炸弹防护)。"""
    with zipfile.ZipFile(__import__("io").BytesIO(raw)) as zf:
        infos = zf.infolist()
        if len(infos) > ZIP_ENTRY_LIMIT:
            raise ValueError("docx 条目数异常(疑似恶意文件)")
        total = sum(i.file_size for i in infos)
        if total > ZIP_BOMB_LIMIT:
            raise ValueError("docx 解压后过大(疑似压缩炸弹)")
        xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    paragraphs = re.split(r"</w:p>", xml)
    lines = []
    for para in paragraphs:
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, re.S)
        line = "".join(texts)
        line = (line
                .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&apos;", "'"))
        if line.strip():
            lines.append(line.strip())
    return "\n".join(lines)


def _strip_markdown(text: str) -> str:
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)       # 标题
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)          # 图片
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)      # 链接
    text = re.sub(r"`{1,3}[^`]*`{1,3}", "", text)             # 行内代码
    text = re.sub(r"^[>*+\-\s]+", "", text, flags=re.M)       # 列表符号
    text = re.sub(r"^---+$", "", text, flags=re.M)            # 分隔线
    return text


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
