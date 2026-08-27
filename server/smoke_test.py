# -*- coding: utf-8 -*-
"""冒烟回归:核心纯函数路径的鲁棒性验证(无外部依赖,不含网络/GPU)。

服务器上运行:
    python3 server/smoke_test.py
"""
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import analyze
import extract
import tts
from builder import styles

FAIL = []


def ok(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f" [{name}]" + (f"  {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


def _raises(fn, exc):
    try:
        fn()
        return False
    except exc:
        return True
    except Exception:
        return False


def _via(fn, arg):
    return lambda: fn(arg)


def _tmp_text(name, content):
    p = Path(__import__("tempfile").gettempdir()) / f"ttv_smoke_{name}"
    p.write_text(content, encoding="utf-8")
    return str(p)


def _article(n=40):
    return ("新质生产力是创新起主导作用的先进生产力质态,特点是创新,关键在质优。"
            "2024年我国全社会研究与试验发展经费投入超过3.6万亿元,发明专利有效量突破500万件。"
            "发展新质生产力,基础在科技创新,路径在产业升级,关键在改革赋能,根基在人才支撑。") * n


# ───────────────────────── extract ─────────────────────────

ok("extract txt 解码", "高质量发展" in extract.extract_text(
    _tmp_text("a.txt", "高质量发展是全面建设社会主义现代化国家的首要任务。" * 12)))
ok("extract md 去标记", "# 标题\n**正文内容**" not in extract.extract_text(
    _tmp_text("b.md", "# 标题\n" + "正文内容," * 60)))
ok("extract 过短拒绝", _raises(lambda: extract.extract_text(_tmp_text("c.txt", "太短")), ValueError))


def _bad_docx():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("junk.txt", "not a docx")
    return buf.getvalue()


ok("extract 无效 docx 友好报错",
   _raises(_via(extract._extract_docx, _bad_docx()), ValueError))


def _valid_docx():
    xml = ("<?xml version='1.0'?><w:document><w:body>"
           + "".join(f"<w:p><w:r><w:t>第{i}段内容,发展新质生产力。</w:t></w:r></w:p>" for i in range(20))
           + "</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


ok("extract docx 正常提取", len(extract._extract_docx(_valid_docx())) > 100)


# ───────────────────────── styles ─────────────────────────

for preset in ("solemn-red", "academic-ink", "modern-blue"):
    st = styles.get_style(styles.resolve_combo(preset, None, None, None, None))
    need_keys = ("bg", "primary", "deep", "accent2", "card", "card_border", "ghost",
                 "text", "muted", "light", "divider", "caption_cur", "caption_bg",
                 "caption_border", "font_title", "font_body", "font_bold", "voice",
                 "bgm", "title_size", "radius", "deco_style", "motion", "overlap",
                 "push_up_ok")
    missing = [k for k in need_keys if k not in st]
    ok(f"styles {preset} 键完整", not missing, str(missing))

combo = styles.resolve_combo(None, "all-sans", "不存在的配色", None, "brisk")
ok("styles 非法维度回退默认", combo["palette"] == "china-red" and combo["font"] == "all-sans"
   and combo["motion"] == "brisk")

ok("styles 非法预设回退", styles.resolve_combo("不存在的", None, None, None, None)["preset"] is None)


# ───────────────────────── tts 时长靠拢 ─────────────────────────

def _script_with_vo(vo_durs):
    frames = [{"index": 1, "type": "opening", "voiceover": "", "duration": 7}]
    idx = 2
    for d in vo_durs:
        frames.append({"index": idx, "type": "statement", "voiceover": "x" * 20,
                       "duration": d + 1.4, "transition_in": "cut",
                       "content": {"eyebrow": "核心观点", "thesis": "论点", "support": "支撑",
                                   "keywords": ["a", "b", "c"]}})
        idx += 1
    frames.append({"index": idx, "type": "closing", "voiceover": "", "duration": 4.5})
    return {"frames": frames, "duration_sec": 0}


vo = {i: {"duration": d, "words": []} for i, d in enumerate((6.0, 7.0, 8.0), start=2)}

s = _script_with_vo([6.0, 7.0, 8.0])
tts.apply_real_durations(s, vo, tail_pad=1.4, target=60.0)
ok("tts 扩展靠拢目标(21s语音→60s目标)", 50 <= s["duration_sec"] <= 63,
   f"total={s['duration_sec']}")

s2 = _script_with_vo([6.0, 7.0, 8.0])
tts.apply_real_durations(s2, vo, tail_pad=1.4, target=22.0)
# 物理下限 = 语音 21s + 开场 5s + 结尾 3s + 最小留白 3×0.6s ≈ 30.8s:
# 目标低于下限时应压缩到下限(而不是无下限地压到目标)
ok("tts 压缩到物理下限(21s语音→22s目标不可达,压至≈31s)", 30 <= s2["duration_sec"] <= 32,
   f"total={s2['duration_sec']}")

s3 = _script_with_vo([6.0, 7.0, 8.0])
tts.apply_real_durations(s3, vo, tail_pad=1.4, target=None)
ok("tts 无目标保持自然", 32 < s3["duration_sec"] < 38, f"total={s3['duration_sec']}")


# ───────────────────────── analyze 校验门 ─────────────────────────

def _base_frames():
    article = _article()
    frames = [
        {"index": 1, "type": "opening", "voiceover": "", "duration": 7, "transition_in": "cut",
         "content": {"eyebrow": "眉线", "title": "标题"}},
        {"index": 2, "type": "statement", "voiceover": "新质生产力是创新起主导作用的先进生产力质态。它摆脱传统增长路径,以高科技、高效能、高质量为特征,是符合新发展理念的先进质态,特点是创新,关键在质优。",
         "duration": 12, "transition_in": "cut",
         "content": {"eyebrow": "核心观点", "thesis": "论点", "support": "支撑句", "keywords": ["创新", "质优", "先进"]}},
        {"index": 3, "type": "points", "voiceover": "发展新质生产力,基础在科技创新,路径在产业升级。改革赋能与人才支撑同样不可或缺,四者构成完整体系。",
         "duration": 12, "transition_in": "cut",
         "content": {"title": "四个着力点", "points": ["科技创新", "产业升级", "改革赋能", "人才支撑"]}},
        {"index": 4, "type": "data", "voiceover": "我国全社会研发经费投入超过3.6万亿元,比上年实际增长百分之八点三。发明专利有效量突破500万件,创新实力持续增强。",
         "duration": 12, "transition_in": "cut",
         "content": {"items": [{"value": "3.6", "unit": "万亿元", "note": "研发经费投入", "chart": "bar"},
                               {"value": "500", "unit": "万件", "note": "发明专利", "chart": "ring"}],
                     "conclusion": "创新驱动成效显著"}},
        {"index": 5, "type": "elaboration", "voiceover": "从要素投入到创新驱动的转变,是发展方式的深刻变革。新技术改造传统产业,新兴产业培育壮大,未来产业前瞻布局,共同构成产业升级的完整路径。",
         "duration": 12, "transition_in": "cut",
         "content": {"title": "产业升级路径", "cards": [{"id": "01", "heading": "传统产业改造", "note": "用新技术提升"},
                                                       {"id": "02", "heading": "新兴产业壮大", "note": "保持领先优势"},
                                                       {"id": "03", "heading": "未来产业布局", "note": "下好先手棋"}]}},
        {"index": 6, "type": "closing", "voiceover": "", "duration": 4.5, "transition_in": "cut",
         "content": {"source": "来源", "author": ""}},
    ]
    return frames, article


frames, article = _base_frames()
script = {"title": "标题", "duration_sec": 120, "frames": frames,
          "analysis": {"outline": "大纲"}}
ok("validate 合格脚本通过", analyze.validate_script(script, article, 120) == [])

bad1 = json.loads(json.dumps(script))
bad1["frames"][1]["voiceover"] = "一句话。"   # 单句且过短
errs = analyze.validate_script(bad1, article, 120)
ok("validate 拒绝一句话旁白", any("一句话带过" in e for e in errs), str(errs[:2]))

bad2 = json.loads(json.dumps(script))
bad2["frames"][4]["content"]["cards"] = bad2["frames"][4]["content"]["cards"][:2]
errs = analyze.validate_script(bad2, article, 120)
ok("validate 拒绝稀疏卡片", any("卡片不足" in e for e in errs), str(errs[:2]))

bad3 = json.loads(json.dumps(script))
bad3["frames"][3]["content"]["items"][0]["value"] = "99.9"   # 不在原文
errs = analyze.validate_script(bad3, article, 120)
ok("validate 拒绝编造数据", any("不在原文" in e for e in errs), str(errs[:2]))


print()
if FAIL:
    print(f"{len(FAIL)} 项失败: {FAIL}")
    sys.exit(1)
print("ALL SMOKE TESTS PASSED")
