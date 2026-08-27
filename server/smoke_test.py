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
from builder import styles, templates

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


# ───────────────────────── analyze 讲解(lecture)校验门 ─────────────────────────

def _lecture_article():
    paras = [
        "问题是时代的声音,民生是最大的政治。发展为了人民、发展依靠人民、发展成果由人民共享。",
        "近年来,各地坚持以人民为中心的发展思想,持续深化基层治理改革,群众获得感不断提升。",
        "推进基层治理现代化,基础在网格,关键在机制,根本在服务,需要久久为功。",
        "各地探索接诉即办机制,把群众诉求解决在第一时间、第一现场,成效明显。",
        "同时也要看到,一些地方仍存在重形式轻实效的问题,必须持续整改。",
        "基层强则国家强,基层安则天下安。",
    ]
    return paras, "\n\n".join(paras)


def _lecture_frames():
    paras, article = _lecture_article()
    frames = [
        {"index": 1, "type": "opening", "voiceover": "", "duration": 7, "transition_in": "cut",
         "content": {"eyebrow": "逐段精讲", "title": "标题"}},
        {"index": 2, "type": "section", "voiceover": "这是第一章:先审题,搞清楚文章到底要回答什么问题。很多同学拿到题目就急着动笔,其实第一步应该是把中心任务定下来。接下来我们逐段拆解,看每一段在全文里承担什么任务。",
         "duration": 10, "transition_in": "cut",
         "content": {"number": "壹", "title": "审题", "subtitle": "导语"}},
        {"index": 3, "type": "textblock", "voiceover": "我们先看第一段。这段只有两句话,作用是开门见山点出文章主旨,把问题与民生直接关联。大家注意,这是政论文最常见的开头方式:先用判断句立论,再给出展开的方向,我们继续往下看。",
         "duration": 20, "transition_in": "cut",
         "content": {"para": 1, "role": "开头引入", "text": paras[0]}},
        {"index": 4, "type": "annotation", "voiceover": "这一句是全文的中心论点。大家注意:它用的是判断句式,先立论再展开,这是申论开头最稳妥的写法。换一个题目,我们同样可以先用判断句把观点立起来,再从容展开论证。",
         "duration": 22, "transition_in": "cut",
         "content": {"para": 1, "sentences": [
             {"text": paras[0][:12], "kind": "论点", "note": "判断句式立论,直接点题"},
             {"text": paras[0][12:33], "kind": "分析", "note": "三句排比展开,层层递进"}]}},
        {"index": 5, "type": "method", "voiceover": "把这段的写法提炼出来:开头用判断句直接亮明中心论点,再用排比展开。这个方法是很多社会治理类题目都能用的,只要把论点换成你要论述的主题,结构完全可以照搬。",
         "duration": 22, "transition_in": "cut",
         "content": {"title": "可迁移写法", "cards": [
             {"id": "01", "heading": "判断句式开篇", "note": "开门见山立论"},
             {"id": "02", "heading": "排比展开", "note": "三层递进支撑"}]}},
        {"index": 6, "type": "points", "voiceover": "基层治理的三根支柱分别是网格、机制和服务。这三个词不是随便排的,它们对应了载体、保障和目标三个层次。文章后文就是围绕这三点展开的,读的时候可以按这个线索去抓每段的主干。",
         "duration": 22, "transition_in": "cut",
         "content": {"title": "三个着力点", "points": ["网格", "机制", "服务", "改革"]}},
        {"index": 7, "type": "process", "voiceover": "把整篇文章的框架连起来看:开头立论,接着交代背景,再提出三个着力点,最后落到久久为功的要求。这就是典型的先总后分结构,写申论的时候,我们完全可以按照这个骨架来搭自己的文章。",
         "duration": 22, "transition_in": "cut",
         "content": {"title": "文章框架", "steps": [
             {"name": "开头立论", "note": "判断句点题"},
             {"name": "背景铺垫", "note": "结合实际"},
             {"name": "三点展开", "note": "并列支撑"},
             {"name": "收束要求", "note": "对策落地"}]}},
        {"index": 8, "type": "closing", "voiceover": "", "duration": 4.5, "transition_in": "cut",
         "content": {"source": "来源", "author": ""}},
    ]
    return frames, article


lframes, larticle = _lecture_frames()
lscript = {"title": "标题", "duration_sec": 300, "video_kind": "lecture",
           "frames": lframes, "analysis": {"outline": "大纲"}}
ok("validate 讲解合格脚本通过", analyze.validate_script(lscript, larticle, 300, "lecture") == [])

lbad = json.loads(json.dumps(lscript))
lbad["frames"][2]["content"]["text"] = "这不是原文里的话,而是完全编造出来的句子内容"
errs = analyze.validate_script(lbad, larticle, 300, "lecture")
ok("validate 讲解拒绝编造原文引用", any("不逐字" in e for e in errs), str(errs[:2]))

