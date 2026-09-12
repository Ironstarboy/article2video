# -*- coding: utf-8 -*-
"""风格系统 v2:四维度组合(字体 × 配色 × 背景 × 动效)。

每个维度独立可选,由 get_style() 合成完整 style dict;预设(原三套经典风格)
是四维度的默认组合。模板层(templates.py)只依赖 style dict 的通用键:
bg/primary/deep/accent2/card/card_border/ghost/text/muted/light/divider/
caption_cur/caption_bg/caption_border/font_title/font_body/font_bold/
voice/bgm/title_size/radius/deco_style/motion/overlap/cyan(可选)
"""

# ═══════════ 一、配色(Palettes) ═══════════

PALETTES = {
    "china-red": {
        "name": "中国红 · 政论经典",
        "desc": "暖白底,中国红点睛,金色仪式感",
        "bg": "#FAFAF8", "primary": "#C8161D", "deep": "#8F1118", "accent2": "#C9A063",
        "card": "#F9E8E9", "card_border": "rgba(200,22,29,0.18)", "ghost": "rgba(200,22,29,0.08)",
        "text": "#222222", "muted": "#666666", "light": "#969696", "divider": "#E5E5E5",
        "caption_cur": "#C8161D", "caption_bg": "#F9E8E9", "caption_border": "rgba(200,22,29,0.18)",
        "voice": "male", "bgm": "solemn-red.mp3", "radius": 12, "title_size": 88,
    },
    "ink-green": {
        "name": "黛青墨韵 · 书香学术",
        "desc": "宣纸米白,黛青墨色,朱砂印章一点",
        "bg": "#F6F1E4", "primary": "#1F4E5F", "deep": "#16394A", "accent2": "#8B5E34",
        "card": "#EFE9DA", "card_border": "rgba(139,94,52,0.35)", "ghost": "rgba(31,78,95,0.07)",
        "text": "#2A2A2A", "muted": "#5F5A50", "light": "#9A9384", "divider": "#D8D2C2",
        "caption_cur": "#1F4E5F", "caption_bg": "#EFE9DA", "caption_border": "rgba(139,94,52,0.35)",
        "voice": "female", "bgm": "academic-ink.mp3", "radius": 4, "title_size": 84,
    },
    "tech-blue": {
        "name": "科技蓝 · 时代前沿",
        "desc": "冷白底,科技蓝与亮青,琥珀数据高亮",
        "bg": "#F5F8FC", "primary": "#0A4DA3", "deep": "#0A2A5E", "accent2": "#FFB400",
        "card": "#E8F1FA", "card_border": "rgba(10,77,163,0.18)", "ghost": "rgba(10,77,163,0.07)",
        "text": "#1A2B3C", "muted": "#5A6B7D", "light": "#8CA0B3", "divider": "#E3EAF2",
        "caption_cur": "#0A4DA3", "caption_bg": "#E8F1FA", "caption_border": "rgba(10,77,163,0.18)",
        "voice": "male_narrator", "bgm": "modern-blue.mp3", "radius": 16, "title_size": 86,
        "cyan": "#00A8CC",
    },
    "editor-navy": {
        "name": "藏蓝赭红 · 编辑部",
        "desc": "暖白纸感,深藏蓝结构,赭红强调",
        "bg": "#F8F6F3", "primary": "#A61B29", "deep": "#1E3A5F", "accent2": "#B08A4E",
        "card": "#F3EFE8", "card_border": "rgba(30,58,95,0.22)", "ghost": "rgba(30,58,95,0.07)",
        "text": "#2D2D2D", "muted": "#6B6B6B", "light": "#9A948B", "divider": "#E5E0D8",
        "caption_cur": "#A61B29", "caption_bg": "#F3EFE8", "caption_border": "rgba(30,58,95,0.22)",
        "voice": "male", "bgm": "solemn-red.mp3", "radius": 8, "title_size": 86,
    },
}

