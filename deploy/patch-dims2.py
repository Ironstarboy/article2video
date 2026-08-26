# -*- coding: utf-8 -*-
"""templates.py 分支改造 v2:短锚点有序替换 + 正则兜底。"""
import re

p = 'server/builder/templates.py'
s = open(p, encoding='utf-8').read()

R = []  # (old, new, count)

# 1) 先处理包含子串的长锚点
R.append(('if k in ("academic-ink", "modern-blue"):',
          'if style["deco_style"] in ("wash", "tech"):'))
R.append(('line_color = style["accent2"] if k == "academic-ink" else style["divider"]',
          'line_color = style["accent2"] if style["deco_style"] == "wash" else style["divider"]'))

# 2) 短锚点全量替换(所有出现处语义一致)
R.append(('if k == "solemn-red":', 'if style["deco_style"] == "orbit":'))
R.append(('elif k == "academic-ink":', 'elif style["deco_style"] == "wash":'))
R.append(('if k == "academic-ink":', 'if style["deco_style"] == "wash":'))
R.append(('if k == "modern-blue":', 'if style.get("cyan"):'))
R.append(('radius = {"solemn-red": 12, "academic-ink": 4, "modern-blue": 16}[k]',
          'radius = style["radius"]'))
R.append(('ghost_color = style["ghost"] if k == "academic-ink" else style["ghost"]',
          'ghost_color = style["ghost"]'))

for old, new in R:
    n = s.count(old)
    if n == 0:
        print('WARN 未找到:', old[:40])
        continue
    s = s.replace(old, new)
    print(f'替换 ×{n}:', old[:40])

# 3) 正则:箭头色 dict
s, n = re.subn(r'arrow_color = \{.*?\}\[k\]',
               'arrow_color = (style.get("cyan", style["primary"]) if style.get("cyan") '
               'else (style["accent2"] if style["deco_style"] == "wash" else style["light"]))',
               s, flags=re.S)
print('箭头色正则 ×', n)

# 4) 流程圈内字
old = '[:2] if k != "academic-ink" else step.get("name", "")[:1]'
new = '[:1] if style["deco_style"] == "wash" else step.get("name", "")[:2]'
n = s.count(old)
assert n, '流程字锚点未找到'
s = s.replace(old, new)
print('流程字 ×', n)

# 5) 对比中线 dict
old = re.compile(r'mid_bg = \{.*?\}\[k\]', re.S)
s, n = old.subn('''if style.get("cyan"):
        mid_bg = f"linear-gradient(180deg,{style['primary']},{style.get('cyan', style['primary'])})"
    elif style["deco_style"] == "wash":
        mid_bg = "#A63A2B"
    elif style["deco_style"] == "orbit":
        mid_bg = style["accent2"]
    else:
        mid_bg = style["primary"]''', s)
print('对比中线正则 ×', n)

# 6) 结尾线样式 dict
old = re.compile(r'line_style = \{.*?\}\[k\]', re.S)
s, n = old.subn('''if style.get("cyan"):
        line_style = (f"width:300px;height:3px;border-radius:2px;"
                      f"background:linear-gradient(90deg,{style['primary']},{style.get('cyan', style['primary'])});")
    elif style["deco_style"] == "wash":
        line_style = f"width:120px;height:2px;background:{style['accent2']};"
    else:
        line_style = f"width:120px;height:2px;background:{style['primary']};"''', s)
print('结尾线正则 ×', n)

leftovers = re.findall(r'[= ]k == "[a-z-]+"|k in \(|k != |k\)', s)
print('残留:', leftovers if leftovers else '无')
open(p, 'w', encoding='utf-8').write(s)
print('DONE')
