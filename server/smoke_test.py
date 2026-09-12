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
import avatar_library
import config
import extract
import preferences
import settings
import tts
from builder import styles, templates

FAIL = []


def ok(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f" [{name}]" + (f"  {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


def skip(name, detail=""):
    print(f"SKIP [{name}]" + (f"  {detail}" if detail else ""))


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

# ── 项目标题清洗(自动总结与脚本标题兜底共用) ──
ok("标题清洗:两行式脚本标题并成一行",
   analyze.clean_title("以新质生产力\n塑造发展新优势") == "以新质生产力 塑造发展新优势")
ok("标题清洗:剪掉书名号与标点", analyze.clean_title("《以创新驱动发展》。") == "以创新驱动发展")
ok("标题清洗:限长", len(analyze.clean_title("长" * 80)) == 24)
ok("标题清洗:空值返回空串", analyze.clean_title(None) == "" and analyze.clean_title("  ") == "")
_prompt = analyze._title_prompt({"title": "T", "analysis": {"core_argument": "C"},
                                 "frames": [{"voiceover": "V"}]}, "文章开头", "promo")
ok("标题总结 prompt 带脚本信息与文章开头",
   "T" in _prompt and "C" in _prompt and "V" in _prompt and "文章开头" in _prompt)
ok("标题总结 system 要求 JSON 与字数",
   "JSON" in analyze.TITLE_SYSTEM and "12-22" in analyze.TITLE_SYSTEM)


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

import asyncio as _asyncio

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

    # ── 项目标题 / 阶段历史(v2.6:入口页项目列表,点某一步直达结果) ──
    ok("jobs 标题规范化:压空白与换行",
       _jobs_mod.normalize_title("  甲  乙 \n 丙 ") == "甲 乙 丙")
    ok("jobs 标题规范化:限长 60",
       len(_jobs_mod.normalize_title("长" * 200)) == _jobs_mod.TITLE_MAX)
    ok("jobs 标题规范化:空标题报错",
       _raises(_via(_jobs_mod.normalize_title, "   "), ValueError))
    ok("jobs 标题规范化:缺字段报错",
       _raises(_via(_jobs_mod.normalize_title, None), ValueError))

    _t = _jobs_mod.create_job("solemn-red", 120, "新质生产力研究.md")
    ok("jobs 标题回退文件名", _t.display_title() == "新质生产力研究")
    _t.set(title="以新质生产力\n塑造发展新优势", title_source="auto")
    ok("jobs 标题单行化", _t.display_title() == "以新质生产力 塑造发展新优势")
    _t.set(title="", title_source="")
    _t.paths()["script"].write_text(
        json.dumps({"title": "《脚本里的标题》", "frames": [1, 2, 3]}), encoding="utf-8")
    ok("jobs 标题回退脚本标题", _t.display_title() == "《脚本里的标题》")

    for _i in range(_jobs_mod.HISTORY_MAX + 5):
        _t.record_history("render", detail=f"第 {_i} 次")
    _hist = _t.history()
    ok("jobs 历史有条数上限", len(_hist) == _jobs_mod.HISTORY_MAX, f"len={len(_hist)}")
    ok("jobs 历史保留最新一条",
       _hist[-1]["detail"] == f"第 {_jobs_mod.HISTORY_MAX + 4} 次")
    ok("jobs 历史带中文标签与时间",
       _hist[-1]["label"] == "渲染成片" and _hist[-1]["at"] > 0)
    _t.record_history("build", status="failed", detail="配音失败")
    ok("jobs 历史可记失败", _t.history()[-1]["status"] == "failed")
    _sum = _t.summary()
    ok("jobs summary 带标题与历史",
       bool(_sum["title"]) and len(_sum["history"]) == _jobs_mod.HISTORY_MAX
       and _sum["history"][-1]["step"] == "build")
    ok("jobs summary 不含 script", "script" not in _sum)
    ok("jobs summary 含定位/产物字段",
       {"job_id", "status", "updated_at", "artifacts"} <= set(_sum))
    ok("jobs set 刷新 updated_at", _t.state["updated_at"] >= _t.state["created_at"])

    # 老任务补标题/历史:脚本、工程、产物都在磁盘上,state 里却没有记录
    _old = _jobs_mod.create_job("solemn-red", 120, "旧文章.md")
    _old.paths()["script"].write_text(
        json.dumps({"title": "旧脚本标题", "frames": [1]}), encoding="utf-8")
    _old_proj = _old.paths()["project"]
    _old_proj.mkdir(parents=True, exist_ok=True)
    (_old_proj / "index.html").write_text("<html></html>", encoding="utf-8")
    _old_renders = _old.paths()["renders"]
    _old_renders.mkdir(parents=True, exist_ok=True)
    (_old_renders / "final.mp4").write_bytes(b"f" * 20480)
    _old.state["title"] = ""
    _old.state["title_source"] = ""
    _old.state["history"] = []
    _old.state["total_sec"] = 78.0
    _old._record_artifact("final", _old_renders / "final.mp4")
    _old._backfill_meta()
    ok("jobs 旧任务补标题", _old.state.get("title") == "旧脚本标题")
    ok("jobs 旧任务补历史(分析/构建/渲染)",
       [h["step"] for h in _old.history()] == ["analyze", "build", "render"],
       f"steps={[h['step'] for h in _old.history()]}")
    ok("jobs 补的历史带 derived 标记", _old.history()[0].get("derived") is True)
    ok("jobs 补录把 updated_at 提到最近一次活动",
       _old.state["updated_at"] >= max(h["at"] for h in _old.history()),
       f"updated_at={_old.state['updated_at']}")

    # 后台阶段失败要落一条历史(界面上才说得出"哪一步挂了")
    _fl = _jobs_mod.create_job("solemn-red", 120, "坏任务.md")

    def _boom(job):
        raise RuntimeError("模拟阶段失败")

    _jobs_mod.run_in_background(_fl, _boom, step="render").join(5)
    ok("jobs 后台失败写 failed 状态",
       _fl.status == "failed" and "模拟阶段失败" in (_fl.state.get("error") or ""))
    ok("jobs 后台失败写历史",
       bool(_fl.history()) and _fl.history()[-1]["step"] == "render"
       and _fl.history()[-1]["status"] == "failed")
finally:
    _os.environ["TTV_ROOT"] = _orig_root or str(Path(__file__).resolve().parents[1])
    _il.reload(_config)
    _il.reload(_jobs_mod)


# ═══════════════════════ 数字人片段(纯函数,不含 GPU/网络) ═══════════════════════

import avatar  # noqa: E402

_audio = Path(_tmp_text("fake_vo.mp3", "x" * 64))
# 用仓库内真实形象图的**绝对路径**:此前写的是相对路径 "assets/avatars/jinli.png",
# 只有恰好以仓库根为 cwd 运行时才存在(从 server/ 目录跑必然 FileNotFoundError)。
_img = Path(config.AVATAR_BUILTIN_FILE)
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

# ── 数字人抠像(只保留人像、背景透明) ──
# 核心是三条口径:遮罩文件名要能被版本/模型失效;抠像坐标必须贴画面下缘;
# 滤镜只做 alphamerge(不再有卡片留白/投影)。
_co = avatar.cutout_overlay_filter("1:v", "9:v", "OUT", 320)
ok("avatar 抠像滤镜含 alphamerge 且无卡片痕迹",
   "[OUT]" in _co and "alphamerge" in _co and "[1:v]" in _co and "[9:v]" in _co
   and "boxblur" not in _co and "pad=" not in _co)
# alphamerge 要求两路尺寸一致:遮罩跟着片段缓存(片段多大就多大),必须一起缩放到目标尺寸
ok("avatar 抠像滤镜把遮罩也缩放到目标尺寸",
   "[9:v]scale=320:320" in _co and "[1:v]format=rgba,scale=320:320" in _co)
ok("avatar 抠像滤镜与卡片滤镜不是同一条",
   _co != avatar.card_overlay_filter("1:v", "9:v", "OUT", 320, 20))
ok("avatar 抠像遮罩名带模型标识与版本",
   avatar.matte_name("clip_x_300_5.000_2.mp4")
   == f"clip_x_300_5.000_2.{config.MATTE_MODEL_TAG}{config.MATTE_VERSION}.mp4")
ok("avatar 抠像遮罩与片段同目录同名派生",
   avatar.matte_path(Path("/tmp/a/clip_x_300_5.000_2.mp4")).parent == Path("/tmp/a"))
ok("avatar 抠像遮罩路径随版本变化",
   avatar.matte_name("clip_x.mp4") != f"clip_x.{config.MATTE_MODEL_TAG}0.mp4")
ok("avatar 抠像开关只认布尔(字符串不算)",
   avatar.normalize_cutout(True) is True and avatar.normalize_cutout(None, True) is True
   and _raises(_via(avatar.normalize_cutout, "true"), ValueError))
ok("avatar 抠像开关宽松版对坏值回退",
   avatar.safe_cutout("是") is config.AVATAR_CUTOUT
   and avatar.safe_cutout("是", True) is True
   and avatar.safe_cutout("是", False) is False)
# 四个角落都能摆:左右按角落的 左/右,纵向按 上/下;只有下排贴画面下缘(切口落在画面外沿)
_cut_tl = avatar.cutout_xy("tl", 300, margin_x=40, margin_y=36, video_w=1920, video_h=1080)
_cut_tr = avatar.cutout_xy("tr", 300, margin_x=40, margin_y=36, video_w=1920, video_h=1080)
_cut_bl = avatar.cutout_xy("bl", 300, margin_x=40, margin_y=36, video_w=1920, video_h=1080)
_cut_br = avatar.cutout_xy("br", 300, margin_x=40, margin_y=36, video_w=1920, video_h=1080)
ok("avatar 抠像位置四个角落各不相同",
   len({_cut_tl, _cut_tr, _cut_bl, _cut_br}) == 4)
ok("avatar 抠像上排留头顶空间(tl/tr → margin_y)",
   _cut_tl[1] == 36 and _cut_tr[1] == 36)
ok("avatar 抠像下排贴画面下缘(bl/br → 画面高 - 边长)",
   _cut_bl[1] == 1080 - 300 and _cut_br[1] == 1080 - 300)
ok("avatar 抠像左右按角落决定",
   _cut_tl[0] == 40 and _cut_bl[0] == 40
   and _cut_tr[0] == 1920 - 300 - 40 and _cut_br[0] == 1920 - 300 - 40)
ok("avatar 抠像位置受下缘留白影响",
   avatar.cutout_xy("br", 300, bottom_margin=24)[1] == 1080 - 300 - 24)
ok("avatar 抠像位置不会把画面顶出去(尺寸过大时夹回)",
   avatar.cutout_xy("tl", 1080, margin_y=36, video_w=1920, video_h=1080)[1] == 0)

# ── 抠像 worker(server/matte.py):纯函数部分不依赖 numpy/onnxruntime ──
import matte  # noqa: E402
ok("抠像优先用 GPU、CPU 兜底",
   matte.resolve_providers(["CPUExecutionProvider", "CUDAExecutionProvider"])
   == ["CUDAExecutionProvider", "CPUExecutionProvider"])
ok("抠像只有 CPU 时也能跑",
   matte.resolve_providers(["CPUExecutionProvider"]) == ["CPUExecutionProvider"])
ok("抠像拿不到 provider 列表时给 CPU 兜底",
   matte.resolve_providers([]) == ["CPUExecutionProvider"]
   and matte.resolve_providers(None) == ["CPUExecutionProvider"])
ok("抠像模型输入按最短边等比缩放",
   matte.model_size(300, 300, 512) == (512, 512)
   and matte.model_size(640, 480, 512) == (683, 512))
ok("抠像可用性判据返回(可否, 原因)",
   isinstance(avatar.matte_available(), tuple)
   and len(avatar.matte_available()) == 2)

# ── 配音可懂度抽检(server/voice_check.py):纯函数,不加载 whisper ──
import voice_check  # noqa: E402

ok("配音抽检 LCS:完全一致为 1",
   voice_check.lcs_ratio("问题是时代的声音", "问题是时代的声音") == 1.0)
ok("配音抽检 LCS:完全不相干接近 0",
   voice_check.lcs_ratio("问题是时代的声音", "完全不相干的内容") < 0.2)
ok("配音抽检 LCS:半句相符落在中间",
   0.3 < voice_check.lcs_ratio("问题是时代的声音,回答并指导解决问题是理论的根本任务",
                               "问题是时代的声音") < 0.6)
ok("配音抽检 LCS:空听写记 0(不是 1)",
   voice_check.lcs_ratio("有台词", "") == 0.0)
ok("配音抽检阈值留足 whisper 自身误差的余量",
   0.0 < voice_check.WARN_LCS <= 0.5)
_vc_dir = Path(_tmp_text("vc_dir", "x")).parent / "vc_audio"
_vc_dir.mkdir(exist_ok=True)
(_vc_dir / "vo_02.mp3").write_bytes(b"x")
(_vc_dir / "vo_03.mp3").write_bytes(b"x")
_vc_script = {"frames": [{"index": 2, "voiceover": "短句"},
                         {"index": 3, "voiceover": "这是一句明显更长的台词,抽检优先挑它"},
                         {"index": 9, "voiceover": "没有配音文件"}]}
ok("配音抽检优先挑最长的、且有配音文件的帧",
   [p[1] for p in voice_check.pick_frames(_vc_script, _vc_dir, 2)] == [3, 2])
ok("配音抽检没有可检帧时返回空",
   voice_check.pick_frames({"frames": [{"index": 1, "voiceover": ""}]}, _vc_dir, 2) == [])

# ── 数字人大小(播报视频画面边长):接口层靠它把非法值拦成 400 ──
ok("avatar 尺寸缺省回退默认", avatar.normalize_size(None) == config.AVATAR_SIZE
   and avatar.normalize_size("") == config.AVATAR_SIZE)
ok("avatar 尺寸接受合法偶数", avatar.normalize_size(480) == 480)
ok("avatar 尺寸接受字符串(表单/查询参数)", avatar.normalize_size("464") == 464)
ok("avatar 尺寸拒绝奇数(H.264 yuv420p 会失败)",
   _raises(_via(avatar.normalize_size, 321), ValueError))
ok("avatar 尺寸拒绝低于下限", _raises(_via(avatar.normalize_size, 8), ValueError))
ok("avatar 尺寸拒绝高于上限", _raises(_via(avatar.normalize_size, 4000), ValueError))
ok("avatar 尺寸拒绝非数字", _raises(_via(avatar.normalize_size, "大"), ValueError))
# 读路径(轮询)不能因为历史 state 里的坏值把接口打成 500
ok("avatar 尺寸宽松版对坏值回退默认",
   avatar.safe_size(321) == config.AVATAR_SIZE
   and avatar.safe_size("bad", 480) == 480)
ok("avatar 尺寸下拉含默认值且升序去重",
   config.avatar_size_options() == sorted(set(config.avatar_size_options()))
   and config.AVATAR_SIZE in config.avatar_size_options())
ok("avatar 尺寸下拉剔除非法项(奇数/越界)",
   all(s % 2 == 0 and config.AVATAR_SIZE_MIN <= s <= config.AVATAR_SIZE_MAX
       for s in config.avatar_size_options()))
ok("avatar 拼接系数随面积缩放(大画面更慢)",
   avatar.concat_rt_factor(640) < avatar.concat_rt_factor(config.AVATAR_SIZE)
   < avatar.concat_rt_factor(240))
ok("avatar 拼接系数在实测基准边长等于系数值",
   abs(avatar.concat_rt_factor(config.AVATAR_CONCAT_BASE_SIZE)
       - avatar.AVATAR_CONCAT_RT_FACTOR) < 1e-9)
ok("avatar 拼接系数基准不随默认边长漂移",
   avatar.concat_rt_factor(config.AVATAR_CONCAT_BASE_SIZE)
   == max(0.5, avatar.AVATAR_CONCAT_RT_FACTOR))

# ── 数字人位置(成片里的四角锚点) ──
_xy_tr = avatar.corner_xy("tr", 300, margin_x=40, margin_y=36,
                          video_w=1920, video_h=1080, pad=8)
ok("数字人默认位置是右上角",
   config.AVATAR_CORNER == "tr" and _xy_tr == (1920 - 300 - 16 - 40, 36), f"{_xy_tr}")
ok("数字人四角坐标各不相同且贴对应边",
   avatar.corner_xy("tl", 300, 40, 36, 1920, 1080, 8) == (40, 36)
   and avatar.corner_xy("bl", 300, 40, 36, 1920, 1080, 8)== (40, 1080 - 300 - 16 - 36)
   and avatar.corner_xy("br", 300, 40, 36, 1920, 1080, 8) == (1920 - 300 - 16 - 40,
                                                              1080 - 300 - 16 - 36))
ok("数字人四角留白对称(左右/上下边距一致)",
   avatar.corner_xy("tl", 300, 40, 36, 1920, 1080, 8)[0]
   == 1920 - (avatar.corner_xy("tr", 300, 40, 36, 1920, 1080, 8)[0] + 300 + 16))
ok("数字人坐标不为负(卡片比画面还大时)",
   avatar.corner_xy("br", 1080, 40, 36, 640, 360, 8) == (0, 0))
ok("数字人位置接受中文名", avatar.normalize_corner("右上") == "tr"
   and avatar.normalize_corner("左下") == "bl")
ok("数字人位置缺省回退默认", avatar.normalize_corner(None) == config.AVATAR_CORNER)
ok("数字人位置拒绝非法值", _raises(_via(avatar.normalize_corner, "中间"), ValueError))
ok("数字人位置宽松版对坏值回退默认",
   avatar.safe_corner("中间") == config.AVATAR_CORNER
   and avatar.safe_corner("中间", "bl") == "bl")
ok("数字人位置清单四角齐全且含默认角",
   [o["key"] for o in config.avatar_corner_options()] == ["tl", "tr", "br", "bl"]
   and config.AVATAR_CORNER in [o["key"] for o in config.avatar_corner_options()])

_tl_src = [{"index": 1, "clip": "/tmp/a.mp4", "start": 1.5, "duration": 3.0}]
_tl_path = Path(_tmp_text("tl.json", ""))
avatar.write_timeline(_tl_src, _tl_path)
ok("avatar 时间轴读写往返", avatar.read_timeline(_tl_path) == _tl_src)
ok("avatar 缺失时间轴返回空列表", avatar.read_timeline(Path("/tmp/不存在_tl.json")) == [])

ok("avatar 注册表默认形象可解析",
   styles.avatar_file() == styles.AVATARS[styles.DEFAULT_AVATAR]["file"])
ok("avatar 未知形象回退默认", styles.avatar_file("不存在的形象") == styles.avatar_file())


# ═══════════════ 全局偏好(新任务默认抠不抠背景) ═══════════════
#
# 为什么要有它:抠像原来是**任务级**选项且默认关,换完数字人形象新建任务还得回创作页
# 勾一次「只保留人像(背景透明)」,忘了就是"背景没抠掉"(用户真实反馈)。
# 现在它是全局偏好:落盘、形象页可改、出厂默认 true(环境变量仍是出厂默认口径)。

# 本段与下面的形象库段共用这几个 stdlib(都要临时目录 + 重载模块)
import importlib as _il2  # noqa: E402
import os as _os2  # noqa: E402
import shutil as _shutil  # noqa: E402
import tempfile as _tempfile  # noqa: E402
import zlib as _zlib  # noqa: E402

_pref_dir = Path(_tempfile.mkdtemp(prefix="ttv_smoke_pref_"))
_pref_orig_env = _os2.environ.get("TTV_PREFERENCES")
_pref_orig_mod = preferences
try:
    _os2.environ["TTV_PREFERENCES"] = str(_pref_dir / "preferences.json")
    _il2.reload(config)
    preferences = _il2.reload(_pref_orig_mod)

    ok("偏好出厂默认为「新任务抠背景」", preferences.load()["avatar_cutout_new_jobs"] is True)
    ok("偏好文件不存在时用出厂默认(不报错)",
       not Path(config.PREFERENCES_FILE).exists() and preferences.avatar_cutout_new_jobs() is True)

    preferences.set_avatar_cutout_new_jobs(False)
    ok("偏好可写入并立刻读到", preferences.avatar_cutout_new_jobs() is False
       and Path(config.PREFERENCES_FILE).exists())
    ok("偏好落盘是纯 JSON", isinstance(
        json.loads(Path(config.PREFERENCES_FILE).read_text(encoding="utf-8")), dict))
    preferences.set_avatar_cutout_new_jobs(True)
    ok("偏好可反复改回", preferences.avatar_cutout_new_jobs() is True)
    ok("偏好只认真正的布尔",
       _raises(_via(preferences.set_avatar_cutout_new_jobs, "true"), ValueError)
       and _raises(_via(preferences.set_avatar_cutout_new_jobs, 1), ValueError))

    Path(config.PREFERENCES_FILE).write_text("{ 不是 JSON", encoding="utf-8")
    ok("偏好文件损坏时自愈回出厂默认",
       preferences.avatar_cutout_new_jobs() is True)
    Path(config.PREFERENCES_FILE).write_text('{"avatar_cutout_new_jobs": "yes"}', encoding="utf-8")
    ok("偏好字段类型不对时自愈回出厂默认",
       preferences.avatar_cutout_new_jobs() is True)
    Path(config.PREFERENCES_FILE).write_text('{"avatar_cutout_new_jobs": false}', encoding="utf-8")
    ok("偏好文件正常时以文件为准(压过出厂默认)",
       preferences.avatar_cutout_new_jobs() is False)
    Path(config.PREFERENCES_FILE).unlink()

    ok("偏好载荷含出厂默认与文件路径",
       {"avatar_cutout_new_jobs", "factory", "file"} <= set(preferences.payload()))

    # 接口:GET 读、POST 写,字符串一律 400
    _pf_main = __import__("main")
    _pcli = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(_pf_main.app)
    ok("接口 GET /api/preferences 返回布尔",
       _pcli.get("/api/preferences").json()["avatar_cutout_new_jobs"] is True)
    ok("接口 POST 关掉后 GET 与 /api/styles 都变 false",
       _pcli.post("/api/preferences", json={"avatar_cutout_new_jobs": False}).json()[
           "avatar_cutout_new_jobs"] is False
       and _pcli.get("/api/styles").json()["avatar_cutout_default"] is False)
    ok("接口 POST 字符串 400 且不改动原值",
       _pcli.post("/api/preferences", json={"avatar_cutout_new_jobs": "true"}).status_code == 400
       and _pcli.get("/api/preferences").json()["avatar_cutout_new_jobs"] is False)
    ok("接口 POST 空体不改动原值",
       _pcli.post("/api/preferences", json={}).status_code == 200
       and _pcli.get("/api/preferences").json()["avatar_cutout_new_jobs"] is False)
    _pcli.post("/api/preferences", json={"avatar_cutout_new_jobs": True})
    ok("/api/styles 也下发 preferences 块(前端开关与勾选框共用一份口径)",
       _pcli.get("/api/styles").json()["preferences"]["avatar_cutout_new_jobs"] is True)
finally:
    preferences = _pref_orig_mod
    if _pref_orig_env is None:
        _os2.environ.pop("TTV_PREFERENCES", None)
    else:
        _os2.environ["TTV_PREFERENCES"] = _pref_orig_env
    _il2.reload(config)
    _shutil.rmtree(_pref_dir, ignore_errors=True)


# ═══════════════ 设置(分析服务端点 / 成片保存位置) ═══════════════
#
# 网页「设置」页写的东西要**保存即生效**:分析服务三件套(地址/模型/密钥)必须每次调用
# 现读(原来是 import 时固化的常量),成片保存位置要在渲染完成后被真正用上。
# 这一段的重点是"泄漏面"与"生效链路"两件事:
#   · public() 只回密钥掩码,序列化后绝不能出现明文;
#   · analyze 真的把**刚保存的**地址与密钥发出去(用假 httpx 捕获请求,不联网);
#   · 另存失败不能拖垮出片(export_final 自己吞异常)。

import importlib as _il3  # noqa: E402
import os as _os3  # noqa: E402
import shutil as _shutil3  # noqa: E402
import tempfile as _tempfile3  # noqa: E402
import types as _types3  # noqa: E402

set_dir = Path(_tempfile3.mkdtemp(prefix="ttv_smoke_set_"))
_set_orig_env = {k: _os3.environ.get(k) for k in
                 ("TTV_SETTINGS", "TTV_DEEPSEEK_URL", "TTV_DEEPSEEK_MODEL",
                  "TTV_DEEPSEEK_KEY", "TTV_EXPORT_DIR")}
_set_orig_cfg, _set_orig_mod = config, settings
_set_orig_httpx = analyze.httpx
try:
    _os3.environ.update({
        "TTV_SETTINGS": str(set_dir / "settings.json"),
        "TTV_DEEPSEEK_URL": "http://factory.test/v1",
        "TTV_DEEPSEEK_MODEL": "FactoryModel",
        "TTV_DEEPSEEK_KEY": "sk-factory-9999",
        "TTV_EXPORT_DIR": "",
    })
    _il3.reload(config)
    settings = _il3.reload(_set_orig_mod)

    ok("设置出厂默认来自环境变量(文件不存在时)",
       settings.llm_endpoint() == ("http://factory.test/v1", "FactoryModel", "sk-factory-9999")
       and settings.export_dir() is None)

    settings.update({"llm_url": "https://cloud.test/v1/", "llm_model": "NewModel",
                     "llm_key": "sk-user-abcdef", "export_dir": str(set_dir / "out")})
    ok("保存后立刻生效(地址结尾斜杠被规范化)",
       settings.llm_endpoint() == ("https://cloud.test/v1", "NewModel", "sk-user-abcdef"))
    ok("成片保存位置保存后立刻生效",
       settings.export_dir() == set_dir / "out" and (set_dir / "out").is_dir())
    ok("设置文件是纯 JSON 且权限收紧到 0600",
       isinstance(json.loads(Path(config.SETTINGS_FILE).read_text(encoding="utf-8")), dict)
       and (Path(config.SETTINGS_FILE).stat().st_mode & 0o777) == 0o600)

    pub = settings.public()
    ok("接口载荷只给密钥掩码,明文不出后端",
       "sk-user-abcdef" not in json.dumps(pub, ensure_ascii=False)
       and pub["llm_key_set"] is True and pub["llm_key_masked"].endswith("cdef"))
    ok("载荷里的出厂默认同样不含密钥明文",
       "sk-factory-9999" not in json.dumps(pub.get("factory") or {}, ensure_ascii=False))

    settings.update({"llm_key": ""})
    ok("密钥可清除,且不会被出厂默认「复活」", settings.llm_endpoint()[2] == "")
    settings.update({"export_dir": ""})
    ok("保存位置可清空(= 不额外另存)", settings.export_dir() is None)

    ok("地址不合法时抛人话 ValueError",
       _raises(lambda: settings.update({"llm_url": "8.130.213.80:20001"}), ValueError))
    ok("保存位置不是绝对路径时抛人话 ValueError",
       _raises(lambda: settings.update({"export_dir": "relative/dir"}), ValueError))
    ok("保存位置指向一个已存在的文件时被拒",
       _raises(lambda: settings.update({"export_dir": __file__}), ValueError))
    ok("字段类型不对时被拒(不做隐式转换)",
       _raises(lambda: settings.update({"llm_url": 123}), ValueError))
    ok("校验失败不会写坏已有设置",
       settings.llm_endpoint() == ("https://cloud.test/v1", "NewModel", ""))

    Path(config.SETTINGS_FILE).write_text("{ 不是 JSON", encoding="utf-8")
    ok("设置文件损坏时自愈回出厂默认",
       settings.llm_endpoint()[0] == "http://factory.test/v1")
    Path(config.SETTINGS_FILE).write_text('{"llm_url": "不是地址"}', encoding="utf-8")
    ok("设置里字段非法时回出厂默认(不把必然失败的值当用户设置)",
       settings.llm_endpoint()[0] == "http://factory.test/v1")
    Path(config.SETTINGS_FILE).unlink()

    # 生效链路:analyze 必须把**刚保存的**地址/密钥发出去(假 httpx,不联网)
    _cap3 = {}

    class _FakeResp3:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}

    class _FakeClient3:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            _cap3["url"], _cap3["headers"] = url, headers or {}
            return _FakeResp3()

    analyze.httpx = _types3.SimpleNamespace(Client=_FakeClient3,
                                            Timeout=lambda *a, **k: None)
    settings.update({"llm_url": "https://live.test/v1", "llm_model": "LiveModel",
                     "llm_key": "sk-live-123456"})
    _content3 = analyze._call_local("sys", "user", max_tokens=16)
    ok("分析调用现读设置里的地址(不是 import 时固化的常量)",
       _cap3.get("url") == "https://live.test/v1/chat/completions", str(_cap3.get("url")))
    ok("分析调用带上了刚保存的密钥",
       (_cap3.get("headers") or {}).get("Authorization") == "Bearer sk-live-123456")
    ok("假网关的返回被正常解析", isinstance(_content3, str))
    analyze.httpx = _set_orig_httpx

    # 成片另存:真的复制一份、文件名来自项目标题、失败不影响出片
    _set_main = __import__("main")
    _src3 = set_dir / "final.mp4"
    _src3.write_bytes(b"x" * 4096)

    class _FakeJob3:
        def __init__(self):
            self.id = "abcdef123456"
            self.state = {"title": "测试:成片/标题"}
            self.saved = {}

        def set(self, **kw):
            self.saved.update(kw)

    _job3 = _FakeJob3()
    settings.update({"export_dir": str(set_dir / "out")})
    _set_main.export_final(_job3, _src3)
    _dest3 = set_dir / "out" / "测试_成片_标题.mp4"
    ok("另存到指定位置:文件名由项目标题洗净得到(非法字符换成下划线)",
       _dest3.exists() and _dest3.stat().st_size == 4096
       and _job3.saved.get("export_path") == str(_dest3))
    ok("另存是复制不是移动(项目里那份仍是下载来源)", _src3.exists())

    _job3b = _FakeJob3()
    _set_main.export_final(_job3b, _src3)
    ok("同名已有文件时加任务号后缀,不覆盖上一次的成片",
       (set_dir / "out" / "测试_成片_标题_abcdef.mp4").exists())

    _job3c = _FakeJob3()
    settings.update({"export_dir": ""})
    _set_main.export_final(_job3c, _src3)
    ok("没设置保存位置时什么都不做(行为与设置页出现之前一致)",
       "export_path" not in _job3c.saved)

    _job3d = _FakeJob3()
    settings.update({"export_dir": str(set_dir / "out")})
    _set_main.export_final(_job3d, set_dir / "不存在.mp4")
    ok("源文件不存在时静默跳过,不抛异常影响出片",
       "export_path" not in _job3d.saved)

    # 接口:GET 读、POST 写、非法 400、空体不改动、恢复默认
    settings = _il3.reload(_set_orig_mod)
    settings.update({"llm_url": "https://api.test/v1", "llm_model": "ApiModel",
                     "llm_key": "sk-api-777777", "export_dir": str(set_dir / "exp")})
    _scli = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(_set_main.app)
    _g3 = _scli.get("/api/settings")
    ok("接口 GET /api/settings 回掩码与保存位置",
       _g3.status_code == 200 and _g3.json()["llm_key_set"] is True
       and "sk-api-777777" not in _g3.text and _g3.json()["export_dir"] == str(set_dir / "exp"))
    ok("接口 POST 空体不改动原值",
       _scli.post("/api/settings", json={}).status_code == 200
       and _scli.get("/api/settings").json()["llm_model"] == "ApiModel")
    ok("接口 POST 改模型立刻生效",
       _scli.post("/api/settings", json={"llm_model": "ApiModel2"}).json()["llm_model"] == "ApiModel2")
    _bad3 = _scli.post("/api/settings", json={"llm_url": "没有协议头"})
    ok("接口 POST 非法地址 400 且回的是人话", _bad3.status_code == 400
       and "http://" in _bad3.json()["detail"])
    ok("接口 POST 400 后原值不变",
       _scli.get("/api/settings").json()["llm_url"] == "https://api.test/v1")
    ok("接口 POST 字段类型不对 400",
       _scli.post("/api/settings", json={"llm_model": 5}).status_code == 400)
    _ok3 = _scli.post("/api/settings/reset")
    ok("接口 POST /api/settings/reset 回到出厂默认(文件被删,不是把默认写死进文件)",
       _ok3.status_code == 200 and _ok3.json()["llm_url"] == "http://factory.test/v1"
       and not Path(config.SETTINGS_FILE).exists())
    ok("恢复默认后成片保存位置也不额外另存", _ok3.json()["export_dir"] == "")

    # 试连探针:指向一个必然连不上的本地端口,必须回一句人话而不是抛异常
    _probe3 = settings.probe_llm("http://127.0.0.1:1/v1")
    ok("测试连接连不上时回人话(不抛异常)",
       _probe3.get("ok") is False and isinstance(_probe3.get("message"), str)
       and len(_probe3["message"]) > 0, str(_probe3.get("message"))[:40])
finally:
    analyze.httpx = _set_orig_httpx
    settings = _set_orig_mod
    for _k3, _v3 in _set_orig_env.items():
        if _v3 is None:
            _os3.environ.pop(_k3, None)
        else:
            _os3.environ[_k3] = _v3
    _il3.reload(config)
    _shutil3.rmtree(set_dir, ignore_errors=True)


# ═══════════════ 数字人形象库(上传/查看/设默认/重命名/删除,零第三方依赖) ═══════════════
#
# 关键口径(每条都对应一个真实踩点):
#   ① 运行环境没有 Pillow,图片宽高/完整性只能按**文件头**解析(解析不出即损坏图);
#   ② 同一张图重复上传不能越传越多(按内容哈希命名去重);
#   ③ 内置形象可设默认但不可删,删掉当前默认后默认位必须落到剩余条目;
#   ④ 清单损坏/条目丢文件/目录里多出未登记图片,三种情况都要自愈,读路径不抛异常;
#   ⑤ 生效形象每次调用重新解析:环境变量 > 库默认 > 内置形象。

import glob as _glob  # noqa: E402
import struct as _struct  # noqa: E402
import zlib as _zlib  # noqa: E402


def _png(w, h, rgb=(200, 30, 40)):
    """现场造一张最小合法 PNG(PIL 不可用,测试样本自己拼)。"""
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def _chunk(tag, data):
        body = tag + data
        return (_struct.pack(">I", len(data)) + body
                + _struct.pack(">I", _zlib.crc32(body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", _struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", _zlib.compress(raw)) + _chunk(b"IEND", b""))


def _jpeg(w, h):
    """最小 JPEG:SOI + SOF0(带真实宽高)+ EOI(只要求头解析器认得出)。"""
    sof = (b"\xff\xc0" + _struct.pack(">H", 17) + b"\x08"
           + _struct.pack(">HH", h, w) + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01")
    return b"\xff\xd8" + sof + b"\xff\xd9"


def _webp_vp8l(w, h):
    """最小 VP8L(无损):0x2F 签名 + 14 位宽高各减一。"""
    bits = (w - 1) | ((h - 1) << 14)
    body = b"VP8L" + _struct.pack("<I", 5) + b"\x2f" + _struct.pack("<I", bits)
    return b"RIFF" + _struct.pack("<I", 4 + len(body)) + b"WEBP" + body


ok("形象库模块不引入 Pillow(运行环境没有它,只能按文件头解析)",
   not any(m == "PIL" or m.startswith("PIL.") for m in sys.modules)
   and "PIL" not in Path(avatar_library.__file__).read_text(encoding="utf-8"))
ok("形象库图片头解析:PNG",
   avatar_library.image_size(_png(321, 123), ".png") == (321, 123))
ok("形象库图片头解析:JPEG", avatar_library.image_size(_jpeg(640, 480), ".jpg") == (640, 480))
ok("形象库图片头解析:WebP", avatar_library.image_size(_webp_vp8l(256, 128), ".webp") == (256, 128))
ok("形象库图片头解析:扩展名与内容不符时以内容为准",
   avatar_library.image_size(_png(64, 32), ".jpg") == (64, 32))
ok("形象库拒绝无法解析的字节流",
   avatar_library.image_size(b"definitely not an image", ".png") == (0, 0)
   and avatar_library.image_size(b"", ".png") == (0, 0))
ok("形象库魔数识别与扩展名一致",
   avatar_library.sniff_ext(_png(8, 8)) == ".png"
   and avatar_library.sniff_ext(_jpeg(8, 8)) == ".jpg"
   and avatar_library.sniff_ext(b"\x00" * 64) == "")

# ── 库的增删改查:整块用临时目录 + 重新加载 config/avatar_library,绝不碰真实 assets/avatars/ ──
_av_lib_dir = Path(_tempfile.mkdtemp(prefix="ttv_smoke_avlib_"))
_av_orig_env = _os2.environ.get("TTV_AVATAR_LIBRARY")
_av_orig_libmod, _av_orig_cfg = avatar_library, config
# 库目录被覆盖成空目录时,内置形象仍要能从真实 assets/ 回退(这正是它不跟随库目录的原因)
_av_builtin_src = _av_lib_dir / "jinli.png"
_shutil.copyfile(avatar_library.builtin_path(), _av_builtin_src)
_av_before = sorted(p.name for p in (Path(config.ASSETS_DIR) / "avatars").glob("*"))
try:
    _os2.environ["TTV_AVATAR_LIBRARY"] = str(_av_lib_dir)
    _il2.reload(config)
    avatar_library = _il2.reload(_av_orig_libmod)
    # 本段既 reload 了 config,就必须把 jobs 与 main 一并对齐:main 是"首次导入"发生在
    # 本段之后的模块,它 import 的是**当时**的 jobs/config 对象。少对齐一次,后面 jobs 段
    # 新建的任务在 main 眼里就是"不存在"(_job_alive 判 false → stage_build 静默空转),
    # 表现为一堆与本功能无关的测试莫名失败 —— 这是测试里"重置模块"打断对象同一性的真实踩点。
    _jobs_mod = _il2.reload(_jobs_mod)
    _il2.reload(__import__("main"))

    _st0 = avatar_library.list_avatars()
    ok("形象库空目录自动注入内置形象",
       [i["id"] for i in _st0["items"]] == ["jinli"]
       and _st0["items"][0]["builtin"] and _st0["default_id"] == "jinli")
    ok("形象库内置形象来自真实 assets(不跟随库目录)",
       Path(_st0["items"][0]["path"]) == _av_builtin_src
       or Path(_st0["items"][0]["path"]) == avatar_library.builtin_path())

    _it, _dup = avatar_library.add_avatar(_png(400, 500), "face.png", name="  新 脸  ")
    ok("形象库上传成功并解析出真实宽高",
       (_it["width"], _it["height"]) == (400, 500) and not _dup, f"{_it['width']}x{_it['height']}")
    ok("形象库上传按内容哈希命名(天然去重)",
       _it["id"] == "av_" + __import__("hashlib").sha256(_png(400, 500)).hexdigest()[:16]
       and _it["file"] == _it["id"] + ".png")
    ok("形象库上传名称做空白清洗", _it["name"] == "新 脸")
    _it2, _dup2 = avatar_library.add_avatar(_png(400, 500), "copy.png")
    ok("形象库重复上传不新增副本", _dup2 and _it2["id"] == _it["id"]
       and len(avatar_library.list_avatars()["items"]) == 2)
    _st = avatar_library.list_avatars()
    ok("形象库条目落清单且默认位不变", _st["items"][1]["id"] == _it["id"]
       and _st["default_id"] == "jinli")
    ok("形象库条目字段齐备(供界面展示)",
       all(k in _st["items"][1] for k in ("name", "width", "height", "bytes", "created_at")))
    ok("形象库首次读取即落清单(自愈写入,不用等第一次上传)",
       Path(config.AVATAR_LIBRARY_FILE).exists())
    ok("形象库清单可被 JSON 解析(纯文本、可备份)", isinstance(
        json.loads((Path(config.AVATAR_LIBRARY_FILE)).read_text(encoding="utf-8")), dict))
    # 清单要能被「整目录拷走就搬家」:里面不能出现绝对路径(内置条目的 path 由 config 现算,
    # 不落盘)。这条与下一条是同一个真实踩点的两半:剥掉 path 后若不与**磁盘形态**比对
    # "该不该写回",清单会永远建不出来。
    _disk = json.loads(Path(config.AVATAR_LIBRARY_FILE).read_text(encoding="utf-8"))
    ok("形象库清单不含绝对路径(可整目录迁移)",
       _disk["items"] and all("path" not in i for i in _disk["items"])
       and not any(str(i.get("file", "")).startswith("/") for i in _disk["items"]))
    ok("形象库内存条目仍带解析好的绝对路径(内置不跟随库目录)",
       all(it["path"] for it in avatar_library.list_avatars()["items"] if it["builtin"]))
    _mk = Path(config.AVATAR_LIBRARY_FILE).stat().st_mtime_ns
    avatar_library.list_avatars()
    ok("形象库状态无变化时不重写清单(读路径不产生写放大)",
       Path(config.AVATAR_LIBRARY_FILE).stat().st_mtime_ns == _mk)

    avatar_library.set_default(_it["id"])
    ok("形象库可设默认并立刻生效",
       avatar_library.current_info()["id"] == _it["id"]
       and avatar_library.resolve_default_image() == _av_lib_dir / _it["file"])
    ok("形象库生效形象与 config 解析一致",
       config.resolve_avatar_image() == avatar_library.resolve_default_image())

    avatar_library.rename_avatar(_it["id"], "换 名")
    ok("形象库重命名即时生效", avatar_library.find(_it["id"])["name"] == "换 名")
    ok("形象库重命名清洗控制字符",
       avatar_library.rename_avatar(_it["id"], "ab\x07c\x00d")["name"] == "abcd")

    ok("形象库拒绝非白名单扩展名",
       _raises(lambda: avatar_library.add_avatar(_png(8, 8), "x.gif"), ValueError))
    ok("形象库拒绝损坏图片(解析不出宽高)",
       _raises(lambda: avatar_library.add_avatar(b"not an image", "x.png"), ValueError))
    ok("形象库拒绝超限体积",
       _raises(lambda: avatar_library.add_avatar(b"\x89PNG" + b"\x00" * (config.AVATAR_UPLOAD_MAX + 1),
                                                 "big.png"), ValueError))
    ok("形象库拒绝空内容",
       _raises(lambda: avatar_library.add_avatar(b"", "x.png"), ValueError))
    ok("形象库同图上传内置图不产生副本",
       avatar_library.add_avatar(_av_builtin_src.read_bytes(), "jinli.png")[0]["id"] == "jinli")

    # 环境变量是最外层覆盖:库里选了默认,环境变量仍然赢
    _os2.environ["TTV_AVATAR_IMAGE"] = "/tmp/pinned-face.png"
    ok("形象库生效形象被环境变量覆盖",
       avatar_library.current_info()["env_override"] is True
       and config.resolve_avatar_image() == Path("/tmp/pinned-face.png"))
    del _os2.environ["TTV_AVATAR_IMAGE"]
    ok("形象库去掉环境变量后回到库默认",
       avatar_library.current_info()["env_override"] is False
       and avatar_library.current_info()["id"] == _it["id"])

    # 自愈:清单损坏 / 条目丢文件 / 目录里多出未登记图片
    Path(config.AVATAR_LIBRARY_FILE).write_text("{ 这不是 JSON", encoding="utf-8")
    _st = avatar_library.list_avatars()
    ok("形象库清单损坏时自愈(不抛异常,磁盘图片仍在)",
       _st["items"][0]["id"] == "jinli" and any(i["id"] == _it["id"] for i in _st["items"]))
    Path(config.AVATAR_LIBRARY_FILE).unlink()
    ok("形象库清单丢失时自愈", len(avatar_library.list_avatars()["items"]) >= 2)

    _ghost = _av_lib_dir / "av_ghost0000000000.png"
    _ghost.write_bytes(_png(20, 10))
    _st = avatar_library.list_avatars()
    ok("形象库目录里未登记的图片自动补登记",
       any(i["file"] == _ghost.name for i in _st["items"]))
    _ghost.unlink()
    ok("形象库条目文件丢失时自动摘除",
       not any(i["file"] == "av_ghost0000000000.png"
               for i in avatar_library.list_avatars()["items"]))

    _victim, _ = avatar_library.add_avatar(_png(11, 13), "victim.png", name="待删")
    avatar_library.set_default(_victim["id"])
    avatar_library.delete_avatar(_victim["id"])
    ok("形象库删除当前默认后默认位回落到剩余条目",
       avatar_library.current_info()["id"] != _victim["id"]
       and avatar_library.find(_victim["id"]) is None)
    ok("形象库删除条目时文件一并清理",
       not (Path(config.AVATAR_LIBRARY_DIR) / _victim["file"]).exists())
    ok("形象库内置形象不可删除(权限错)",
       _raises(_via(avatar_library.delete_avatar, "jinli"), PermissionError))
    ok("形象库删除不存在的条目报 KeyError",
       _raises(_via(avatar_library.delete_avatar, "nope"), KeyError))
    ok("形象库设置不存在的默认报 KeyError",
       _raises(_via(avatar_library.set_default, "nope"), KeyError))

    # ── 接口契约(TestClient,进程内,不需要 GPU/gRPC 服务) ──
    # 这里只 import、**不 reload** main:main 在 jobs 段之后首次导入,已绑定本段的
    # config/jobs;reload 会让它重新 import 一份**新的** jobs 模块,于是后面 jobs 段创建的
    # 任务对象不再等于新注册表里的那个 —— _job_alive 判 false、stage_build 静默空转,
    # 后续测试会莫名其妙地失败。这是真实踩点:测试里的"重置模块"会打断自己依赖的对象同一性。
    _av_main = __import__("main")
    _cli = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(_av_main.app)
    _r = _cli.get("/api/avatars")
    ok("接口 形象列表返回 200 与字段齐备",
       _r.status_code == 200
       and {"items", "default_id", "current", "max_bytes", "accept"} <= set(_r.json()))
    _r = _cli.post("/api/avatars", files={"file": ("api.png", _png(120, 90), "image/png")},
                   data={"name": "接口脸"})
    ok("接口 上传返回 200 与条目", _r.status_code == 200 and _r.json()["ok"]
       and _r.json()["item"]["width"] == 120)
    _api_id = _r.json()["item"]["id"]
    ok("接口 重复上传标记 duplicate",
       _cli.post("/api/avatars", files={"file": ("api.png", _png(120, 90), "image/png")}
                 ).json()["duplicate"] is True)
    ok("接口 上传坏图 400",
       _cli.post("/api/avatars", files={"file": ("x.png", b"nope", "image/png")}).status_code == 400)
    ok("接口 上传非法扩展名 400",
       _cli.post("/api/avatars", files={"file": ("x.gif", _png(4, 4), "image/gif")}).status_code == 400)
    _r = _cli.get(f"/api/avatars/{_api_id}/file")
    ok("接口 取图 200 且 Content-Type/缓存头正确",
       _r.status_code == 200 and _r.headers["content-type"].startswith("image/png")
       and "immutable" in _r.headers.get("cache-control", ""))
    ok("接口 设默认 200 且生效",
       _cli.post(f"/api/avatars/{_api_id}/default").json()["current"]["id"] == _api_id)
    ok("接口 重命名 200 且改名生效",
       _cli.post(f"/api/avatars/{_api_id}/rename", json={"name": "改过"}
                 ).json()["item"]["name"] == "改过")
    ok("接口 未知形象一律 404",
       _cli.get("/api/avatars/nope/file").status_code == 404
       and _cli.post("/api/avatars/nope/default").status_code == 404
       and _cli.delete("/api/avatars/nope").status_code == 404)
    ok("接口 删除内置形象 409",
       _cli.delete("/api/avatars/jinli").status_code == 409)
    _r = _cli.delete(f"/api/avatars/{_api_id}")
    ok("接口 删除 200 且默认位回退", _r.status_code == 200
       and _r.json()["current"]["id"] != _api_id)
    ok("接口 形象删除后取图 404", _cli.get(f"/api/avatars/{_api_id}/file").status_code == 404)
    _lib = _cli.get("/api/styles").json()["avatar_library"]
    ok("接口 /api/styles 下发形象库(current 与上传规格)",
       {"items", "current", "max_bytes", "accept"} <= set(_lib)
       and _lib["current"]["name"] == avatar_library.current_info()["name"])
finally:
    avatar_library = _av_orig_libmod
    if _av_orig_env is None:
        _os2.environ.pop("TTV_AVATAR_LIBRARY", None)
    else:
        _os2.environ["TTV_AVATAR_LIBRARY"] = _av_orig_env
    _os2.environ.pop("TTV_AVATAR_IMAGE", None)
    _il2.reload(config)
    _shutil.rmtree(_av_lib_dir, ignore_errors=True)

_av_after = sorted(p.name for p in (Path(config.ASSETS_DIR) / "avatars").glob("*"))
ok("形象库测试不污染仓库真实 assets/avatars/", _av_before == _av_after)

ok("形象库生效形象解析不在 import 时固化(改库即改结果)",
   config.resolve_avatar_image() == avatar_library.resolve_default_image())


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

# 播报音轨必须与源配音**逐字节对齐**:16bit 下"采样数当字节数"用会让整条人声
# 每个采样错位一个字节(听起来全是噪声,但静音段仍然正常,极难发现)。
# 用一段已知正弦做源,直接比对字节。
_src_wav = Path(_tmp_text("bc_src.wav", ""))
with _wave.open(str(_src_wav), "wb") as _w:
    _w.setnchannels(1)
    _w.setsampwidth(2)
    _w.setframerate(44100)
    import math as _math
    _tone = b"".join(
        int(12000 * _math.sin(2 * _math.pi * 440 * i / 44100)).to_bytes(2, "little", signed=True)
        for i in range(44100))
    _w.writeframes(_tone)
_out_wav = Path(_tmp_text("bc_out.wav", ""))
avatar.build_broadcast_audio(
    [{"index": 2, "clip": "/tmp/none.mp4", "start": 0.0, "duration": 1.5}],
    {2: {"path": str(_src_wav)}}, _out_wav)
_e = _out_wav.read_bytes()[44:]
_head_b = int(44100 * 0.25) * 2                      # 0.25s × 44100 × 2 字节
ok("播报音轨帧首静音恰好 0.25s(按字节)",
   len(_e) >= _head_b and _e[:_head_b] == b"\x00" * _head_b,
   f"前 {_head_b} 字节应为全零")
ok("播报音轨与源配音逐字节对齐(无半字节错位)",
   _e[_head_b:_head_b + len(_tone)] == _tone,
   f"比对区间 [{_head_b}, {_head_b + len(_tone)})")

# 同一处字节/采样换算还有另一半:`need = int(rate * 2 * dur)` 在**真实时长**下有一半
# 概率落在奇数上。上面那条测试用的 2.5s / 1.5s 恰好都是偶数、且只铺了一帧,所以
# 一直踩不到这个分支。wave 写出奇数长度时声明帧数会比数据区少一个字节 → 从这一帧
# 起每一帧都整体错位一个字节,整条音轨中段开始变"雪花声"(实测线上任务 -9.4 dB)。
# 这里让**第一帧**的 need 落在奇数上,断言紧随其后的第二帧人声仍然逐字节对齐。
_odd_dur = 3.0000114                  # 真实时长的小数尾巴:88200 × 它 = 264601.005 → 奇数
_bc_rate = 44100
ok("测试前提:该时长下帧字节数为奇数(模拟 ffprobe 真实时长)",
   int(_bc_rate * 2 * _odd_dur) % 2 == 1, f"need={int(_bc_rate * 2 * _odd_dur)}")
_odd_out = Path(_tmp_text("bc_odd.wav", ""))
avatar.build_broadcast_audio(
    [{"index": 2, "clip": "/tmp/none_a.mp4", "start": 0.0, "duration": _odd_dur},
     {"index": 3, "clip": "/tmp/none_b.mp4", "start": _odd_dur, "duration": 1.5}],
    {2: {"path": str(_src_wav)}, 3: {"path": str(_src_wav)}}, _odd_out)
with _wave.open(str(_odd_out), "rb") as _w:
    _odd_frames = _w.getnframes()
_odd_data = _odd_out.read_bytes()[44:]
ok("播报音轨数据区长度 = 2×声明帧数(奇数帧长不留残字节)",
   len(_odd_data) == _odd_frames * 2,
   f"数据区 {len(_odd_data)} 字节 vs 声明 {_odd_frames * 2} 字节")
# 第一帧按下限取整到整数采样(264600 字节)后,第二帧的人声必须从偶数字节偏移开始;
# 若那一个残字节还在,比对区间会整体错开 1 字节 → 全不等。
_odd_need1 = int(_bc_rate * _odd_dur) * 2
_off2 = _odd_need1 + _head_b
ok("奇数帧长之后的下一帧人声仍逐字节对齐(不错位一个字节)",
   len(_odd_data) >= _off2 + len(_tone)
   and _odd_data[_off2:_off2 + len(_tone)] == _tone,
   f"第二帧人声应在 [{_off2}, {_off2 + len(_tone)}),第一帧长 {_odd_need1} 字节")

# 配音验收必须同时看「时长」和「有没有声音」:eafca9e512a8 整组配音就是
# 峰值 -91dB 的占位静音,时长却完全"合理",只查时长会全部放行。
sil_wav = Path(_tmp_text("bc_silent.wav", ""))
with _wave.open(str(sil_wav), "wb") as _w:
    _w.setnchannels(1)
    _w.setsampwidth(2)
    _w.setframerate(44100)
    _w.writeframes(b"\x00" * (44100 * 2))          # 1.0s 静音
ok("tts 有声音的配音判合格", tts.audio_plausible("测试文本", _src_wav, 1.0))
ok("tts 静音配音(时长正常)判不合格",
   not tts.audio_plausible("测试文本", sil_wav, 1.0))
ok("tts 峰值可读出", (tts.audio_peak_db(sil_wav) or 0) < -60,
   f"静音峰值={tts.audio_peak_db(sil_wav)}")

ok("播报耗时估算随片长增长",
   avatar.estimate_broadcast_sec(600) > avatar.estimate_broadcast_sec(300) > 0)
# 拼接系数按面积比从**实测基准边长**外推:默认边长(300)不等于基准(320)时,
# 预计时间必须用 300 自己的系数,而不是照搬 320 的实测值
_ct_default = avatar.AVATAR_CONCAT_RT_FACTOR * (config.AVATAR_CONCAT_BASE_SIZE / config.AVATAR_SIZE) ** 2
ok("播报耗时估算=配音+人像+拼接",
   avatar.estimate_broadcast_sec(60) == round(60 / avatar.AVATAR_RT_FACTOR
                                             + 60 / _ct_default
                                             + 60 / avatar.AVATAR_TTS_RT_FACTOR))
ok("播报耗时估算可排除已缓存的配音",
   avatar.estimate_broadcast_sec(60, include_tts=False)
   < avatar.estimate_broadcast_sec(60, include_tts=True))
ok("播报 ETA 步骤1 无进度时不给数字", avatar.broadcast_eta(1, 0, None, 0, 0, 100, 100) is None)
ok("播报 ETA 步骤1 同一帧完成后给正数",
   (avatar.broadcast_eta(1, 1, 4, 10.0, 0, 100, 100) or 0) > 0)
ok("播报 ETA 步骤3 等于剩余拼接时间",
   avatar.broadcast_eta(3, 0, 0, 30.0, 0, 100, 100, 60.0)
   == round(40 / _ct_default))
ok("播报 ETA 步骤2 用实测速率(快于静态系数时更小)",
   avatar.broadcast_eta(2, 2, 4, 20.0, 20.0, 40.0, 40.0)
   < avatar.broadcast_eta(2, 0, 4, 0.0, 0.0, 40.0, 40.0))
# 尺寸影响的是**拼接编码**(人像推理在服务端固定 464,与目标边长无关),
# 所以预计时间只随拼接段变化,且方向必须是"画面越大越慢",否则界面上会低估
ok("播报耗时估算随尺寸增长",
   avatar.estimate_broadcast_sec(600, size=640)
   > avatar.estimate_broadcast_sec(600, size=config.AVATAR_SIZE)
   > avatar.estimate_broadcast_sec(600, size=240))
ok("播报 ETA 步骤3 随尺寸增长",
   avatar.broadcast_eta(3, 0, 0, 30.0, 0, 100, 100, 60.0, size=640)
   > avatar.broadcast_eta(3, 0, 0, 30.0, 0, 100, 100, 60.0))

_wt = tts.word_times("发展新质生产力", 4.0)
ok("词级时间轴起点含 VO_OFFSET", abs(_wt[0][1] - tts.VO_OFFSET) < 1e-6)
# 词级时间轴从 VO_OFFSET 起铺满配音时长(与成片 audio 的 data-start 同一口径)
ok("词级时间轴跨度等于配音时长", abs((_wt[-1][2] - _wt[0][1]) - 4.0) < 1e-6)

# ── 配音时长验收(本地 CosyVoice3 解码不稳定:残句 0.01× / 复读 3.4×)──
_t42 = "发展新质生产力需要因地制宜实事求是"
_expect = len(_t42) / 4.2
ok("tts 时长比值 = 实际 / 预期", abs(tts.duration_ratio(_t42, _expect) - 1.0) < 1e-6)
ok("tts 正常时长判合格", tts.duration_plausible(_t42, _expect * 1.2))
ok("tts 残句(0.3×)判不合格", not tts.duration_plausible(_t42, _expect * 0.3))
ok("tts 复读(2.5×)判不合格", not tts.duration_plausible(_t42, _expect * 2.5))
ok("tts 验收窗口可配", tts.ACCEPT_RATIO[0] < 1.0 < tts.ACCEPT_RATIO[1])

# ── TTS 运行时钉版(e868f32bec3d 全片乱码的根因:transformers 4.57 让语音 LLM 输出乱码,
#    而时长 0.84–0.88×、峰值 -2dB 全部"正常",时长/静音验收都拦不住)──
ok("钉版校验:版本相符时不报", config.pinned_dep_mismatch(config.PINNED_TTS_DEPS) == [])
ok("钉版校验:transformers 过高即报",
   any("transformers" in m for m in config.pinned_dep_mismatch({"transformers": "4.57.3"})))
ok("钉版校验:依赖缺失也算不符",
   any("缺失" in m for m in config.pinned_dep_mismatch({})))
_bad = config.pinned_dep_mismatch({"transformers": "4.57.3", "tokenizers": "0.22.2"})
ok("钉版校验:两项都不符时都报出来", len(_bad) == 2, " ；".join(_bad))

# 环境校验:tts-venv 里实际装的必须就是钉版(venv 不存在则跳过,不判失败)
_tts_py = Path(config.TTS_VENV_DIR) / "bin" / "python"
if not _tts_py.exists():
    skip("TTS venv 运行时为钉版", f"{_tts_py} 不存在")
else:
    import subprocess as _sp
    _r = _sp.run([str(_tts_py), "-c",
                  "import json,transformers,tokenizers;"
                  "print(json.dumps({'transformers':transformers.__version__,"
                  "'tokenizers':tokenizers.__version__}))"],
                 capture_output=True, text=True, timeout=120)
    try:
        _got = json.loads((_r.stdout or "").strip().splitlines()[-1])
    except Exception:
        _got = None
    if _got is None:
        skip("TTS venv 运行时为钉版", f"探测失败:{(_r.stderr or '').strip()[-120:]}")
    else:
        _mism = config.pinned_dep_mismatch(_got)
        ok("TTS venv 运行时为钉版(否则合成必乱码)", _mism == [],
           " ；".join(_mism) if _mism else str(_got))


# ═══════════ 数字人出镜开关 / 几何:接口层的规则(临时 ROOT,不碰真实任务) ═══════════
#
# 这里必须过一遍 main.py:规则不在纯函数里,而在"渲染前先看出镜开关"这一步 ——
# 关掉出镜后,磁盘上仍留着上次构建的 avatar_timeline.json,只按文件判断会把
# 不该出现的人像叠回去(成片出来才发现)。

_orig_root2 = _os.environ.get("TTV_ROOT")
try:
    _os.environ["TTV_ROOT"] = _tmpf.mkdtemp(prefix="ttv_geom_")
    _il.reload(_config)
    _il.reload(_jobs_mod)
    # main 必须与**刚 reload 的** config/jobs 对齐:它持有的是 `from jobs import JOBS, ...`
    # 那份绑定。首次导入时(它在本段之前已被前面的用例导入)若不对齐,本段新建的任务在
    # _job_alive 眼里就不存在,stage_build 会静默空转。
    import main as _main  # noqa: E402 - 必须在 TTV_ROOT 指向临时目录之后再导入
    _il.reload(_main)

    _gj = _jobs_mod.create_job("solemn-red", 120, "geom.txt")
    _gproj = _gj.paths()["project"]
    _gproj.mkdir(parents=True, exist_ok=True)
    (_gproj / "avatar_timeline.json").write_text(
        json.dumps([{"index": 1, "clip": "/tmp/none.mp4", "start": 0.0, "duration": 2.0}]),
        encoding="utf-8")

    _gj.set(avatar=True)
    ok("出镜时渲染会叠加(时间轴非空)", len(_main._overlay_timeline(_gj, _gproj)) == 1)
    _gj.set(avatar=False)
    ok("关掉出镜后即使旧时间轴还在也不叠加",
       _main._overlay_timeline(_gj, _gproj) == [])
    _gj.set(avatar=True)
    ok("重新开启出镜后旧时间轴又能用",
       len(_main._overlay_timeline(_gj, _gproj)) == 1)

    # 几何缺省与坏值:老任务没有 avatar_geom → 默认右上/AVATAR_SIZE/**抠像取全局偏好**;
    # 坏值不抛错。抠像的默认不再是静态的 config.AVATAR_CUTOUT,而是 preferences 里的值。
    _gj.state.pop("avatar_geom", None)
    _gj.state.pop("avatar_cutout_explicit", None)
    _pref_cut = _main.preferences.avatar_cutout_new_jobs()
    ok("老任务几何回默认(右上 / 默认边长 / 抠像跟随全局偏好)",
       _main._avatar_geom(_gj) == {"corner": config.AVATAR_CORNER,
                                   "size": config.AVATAR_SIZE, "cutout": _pref_cut},
       str(_main._avatar_geom(_gj)))
    _gj.state["avatar_geom"] = {"corner": "中间", "size": 321, "cutout": "是"}
    ok("几何坏值不抛错、回默认",
       _main._avatar_geom(_gj) == {"corner": config.AVATAR_CORNER,
                                   "size": config.AVATAR_SIZE, "cutout": _pref_cut})
    # 全局偏好只影响"没存过"的任务;任务明确存过的值不受影响(不能悄悄改用户的任务设置)
    _orig_pref_setter = _main.preferences.set_avatar_cutout_new_jobs
    try:
        _main.preferences.set_avatar_cutout_new_jobs(not _pref_cut)
        _gj.state["avatar_geom"] = {"corner": "bl", "size": 480, "cutout": _pref_cut}
        ok("全局偏好改了也不动已存过几何的任务",
           _main._avatar_geom(_gj)["cutout"] is _pref_cut)
        _gj.state.pop("avatar_geom", None)
        ok("全局偏好改了之后,没存过几何的任务跟着变",
           _main._avatar_geom(_gj)["cutout"] is (not _pref_cut))
    finally:
        _orig_pref_setter(_pref_cut)
    ok("几何解析缺省沿用现值",
       _main._normalize_geom(None, None, None,
                             {"corner": "bl", "size": 480, "cutout": True})
       == {"corner": "bl", "size": 480, "cutout": True})
    ok("几何解析非法位置抛错",
       _raises(lambda: _main._normalize_geom("中间", None), ValueError))
    ok("几何解析非法边长抛错",
       _raises(lambda: _main._normalize_geom(None, 321), ValueError))
    ok("几何解析非法抠像值抛错(字符串不算布尔)",
       _raises(lambda: _main._normalize_geom(None, None, "true"), ValueError))
    # 抠像降级提示:只有"一条遮罩都没拿到"才写 avatar_error(个别缺失不打扰用户)
    ok("抠像未开启时不报降级",
       _main._cutout_missing({"cutout": False}, [{"matte": None}]) == "")
    ok("抠像拿到遮罩时不报降级",
       _main._cutout_missing({"cutout": True}, [{"matte": "a.mp4"}, {"matte": None}]) == "")
    ok("抠像一条都没抠成时给出原因",
       _main._cutout_missing({"cutout": True}, [{"matte": None}]).startswith("抠像不可用"))
    ok("没有时间轴时不报降级",
       _main._cutout_missing({"cutout": True}, []) == "")

    # ── 一键出片:构建 + 渲染一次触发(不拉 Studio、不停在预览态、失败账各记各的) ──
    # 重活(配音/组装/渲染/Studio)全部打桩,这里只验阶段编排与状态口径。
    _sb = _jobs_mod.create_job("solemn-red", 60, "build-direct.txt")
    _studio_calls = []
    _leaves = (_main._synthesize_and_fit, _main.assemble.build, _main.start_studio, _main._run_check)
    try:
        _main._synthesize_and_fit = lambda job, reuse_vo=True: ({"frames": []}, {}, "cosyvoice3", True)
        _main.assemble.build = lambda script, combo, vo, proj: {"total": 12.0, "starts": {}}
        _main.start_studio = lambda job: _studio_calls.append(job.id)
        _main._run_check = lambda job: None
        _main.stage_build(_sb, preview=False)
        ok("构建 preview=False 不拉 Studio(直达出片没人看编辑器)", _studio_calls == [])
        ok("构建 preview=False 停在 building(不等用户点渲染)", _sb.status == "building",
           _sb.status)
        ok("构建 preview=False 照记 build 历史",
           _sb.history()[-1]["step"] == "build" and _sb.status != "preview")
        _main.stage_build(_sb, preview=True)
        ok("构建 preview=True 照旧拉 Studio 并停在 preview",
           _studio_calls == [_sb.id] and _sb.status == "preview", _sb.status)
    finally:
        (_main._synthesize_and_fit, _main.assemble.build,
         _main.start_studio, _main._run_check) = _leaves

    _drs = _jobs_mod.create_job("solemn-red", 60, "direct.txt")
    _drs.set(status="building")   # api_render 在 dispatch 前就是这个状态
    _calls = []

    def _stub_build(job, force_voice=False, preview=True):
        _calls.append(("build", preview, job.status))
        job.set(total_sec=12.0)
        job.record_history("build", detail="总时长 12 秒")

    def _stub_render(job, fmt="mp4"):
        _calls.append(("render", fmt, job.status))
        job.set(status="rendered", render_format=fmt)
        job.record_history("render", detail="成片 1.0 MB")

    _stages = (_main.stage_build, _main.stage_render)
    try:
        _main.stage_build, _main.stage_render = _stub_build, _stub_render
        _main.stage_direct_render(_drs, "mp4")
    finally:
        _main.stage_build, _main.stage_render = _stages
    ok("一键出片:先构建后渲染,构建段用 preview=False",
       _calls == [("build", False, "building"), ("render", "mp4", "building")], str(_calls))
    ok("一键出片:构建段不停在 preview(前端因此不会去加载 Studio)",
       _calls[0][2] == "building")
    ok("一键出片:状态最终为 rendered", _drs.status == "rendered")
    ok("一键出片:跑完清掉 direct_render 标记", _drs.state.get("direct_render") is False)
    ok("一键出片:构建与渲染各留一条历史",
       [h["step"] for h in _drs.history()] == ["build", "render"],
       str([h["step"] for h in _drs.history()]))

    # 失败口径:构建炸了记 build(且不再往下渲染),渲染炸了记 render —— 与分步走完全一样
    _drb = _jobs_mod.create_job("solemn-red", 60, "direct-build-fail.txt")
    _bfail = []

    def _boom_build(job, force_voice=False, preview=True):
        _bfail.append("build")
        raise RuntimeError("构建炸了")

    def _count_render(job, fmt="mp4"):
        _bfail.append("render")

    try:
        _main.stage_build, _main.stage_render = _boom_build, _count_render
        try:
            _main.stage_direct_render(_drb, "mp4")
        except RuntimeError:
            pass
    finally:
        _main.stage_build, _main.stage_render = _stages
    ok("一键出片:构建段失败不再进入渲染", _bfail == ["build"], str(_bfail))
    ok("一键出片:构建段失败记在 build 上",
       _drb.history()[-1]["step"] == "build" and _drb.history()[-1]["status"] == "failed",
       str(_drb.history()))
    ok("一键出片:构建段失败也清掉 direct_render 标记",
       _drb.state.get("direct_render") is False)

    _drr = _jobs_mod.create_job("solemn-red", 60, "direct-render-fail.txt")

    def _ok_build(job, force_voice=False, preview=True):
        pass

    def _boom_render(job, fmt="mp4"):
        raise RuntimeError("渲染炸了")

    try:
        _main.stage_build, _main.stage_render = _ok_build, _boom_render
        try:
            _main.stage_direct_render(_drr, "mp4")
        except RuntimeError:
            pass
    finally:
        _main.stage_build, _main.stage_render = _stages
    ok("一键出片:渲染段失败记在 render 上",
       _drr.history()[-1]["step"] == "render" and _drr.history()[-1]["status"] == "failed",
       str(_drr.history()))

    # 接口层:build=true 从 analyzed 就能触发,且在 dispatch 之前就把状态翻成 building(防连点)
    class _Req:
        def __init__(self, payload):
            self._p = payload

        async def json(self):
            return self._p

    def _code(fn):
        try:
            fn()
            return 0
        except _main.HTTPException as e:
            return e.status_code
        except Exception:
            return -1

    _ar = _jobs_mod.create_job("solemn-red", 60, "api-direct.txt")
    _ar.paths()["script"].write_text(json.dumps({"frames": []}), encoding="utf-8")
    _ar.set(status="analyzed")
    _bg = []
    _real_bg = _main.run_in_background
    try:
        _main.run_in_background = lambda job, fn, *a, **kw: _bg.append((fn.__name__, a, kw))
        _res = _asyncio.run(_main.api_render(_ar.id, _Req({"format": "mp4", "build": True})))
        ok("接口:build=true 回 direct 标记", _res == {"ok": True, "direct": True}, str(_res))
        ok("接口:直达出片在 dispatch 前把状态翻成 building(窗口内连点会被 409 挡下)",
           _ar.status == "building", _ar.status)
        ok("接口:直达出片打上 direct_render 标记", _ar.state.get("direct_render") is True)
        ok("接口:直达出片派发 stage_direct_render 且 step=None(失败账由阶段自己记)",
           _bg and _bg[0][0] == "stage_direct_render" and _bg[0][2].get("step") is None,
           str(_bg))
        ok("接口:忙态(building)再点一键出片被 409 挡下",
           _code(lambda: _asyncio.run(
               _main.api_render(_ar.id, _Req({"build": True})))) == 409)
        ok("接口:build 传字符串不算布尔(400)",
           _code(lambda: _asyncio.run(
               _main.api_render(_ar.id, _Req({"build": "true"})))) == 400)
        _ar.state["status"] = "analyzed"     # 回到可触发态,单独验"没有脚本"
        _ar.paths()["script"].unlink()
        ok("接口:没有脚本时一键出片被 409 挡下",
           _code(lambda: _asyncio.run(
               _main.api_render(_ar.id, _Req({"build": True})))) == 409)
        # 老路径不受影响:不传 build 时仍要求已构建好预览,并派发 stage_render(step=render)
        _bg.clear()
        _ar.paths()["script"].write_text(json.dumps({"frames": []}), encoding="utf-8")
        _ar.state["status"] = "preview"
        _res2 = _asyncio.run(_main.api_render(_ar.id, _Req({"format": "mov"})))
        ok("接口:不传 build 时仍只渲染(回 direct=false)",
           _res2 == {"ok": True, "direct": False}, str(_res2))
        ok("接口:只渲染仍要求已构建好预览",
           _bg and _bg[0][0] == "stage_render" and _bg[0][2].get("step") == "render"
           and _bg[0][1] == ("mov",), str(_bg))
        _ar.state["status"] = "analyzed"
        ok("接口:analyzed 时只渲染被 409 挡下(必须先构建)",
           _code(lambda: _asyncio.run(
               _main.api_render(_ar.id, _Req({"format": "mp4"})))) == 409)
        ok("接口:坏格式仍 400",
           _code(lambda: _asyncio.run(
               _main.api_render(_ar.id, _Req({"format": "avi"})))) == 400)
    finally:
        _main.run_in_background = _real_bg

    # 列表项要能自己判断"能不能一键出片":有脚本(script_updated_at)+ 不在忙态
    _sum_direct = _ar.summary()
    ok("列表项带 script_updated_at 与 direct_render",
       "script_updated_at" in _sum_direct and "direct_render" in _sum_direct,
       str(sorted(_sum_direct)))

    # 配音复用指纹:必须含「合成口径」—— 运行时修好了,烧坏的旧配音不能还接着用
    # (2026-09-12 乱码事故:transformers 4.52+ 打乱语音 LLM 输出,时长正常、读音全错)
    _vc_frames = {"frames": [{"index": 1, "voiceover": "测试台词"}]}
    _sig_a = _main._vo_signature(_vc_frames, "male", "cosyvoice3")
    _orig_vo_v = config.VO_SYNTH_VERSION
    try:
        config.VO_SYNTH_VERSION = str(_orig_vo_v) + "-changed"
        _sig_b = _main._vo_signature(_vc_frames, "male", "cosyvoice3")
    finally:
        config.VO_SYNTH_VERSION = _orig_vo_v
    ok("配音指纹随合成口径变化(改口径即重烧旧配音)", _sig_a != _sig_b)
    ok("配音指纹随台词变化",
       _sig_a != _main._vo_signature(
           {"frames": [{"index": 1, "voiceover": "改过的台词"}]}, "male", "cosyvoice3"))
    ok("配音指纹随音色变化",
       _sig_a != _main._vo_signature(_vc_frames, "female", "cosyvoice3"))
    ok("配音指纹随引擎变化",
       _sig_a != _main._vo_signature(_vc_frames, "male", "doubao"))
    ok("配音口径含钉版依赖与合成版本",
       "transformers==" in config.vo_runtime_fingerprint()
       and f"vo{config.VO_SYNTH_VERSION}" in config.vo_runtime_fingerprint())
finally:
    _os.environ["TTV_ROOT"] = _orig_root2 or str(Path(__file__).resolve().parents[1])
    _il.reload(_config)
    _il.reload(_jobs_mod)


print()
if FAIL:
    print(f"{len(FAIL)} 项失败: {FAIL}")
    sys.exit(1)
print("ALL SMOKE TESTS PASSED")