# ═══════════ 二、字体(Fonts) ═══════════

FONTS = {
    "song-title": {
        "name": "宋体标题 · 黑体正文",
        "desc": "庄重正统,标题思源宋体 Heavy",
        "font_title": "'SongHeavy',serif", "font_body": "'Sans',sans-serif", "font_bold": "'SansBold',sans-serif",
    },
    "all-song": {
        "name": "全宋体 · 学术书卷",
        "desc": "正文亦用宋体,学者书斋气",
        "font_title": "'SongHeavy',serif", "font_body": "'Song',serif", "font_bold": "'SansBold',sans-serif",
    },
    "all-sans": {
        "name": "全黑体 · 现代明快",
        "desc": "全黑体,现代感与可读性",
        "font_title": "'SansBold',sans-serif", "font_body": "'Sans',sans-serif", "font_bold": "'SansBold',sans-serif",
    },
}

# ═══════════ 三、背景装饰(Backgrounds) ═══════════

BACKGROUNDS = {
    "orbit": {"name": "地球环 · 经纬网格", "desc": "政论经典,环线网格点阵"},
    "wash": {"name": "水墨远山 · 竹枝", "desc": "学术留白,远山竹影印章"},
    "tech": {"name": "科技网格 · 折线", "desc": "现代数据感,光晕折线"},
    "minimal": {"name": "极简留白 · 细线", "desc": "纯净克制,仅细网格与色条"},
}

# ═══════════ 四、动效(Motions) ═══════════

MOTIONS = {
    "dignified": {"name": "庄重缓叙", "desc": "慢 crossfade 0.7s,克制入场"},
    "brisk": {"name": "明快节奏", "desc": "crossfade 0.45s,支持上推转场"},
    "still": {"name": "极简静止", "desc": "轻 fade 0.3s,几乎无位移"},
}

# ═══════════ 预设(经典三套 = 四维组合) ═══════════

PRESETS = {
    "solemn-red": {"font": "song-title", "palette": "china-red", "bg": "orbit", "motion": "dignified",
                   "name": "庄重肃穆 · 中国红"},
    "academic-ink": {"font": "all-song", "palette": "ink-green", "bg": "wash", "motion": "dignified",
                     "name": "清雅学术 · 墨黛青"},
    "modern-blue": {"font": "all-sans", "palette": "tech-blue", "bg": "tech", "motion": "brisk",
                    "name": "现代锐意 · 科技蓝"},
}

# 动效参数
MOTION_PARAMS = {
    "dignified": {"overlap": 0.7, "push_up": False},
    "brisk": {"overlap": 0.45, "push_up": True},
    "still": {"overlap": 0.3, "push_up": False},
}

# ═══════════ 数字人形象(Avatars) ═══════════
# 固定一个默认形象,不在前端让用户选;换图只需替换 file 指向的图片
# (图片相对 assets/),或用环境变量 TTV_AVATAR_IMAGE 覆盖。
AVATARS = {
    "jinli": {
        "name": "金立",
        "desc": "复旦大学校长金立,新闻播报形象",
        "file": "avatars/jinli.png",
    },
}
DEFAULT_AVATAR = "jinli"


def avatar_file(key: str | None = None) -> str:
    """形象键 → assets/ 下的相对路径;未知键回落到默认形象。"""
    a = AVATARS.get(key or DEFAULT_AVATAR) or AVATARS[DEFAULT_AVATAR]
    return a["file"]


def _combo_key(combo: dict) -> str:
    return f"{combo['font']}|{combo['palette']}|{combo['bg']}|{combo['motion']}"


def resolve_combo(style: str | None, font: str | None, palette: str | None,
                  bg: str | None, motion: str | None) -> dict:
    """由 preset 或四维参数解析最终组合。"""
    base = PRESETS.get(style or "") or PRESETS["solemn-red"]
    return {
        "preset": style if style in PRESETS else None,
        "font": font if font in FONTS else base["font"],
        "palette": palette if palette in PALETTES else base["palette"],
        "bg": bg if bg in BACKGROUNDS else base["bg"],
        "motion": motion if motion in MOTIONS else base["motion"],
    }


