# -*- coding: utf-8 -*-
"""帧模板:script.json 的每一帧 → (帧 HTML, 字幕 HTML, GSAP tween 行)。

约定:
- S = 帧的「计划开始时间」(旁白与字幕计时基准)
- 帧元素 id:f{i}-<name>;字幕词 span id:f{i}-w{n}
- 被 GSAP 补间的元素,其 CSS 里绝不写 transform(gsap_css_transform_conflict)
- 帧入场:crossfade/push_up 由 assemble 在 section 级处理,模板只做内容动画
"""
import html as _html

from builder.styles import deco_body, deco_closing, deco_opening

E = _html.escape


def _lines(text, n):
    parts = (text or "").split("\n")
    return (parts + [""] * n)[:n]


def render_frame(frame, style, S, ctx=None) -> tuple[str, str, list[str]]:
    """返回 (section_html, caption_html, js_lines)。ctx: {title, total} 用于页脚。"""
    i = frame["index"]
    t = frame["type"]
    c = frame.get("content") or {}
    ctx = ctx or {}
    fn = {
        "opening": _opening, "section": _section, "statement": _statement,
        "elaboration": _elaboration, "quote": _quote, "data": _data,
        "points": _points, "process": _process, "contrast": _contrast,
        "closing": _closing,
        # 讲解视频(lecture)专用帧
        "textblock": _textblock, "annotation": _annotation, "method": _method,
    }[t]
    sec, cap, js = fn(i, c, style, S)
    # 全帧统一页脚:《标题》 · 帧序(编辑部信息密度)
    title = (ctx.get("title") or "").replace("\n", " ")
    foot = (f'<div style="position:absolute;left:320px;right:320px;bottom:44px;'
            f'display:flex;justify-content:space-between;font-family:{style["font_body"]};'
            f'font-size:20px;color:{style["muted"]};opacity:0.8;" id="f{i}-foot">'
            f'<span>《{title[:20]}》</span><span>{i:02d} / {ctx.get("total", 0):02d}</span></div>')
    sec = sec.replace("</section>", foot + "</section>")
    js.append(f'tl.from("#f{i}-foot",{{autoAlpha:0,duration:0.5}},{S}+0.6);')
    return sec, cap, js


def _wrap(i, style, deco_svg, inner_html, extra_style=""):
    return (f'<section class="clip" id="sec{i}" data-start="{S_PLACEHOLDER}" data-duration="{D_PLACEHOLDER}" '
            f'data-track-index="2" style="background:{style["bg"]};{extra_style}">'
            f'<div style="position:absolute;inset:0;">{deco_svg}</div>'
            f'{inner_html}</section>')


S_PLACEHOLDER, D_PLACEHOLDER = "##S##", "##D##"


# ───────────────────────────── 开场 ─────────────────────────────

def _opening(i, c, style, S):
    k = style["key"]
    lines = _lines(c.get("title", ""), 2)
    tsize = style.get("title_size", 88)
    deco = _deco_open(style)
    parts = [f'<div class="inner center" style="padding:0 320px;">']
    parts.append(f'<div id="f{i}-eyebrow" style="font-family:{style["font_bold"]};font-size:26px;'
                 f'color:{style["primary"]};letter-spacing:0.35em;margin-bottom:56px;">{E(c.get("eyebrow", "") or "")}</div>')
    for n in range(2):
        txt = lines[n]
        if txt:
            parts.append(f'<div id="f{i}-title-l{n+1}" style="font-family:{style["font_title"]};'
                         f'font-size:{tsize}px;color:{style["deep"]};line-height:1.25;">{E(txt)}</div>')
    parts.append(f'<div id="f{i}-divider" style="width:240px;height:2px;background:{style["accent2"]};margin:56px 0 40px;"></div>')
    if c.get("subtitle"):
        parts.append(f'<div id="f{i}-sub" style="font-family:{style["font_body"]};font-size:32px;'
                     f'color:{style["muted"]};">{E(c["subtitle"])}</div>')
    parts.append("</div>")
    js = []
    if style["deco_style"] == "orbit":
        js.append(f'tl.from("#gold-star",{{scale:0.6,autoAlpha:0,duration:0.9,ease:"power2.out",svgOrigin:"960 290"}},{S}+0.1);')
    elif style["deco_style"] == "wash":
        js.append(f'tl.from("#seal",{{scale:0.7,autoAlpha:0,duration:0.8,ease:"power2.out",svgOrigin:"960 320"}},{S}+0.1);')
    js.append(f'tl.from("#f{i}-eyebrow",{{y:12,autoAlpha:0,duration:0.5,ease:"power2.out"}},{S}+0.25);')
    for n in range(2):
        if lines[n]:
            js.append(f'tl.from("#f{i}-title-l{n+1}",{{y:24,autoAlpha:0,duration:0.7,ease:"power3.out"}},{S}+{0.5 + n * 0.08});')
    js.append(f'tl.from("#f{i}-divider",{{scaleX:0,duration:0.5,ease:"power2.out"}},{S}+1.0);')
    if c.get("subtitle"):
        js.append(f'tl.from("#f{i}-sub",{{y:12,autoAlpha:0,duration:0.5,ease:"power2.out"}},{S}+1.2);')
    return _wrap(i, style, deco, "".join(parts)), "", js


