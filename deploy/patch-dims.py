# -*- coding: utf-8 -*-
"""templates.py 分支改造:风格键分支 → 维度属性(deco_style/cyan/radius)。"""
p = 'server/builder/templates.py'
s = open(p, encoding='utf-8').read()

# _opening 开场装饰分支
old = '''    if k == "solemn-red":
        js.append(f'tl.from("#gold-star",{{scale:0.6,autoAlpha:0,duration:0.9,ease:"power2.out",svgOrigin:"960 290"}},{S}+0.1);')
    elif k == "academic-ink":
        js.append(f'tl.from("#seal",{{scale:0.7,autoAlpha:0,duration:0.8,ease:"power2.out",svgOrigin:"960 320"}},{S}+0.1);')'''
new = '''    if style["deco_style"] == "orbit":
        js.append(f'tl.from("#gold-star",{{scale:0.6,autoAlpha:0,duration:0.9,ease:"power2.out",svgOrigin:"960 290"}},{S}+0.1);')
    elif style["deco_style"] == "wash":
        js.append(f'tl.from("#seal",{{scale:0.7,autoAlpha:0,duration:0.8,ease:"power2.out",svgOrigin:"960 320"}},{S}+0.1);')'''
assert old in s, 'opening 未匹配'
s = s.replace(old, new)

# _section
s = s.replace("ghost_color = style[\"ghost\"] if k == \"academic-ink\" else style[\"ghost\"]",
              "ghost_color = style[\"ghost\"]")

# _statement 竖条渐变(cyan 配色才有)
old = '''    bar_bg = (f"linear-gradient(180deg,{style['primary']},{style.get('cyan', style['primary'])})"
              if k == "modern-blue" else style["primary"])'''
new = '''    bar_bg = (f"linear-gradient(180deg,{style['primary']},{style.get('cyan', style['primary'])})"
              if style.get("cyan") else style["primary"])'''
assert old in s, 'statement bar 未匹配'
s = s.replace(old, new)

# _elaboration 圆角与卡片装饰
s = s.replace('radius = {"solemn-red": 12, "academic-ink": 4, "modern-blue": 16}[k]',
              'radius = style["radius"]')
s = s.replace('        if k == "modern-blue":', '        if style.get("cyan"):')
s = s.replace('        if k == "solemn-red":', '        if style["deco_style"] == "orbit":')

# _quote 关键词色
s = s.replace('kw_color = style["accent2"] if k == "modern-blue" else style["primary"]',
              'kw_color = style["accent2"] if style.get("cyan") else style["primary"]')

# _data 柱状图最高柱与折线端点色
s = s.replace('(1.0, style["accent2"] if k == "modern-blue" else style["primary"])',
              '(1.0, style["accent2"] if style.get("cyan") else style["primary"])')
s = s.replace('fill="{style["accent2"] if k == "modern-blue" else style["primary"]}"/>',
              'fill="{style["accent2"] if style.get("cyan") else style["primary"]}"/>')

# _points 序号样式按背景风格
old = '''        if k == "solemn-red":
            parts.append(f'<span style="width:10px;height:10px;border-radius:50%;background:{style["primary"]};flex:none;"></span>'
                         f'<span style="font-family:{style["font_bold"]};font-size:30px;color:{style["primary"]};'
                         f'width:64px;flex:none;">{n+1:02d}</span>')
        elif k == "academic-ink":'''
new = '''        if style["deco_style"] == "orbit":
            parts.append(f'<span style="width:10px;height:10px;border-radius:50%;background:{style["primary"]};flex:none;"></span>'
                         f'<span style="font-family:{style["font_bold"]};font-size:30px;color:{style["primary"]};'
                         f'width:64px;flex:none;">{n+1:02d}</span>')
        elif style["deco_style"] == "wash":'''
assert old in s, 'points 分支未匹配'
s = s.replace(old, new)
s = s.replace('        if k in ("academic-ink", "modern-blue"):',
              '        if style["deco_style"] in ("wash", "tech"):')
s = s.replace('line_color = style["accent2"] if k == "academic-ink" else style["divider"]',
              'line_color = style["accent2"] if style["deco_style"] == "wash" else style["divider"]')

# _process 箭头与圈内字
s = s.replace('arrow_color = {"solemn-red": style["light"], "academic-ink": style["accent2"], "modern-blue": style.get("cyan", style["primary"])}[k]',
              'arrow_color = (style.get("cyan", style["primary"]) if style.get("cyan") '
              'else (style["accent2"] if style["deco_style"] == "wash" else style["light"]))')
s = s.replace('[:2] if k != "academic-ink" else step.get("name", "")[:1]',
              '[:1] if style["deco_style"] == "wash" else step.get("name", "")[:2]')

# _contrast 中线
old = '''    mid_bg = {"solemn-red": style["accent2"], "academic-ink": "#A63A2B",
              "modern-blue": f"linear-gradient(180deg,{style['primary']},{style.get('cyan', style['primary'])})"}[k]'''
new = '''    if style.get("cyan"):
        mid_bg = f"linear-gradient(180deg,{style['primary']},{style.get('cyan', style['primary'])})"
    elif style["deco_style"] == "wash":
        mid_bg = "#A63A2B"
    elif style["deco_style"] == "orbit":
        mid_bg = style["accent2"]
    else:
        mid_bg = style["primary"]'''
assert old in s, 'contrast mid 未匹配'
s = s.replace(old, new)

# _closing 线样式
old = '''    line_style = {"solemn-red": f"width:120px;height:2px;background:{style['primary']};",
                  "academic-ink": f"width:120px;height:2px;background:{style['accent2']};",
                  "modern-blue": f"width:300px;height:3px;border-radius:2px;"
                                 f"background:linear-gradient(90deg,{style['primary']},{style.get('cyan', style['primary'])});"}[k]'''
new = '''    if style.get("cyan"):
        line_style = (f"width:300px;height:3px;border-radius:2px;"
                      f"background:linear-gradient(90deg,{style['primary']},{style.get('cyan', style['primary'])});")
    elif style["deco_style"] == "wash":
        line_style = f"width:120px;height:2px;background:{style['accent2']};"
    else:
        line_style = f"width:120px;height:2px;background:{style['primary']};"'''
assert old in s, 'closing line 未匹配'
s = s.replace(old, new)

# closing 印章(背景 wash)
s = s.replace('    if k == "academic-ink":\n        parts.append(f\'<div id="f{i}-seal"',
              '    if style["deco_style"] == "wash":\n        parts.append(f\'<div id="f{i}-seal"')

# 移除残留的 k 变量赋值(保留无害,但确认没有遗漏分支)
import re
leftovers = re.findall(r'[= ]k == "[a-z-]+"', s)
print('残留 k 分支:', leftovers if leftovers else '无')
open(p, 'w', encoding='utf-8').write(s)
print('templates.py patched')
