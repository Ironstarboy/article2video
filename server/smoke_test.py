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


# ───────────────────────── 帧模板全量渲染 + 标题转义 ─────────────────────────

_st2 = styles.get_style(styles.resolve_combo("solemn-red", None, None, None, None))
_samples = {
    "opening": {"eyebrow": "眉线", "title": "标题", "subtitle": "副题"},
    "section": {"number": "壹", "title": "章节", "subtitle": "导语"},
    "statement": {"eyebrow": "核心", "thesis": "论点", "support": "支撑句", "keywords": ["a", "b"]},
    "elaboration": {"title": "标题", "cards": [{"id": "01", "heading": "h", "note": "n"},
                                               {"id": "02", "heading": "h", "note": "n"},
                                               {"id": "03", "heading": "h", "note": "n"}]},
    "quote": {"quote": "引语", "source": "出处", "keyword": "引"},
    "data": {"items": [{"value": "3.6", "unit": "万亿元", "note": "n", "chart": "bar"},
                       {"value": "500", "unit": "万件", "note": "n", "chart": "ring"}],
             "conclusion": "c"},
    "points": {"title": "标题", "points": ["a", "b", "c", "d"]},
    "process": {"title": "标题", "steps": [{"name": "a", "note": "n"}] * 4},
    "contrast": {"left_label": "左", "left_points": ["a", "b", "c"],
                 "right_label": "右", "right_points": ["x", "y", "z"]},
    "closing": {"source": "来源", "author": "作者"},
    "textblock": {"para": 1, "role": "r", "text": "原文段落内容", "focus": "f"},
    "annotation": {"para": 1, "sentences": [{"text": "原句", "kind": "论点", "note": "批注"}]},
    "method": {"title": "写法", "cards": [{"id": "01", "heading": "h", "note": "n"}]},
}
_all_render_ok = True
for _t, _c in _samples.items():
    try:
        _h, _cap, _js = templates.render_frame(
            {"index": 1, "type": _t, "scene": "s", "voiceover": "", "duration": 7,
             "transition_in": "cut", "content": _c}, _st2, 0.0,
            {"title": "测试标题", "total": 3})
        _all_render_ok = _all_render_ok and isinstance(_h, str) and "<section" in _h
    except Exception as _e:
        _all_render_ok = False
        print(f"    render_frame[{_t}] 异常: {_e}")
ok("模板 13 种帧类型全部可渲染", _all_render_ok)

_xss = templates.render_frame(
    {"index": 1, "type": "opening", "scene": "", "voiceover": "", "duration": 7,
     "transition_in": "cut", "content": {"eyebrow": "e", "title": "</title><script>alert(1)</script>"}},
    _st2, 0.0, {"title": "</div><script>alert(1)</script>", "total": 1})
ok("模板 标题 HTML 转义防注入", "<script>alert" not in _xss[0])


# ───────────────────────── extract 边界扩展 ─────────────────────────

_gbk_path = Path(__import__("tempfile").gettempdir()) / "ttv_smoke_gbk.txt"
_gbk_path.write_bytes("高质量发展是全面建设社会主义现代化国家的首要任务。" .encode("gb18030") * 12)
ok("extract gb18030 解码", "高质量发展" in extract.extract_text(str(_gbk_path)))

ok("extract 20 万字上限", _raises(
    lambda: extract.extract_text(_tmp_text("over.txt", "字" * 200001)), ValueError))

_big_path = Path(__import__("tempfile").gettempdir()) / "ttv_smoke_big.txt"
_big_path.write_text("文" * 800000, encoding="utf-8")   # 2.4MB,必超上限
ok("extract 超字节数预检拒绝", _raises(lambda: extract.extract_text(str(_big_path)), ValueError))


# ───────────────────────── assemble 导入链(fonttools 依赖) ─────────────────────────

try:
    from builder import assemble  # noqa: F401
    import fontTools.subset  # noqa: F401
    _assemble_ok = True