def _deco_open(style):
    return deco_opening(style)


# ───────────────────────────── 章节页 ─────────────────────────────

def _section(i, c, style, S):
    k = style["key"]
    num = E(c.get("number", ""))
    ghost_color = style["ghost"]
    parts = ['<div class="inner left" style="padding:0 320px;">',
             '<div style="display:flex;align-items:center;gap:56px;">',
             f'<div id="f{i}-num" data-layout-ignore style="font-family:{style["font_title"]};font-size:150px;'
             f'color:{ghost_color};line-height:1;">{num}</div>',
             '<div style="display:flex;flex-direction:column;gap:36px;">',
             f'<div id="f{i}-title" style="font-family:{style["font_title"]};font-size:62px;'
             f'color:{style["deep"]};line-height:1.2;">{E(c.get("title", ""))}</div>',
             f'<div id="f{i}-line" style="width:160px;height:2px;background:{style["primary"]};"></div>']
    if c.get("subtitle"):
        parts.append(f'<div id="f{i}-sub" style="font-family:{style["font_body"]};font-size:26px;'
                     f'color:{style["muted"]};">{E(c["subtitle"])}</div>')
    parts += ["</div>", "</div>", "</div>"]
    js = [
        f'tl.from("#f{i}-num",{{autoAlpha:0,duration:0.4}},{S}+0.2);',
        f'tl.from("#f{i}-title",{{y:20,autoAlpha:0,duration:0.5,ease:"power2.out"}},{S}+0.4);',
        f'tl.from("#f{i}-line",{{scaleX:0,duration:0.4,ease:"power2.out"}},{S}+0.6);',
    ]
    if c.get("subtitle"):
        js.append(f'tl.from("#f{i}-sub",{{y:10,autoAlpha:0,duration:0.4}},{S}+0.8);')
    return _wrap(i, style, deco_body(style), "".join(parts)), "", js


# ───────────────────────────── 论点页 ─────────────────────────────

def _statement(i, c, style, S):
    k = style["key"]
    bar_bg = (f"linear-gradient(180deg,{style['primary']},{style.get('cyan', style['primary'])})"
              if style.get("cyan") else style["primary"])
    lines = _lines(c.get("thesis", ""), 2)
    parts = ['<div class="inner left" style="padding:0 320px 0 420px;">',
             f'<div id="f{i}-bar" style="position:absolute;left:232px;top:260px;width:4px;height:560px;background:{bar_bg};"></div>',
             f'<div id="f{i}-eyebrow" style="font-family:{style["font_bold"]};font-size:26px;'
             f'color:{style["primary"]};letter-spacing:0.2em;margin-bottom:44px;">'
             f'<span style="display:inline-block;width:24px;height:3px;background:{style["primary"]};vertical-align:middle;margin-right:16px;"></span>'
             f'{E(c.get("eyebrow", "") or "")}</div>']
    for n in range(2):
        if lines[n]:
            parts.append(f'<div id="f{i}-t-l{n+1}" style="font-family:{style["font_title"]};font-size:54px;'
                         f'color:{style["text"]};line-height:1.35;">{E(lines[n])}</div>')
    if c.get("support"):
        parts.append(f'<div id="f{i}-sup" style="font-family:{style["font_body"]};font-size:29px;'
                     f'color:{style["muted"]};margin-top:32px;line-height:1.7;max-width:1200px;">{E(c["support"])}</div>')
    kws = c.get("keywords") or []
    if kws:
        chips = "".join(
            f'<span id="f{i}-kw{n+1}" style="display:inline-block;padding:7px 20px;'
            f'border:1px solid {style["primary"]};border-radius:999px;'
            f'font-family:{style["font_bold"]};font-size:22px;color:{style["primary"]};'
            f'margin:0 16px 0 0;">{E(k[:4])}</span>'
            for n, k in enumerate(kws[:4]))
        parts.append(f'<div style="margin-top:40px;">{chips}</div>')
    parts.append("</div>")
    js = [f'tl.from("#f{i}-bar",{{scaleY:0,duration:0.6,ease:"power2.out",transformOrigin:"top center"}},{S}+0.1);',
          f'tl.from("#f{i}-eyebrow",{{autoAlpha:0,duration:0.4}},{S}+0.25);']
    for n in range(min(4, len(kws))):
        js.append(f'tl.from("#f{i}-kw{n+1}",{{y:10,autoAlpha:0,duration:0.4,ease:"power2.out"}},{S}+{0.9 + n * 0.12});')
    for n in range(2):
        if lines[n]:
            js.append(f'tl.from("#f{i}-t-l{n+1}",{{y:20,autoAlpha:0,duration:0.5,ease:"power2.out"}},{S}+{0.4 + n * 0.1});')
    if c.get("support"):
        js.append(f'tl.from("#f{i}-sup",{{y:14,autoAlpha:0,duration:0.5,ease:"power2.out"}},{S}+0.75);')
    return _wrap(i, style, deco_body(style), "".join(parts)), "", js


# ───────────────────────────── 论证展开页 ─────────────────────────────