def get_style(combo: dict | str) -> dict:
    """由组合(或预设键)合成完整 style dict,供模板层使用。"""
    if isinstance(combo, str):
        combo = resolve_combo(combo, None, None, None, None)
    pal = PALETTES[combo["palette"]]
    fnt = FONTS[combo["font"]]
    mp = MOTION_PARAMS[combo["motion"]]
    style = dict(pal)
    style.update(fnt)
    style.update({
        "key": _combo_key(combo),
        "combo": combo,
        "deco_style": combo["bg"],
        "motion": combo["motion"],
        "overlap": mp["overlap"],
        "push_up_ok": mp["push_up"],
    })
    return style


def combo_label(combo: dict) -> str:
    """组合的人类可读描述(注入 DeepSeek 提示词)。"""
    pal = PALETTES[combo["palette"]]
    fnt = FONTS[combo["font"]]
    bgd = BACKGROUNDS[combo["bg"]]
    mot = MOTIONS[combo["motion"]]
    return (f"{pal['name']}({pal['desc']});字体:{fnt['name']}({fnt['desc']});"
            f"背景:{bgd['name']}({bgd['desc']});动效:{mot['name']}({mot['desc']});"
            f"主色 {pal['primary']},标题色 {pal['deep']},点缀 {pal['accent2']},底色 {pal['bg']}。")


# ═══════════ SVG 装饰(按 deco_style 分发) ═══════════

def _grid(style, opacity, color=None, verticals=(160, 320, 480, 640, 800, 960, 1120, 1280, 1440, 1600, 1760),
          horizontals=(180, 360, 540, 720, 900)):
    c = color or ("#C9C9C9" if style["deco_style"] == "orbit" else style["accent2"])
    v = "".join(f'<path d="M{x} 0V1080"/>' for x in verticals)
    h = "".join(f'<path d="M0 {y}H1920"/>' for y in horizontals)
    return f'<g fill="none" stroke="{c}" stroke-width="1" opacity="{opacity}">{v}{h}</g>'


def _deco_orbit(style):
    return f'''{_grid(style, 0.12)}
<g fill="none" stroke="{style["primary"]}">
<circle cx="1540" cy="400" r="360" opacity="0.10"/><circle cx="1540" cy="400" r="290" opacity="0.07"/><circle cx="1540" cy="400" r="225" opacity="0.05"/></g>
<g fill="{style["primary"]}" opacity="0.10">
<circle cx="90" cy="90" r="3"/><circle cx="126" cy="90" r="3"/><circle cx="162" cy="90" r="3"/><circle cx="198" cy="90" r="3"/><circle cx="234" cy="90" r="3"/><circle cx="270" cy="90" r="3"/>
<circle cx="90" cy="126" r="3"/><circle cx="126" cy="126" r="3"/><circle cx="162" cy="126" r="3"/><circle cx="198" cy="126" r="3"/><circle cx="234" cy="126" r="3"/><circle cx="270" cy="126" r="3"/>
<circle cx="90" cy="162" r="3"/><circle cx="126" cy="162" r="3"/><circle cx="162" cy="162" r="3"/><circle cx="198" cy="162" r="3"/><circle cx="234" cy="162" r="3"/><circle cx="270" cy="162" r="3"/></g>'''