except ImportError as _e:
    _assemble_ok = False
    print(f"    assemble/fonttools 导入失败: {_e}")
ok("assemble/fonttools 可导入", _assemble_ok)


# ───────────────────────── 丢帧压缩 / promo 金句接地 / 两阶段 prompt ─────────────────────────

_dsf = [
    {"index": 1, "type": "opening", "voiceover": "", "duration": 7, "content": {"title": "t"}},
    {"index": 2, "type": "statement", "voiceover": "论据充分支撑观点,结构完整。",
     "duration": 12, "content": {"thesis": "t", "support": "s", "keywords": []}},
    {"index": 3, "type": "statement", "voiceover": "一句话带过吧。",
     "duration": 12, "content": {"thesis": "t", "support": "s", "keywords": []}},
    {"index": 4, "type": "closing", "voiceover": "", "duration": 4.5, "content": {"source": "s"}},
]
_n_dropped = analyze._drop_shortest_frames(_dsf, 20, 4)
ok("丢帧压缩按旁白最短丢弃", _n_dropped == 1 and _dsf[1]["type"] == "statement"
   and len(_dsf) == 3, f"dropped={_n_dropped} types={[f['type'] for f in _dsf]}")

_pq = [{"index": 3, "type": "quote", "voiceover": "金句页。", "duration": 10,
        "content": {"quote": "基层强则国家强,基层安则天下安。", "source": "原文"}}]
_warn = analyze._ground_promo_quotes(_pq, _larticle)
ok("promo 金句接地保留原句", _pq[0]["content"]["quote"] == "基层强则国家强,基层安则天下安。"
   and not _warn)

_pq2 = [{"index": 3, "type": "quote", "voiceover": "金句页。", "duration": 10,
         "content": {"quote": "这是编造出来的一句假金句", "source": "原文"}}]
_warn2 = analyze._ground_promo_quotes(_pq2, _larticle)
ok("promo 金句无法接地保留并告警", _pq2[0]["content"]["quote"] == "这是编造出来的一句假金句"
   and len(_warn2) == 1)

# 截断引语(……):逐字校验与接地必须分段感知
_tq_article = "创新驱动发展之路越走越宽广。不断塑造发展新动能新优势。"
_tq_norm = analyze._norm_text(_tq_article)
ok("截断引语逐字校验(分段)", analyze._quote_parts_verbatim(
    "创新驱动发展之路……不断塑造发展新动能新优势", _tq_norm))
ok("截断引语伪造段落被拒", not analyze._quote_parts_verbatim(
    "创新驱动……编造的句子", _tq_norm))
_tg = analyze._ground_quote("创新驱动发展之路越走越宽……不断塑造发展新动能新优势",
                            _tq_article, _tq_norm)
ok("截断引语分段接地", _tg is not None and "……" in _tg
   and analyze._norm_text(_tg.split("……")[0]) in _tq_norm, str(_tg))

_pa = analyze.build_analysis_prompt(larticle, 120, lcombo)
ok("两阶段·分析 prompt 含契约要素", "论证蓝图" in _pa and "120 秒" in _pa
   and "argument_chain" in analyze.ANALYSIS_SYSTEM and "frame_plan" in analyze.ANALYSIS_SYSTEM
   and "逐字" in analyze.ANALYSIS_SYSTEM)
_ps = analyze.build_script_prompt(
    larticle, {"core_argument": "c", "argument_chain": [], "frame_plan": [],
               "article_summary": "s", "data_ledger": [], "quotes": [],
               "key_visuals": []}, 120, lcombo)
ok("两阶段·脚本 prompt 含蓝图与示例", "论证蓝图" in _ps and "statement 示例" in _ps
   and "data_ledger" in _ps)


# ───────────────────────── 备课方案:覆盖校验 / 分段过滤 / 同段校验 ─────────────────────────