def _elaboration(i, c, style, S):
    k = style["key"]
    radius = style["radius"]
    cards = c.get("cards") or []
    parts = ['<div class="inner plain" style="padding:0 320px;">',
             f'<div id="f{i}-title" style="font-family:{style["font_title"]};font-size:42px;'
             f'color:{style["deep"]};margin-bottom:64px;">{E(c.get("title", "") or "")}</div>',
             '<div style="display:flex;gap:40px;">']
    js = [f'tl.from("#f{i}-title",{{y:16,autoAlpha:0,duration:0.4,ease:"power2.out"}},{S}+0.2);']
    for n, card in enumerate(cards):
        cid = f"f{i}-c{n+1}"
        parts.append(f'<div id="{cid}" style="flex:1;background:{style["card"]};'
                     f'border:1px solid {style["card_border"]};border-radius:{radius}px;padding:36px 32px;'
                     'display:flex;flex-direction:column;min-height:320px;">')
        if style.get("cyan"):
            parts.append(f'<div id="{cid}-bar" style="height:4px;border-radius:2px;'
                         f'background:linear-gradient(90deg,{style["primary"]},{style.get("cyan", style["primary"])});margin-bottom:28px;"></div>')
            js.append(f'tl.from("#{cid}-bar",{{scaleX:0,duration:0.4,transformOrigin:"left center"}},{S}+{0.5 + n * 0.18});')
        parts.append(f'<div style="font-family:{style["font_bold"]};font-size:26px;color:{style["primary"]};'
                     f'letter-spacing:0.1em;margin-bottom:18px;">{E(card.get("id", f"{n+1:02d}"))}</div>')
        parts.append(f'<div style="font-family:{style["font_bold"]};font-size:29px;color:{style["text"]};'
                     f'line-height:1.4;margin-bottom:14px;">{E(card.get("heading", ""))}</div>')
        parts.append(f'<div style="font-family:{style["font_body"]};font-size:21px;color:{style["muted"]};'
                     f'line-height:1.7;">{E(card.get("note", ""))}</div>')
        if style["deco_style"] == "orbit":
            parts.append(f'<div style="margin-top:auto;padding-top:24px;border-bottom:2px solid {style["primary"]};opacity:0.5;"></div>')
        parts.append("</div>")
        js.append(f'tl.from("#{cid}",{{y:40,autoAlpha:0,scale:0.98,duration:0.45,ease:"power3.out"}},{S}+{0.5 + n * 0.18});')
    parts += ["</div>", "</div>"]
    return _wrap(i, style, deco_body(style), "".join(parts)), "", js


# ───────────────────────────── 金句页 ─────────────────────────────

def _quote(i, c, style, S):
    k = style["key"]
    kw = c.get("keyword", "").strip()
    kw_color = style["accent2"] if style.get("cyan") else style["primary"]
    lines = _lines(c.get("quote", ""), 3)
    parts = ['<div class="inner center" style="padding:0 340px;">',
             f'<div id="f{i}-qm" style="font-family:{style["font_title"]};font-size:120px;color:{style["primary"]};'
             f'line-height:0.6;margin-bottom:64px;">“</div>']
    js = [f'tl.from("#f{i}-qm",{{scale:0.9,autoAlpha:0,duration:0.5,ease:"power2.out",transformOrigin:"center bottom"}},{S}+0.1);']
    for n in range(3):
        if lines[n]:
            txt = lines[n]
            if kw and kw in txt:
                txt = txt.replace(kw, f'<span style="color:{kw_color};">{kw}</span>')
            parts.append(f'<div id="f{i}-q-l{n+1}" style="font-family:{style["font_title"]};font-size:46px;'
                         f'color:{style["text"]};line-height:1.45;">{txt}</div>')
            js.append(f'tl.from("#f{i}-q-l{n+1}",{{y:16,autoAlpha:0,duration:0.5,ease:"power2.out"}},{S}+{0.4 + n * 0.25});')
    parts.append('<div style="margin-top:56px;">'
                 f'<span id="f{i}-src-dash" style="display:inline-block;width:40px;height:2px;'
                 f'background:{style["accent2"]};vertical-align:middle;margin-right:20px;"></span>'
                 f'<span id="f{i}-src" style="font-family:{style["font_body"]};font-size:26px;color:{style["muted"]};">'
                 f'{E(c.get("source", "") or "")}</span></div>')
    parts.append("</div>")
    js.append(f'tl.from("#f{i}-src-dash",{{scaleX:0,duration:0.4,ease:"power2.out",transformOrigin:"left center"}},{S}+0.8);')
    js.append(f'tl.from("#f{i}-src",{{autoAlpha:0,duration:0.4}},{S}+0.95);')
    return _wrap(i, style, deco_body(style), "".join(parts)), "", js


# ───────────────────────────── 数据页 ─────────────────────────────