lbad2 = json.loads(json.dumps(lscript))
lbad2["frames"][3]["content"]["sentences"][0]["kind"] = "总结"
errs = analyze.validate_script(lbad2, larticle, 300, "lecture")
ok("validate 讲解拒绝非法批注类型", any("kind 非法" in e for e in errs), str(errs[:2]))

lbad3 = json.loads(json.dumps(lscript))
lbad3["frames"] = lscript["frames"][:3]
errs = analyze.validate_script(lbad3, larticle, 300, "lecture")
ok("validate 讲解帧数下限 8", any("8-200" in e for e in errs), str(errs[:1]))

_script_promo_with_lecture_frame = json.loads(json.dumps(script))
_script_promo_with_lecture_frame["frames"][2]["type"] = "annotation"   # 宣传脚本不允许讲解帧
errs = analyze.validate_script(_script_promo_with_lecture_frame, article, 120)
ok("validate 宣传拒绝讲解帧类型", any("仅讲解视频可用" in e for e in errs), str(errs[:2]))


# ───────────────────────── 讲解引用接地(grounding) ─────────────────────────

_lparas, _larticle = _lecture_article()
_lart_norm = analyze._norm_text(_larticle)

ok("grounding 精确引用原样返回", analyze._ground_quote(_lparas[0], _larticle, _lart_norm) == _lparas[0])

_rewritten = _lparas[2][:12] + "重点在" + _lparas[2][15:]   # 2 字小改写(关键在→重点在)
_g = analyze._ground_quote(_rewritten, _larticle, _lart_norm)
ok("grounding 小改写被钉回原文", _g is not None and _g != _rewritten
   and analyze._norm_text(_g) in _lart_norm, f"grounded={(_g or '')[:30]}")

_g2 = analyze._ground_quote("这是完全编造不存在的句子内容", _larticle, _lart_norm)
ok("grounding 编造文本拒绝接地", _g2 is None, str(_g2))

_frame_with_bad_quote = json.loads(json.dumps(lscript))
_frame_with_bad_quote["frames"][2]["content"]["text"] = _rewritten
_n = analyze._ground_frames(_frame_with_bad_quote["frames"], _larticle)
ok("grounding frames 就地替换", _n >= 1
   and analyze._norm_text(_frame_with_bad_quote["frames"][2]["content"]["text"]) in _lart_norm)

ok("kind 归一化 例证→论据", analyze._norm_kind("例证") == "论据")
ok("kind 归一化 措施→对策", analyze._norm_kind("措施") == "对策")
ok("kind 归一化 承上启下→过渡", analyze._norm_kind("承上启下") == "过渡")
ok("kind 归一化 未知词→分析", analyze._norm_kind("高亮强调") == "分析")


# ───────────────────────── 讲解段级治愈(healing) ─────────────────────────

def _heal_frames():
    paras, _ = _lecture_article()
    frames = [
        {"index": 1, "type": "opening", "voiceover": "", "duration": 7,
         "transition_in": "cut", "content": {"eyebrow": "逐段精讲", "title": "标题"}},
        {"index": 2, "type": "annotation", "voiceover": "我们来看这两句批注,第一句是原文,第二句需要注意其写法。",
         "duration": 15, "transition_in": "cut",
         "content": {"para": 1, "sentences": [
             {"text": paras[0][:12], "kind": "论点", "note": "判断句立论"},
             {"text": "这句是被模型改写过的非原文", "kind": "分析", "note": "应被治愈移除"}]}},
        {"index": 3, "type": "annotation", "voiceover": "这两句都不是原文,整帧应被丢弃。",
         "duration": 15, "transition_in": "cut",
         "content": {"para": 2, "sentences": [
             {"text": "编造的句子甲", "kind": "论点", "note": "x"},
             {"text": "编造的句子乙", "kind": "论据", "note": "y"}]}},
        {"index": 4, "type": "textblock", "voiceover": "这一段原文页的文字被改写了,应整帧丢弃。",
         "duration": 15, "transition_in": "cut",
         "content": {"para": 3, "role": "论据", "text": "这段文字被模型改写成了另一句话"}},
        {"index": 5, "type": "textblock", "voiceover": "这一段是原文,应保留。",
         "duration": 15, "transition_in": "cut",
         "content": {"para": 3, "role": "论据", "text": paras[2]}},
        {"index": 6, "type": "closing", "voiceover": "", "duration": 4.5,
         "transition_in": "cut", "content": {"source": "来源", "author": ""}},
    ]
    return frames, paras


