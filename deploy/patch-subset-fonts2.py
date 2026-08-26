# -*- coding: utf-8 -*-
"""根治方框 v2(基于服务器原始状态):逐任务字体子集化 + base64 内嵌 + gsap 内联。"""
import re

p = 'server/builder/assemble.py'
s = open(p, encoding='utf-8').read()

# 1) 静态 FONT_FACES → 子集化函数
old = '''FONT_FACES = """
@font-face{{font-family:'SongHeavy';src:url("assets/fonts/SourceHanSerifCN-Heavy.otf") format("opentype");font-weight:normal;font-style:normal;}}
@font-face{{font-family:'Song';src:url("assets/fonts/SourceHanSerifCN-Regular.otf") format("opentype");font-weight:normal;font-style:normal;}}
@font-face{{font-family:'Sans';src:url("assets/fonts/NotoSansSC-Regular.otf") format("opentype");font-weight:normal;font-style:normal;}}
@font-face{{font-family:'SansBold';src:url("assets/fonts/NotoSansSC-Bold.otf") format("opentype");font-weight:normal;font-style:normal;}}
"""'''
new = '''FONT_SOURCES = {
    "SongHeavy": "SourceHanSerifCN-Heavy.otf",
    "Song": "SourceHanSerifCN-Regular.otf",
    "Sans": "NotoSansSC-Regular.otf",
    "SansBold": "NotoSansSC-Bold.otf",
}

# 子集化时始终保留的字符(模板固定文案 + 数字/标点/序号字)
SAFE_CHARS = (
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "一二三四五六七八九十百千万亿零壹贰叁肆伍陆柒捌玖拾"
    "，。、;:!?()()《》「」『』""''·—…%-+×/\\n\\t"
    "第章节帧总时长来源作者核心观点论证结构视觉化元素转场旁白画面类型"
    "庄重肃穆中国红清雅学术墨黛青现代锐意科技蓝藏蓝赭编辑部"
    "字体配色背景动效政论经典书香学术时代前沿其一其二其三其四"
    "上传文件粘贴文字开始分析构建预览渲染成片播放器编辑器已选择此风格"
    "理论文章转视频工作台分钟秒"
)


def build_font_faces(page_text: str) -> str:
    """字体子集化 + base64 内嵌。

    原因:hyperframes 内置静态服务器把一切资源按 text/html 下发,
    Chrome 严格校验字体 MIME 会拒绝加载 → 渲染全部方框;内嵌彻底绕过。
    同时按本任务实际用到的字符子集化(每个任务 1-2MB,而非全量 54MB)。
    """
    import base64
    import io
    from fontTools.subset import Subsetter, Options
    from fontTools.ttLib import TTFont
    text = page_text + SAFE_CHARS
    faces = []
    for fam, fname in FONT_SOURCES.items():
        src = FONTS_DIR / fname
        if not src.exists():
            faces.append(
                f"@font-face{{font-family:'{fam}';src:url(\\"assets/fonts/{fname}\\") "
                f"format(\\"opentype\\");font-weight:normal;font-style:normal;}}")
            continue
        f = TTFont(str(src))
        opts = Options()
        opts.flavor = "woff2"
        ss = Subsetter(opts)
        ss.populate(text=text)
        ss.subset(f)
        buf = io.BytesIO()
        f.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        faces.append(
            f"@font-face{{font-family:'{fam}';src:url(data:font/woff2;base64,{b64}) "
            f"format('woff2');font-weight:normal;font-style:normal;}}")
    return "\\n".join(faces)'''
assert old in s, 'FONT_FACES 未匹配'
s = s.replace(old, new)

# 2) 组装顺序:先收集文本再生成字体 CSS
old = '''    # 4) 组装 index.html
    inner_css = f"""'''
new = '''    # 4) 收集页面可见文本(用于字体子集化)
    page_text = script.get("title", "") + "".join(
        (f.get("voiceover") or "") + (f.get("scene") or "")
        + json.dumps(f.get("content") or {}, ensure_ascii=False)
        for f in frames
    )
    font_faces_css = build_font_faces(page_text)

    # 5) 组装 index.html
    inner_css = f"""'''
assert old in s, '组装顺序未匹配'
s = s.replace(old, new)

old = '''<script src="assets/vendor/gsap.min.js"></script>
<style>
{FONT_FACES}'''
new = '''<script>
{gsap_inline}
</script>
<style>
{font_faces_css}'''
assert old in s, 'gsap/font 引用未匹配'
s = s.replace(old, new)

# 3) gsap 内联内容(放在组装前读取)
old = '''    js_block = "\\n  ".join(js)
    index_html = f"""'''
new = '''    js_block = "\\n  ".join(js)
    # gsap 内联(外链脚本被内置服务器按 text/html 下发会被 Chrome 拒绝执行)
    gsap_path = VENDOR_DIR / "gsap.min.js"
    gsap_inline = gsap_path.read_text(encoding="utf-8") if gsap_path.exists() else ""
    index_html = f"""'''
assert old in s, 'js_block 未匹配'
s = s.replace(old, new)

open(p, 'w', encoding='utf-8').write(s)
print('assemble.py subset v2 patched')