def _data(i, c, style, S):
    items = c.get("items") or []
    num_size = 150 if len(items) <= 2 else 110   # 3 组数据时缩小字号防溢出
    parts = ['<div class="inner center" style="padding:0 320px;">',
             '<div style="display:flex;gap:80px;justify-content:center;align-items:flex-start;">']
    js = []
    for n, item in enumerate(items):
        val = str(item.get("value", "0"))
        numeric = val.replace(".", "", 1).replace("-", "", 1).isdigit() and val.count(".") <= 1
        parts.append('<div style="display:flex;flex-direction:column;align-items:center;">')
        if numeric:
            parts.append('<div style="display:flex;align-items:baseline;gap:12px;">'
                         f'<span id="f{i}-n{n+1}" style="font-family:{style["font_title"]};font-size:{num_size}px;'
                         f'color:{style["primary"]};line-height:1;">0</span>'
                         f'<span id="f{i}-u{n+1}" style="font-family:{style["font_bold"]};font-size:32px;'
                         f'color:{style["text"]};">{E(item.get("unit", ""))}</span></div>')
        else:
            # 非数字(如定性表述):渲染为静态文本,绝不进入 JS
            parts.append('<div style="display:flex;align-items:baseline;gap:12px;max-width:1100px;text-align:center;">'
                         f'<span id="f{i}-n{n+1}" style="font-family:{style["font_title"]};font-size:62px;'
                         f'color:{style["primary"]};line-height:1.35;">{E(val)}</span>'
                         f'<span id="f{i}-u{n+1}" style="font-family:{style["font_bold"]};font-size:32px;'
                         f'color:{style["text"]};">{E(item.get("unit", ""))}</span></div>')
        if item.get("note"):
            parts.append(f'<div id="f{i}-note{n+1}" style="font-family:{style["font_body"]};font-size:25px;'
                         f'color:{style["muted"]};margin-top:20px;">{E(item["note"])}</div>')
        chart = item.get("chart")
        if chart in ("bar", "line", "ring"):
            parts.append(_chart_svg(i, n + 1, chart, style))
            _chart_js(js, i, n + 1, chart, style, S)
        parts.append("</div>")
        if numeric:
            target = float(val)
            decimals = 1 if "." in val else 0
            js.append(
                f'tl.fromTo({{v:0}},{{v:0}},{{v:{target},duration:1.2,ease:"power2.out",'
                f'onUpdate:function(){{var el=document.getElementById("f{i}-n{n+1}");'
                f'if(el){{el.textContent=this.targets()[0].v.toFixed({decimals});}}}}}},{S}+0.3);')
        else:
            js.append(f'tl.from("#f{i}-n{n+1}",{{y:14,autoAlpha:0,duration:0.5,ease:"power2.out"}},{S}+0.3);')
        if item.get("note"):
            js.append(f'tl.from("#f{i}-note{n+1}",{{y:10,autoAlpha:0,duration:0.4}},{S}+0.5);')
    parts.append("</div>")
    if c.get("conclusion"):
        parts.append(f'<div id="f{i}-con" style="font-family:{style["font_bold"]};font-size:29px;'
                     f'color:{style["text"]};margin-top:64px;">{E(c["conclusion"])}</div>')
        js.append(f'tl.from("#f{i}-con",{{y:12,autoAlpha:0,duration:0.5,ease:"power2.out"}},{S}+1.4);')
    parts.append("</div>")
    return _wrap(i, style, deco_body(style), "".join(parts)), "", js


def _chart_svg(i, n, chart, style):
    k = style["key"]
    if chart == "bar":
        bars = [(0.55, style["primary"]), (0.8, style["primary"]), (1.0, style["accent2"] if style.get("cyan") else style["primary"])]
        rects = "".join(
            f'<rect id="f{i}-ch{n}-r{m+1}" x="{30 + m * 62}" y="{220 - int(200 * h)}" width="44" height="{int(200 * h)}" '
            f'fill="{color}" rx="3" opacity="0.9"/>'
            for m, (h, color) in enumerate(bars))
        return (f'<svg width="240" height="240" viewBox="0 0 240 240" xmlns="http://www.w3.org/2000/svg" '
                f'style="margin-top:28px;"><line x1="20" y1="220" x2="228" y2="220" stroke="{style["divider"]}" '
                f'stroke-width="2"/>{rects}</svg>')
    if chart == "line":
        return (f'<svg width="240" height="140" viewBox="0 0 240 140" xmlns="http://www.w3.org/2000/svg" '
                f'style="margin-top:28px;"><polyline id="f{i}-ch{n}-l" points="20,110 80,85 140,95 220,40" '
                f'fill="none" stroke="{style.get("cyan", style["primary"])}" stroke-width="4" stroke-linecap="round" '
                f'stroke-dasharray="320" stroke-dashoffset="320"/>'
                f'<circle cx="220" cy="40" r="7" fill="{style["accent2"] if style.get("cyan") else style["primary"]}"/></svg>')
    # ring
    return (f'<svg width="140" height="140" viewBox="0 0 140 140" xmlns="http://www.w3.org/2000/svg" '
            f'style="margin-top:28px;"><circle cx="70" cy="70" r="56" fill="none" stroke="{style["divider"]}" stroke-width="10"/>'
            f'<circle id="f{i}-ch{n}-ring" cx="70" cy="70" r="56" fill="none" '
            f'stroke="{style.get("cyan", style["primary"])}" stroke-width="10" stroke-linecap="round" '
            f'stroke-dasharray="352" stroke-dashoffset="352" transform="rotate(-90 70 70)"/></svg>')


def _chart_js(js, i, n, chart, style, S):
    if chart == "bar":
        for m in range(3):
            js.append(f'tl.from("#f{i}-ch{n}-r{m+1}",{{scaleY:0,duration:0.5,ease:"power2.out",'
                      f'transformOrigin:"bottom center"}},{S}+{0.55 + m * 0.15});')
    elif chart == "line":
        js.append(f'tl.to("#f{i}-ch{n}-l",{{strokeDashoffset:0,duration:1.0,ease:"power2.out"}},{S}+0.5);')
    else:
        js.append(f'tl.to("#f{i}-ch{n}-ring",{{strokeDashoffset:98,duration:1.2,ease:"power2.out"}},{S}+0.5);')