_plan_gap = {"article_type": "x", "type_reason": "r", "central_task": "t",
             "chapters": [{"number": "壹", "title": "t", "minutes": 2.0,
                           "para_range": [1, 2], "content_plan": "c"},
                          {"number": "贰", "title": "t", "minutes": 3.0,
                           "para_range": [4, 6], "content_plan": "c"}],
             "paragraph_notes": [{"para": i + 1, "role": "分析", "key_idea": "k",
                                  "teach_points": ["a"]} for i in range(6)],
             "methods": ["m1", "m2", "m3"], "exam_method_summary": "s"}
errs = analyze._validate_plan(_plan_gap, 6, 300, analyze._norm_text(_hart))
ok("plan 章节空洞被拒(第 3 段无覆盖)", any("空洞" in e for e in errs), str(errs[:2]))

_fp = {"article_type": "x", "type_reason": "r", "central_task": "t",
       "chapters": [{"number": "壹", "title": "t", "minutes": 5.0,
                     "para_range": [1, 2], "content_plan": "c"}],
       "paragraph_notes": [{"para": 1, "role": "分析", "key_idea": "k",
                            "teach_points": ["a"], "line_analysis": False}],
       "methods": ["m1", "m2"], "exam_method_summary": "s"}
analyze._fixup_plan(_fp, _lparas, 300, analyze._norm_text(_larticle))
ok("plan 修复补齐章节覆盖", _fp["chapters"][0]["para_range"] == [1, len(_lparas)])
ok("plan 修复补齐段落要点", len(_fp["paragraph_notes"]) == len(_lparas))

_pf = analyze._plan_for_segment(
    {"article_type": "x", "chapters": [{"number": "壹", "title": "a", "minutes": 3.0,
                                        "para_range": [1, 3], "content_plan": "c"},
                                       {"number": "贰", "title": "b", "minutes": 2.0,
                                        "para_range": [4, 6], "content_plan": "c"}],
     "paragraph_notes": [{"para": i + 1, "role": "分析", "key_idea": "k"}
                         for i in range(6)],
     "methods": ["m1", "m2"], "exam_method_summary": "s"},
    {"chapters": [{"number": "壹", "title": "a", "minutes": 3.0,
                   "para_range": [1, 3], "content_plan": "c"}]})
ok("plan 分段过滤只留本段要点", len(_pf["chapters"]) == 1
   and len(_pf["paragraph_notes"]) == 3)

_ab = analyze._para_bounds(_larticle, _lart_norm)
_af = {"index": 2, "type": "annotation", "voiceover": "x" * 20, "duration": 10,
       "transition_in": "cut",
       "content": {"para": 1, "sentences": [
           {"text": _lparas[0][:12], "kind": "论点", "note": "n"},
           {"text": _lparas[2][:12], "kind": "分析", "note": "n"}]}}
_errs_cross = analyze._annotation_para_errs(_af, 1, _lart_norm, _ab)
ok("annotation 跨段批注句被拒", any("同一段" in e for e in _errs_cross), str(_errs_cross))


# ───────────────────────── jobs 状态机(临时 ROOT,最后执行) ─────────────────────────

import importlib as _il
import os as _os
import tempfile as _tmpf