_hf, _hparas = _heal_frames()
_hart = "\n\n".join(_hparas)
analyze._fixup_segment_frames(_hf, _hart, 60)
_h_types = [f["type"] for f in _hf]
ok("heal 保留部分可接地批注句", "annotation" in _h_types
   and len(_hf[[f["type"] for f in _hf].index("annotation")]["content"]["sentences"]) == 1)
ok("heal 丢弃全坏批注帧", _h_types.count("annotation") == 1)
ok("heal 丢弃改写原文帧", _h_types.count("textblock") == 1
   and analyze._norm_text(_hf[[f["type"] for f in _hf].index("textblock")]["content"]["text"])
   in analyze._norm_text(_hart))

# 非尾段 closing(模型把「本章小结」误写成结尾帧)→ statement 小结帧
import copy as _copy
_c2 = _copy.deepcopy(_hf)
_c2 = [f for f in _c2 if f["type"] != "closing"]
_c2.append({"index": 7, "type": "closing",
            "voiceover": "本章先到这里。下一章我们继续看后面的段落。",
            "duration": 10, "transition_in": "cut",
            "content": {"source": "s", "author": ""}})
analyze._fixup_segment_frames(_c2, _hart, 60, is_last=False)
ok("heal 非尾段 closing 转小结帧", _c2[-1]["type"] == "statement"
   and _c2[-1]["content"]["eyebrow"] == "本章小结"
   and _c2[-1]["voiceover"].strip())


# ───────────────────────── 影视剧式字幕窗口 ─────────────────────────

_st = styles.get_style(styles.resolve_combo("solemn-red", None, None, None, None))
_text = "我们先看这一段原文。注意这一句,它用的是判断句式,先立论再展开论证。"
_wds, _t0 = [], 0.0
for _w in tts.split_words(_text):
    _wds.append((_w, _t0, _t0 + 0.5))
    _t0 += 0.5
_wins, _wjs = templates.render_caption_windows(3, _st, _wds)
import re as _re
_line_chars = []
for h, _, _ in _wins:
    for seg in h.split('class="cap-line">')[1:]:
        seg = seg.split("</span>")[0]
        _line_chars.append(sum(len(t) for t in
                               _re.findall(r'<span id="f3-w\d+">([^<]*)</span>', seg)))
ok("字幕窗口每行 ≤19 字且窗口 ≥2 个", len(_wins) >= 2
   and all(n <= 19 for n in _line_chars) and len(_line_chars) >= 3,
   f"wins={len(_wins)} line chars={_line_chars}")


# ───────────────────────── 重点段限流(plan 校验) ─────────────────────────

_plan_ok = {"article_type": "x", "type_reason": "r", "central_task": "t",
            "chapters": [{"number": "壹", "title": "t", "minutes": 5.0,
                          "para_range": [1, 6], "content_plan": "c"}],
            "paragraph_notes": [{"para": i + 1, "role": "分析", "key_idea": "k",
                                 "teach_points": ["a"], "line_analysis": True}
                                for i in range(6)],
            "methods": ["m1", "m2", "m3"], "exam_method_summary": "s"}
errs = analyze._validate_plan(_plan_ok, 6, 300, analyze._norm_text(_hart))
ok("plan 重点段限流(5 分钟 ≤10 段)", errs == [], str(errs[:2]))

_plan_over = json.loads(json.dumps(_plan_ok))
_plan_over["paragraph_notes"] = [{"para": i + 1, "role": "分析", "key_idea": "k",
                                  "teach_points": ["a"], "line_analysis": True}
                                 for i in range(14)]
errs = analyze._validate_plan(_plan_over, 14, 300, analyze._norm_text(_hart))
ok("plan 重点段超限被拒", any("line_analysis" in e for e in errs), str(errs[:1]))

lcombo = styles.resolve_combo("solemn-red", None, None, None, None)
pp = analyze.build_lecture_plan_prompt(larticle, 300, lcombo)
ok("讲解方案 prompt 含文章与时长", "300 秒" in pp and "第1段" in pp and "逐段" in pp)
ok("讲解分段器 5 分钟 1 段", len(analyze._split_segments(
    [{"number": "壹", "title": "t", "minutes": 5.0}], 300)) == 1)
ok("讲解分段器 30 分钟 6 段", len(analyze._split_segments(
    [{"number": str(n), "title": "t", "minutes": 5.0} for n in range(1, 7)], 1800)) == 6)
ok("讲解分段器 末尾小段并入前段", len(analyze._split_segments(
    [{"number": "壹", "title": "t", "minutes": 5.0},
     {"number": "贰", "title": "t", "minutes": 1.5}], 390)) == 1)


print()
if FAIL:
    print(f"{len(FAIL)} 项失败: {FAIL}")
    sys.exit(1)
print("ALL SMOKE TESTS PASSED")