# ───────────────────────────── 分点页 ─────────────────────────────

def _points(i, c, style, S):
    k = style["key"]
    pts = c.get("points") or []
    parts = ['<div class="inner left" style="padding:0 320px;">',
             f'<div id="f{i}-title" style="font-family:{style["font_title"]};font-size:42px;'
             f'color:{style["deep"]};margin-bottom:56px;">{E(c.get("title", "") or "")}</div>']
    js = [f'tl.from("#f{i}-title",{{y:16,autoAlpha:0,duration:0.4,ease:"power2.out"}},{S}+0.2);']
    for n, pt in enumerate(pts):
        rid = f"f{i}-r{n+1}"
        parts.append(f'<div id="{rid}" style="display:flex;align-items:center;gap:32px;margin-bottom:44px;">')
        if style["deco_style"] == "orbit":
            parts.append(f'<span style="width:10px;height:10px;border-radius:50%;background:{style["primary"]};flex:none;"></span>'
                         f'<span style="font-family:{style["font_bold"]};font-size:30px;color:{style["primary"]};'
                         f'width:64px;flex:none;">{n+1:02d}</span>')
        elif style["deco_style"] == "wash":
            nums = ["其一", "其二", "其三", "其四"]
            parts.append(f'<span style="font-family:{style["font_title"]};font-size:30px;color:{style["primary"]};'
                         f'width:96px;flex:none;">{nums[n] if n < 4 else n+1}</span>')
        else:
            parts.append(f'<span style="width:44px;height:44px;border-radius:8px;background:{style["primary"]};'
                         f'color:#FFFFFF;font-family:{style["font_bold"]};font-size:22px;display:flex;'
                         f'align-items:center;justify-content:center;flex:none;">{n+1}</span>')
        parts.append(f'<span style="font-family:{style["font_body"]};font-size:29px;color:{style["text"]};'
                     f'line-height:1.5;">{E(pt)}</span>')
        parts.append("</div>")
        if style["deco_style"] in ("wash", "tech"):
            line_color = style["accent2"] if style["deco_style"] == "wash" else style["divider"]
            parts.append(f'<div id="{rid}-ln" style="height:1px;background:{line_color};'
                         f'opacity:0.35;margin:-18px 0 44px 128px;"></div>')
            js.append(f'tl.from("#{rid}-ln",{{scaleX:0,duration:0.4,transformOrigin:"left center"}},{S}+{0.6 + n * 0.35});')
        js.append(f'tl.from("#{rid}",{{y:28,autoAlpha:0,duration:0.5,ease:"power3.out"}},{S}+{0.45 + n * 0.35});')
    parts.append("</div>")
    return _wrap(i, style, deco_body(style), "".join(parts)), "", js


# ───────────────────────────── 递进流程页 ─────────────────────────────

def _process(i, c, style, S):
    k = style["key"]
    steps = c.get("steps") or []
    parts = ['<div class="inner plain" style="padding:0 320px;">',
             f'<div id="f{i}-title" style="font-family:{style["font_title"]};font-size:42px;'
             f'color:{style["deep"]};margin-bottom:96px;">{E(c.get("title", "") or "")}</div>',
             '<div style="display:flex;align-items:flex-start;justify-content:center;gap:48px;">']
    js = [f'tl.from("#f{i}-title",{{y:16,autoAlpha:0,duration:0.4,ease:"power2.out"}},{S}+0.2);']
    for n, step in enumerate(steps):
        cid = f"f{i}-c{n+1}"
        arrow_color = (style.get("cyan", style["primary"]) if style.get("cyan") else (style["accent2"] if style["deco_style"] == "wash" else style["light"]))
        parts.append(f'<div id="{cid}" style="display:flex;flex-direction:column;align-items:center;width:240px;">'
                     f'<div style="width:84px;height:84px;border-radius:50%;background:#FFFFFF;'
                     f'border:2px solid {style["primary"]};display:flex;align-items:center;justify-content:center;'
                     f'font-family:{style["font_bold"]};font-size:30px;color:{style["primary"]};">{E(step.get("name", "")[:1] if style["deco_style"] == "wash" else step.get("name", "")[:2])}</div>'
                     f'<div id="{cid}-nm" style="font-family:{style["font_bold"]};font-size:27px;color:{style["text"]};'
                     f'margin-top:26px;text-align:center;">{E(step.get("name", ""))}</div>')
        if step.get("note"):
            parts.append(f'<div id="{cid}-nt" style="font-family:{style["font_body"]};font-size:21px;'
                         f'color:{style["muted"]};margin-top:12px;text-align:center;line-height:1.6;">{E(step["note"])}</div>')
        parts.append("</div>")
        if n < len(steps) - 1:
            aid = f"f{i}-a{n+1}"
            parts.append(f'<div id="{aid}" style="display:flex;align-items:flex-start;padding-top:20px;'
                         f'font-size:40px;color:{arrow_color};">→</div>')
            js.append(f'tl.from("#{aid}",{{scaleX:0,autoAlpha:0,duration:0.3,transformOrigin:"left center"}},{S}+{0.75 + n * 0.3});')
        js.append(f'tl.from("#{cid}",{{scale:0,autoAlpha:0,duration:0.35,ease:"back.out(1.4)",transformOrigin:"center"}},{S}+{0.5 + n * 0.3});')
        js.append(f'tl.from("#{cid}-nm",{{y:10,autoAlpha:0,duration:0.35}},{S}+{0.85 + n * 0.3});')
        if step.get("note"):
            js.append(f'tl.from("#{cid}-nt",{{y:8,autoAlpha:0,duration:0.35}},{S}+{1.0 + n * 0.3});')
    parts += ["</div>", "</div>"]
    return _wrap(i, style, deco_body(style), "".join(parts)), "", js