_orig_root = _os.environ.get("TTV_ROOT")
try:
    _os.environ["TTV_ROOT"] = _tmpf.mkdtemp(prefix="ttv_jobs_")
    import config as _config
    import jobs as _jobs_mod
    _il.reload(_config)
    _il.reload(_jobs_mod)
    _j = _jobs_mod.create_job("solemn-red", 120, "t.txt")
    ok("jobs 创建落盘", _j.status == "uploaded" and _j.state_path.exists())
    _j.set(status="analyzing", progress="p")
    _d = _j.to_dict(brief=True)
    ok("jobs brief 模式不含 script", "script" not in _d)
    ok("jobs has_video 初始 False", _d.get("has_video") is False)
    # 模拟重启:uploaded/analyzing 应置 failed
    _il.reload(_jobs_mod)
    _j2 = _jobs_mod.get_job(_j.id)
    ok("jobs 重启 uploaded→failed", _j2 is not None and _j2.status == "failed",
       f"status={_j2.status if _j2 else None}")

    # ── 成片双产物:ppt(纯 PPT 版)+ final(含数字人的最终版) ──
    # 见 docs/数字人操作按钮前端方案.md 第十节
    _legacy_job = _jobs_mod.create_job("solemn-red", 120, "t2.txt")
    _legacy_job.set(status="rendered", render_format="mp4")
    ok("jobs 无产物时 video_path 为 None", _legacy_job.video_path() is None)

    # 造一个旧式产物 out.mp4(模拟双产物改造之前的任务)
    _renders = _legacy_job.paths()["renders"]
    _renders.mkdir(parents=True, exist_ok=True)
    (_renders / "out.mp4").write_bytes(b"x" * 20480)
    ok("jobs 旧产物 out.mp4 可被识别(迁移前)",
       _legacy_job.video_path() is not None
       and _legacy_job.video_path().name == "out.mp4")

    # 重启触发一次性迁移:out.mp4 → final.mp4 + ppt.mp4
    _il.reload(_jobs_mod)
    _mig = _jobs_mod.get_job(_legacy_job.id)
    ok("jobs 旧产物迁出 final.mp4", (_renders / "final.mp4").exists())
    ok("jobs 旧产物迁出 ppt.mp4", (_renders / "ppt.mp4").exists())
    ok("jobs 旧产物 out.mp4 已清理", not (_renders / "out.mp4").exists())
    ok("jobs 迁移后 video_path 指向 final",
       _mig.video_path() is not None and _mig.video_path().name == "final.mp4",
       f"实际={_mig.video_path()}")
    _md = _mig.to_dict(brief=True)
    ok("jobs to_dict 暴露两个产物",
       set(_md.get("artifacts") or {}) == {"ppt", "final"},
       f"artifacts={sorted((_md.get('artifacts') or {}).keys())}")
    ok("jobs 产物记录含大小与格式",
       (_md["artifacts"]["final"].get("bytes") == 20480
        and _md["artifacts"]["final"].get("fmt") == "mp4"))
    ok("jobs 迁移打标记", _mig.state.get("artifacts_migrated") is True)

    # 幂等:再启动一次不得重复迁移(也不得改变产物记录)
    _before = dict(_mig.state.get("artifacts") or {})
    _il.reload(_jobs_mod)
    _again = _jobs_mod.get_job(_legacy_job.id)
    ok("jobs 迁移幂等", (_again.state.get("artifacts") or {}) == _before)

    # 显式记录的产物缺失时不得报错,退回 None(文件被外部删除的情形)
    (_renders / "final.mp4").unlink()
    (_renders / "ppt.mp4").unlink()
    ok("jobs 产物文件缺失时 video_path 安全返回 None",
       _again.video_path() is None or _again.video_path().exists())

    # ── 数字人播报视频:第三个产物(独立于 ppt/final) ──
    _bc_path = _again.paths()["renders"] / "avatar.mp4"
    _bc_path.write_bytes(b"y" * 4096)
    _again._record_artifact("avatar", _bc_path)
    _bd = _again.to_dict(brief=True)
    ok("jobs 播报产物进入 artifacts", "avatar" in (_bd.get("artifacts") or {}),
       f"artifacts={sorted((_bd.get('artifacts') or {}).keys())}")
    ok("jobs 播报产物记录格式与大小",
       _bd["artifacts"]["avatar"].get("fmt") == "mp4"
       and _bd["artifacts"]["avatar"].get("bytes") == 4096)
    ok("jobs 播报产物可按 key 取路径", _again.artifact_path("avatar") == _bc_path)
    _bc_path.unlink()
    ok("jobs 播报产物缺失时安全返回 None", _again.artifact_path("avatar") is None)
    ok("jobs 播报产物缺失不影响最终版入口", _again.video_path() is None)

    # 产物文件在磁盘上、state.artifacts 里没记录(v2.2 之前的渲染不写 artifacts)
    # → 启动时只补记录,不动文件
    _bf = _jobs_mod.create_job("solemn-red", 120, "t3.txt")
    _bf.set(status="rendered", render_format="mp4")
    _bf_renders = _bf.paths()["renders"]
    _bf_renders.mkdir(parents=True, exist_ok=True)
    (_bf_renders / "final.mp4").write_bytes(b"z" * 20480)
    (_bf_renders / "ppt.mp4").write_bytes(b"z" * 20480)
    _il.reload(_jobs_mod)
    _bf_arts = (_jobs_mod.get_job(_bf.id).to_dict(brief=True).get("artifacts") or {})
    ok("jobs 产物未记录时启动补录", set(_bf_arts) == {"ppt", "final"},
       f"artifacts={sorted(_bf_arts)}")
    ok("jobs 补录不改动文件", (_bf_renders / "final.mp4").stat().st_size == 20480)
    _il.reload(_jobs_mod)   # 幂等:final 已记录后不再重复补录
    ok("jobs 补录幂等",
       set((_jobs_mod.get_job(_bf.id).to_dict(brief=True).get("artifacts") or {}))
       == {"ppt", "final"})
