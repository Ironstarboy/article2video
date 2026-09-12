# -*- coding: utf-8 -*-
"""一次性诊断:检查讲解视频任务脚本质量(手动传入 job_id)。"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

job_id = sys.argv[1]
root = Path(os.environ.get("TTV_ROOT", str(Path(__file__).resolve().parents[1])))
p = root / "jobs" / job_id / "script.json"
s = json.load(open(p, encoding="utf-8"))
lp = s.get("lecture_plan", {})
print("== 标题:", s.get("title"), "|", s.get("subtitle"))
print("== 文章类型:", lp.get("article_type"), "| 判定:", (lp.get("type_reason") or "")[:70])
print("== 中心任务:", lp.get("central_task"))
print("== 章节:")
for c in lp.get("chapters", []):
    print("   ", c["number"], c["title"], f"({c['minutes']}分钟)", "para", c["para_range"], "|", c["content_plan"][:50])
print("== 逐段要点:", len(lp.get("paragraph_notes", [])), "段")
for pn in lp.get("paragraph_notes", [])[:5]:
    print("   ", f"第{pn['para']}段[{pn['role']}]", pn["key_idea"][:30], "| 可迁移:", (pn.get("transferable") or "")[:20])
print("== 可迁移写法:")
for m in lp.get("methods", [])[:5]:
    print("   -", m)
print("== 语言表达:", " / ".join(lp.get("language_points", [])[:3])[:120])
print("== 答题方法总结:", (lp.get("exam_method_summary") or "")[:100])
print("== 帧数:", len(s["frames"]), "| duration_sec:", s.get("duration_sec"))
print("== 帧类型分布:", dict(Counter(f["type"] for f in s["frames"])))
print("== 旁白总量:", sum(len((f.get("voiceover") or "")) for f in s["frames"]), "字")
print()
print("== 逐帧概览(类型 | 首 40 字旁白):")
for f in s["frames"]:
    vo = (f.get("voiceover") or "").strip().replace("\n", " ")
    print(f"   {f['index']:>2} {f['type']:<11} {f['duration']:>5}s | {vo[:42]}")