# ───────────────────────────── 对比页 ─────────────────────────────

def _contrast(i, c, style, S):
    k = style["key"]
    if style.get("cyan"):
        mid_bg = f"linear-gradient(180deg,{style['primary']},{style.get('cyan', style['primary'])})"
    elif style["deco_style"] == "wash":
        mid_bg = "#A63A2B"
    elif style["deco_style"] == "orbit":
        mid_bg = style["accent2"]
    else:
        mid_bg = style["primary"]
    def col(cid, label, pts, strong):
        p = [f'<div id="{cid}" style="position:absolute;top:260px;width:520px;left:{320 if not strong else 1080}px;">',
             f'<span style="display:inline-block;padding:8px 24px;border:1px solid {style["primary"]};'
             f'border-radius:999px;font-family:{style["font_bold"]};font-size:24px;'
             f'color:{style["muted"] if (style.get("cyan") and not strong) or (not style.get("cyan") and not strong) else style["primary"]};'
             f'{"background:" + style["primary"] + ";color:#FFFFFF;" if (style.get("cyan") and strong) else ""}'
             f'>{E(label)}</span>',
             '<div style="margin-top:36px;display:flex;flex-direction:column;gap:24px;">']
        for pt in pts:
            p.append(f'<div style="font-family:{style["font_body"]};font-size:28px;line-height:1.6;'
                     f'color:{style["text"] if strong else style["muted"]};">{E(pt)}</div>')
        p.append("</div></div>")
        return "".join(p)
    html = (col(f"f{i}-l", c.get("left_label", ""), c.get("left_points") or [], False)
            + f'<div id="f{i}-m" style="position:absolute;left:958px;top:220px;width:4px;height:640px;background:{mid_bg};border-radius:2px;"></div>'
            + col(f"f{i}-r", c.get("right_label", ""), c.get("right_points") or [], True))
    js = [
        f'tl.from("#f{i}-l",{{x:-50,autoAlpha:0,duration:0.6,ease:"power2.out"}},{S}+0.2);',
        f'tl.from("#f{i}-m",{{scaleY:0,duration:0.5,transformOrigin:"top center"}},{S}+0.4);',
        f'tl.from("#f{i}-r",{{x:50,autoAlpha:0,duration:0.6,ease:"power2.out"}},{S}+0.6);',
    ]
    return _wrap(i, style, deco_body(style), html), "", js


# ───────────────────────────── 讲解帧(lecture) ─────────────────────────────
# 三种讲解视频专用帧,复刻「老师带着学生拆文章」的板书感:
# textblock 原文段展示 / annotation 逐句批注 / method 可迁移写法提炼。

def _textblock(i, c, style, S):
    """原文段页:讲义式展示原文段落 + 本段作用标签(短摘录自动放大字号)。"""
    para = E(str(c.get("para", "")))
    role = E(str(c.get("role", "") or ""))
    text = E(c.get("text", "") or "")
    focus = E(str(c.get("focus", "") or ""))
    # 字号随摘录长度自适应:关键句特写(≤40 字)放大,长摘录收小防溢出
    nlen = len(c.get("text", "") or "")
    tsize = 46 if nlen <= 40 else (40 if nlen <= 100 else 36)
    parts = ['<div class="inner plain" style="padding:0 320px;">',
             '<div style="display:flex;align-items:center;gap:24px;margin-bottom:40px;">',
             f'<span id="f{i}-chip" style="display:inline-block;padding:6px 22px;border:1px solid {style["primary"]};'
             f'border-radius:999px;font-family:{style["font_bold"]};font-size:22px;color:{style["primary"]};">原文 · 第{para}段</span>']
    if role:
        parts.append(f'<span id="f{i}-role" style="display:inline-block;padding:6px 22px;background:{style["primary"]};'
                     f'border-radius:999px;font-family:{style["font_bold"]};font-size:22px;color:{style["bg"]};">本段作用:{role}</span>')
    parts.append("</div>")
    parts.append(f'<div id="f{i}-box" style="background:{style["card"]};border:1px solid {style["card_border"]};'
                 f'border-radius:{style["radius"]}px;padding:48px 60px;position:relative;max-height:640px;overflow:hidden;">'
                 f'<div style="position:absolute;left:0;top:0;bottom:0;width:6px;background:{style["primary"]};'
                 f'border-radius:3px 0 0 3px;"></div>'
                 f'<div id="f{i}-txt" style="font-family:{style["font_title"]};font-size:{tsize}px;color:{style["text"]};'
                 f'line-height:1.95;">{text}</div></div>')
    if focus:
        parts.append(f'<div id="f{i}-focus" style="margin-top:36px;display:flex;align-items:center;gap:18px;">'
                     f'<span style="font-family:{style["font_bold"]};font-size:24px;color:{style["accent2"]};">注意</span>'
                     f'<span style="font-family:{style["font_body"]};font-size:25px;color:{style["muted"]};">{focus}</span></div>')
    parts.append("</div>")
    js = [f'tl.from("#f{i}-chip",{{y:12,autoAlpha:0,duration:0.4,ease:"power2.out"}},{S}+0.2);',
          f'tl.from("#f{i}-role",{{y:12,autoAlpha:0,duration:0.4,ease:"power2.out"}},{S}+0.3);',
          f'tl.from("#f{i}-box",{{y:30,autoAlpha:0,duration:0.5,ease:"power2.out"}},{S}+0.45);']
    if focus:
        js.append(f'tl.from("#f{i}-focus",{{autoAlpha:0,duration:0.4}},{S}+0.8);')
    return _wrap(i, style, deco_body(style), "".join(parts)), "", js