finally:
    _os.environ["TTV_ROOT"] = _orig_root or str(Path(__file__).resolve().parents[1])
    _il.reload(_config)
    _il.reload(_jobs_mod)


# ═══════════════════════ 数字人片段(纯函数,不含 GPU/网络) ═══════════════════════

import avatar  # noqa: E402

_audio = Path(_tmp_text("fake_vo.mp3", "x" * 64))
_img = Path("assets/avatars/jinli.png")
_k_a = avatar.frame_clip_path(_img, _audio, 5.0, 320)
_k_b = avatar.frame_clip_path(_img, _audio, 5.0, 320)
_k_c = avatar.frame_clip_path(_img, _audio, 6.0, 320)
ok("avatar 片段缓存键稳定(同输入同路径)", _k_a == _k_b)
ok("avatar 片段缓存键随帧时长变化", _k_a != _k_c)
ok("avatar 片段缓存键随尺寸变化",
   avatar.frame_clip_path(_img, _audio, 5.0, 320) != avatar.frame_clip_path(_img, _audio, 5.0, 256))
ok("avatar 缓存键含规格版本", f"_{avatar.AVATAR_CLIP_VERSION}" in _k_a.name)

ok("avatar 遮罩名含尺寸与版本",
   avatar.mask_name(320).startswith("mask_320_")
   and f"_v{avatar.AVATAR_CLIP_VERSION}" in avatar.mask_name(320))
ok("avatar 遮罩名随尺寸变化", avatar.mask_name(320) != avatar.mask_name(256))

_fc = avatar.card_overlay_filter("1:v", "2:v", "OUT", 320, 20)
ok("avatar 卡片滤镜标签成对且无占位符残留",
   "[OUT]" in _fc and "MASKV" not in _fc and "[1:v]" in _fc and "[2:v]" in _fc)
ok("avatar 卡片滤镜含圆角遮罩与投影", "alphamerge" in _fc and "boxblur" in _fc)

_tl_src = [{"index": 1, "clip": "/tmp/a.mp4", "start": 1.5, "duration": 3.0}]
_tl_path = Path(_tmp_text("tl.json", ""))
avatar.write_timeline(_tl_src, _tl_path)
ok("avatar 时间轴读写往返", avatar.read_timeline(_tl_path) == _tl_src)
ok("avatar 缺失时间轴返回空列表", avatar.read_timeline(Path("/tmp/不存在_tl.json")) == [])

ok("avatar 注册表默认形象可解析",
   styles.avatar_file() == styles.AVATARS[styles.DEFAULT_AVATAR]["file"])
