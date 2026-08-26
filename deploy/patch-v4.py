# -*- coding: utf-8 -*-
"""补丁 v4:按 CosyVoice3 实测语速(≈1.8 字/秒)重构旁白量规划 + 语速分层 + 校验修正。"""
import re

# ══ 1. analyze.py ══
p = 'server/analyze.py'
s = open(p, encoding='utf-8').read()

# 旁白量规则:按语速分层给出「总旁白字数」
old_rate = '''    # ── 时长适配规则(详略由目标时长决定) ──
    if target_duration <= 90:
        frames_rule = "6-10 帧"
        vo_rule = "每帧 15-30 字,短促有力,只留核心论点与 1 组最强论据"'''
new_rate = '''    # ── 时长适配规则(详略由目标时长决定;旁白字数按 CosyVoice3 实测语速≈1.8 字/秒规划) ──
    if target_duration <= 90:
        frames_rule = "6-10 帧"
        vo_rule = f"每帧 15-28 字,短促有力,只留核心论点与 1 组最强论据;总旁白字数 ≈ {int(target_duration * 1.8)} 字"'''
assert old_rate in s, 'rate 60 未匹配'
s = s.replace(old_rate, new_rate)

s = s.replace('''    elif target_duration <= 180:
        frames_rule = "9-13 帧"
        vo_rule = "每帧 18-38 字,论证链完整呈现"''', '''    elif target_duration <= 180:
        frames_rule = "9-13 帧"
        vo_rule = f"每帧 18-36 字,论证链完整呈现;总旁白字数 ≈ {int(target_duration * 1.8)} 字"''')

s = s.replace('''    elif target_duration <= 360:
        frames_rule = "12-18 帧"
        vo_rule = "每帧 20-45 字,论证逐层展开、数据充分"''', '''    elif target_duration <= 360:
        frames_rule = "12-18 帧"
        vo_rule = f"每帧 22-50 字,论证逐层展开、数据充分;总旁白字数 ≈ {int(target_duration * 1.6)} 字"''')

s = s.replace('''        frames_rule = "14-20 帧"
        vo_rule = (f"每帧 40-60 字,总旁白字数必须 ≥ {int(target_duration * 2.6)} 字;"
                   "论证完全展开、逐层深化;允许用不同表述重述核心论点、每章小结、首尾呼应占满时长,禁止编造新观点")''', '''        frames_rule = "14-20 帧"
        vo_rule = (f"每帧 30-60 字,总旁白字数 ≈ {int(target_duration * 1.45)} 字;"
                   "论证完全展开、逐层深化;允许用不同表述重述核心论点、每章小结、首尾呼应占满时长,禁止编造新观点")''')

# 提示词中的总字数参考同步改
s = s.replace("- 旁白:{vo_rule};总旁白字数 ≈ {round(target_duration * 4.2)} 字",
              "- 旁白:{vo_rule}")

# 校验:单帧上限 60→75;旁白量下限按 1.25×;时长下限放宽到 0.3×
s = s.replace('''            if len(vo) > 60:
                errs.append(f"帧{i+1}({t}) 旁白超 60 字")''', '''            if len(vo) > 75:
                errs.append(f"帧{i+1}({t}) 旁白超 75 字")''')
s = s.replace('''    if total < 0.35 * target_duration or total > 2.5 * target_duration:
        errs.append(f"总时长 {total:.1f}s 与目标 {target_duration}s 偏差过大")''', '''    if total < 0.3 * target_duration or total > 2.5 * target_duration:
        errs.append(f"总时长 {total:.1f}s 与目标 {target_duration}s 偏差过大")''')
s = s.replace('''    vo_total = sum(len((f.get("voiceover") or "").strip()) for f in frames)
    if target_duration >= 300 and vo_total < target_duration * 2.4:
        errs.append(f"旁白总量 {vo_total} 字不足(≥300s 视频需 ≥{int(target_duration * 2.4)} 字,请加长每帧旁白/增加帧数)")''', '''    vo_total = sum(len((f.get("voiceover") or "").strip()) for f in frames)
    if vo_total < target_duration * 1.2:
        errs.append(f"旁白总量 {vo_total} 字不足(需 ≥{int(target_duration * 1.2)} 字,请加长每帧旁白/增加帧数)")''')

# 帧数规则同步(时长与旁白量匹配后,帧数规则保留)
open(p, 'w', encoding='utf-8').write(s)
print('analyze.py v4 patched')

# ══ 2. main.py:语速分层(实测语速 1.8c/s 基准) + 帧尾余量 ══
p = 'server/main.py'
s = open(p, encoding='utf-8').read()
old = '''    speed = 1.0
    if target > 420:
        speed = 0.8
    elif target > 240:
        speed = 0.85   # 长视频语速稍缓,更庄重'''
new = '''    speed = 1.0
    if target > 420:
        speed = 0.8
    elif target > 240:
        speed = 0.85   # 长视频语速稍缓,更庄重
    elif target <= 120:
        speed = 1.05'''
assert old in s, 'speed 未匹配'
s = s.replace(old, new)
# 帧尾余量:短视频收紧
s = s.replace("tts.apply_real_durations(script, vo)",
              "tts.apply_real_durations(script, vo, tail_pad=0.9 if target <= 120 else 1.4)")
open(p, 'w', encoding='utf-8').write(s)
print('main.py v4 patched')

# ══ 3. tts.py:apply_real_durations 支持 tail_pad ══
p = 'server/tts.py'
s = open(p, encoding='utf-8').read()
old = '''def apply_real_durations(script: dict, vo: dict) -> None:
    """根据真实旁白时长重算每帧 duration(开场/结尾固定,VO 帧=旁白+1.2s)。"""
    total = 0.0
    for f in script["frames"]:
        t = f["type"]
        idx = f["index"]
        if t == "opening":
            f["duration"] = 7.0
        elif t == "closing":
            f["duration"] = 4.5
        elif idx in vo:
            f["duration"] = round(max(vo[idx]["duration"] + 1.4, 4.0), 2)
        else:
            f["duration"] = round(float(f.get("duration") or 6.0), 2)
        total += f["duration"]
    script["duration_sec"] = round(total, 1)'''
new = '''def apply_real_durations(script: dict, vo: dict, tail_pad: float = 1.4) -> None:
    """根据真实旁白时长重算每帧 duration(开场/结尾固定,VO 帧=旁白+tail_pad)。"""
    total = 0.0
    for f in script["frames"]:
        t = f["type"]
        idx = f["index"]
        if t == "opening":
            f["duration"] = 7.0
        elif t == "closing":
            f["duration"] = 4.5
        elif idx in vo:
            f["duration"] = round(max(vo[idx]["duration"] + tail_pad, 4.0), 2)
        else:
            f["duration"] = round(float(f.get("duration") or 6.0), 2)
        total += f["duration"]
    script["duration_sec"] = round(total, 1)'''
assert old in s, 'apply_real_durations 未匹配'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('tts.py v4 patched')
print('ALL v4 DONE')