def _kind_color(style, kind):
    """批注类型 → (字色, 底色, 边框色)。过渡类用描边样式(底色 None)。"""
    prim, acc, deep = style["primary"], style["accent2"], style["deep"]
    cyan = style.get("cyan")
    if kind == "论点":
        return style["bg"], prim, prim
    if kind == "论据":
        return deep, acc, acc
    if kind == "对策":
        return style["bg"], deep, deep
    if kind == "分析":
        return deep, (cyan or prim), (cyan or prim)
    if kind == "金句":
        return deep, acc, acc
    return None, None, prim  # 过渡等:描边样式


def _annotation(i, c, style, S):
    """逐句批注页:原句逐字展示 + 类型标注(论点/论据/分析/对策…) + 老师批注。"""
    sens = c.get("sentences") or []
    n = len(sens)
    fsize = 40 if n == 1 else (34 if n == 2 else 30)
    para = c.get("para")
    parts = ['<div class="inner left" style="padding:0 320px;">',
             f'<div id="f{i}-title" style="font-family:{style["font_title"]};font-size:42px;'
             f'color:{style["deep"]};margin-bottom:52px;">逐句批注'
             + (f' · 第{int(para)}段' if isinstance(para, int) else "") + "</div>"]
    js = [f'tl.from("#f{i}-title",{{y:16,autoAlpha:0,duration:0.4,ease:"power2.out"}},{S}+0.2);']
    for k, s in enumerate(sens):
        kind = str(s.get("kind") or "")
        txt = E(s.get("text") or "")
        note = E(str(s.get("note") or ""))
        ctext, cbg, cborder = _kind_color(style, kind)
        bid = f"f{i}-b{k+1}"
        parts.append(f'<div id="{bid}" style="display:flex;align-items:flex-start;gap:28px;margin-bottom:40px;">')
        if cbg:
            parts.append(f'<span style="flex:none;margin-top:6px;display:inline-block;padding:4px 18px;'
                         f'border-radius:999px;background:{cbg};color:{ctext};border:1px solid {cborder};'
                         f'font-family:{style["font_bold"]};font-size:20px;">{E(kind)}</span>')
        else:
            parts.append(f'<span style="flex:none;margin-top:6px;display:inline-block;padding:4px 18px;'
                         f'border-radius:999px;border:1px solid {cborder};color:{style["primary"]};'
                         f'font-family:{style["font_bold"]};font-size:20px;">{E(kind)}</span>')
        parts.append('<div style="flex:1;min-width:0;">')
        parts.append(f'<div style="display:flex;align-items:stretch;gap:22px;">'
                     f'<div style="flex:none;width:5px;border-radius:2px;background:{cbg or cborder};"></div>'
                     f'<div style="font-family:{style["font_title"]};font-size:{fsize}px;color:{style["text"]};'
                     f'line-height:1.6;">{txt}</div></div>')
        parts.append(f'<div style="margin-top:14px;display:flex;gap:16px;align-items:baseline;">'
                     f'<span style="font-family:{style["font_bold"]};font-size:22px;color:{style["primary"]};">批注</span>'
                     f'<span style="font-family:{style["font_body"]};font-size:24px;color:{style["muted"]};'
                     f'line-height:1.7;">{note}</span></div>')
        parts.append("</div></div>")
        js.append(f'tl.from("#{bid}",{{x:26,autoAlpha:0,duration:0.5,ease:"power3.out"}},{S}+{0.4 + k * 0.3});')
    parts.append("</div>")
    return _wrap(i, style, deco_body(style), "".join(parts)), "", js