ok("avatar 未知形象回退默认", styles.avatar_file("不存在的形象") == styles.avatar_file())


# ═══════════════ 数字人播报视频:音轨拼接 / 步骤 ETA(纯函数,无 GPU/网络) ═══════════════

import wave as _wave  # noqa: E402

_tl_audio = [{"index": 2, "clip": "/tmp/none_a.mp4", "start": 0.0, "duration": 2.5},
             {"index": 3, "clip": "/tmp/none_b.mp4", "start": 2.5, "duration": 1.5}]
_wav_out = Path(_tmp_text("bc_audio.wav", ""))
_bc_total = avatar.build_broadcast_audio(_tl_audio, {}, _wav_out)
ok("播报音轨时长等于时间轴汇总", abs(_bc_total - 4.0) < 1e-6, f"实际={_bc_total}")
with _wave.open(str(_wav_out), "rb") as _w:
    _bc_rate, _bc_ch, _bc_frames = _w.getframerate(), _w.getnchannels(), _w.getnframes()
ok("播报音轨规格 44.1k 单声道", _bc_rate == 44100 and _bc_ch == 1)
ok("播报音轨采样数等于总时长", abs(_bc_frames / _bc_rate - 4.0) < 0.005,
   f"{_bc_frames}/{_bc_rate}")
# 无台词帧(vo 里没有该帧)整段静音:首帧 0.25s 偏移内必须全零
with _wave.open(str(_wav_out), "rb") as _w:
    _pcm = _w.readframes(_bc_frames)
ok("播报音轨帧首为静音(与成片 VO_OFFSET 对齐)", _pcm[:1000] == b"\x00" * 1000)
ok("播报音轨缺失配音也不报错(按静音补齐)", _bc_total > 0)

ok("播报耗时估算随片长增长",
   avatar.estimate_broadcast_sec(600) > avatar.estimate_broadcast_sec(300) > 0)
ok("播报耗时估算=配音+人像+拼接",
   avatar.estimate_broadcast_sec(60) == round(60 / avatar.AVATAR_RT_FACTOR
                                             + 60 / avatar.AVATAR_CONCAT_RT_FACTOR
                                             + 60 / avatar.AVATAR_TTS_RT_FACTOR))
ok("播报耗时估算可排除已缓存的配音",
   avatar.estimate_broadcast_sec(60, include_tts=False)
   < avatar.estimate_broadcast_sec(60, include_tts=True))
ok("播报 ETA 步骤1 无进度时不给数字", avatar.broadcast_eta(1, 0, None, 0, 0, 100, 100) is None)
ok("播报 ETA 步骤1 同一帧完成后给正数",
   (avatar.broadcast_eta(1, 1, 4, 10.0, 0, 100, 100) or 0) > 0)
ok("播报 ETA 步骤3 等于剩余拼接时间",
   avatar.broadcast_eta(3, 0, 0, 30.0, 0, 100, 100, 60.0)
   == round(40 / avatar.AVATAR_CONCAT_RT_FACTOR))
ok("播报 ETA 步骤2 用实测速率(快于静态系数时更小)",
   avatar.broadcast_eta(2, 2, 4, 20.0, 20.0, 40.0, 40.0)
   < avatar.broadcast_eta(2, 0, 4, 0.0, 0.0, 40.0, 40.0))

_wt = tts.word_times("发展新质生产力", 4.0)
ok("词级时间轴起点含 VO_OFFSET", abs(_wt[0][1] - tts.VO_OFFSET) < 1e-6)
# 词级时间轴从 VO_OFFSET 起铺满配音时长(与成片 audio 的 data-start 同一口径)
ok("词级时间轴跨度等于配音时长", abs((_wt[-1][2] - _wt[0][1]) - 4.0) < 1e-6)


print()
if FAIL:
    print(f"{len(FAIL)} 项失败: {FAIL}")
    sys.exit(1)
print("ALL SMOKE TESTS PASSED")