def _deco_wash(style):
    return f'''<g fill="none" stroke="{style["deep"]}" stroke-linecap="round">
<path d="M0 1010 Q240 900 480 975 T960 960 T1440 985 T1920 950" stroke-width="2" opacity="0.18"/>
<path d="M0 1045 Q280 960 560 1015 T1040 1000 T1520 1020 T1920 990" stroke-width="1.5" opacity="0.12"/>
<path d="M0 1070 Q320 1010 640 1050 T1280 1035 T1920 1055" stroke-width="1" opacity="0.08"/></g>
<g stroke="{style["primary"]}" fill="none" opacity="0.28">
<path d="M1720 90 L1720 420" stroke-width="3"/>
<path d="M1720 140 L1660 120 L1715 150" stroke-width="2"/>
<path d="M1720 210 L1780 185 L1725 220" stroke-width="2"/>
<path d="M1720 300 L1655 275 L1712 310" stroke-width="2"/></g>
<g fill="{style["primary"]}" opacity="0.20">
<ellipse cx="1662" cy="118" rx="34" ry="9" transform="rotate(-18 1662 118)"/>
<ellipse cx="1778" cy="183" rx="34" ry="9" transform="rotate(16 1778 183)"/>
<ellipse cx="1657" cy="273" rx="34" ry="9" transform="rotate(-16 1657 273)"/></g>
{_grid(style, 0.05)}'''


def _deco_tech(style):
    return f'''{_grid(style, 0.09, color=style["primary"])}
<radialGradient id="glow" cx="0.5" cy="0.5" r="0.5">
<stop offset="0%" stop-color="{style.get("cyan", style["primary"])}" stop-opacity="0.10"/>
<stop offset="100%" stop-color="{style.get("cyan", style["primary"])}" stop-opacity="0"/></radialGradient>
<circle cx="1600" cy="260" r="560" fill="url(#glow)"/>
<g fill="none"><path d="M120 940 L420 800 L700 830 L1020 620 L1360 650 L1760 430" stroke="{style.get("cyan", style["primary"])}" stroke-width="3" opacity="0.30"/></g>
<g fill="{style["accent2"]}" opacity="0.5">
<circle cx="120" cy="940" r="6"/><circle cx="420" cy="800" r="6"/><circle cx="700" cy="830" r="6"/><circle cx="1020" cy="620" r="6"/><circle cx="1360" cy="650" r="6"/><circle cx="1760" cy="430" r="6"/></g>'''


def _deco_minimal(style):
    return f'''{_grid(style, 0.05, color=style["divider"], verticals=(320, 640, 960, 1280, 1600), horizontals=(360, 720))}
<line x1="0" y1="1010" x2="1920" y2="1010" stroke="{style["divider"]}" stroke-width="1" opacity="0.6"/>
<rect x="60" y="60" width="4" height="960" fill="{style["primary"]}" opacity="0.10"/>'''


_DECO_OPEN = {
    "orbit": lambda st: f'''{_deco_orbit(st)}
<g id="gold-star" transform="translate(960,290)">
<path d="M0,-40 L11.8,-12.4 L40,-12.4 L19,8.1 L27,35.3 L0,19.4 L-27,35.3 L-19,8.1 L-40,-12.4 L-11.8,-12.4 Z" fill="{st["accent2"]}" opacity="0.9"/></g>
<g fill="none">
<path d="M0 900 Q960 830 1920 900" stroke="{st["primary"]}" stroke-width="3" opacity="0.14"/>
<path d="M0 960 Q960 890 1920 960" stroke="{st["primary"]}" stroke-width="2" opacity="0.08"/>
<path d="M0 980 Q960 960 1920 980" stroke="{st["accent2"]}" stroke-width="1.5" opacity="0.35"/></g>''',
    "wash": lambda st: f'''{_deco_wash(st)}
<g id="seal" transform="translate(960,320)">
<rect x="-44" y="-44" width="88" height="88" rx="8" fill="#A63A2B" opacity="0.92"/>
<text x="0" y="14" font-family="'SongHeavy',serif" font-size="52" fill="{st["bg"]}" text-anchor="middle">论</text></g>''',
    "tech": lambda st: f'''{_deco_tech(st)}
<g opacity="0.35">
<rect x="1640" y="60" width="200" height="96" rx="10" fill="none" stroke="{st["primary"]}" stroke-width="1.5"/>
<circle cx="1680" cy="90" r="5" fill="{st.get("cyan", st["primary"])}"/><line x1="1700" y1="90" x2="1820" y2="90" stroke="{st["primary"]}" stroke-width="2" opacity="0.5"/>
<line x1="1680" y1="120" x2="1780" y2="120" stroke="{st["primary"]}" stroke-width="2" opacity="0.3"/></g>''',
    "minimal": lambda st: f'''{_deco_minimal(st)}
<rect x="860" y="430" width="200" height="3" fill="{st["primary"]}" opacity="0.5"/>''',
}