def _method(i, c, style, S):
    """写法提炼页:把本段/本章的写法抽象成可迁移的板书卡片。"""
    cards = c.get("cards") or []
    parts = ['<div class="inner plain" style="padding:0 320px;">',
             f'<div id="f{i}-eyebrow" style="font-family:{style["font_bold"]};font-size:24px;'
             f'color:{style["primary"]};letter-spacing:0.25em;margin-bottom:20px;">可迁移写法</div>',
             f'<div id="f{i}-title" style="font-family:{style["font_title"]};font-size:44px;'
             f'color:{style["deep"]};margin-bottom:64px;">{E(c.get("title") or "")}</div>',
             '<div style="display:flex;gap:40px;">']
    js = [f'tl.from("#f{i}-eyebrow",{{autoAlpha:0,duration:0.4}},{S}+0.15);',
          f'tl.from("#f{i}-title",{{y:16,autoAlpha:0,duration:0.4,ease:"power2.out"}},{S}+0.25);']
    for n, card in enumerate(cards):
        cid = f"f{i}-m{n+1}"
        parts.append(f'<div id="{cid}" style="flex:1;background:{style["card"]};'
                     f'border:1px solid {style["card_border"]};border-radius:{style["radius"]}px;'
                     f'padding:36px 32px;display:flex;flex-direction:column;min-height:300px;position:relative;">'
                     f'<div style="position:absolute;left:0;right:0;top:0;height:5px;'
                     f'border-radius:{style["radius"]}px {style["radius"]}px 0 0;background:{style["accent2"]};"></div>'
                     f'<div style="font-family:{style["font_bold"]};font-size:24px;color:{style["primary"]};'
                     f'letter-spacing:0.1em;margin-bottom:24px;">{E(card.get("id", f"{n+1:02d}"))}</div>'
                     f'<div style="font-family:{style["font_title"]};font-size:30px;color:{style["text"]};'
                     f'line-height:1.45;margin-bottom:18px;">{E(card.get("heading", ""))}</div>'
                     f'<div style="font-family:{style["font_body"]};font-size:22px;color:{style["muted"]};'
                     f'line-height:1.75;">{E(card.get("note", ""))}</div></div>')
        js.append(f'tl.from("#{cid}",{{y:36,autoAlpha:0,scale:0.985,duration:0.45,ease:"power3.out"}},{S}+{0.5 + n * 0.18});')
    parts += ["</div>", "</div>"]
    return _wrap(i, style, deco_body(style), "".join(parts)), "", js


# ───────────────────────────── 结尾署名 ─────────────────────────────

def _closing(i, c, style, S):
    k = style["key"]
    source = c.get("source", "")
    author = c.get("author", "")
    credit = f"来源:{source}" + (f" / 作者:{author}" if author else "")
    parts = ['<div class="inner center" style="padding:0 320px;padding-top:120px;">']
    if style["deco_style"] == "wash":
        parts.append(f'<div id="f{i}-seal" style="width:52px;height:52px;border-radius:8px;background:#A63A2B;'
                     f'color:{style["bg"]};font-family:{style["font_title"]};font-size:30px;display:flex;'
                     f'align-items:center;justify-content:center;margin-bottom:56px;">论</div>')
        js = [f'tl.from("#f{i}-seal",{{scale:0.8,autoAlpha:0,duration:0.5,ease:"power2.out"}},{S}+0.1);']
    else:
        js = []
    if style.get("cyan"):
        line_style = (f"width:300px;height:3px;border-radius:2px;"
                      f"background:linear-gradient(90deg,{style['primary']},{style.get('cyan', style['primary'])});")
    elif style["deco_style"] == "wash":
        line_style = f"width:120px;height:2px;background:{style['accent2']};"
    else:
        line_style = f"width:120px;height:2px;background:{style['primary']};"
    parts.append(f'<div id="f{i}-line" style="{line_style}margin-bottom:56px;"></div>')
    parts.append(f'<div id="f{i}-cred" style="font-family:{style["font_body"]};font-size:28px;'
                 f'color:{style["muted"]};">{E(credit)}</div>')
    parts.append(f'<div id="f{i}-ttl" style="font-family:{style["font_title"]};font-size:38px;'
                 f'color:{style["deep"]};margin-top:72px;">{E(c.get("title", "") or "")}</div>')
    parts.append("</div>")
    js += [
        f'tl.from("#f{i}-line",{{scaleX:0,duration:0.5,ease:"power2.out"}},{S}+0.2);',
        f'tl.from("#f{i}-cred",{{autoAlpha:0,duration:0.4}},{S}+0.5);',
        f'tl.from("#f{i}-ttl",{{y:16,autoAlpha:0,duration:0.5,ease:"power2.out"}},{S}+0.8);',
    ]
    return _wrap(i, style, deco_closing(style), "".join(parts)), "", js


# ───────────────────────────── 字幕 ─────────────────────────────

def render_caption(i, style, words) -> tuple[str, list[str]]:
    """字幕 section HTML + 词级高亮 tween。words:[(word, t0, t1)]"""
    if not words:
        return "", []
    spans = "".join(f'<span id="f{i}-w{n}">{E(w)}</span>' for n, (w, _, _) in enumerate(words))
    html = (f'<section class="clip" id="capsec{i}" data-start="{S_PLACEHOLDER}" data-duration="{D_PLACEHOLDER}" data-track-index="3">'
            f'<div class="cap-wrap"><div class="cap-pill" style="background:{style["caption_bg"]};'
            f'border:1px solid {style["caption_border"]};color:#777777;">{spans}</div></div></section>')
    js = []
    for n, (w, t0, t1) in enumerate(words):
        js.append(f'tl.set("#f{i}-w{n}",{{color:"{style["caption_cur"]}",'
                  f'borderBottom:"2px solid {style["caption_cur"]}"}},##S##+{t0:.2f});')
        js.append(f'tl.set("#f{i}-w{n}",{{color:"{style["text"]}",borderBottom:"2px solid transparent"}},##S##+{t1:.2f});')
    return html, js