_DECO_BODY = {
    "orbit": lambda st: f'''{_deco_orbit(st)}
<g stroke="#B9B9B9" stroke-width="2" opacity="0.15" fill="none"><path d="M90 900 L330 760 L610 815 L915 630 L1330 690 L1700 560"/></g>
<g fill="#B9B9B9" opacity="0.22">
<circle cx="90" cy="900" r="5"/><circle cx="330" cy="760" r="5"/><circle cx="610" cy="815" r="5"/><circle cx="915" cy="630" r="5"/><circle cx="1330" cy="690" r="5"/><circle cx="1700" cy="560" r="5"/></g>''',
    "wash": lambda st: f'''{_deco_wash(st)}
<g transform="translate(1800,120)" opacity="0.25">
<rect x="-20" y="-20" width="40" height="40" rx="4" fill="#A63A2B"/>
<text x="0" y="8" font-family="'SongHeavy',serif" font-size="24" fill="{st["bg"]}" text-anchor="middle">论</text></g>''',
    "tech": _deco_tech,
    "minimal": _deco_minimal,
}

_DECO_CLOSING = {
    "orbit": lambda st: f'''{_deco_orbit(st)}
<g fill="none">
<line x1="860" y1="1010" x2="1060" y2="1010" stroke="{st["primary"]}" stroke-width="3" opacity="0.5"/>
<line x1="890" y1="1026" x2="1030" y2="1026" stroke="{st["accent2"]}" stroke-width="1.5" opacity="0.7"/></g>''',
    "wash": lambda st: f'''{_deco_wash(st)}
<line x1="840" y1="1020" x2="1080" y2="1020" stroke="{st["accent2"]}" stroke-width="1.5" opacity="0.5"/>''',
    "tech": lambda st: f'''{_deco_tech(st)}
<linearGradient id="gradBar" x1="0" y1="0" x2="1" y2="0">
<stop offset="0%" stop-color="{st["primary"]}"/><stop offset="100%" stop-color="{st.get("cyan", st["primary"])}"/></linearGradient>
<rect x="810" y="1010" width="300" height="3" rx="1.5" fill="url(#gradBar)" opacity="0.8"/>''',
    "minimal": lambda st: f'''{_deco_minimal(st)}
<line x1="860" y1="1010" x2="1060" y2="1010" stroke="{st["primary"]}" stroke-width="2" opacity="0.6"/>''',
}


def _svg(s, deco, inner):
    return (f'<svg width="1920" height="1080" viewBox="0 0 1920 1080" '
            f'xmlns="http://www.w3.org/2000/svg" style="position:absolute;inset:0;">{deco}{inner}</svg>')


def deco_opening(style) -> str:
    return _svg(style, _DECO_OPEN[style["deco_style"]](style), "")


def deco_body(style) -> str:
    return _svg(style, _DECO_BODY[style["deco_style"]](style), "")


def deco_closing(style) -> str:
    return _svg(style, _DECO_CLOSING[style["deco_style"]](style), "")


def get(key: str) -> dict:
    """兼容旧接口:接受预设键或组合 dict。"""
    if isinstance(key, dict):
        return get_style(key)
    if key in PRESETS:
        return get_style(resolve_combo(key, None, None, None, None))
    raise KeyError(f"未知风格:{key}")
